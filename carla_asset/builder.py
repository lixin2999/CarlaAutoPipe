"""builder 模块：拉起 UE Commandlet 执行引擎侧构建（V1.4 §4.3 / §5.1）。

``UE4Editor-Cmd.exe <uproject> -run=CarlaAssetImport -mode=<vehicle|map>
    -manifest=<path> [-dry-run] [-skip-factory] [-skip-navmesh]
    [-batch-size=N] -stdout -unattended -nopause -nullrhi``

CLI 侧在启动 UE 前执行与 Commandlet 相同算法的黄金模板哈希预检（错误左移），
但最终绝对卡点仍在 UE 进程内（TemplateHashGuard）。

退出码映射：Commandlet 返回 0/1/2/3 与统一契约一致；进程启动失败/崩溃 → 2。
"""

from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Optional

from .checksum import template_checksum
from .config import Settings
from .constants import ExitCode
from .manifest import validate_manifest, vehicle_asset_id
from .report import Report, environment_error


def build_asset(kind: str, manifest_path: str, dry_run: bool = False,
                skip_factory: bool = False, skip_navmesh: bool = False,
                batch_size: Optional[int] = None,
                report: Optional[Report] = None,
                settings: Optional[Settings] = None) -> Report:
    """执行引擎侧构建。kind: vehicle|map"""
    rpt = report or Report(command=f"build-{kind}")
    settings = settings or Settings.load()
    mft = settings.resolve(manifest_path)

    # -- 1. Manifest 校验（失败 → 退出码 1） --------------------------------
    ok, data = validate_manifest(mft, kind, rpt)
    if not ok:
        return rpt.finish(int(ExitCode.ASSET_VALIDATION_FAIL))
    if kind == "vehicle":
        rpt.asset_name = vehicle_asset_id(data)

    # -- 2. 环境自检（失败 → 退出码 3） -------------------------------------
    for key in ("ue_cmd", "uproject"):
        missing = settings.missing(key)
        if missing:
            return environment_error(rpt.command, f"ENV_{key.upper()}_MISSING",
                                     missing["message"], missing["suggestion"])
    if kind == "vehicle":
        missing = settings.missing("golden_template_dir")
        if missing:
            return environment_error(rpt.command, "ENV_TEMPLATE_DIR_MISSING",
                                     missing["message"], missing["suggestion"])

    # -- 3. 黄金模板哈希预检（左移；不符 → 退出码 3） ------------------------
    if kind == "vehicle":
        expected = data.get("golden_template_checksum", "")
        actual = template_checksum(settings.path_of("golden_template_dir"))
        rpt.details["template_checksum_actual"] = actual
        if actual.lower() != expected.lower():
            rpt.add_error(
                "TPL_HASH_MISMATCH",
                f"黄金模板哈希校验不匹配（期望 {expected[:16]}...，实际 {actual[:16]}...）",
                "模板目录可能被误修改：恢复官方 _Template 原始内容，"
                "或在确认模板合法后更新 Manifest 的 golden_template_checksum",
                mft.as_posix())
            return rpt.finish(int(ExitCode.ENVIRONMENT_ERROR))

    # -- 4. 拉起 UE Commandlet ----------------------------------------------
    cmd = [
        str(settings.path_of("ue_cmd")),
        str(settings.path_of("uproject")),
        "-run=CarlaAssetImport", f"-mode={kind}",
        f"-manifest={mft.as_posix()}",
        f"-report={_engine_report_path(rpt, settings, mft).as_posix()}",
        "-stdout", "-unattended", "-nopause", "-nullrhi",
    ]
    if dry_run:
        cmd.append("-dry-run")
    if kind == "vehicle" and (skip_factory or
                              data.get("registration", {}).get("skip_factory")):
        cmd.append("-skip-factory")
    if kind == "map" and skip_navmesh:
        cmd.append("-skip-navmesh")
    if batch_size:
        cmd.append(f"-batch-size={int(batch_size)}")

    rpt.details["engine_cmd"] = " ".join(Path(c).as_posix() if "\\" in c else c
                                         for c in cmd)
    if dry_run:
        # --dry-run：仅完成校验与编排预览，不启动 UE 进程、不落地保存
        rpt.add_info("BUILD_DRY_RUN",
                     "dry-run 模式：已完成 Manifest/哈希/环境校验，跳过 UE 进程执行",
                     "")
        return rpt.finish(int(ExitCode.SUCCESS))

    try:
        proc = subprocess.run(cmd, capture_output=True, text=True,
                              timeout=settings.import_timeout_sec)
    except subprocess.TimeoutExpired:
        rpt.add_error("ENGINE_TIMEOUT",
                      f"UE Commandlet 超时（>{settings.import_timeout_sec}s）",
                      "批量导入建议配合 -batch-size 分片，或调大超时")
        return rpt.finish(int(ExitCode.ENGINE_INTERNAL_ERROR))
    except OSError as e:
        rpt.add_error("ENGINE_SPAWN_FAIL", f"UE 进程启动失败: {e}",
                      "检查 ue_cmd / uproject 配置")
        return rpt.finish(int(ExitCode.ENGINE_INTERNAL_ERROR))

    # -- 5. 退出码映射 --------------------------------------------------------
    code = proc.returncode
    if code not in (0, 1, 2, 3):
        # UE 崩溃通常返回负值/异常码
        code = int(ExitCode.ENGINE_INTERNAL_ERROR)
        rpt.add_error("ENGINE_CRASH", f"UE 进程异常退出码 {proc.returncode}",
                      "查看 UAT/Editor 日志（Saved/Logs/）")
    elif code == int(ExitCode.ENGINE_INTERNAL_ERROR):
        rpt.add_error("ENGINE_INTERNAL", "Commandlet 报告引擎内部异常",
                      "查看引擎侧 JSON 报告与 Editor 日志")
    elif code == int(ExitCode.ASSET_VALIDATION_FAIL) and not rpt.has_error:
        rpt.add_error("ENGINE_VALIDATE_FAIL", "Commandlet 报告资产校验失败",
                      "查看引擎侧 JSON 报告定位字段")
    elif code == int(ExitCode.ENVIRONMENT_ERROR) and not rpt.has_error:
        rpt.add_error("ENGINE_ENV_ERROR", "Commandlet 报告环境错误（模板哈希/路径）",
                      "核对黄金模板与 Manifest 配置")
    rpt.details["engine_exit_code"] = proc.returncode
    rpt.details["stdout_tail"] = (proc.stdout or "")[-2000:]
    return rpt.finish(code)


def _engine_report_path(rpt: Report, settings: Settings, manifest: Path) -> Path:
    """引擎侧统一 JSON 报告输出路径（reports/<name>.engine.json）。"""
    out_dir = settings.resolve(settings.report_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    return out_dir / f"{manifest.stem}.engine.json"
