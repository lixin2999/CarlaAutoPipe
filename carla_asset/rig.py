"""rig 命令实现：拉起 Blender 后台自动绑骨（V1.4 §4.2 / V1.2 §4.2）。

rig_and_validate.py 采用「检查 → 修复绑骨 → 回读验证」三段式，将外部网格
刚性绑定到 CARLA 标准五骨骨架。绝对红线：不修改骨架名称/层级/旋转缩放。
"""

from __future__ import annotations

import subprocess
from typing import Optional

from .config import Settings, blender_scripts_dir
from .constants import ExitCode
from .report import Report, environment_error
from .validate import _merge_blender_report

RIG_SCRIPT = "rig_and_validate.py"


def run_rig(fbx_in: str, out: str, mirror_y: bool = False,
            report: Optional[Report] = None,
            settings: Optional[Settings] = None) -> Report:
    """执行自动绑骨。fbx_in: 输入 FBX；out: 合规 FBX 输出路径。"""
    rpt = report or Report(command="rig")
    settings = settings or Settings.load()

    missing = settings.missing("blender_exe")
    if missing:
        return environment_error("rig", "ENV_BLENDER_MISSING",
                                 f"未找到 Blender: {missing['message']}",
                                 missing["suggestion"])

    src = settings.resolve(fbx_in)
    if not src.is_file():
        return environment_error("rig", "ENV_INPUT_MISSING",
                                 f"输入 FBX 不存在: {src.as_posix()}",
                                 "检查 --fbx 参数")
    dst = settings.resolve(out)
    dst.parent.mkdir(parents=True, exist_ok=True)

    rpt.details["input"] = src.as_posix()
    rpt.details["output"] = dst.as_posix()
    rpt.details["mirror_y"] = mirror_y

    script = (blender_scripts_dir() / RIG_SCRIPT).as_posix()
    out_json = dst.with_name(f"{dst.stem}.rig_report.json")
    cmd = [
        str(settings.path_of("blender_exe")), "--background", "--factory-startup",
        "--python", script, "--",
        "--fbx", src.as_posix(),
        "--out", dst.as_posix(),
        "--report", out_json.as_posix(),
    ]
    if mirror_y:
        cmd.append("--mirror-y")

    try:
        proc = subprocess.run(cmd, capture_output=True, text=True,
                              timeout=settings.import_timeout_sec)
    except subprocess.TimeoutExpired:
        rpt.add_error("BLENDER_TIMEOUT",
                      f"绑骨超时（>{settings.import_timeout_sec}s）", "调大超时或减小资产规模")
        return rpt.finish(int(ExitCode.ENGINE_INTERNAL_ERROR))
    except OSError as e:
        rpt.add_error("BLENDER_SPAWN_FAIL", f"Blender 进程启动失败: {e}",
                      "检查 blender_exe 配置")
        return rpt.finish(int(ExitCode.ENGINE_INTERNAL_ERROR))

    if out_json.is_file():
        _merge_blender_report(rpt, out_json)
        rpt.artifacts.append(out_json.as_posix())

    # 回读验证阶段在 Blender 内部完成：产物缺失视为致命
    if proc.returncode == int(ExitCode.SUCCESS) and not dst.is_file():
        rpt.add_error("RIG_OUTPUT_MISSING",
                      f"绑骨声称成功但输出文件缺失: {dst.as_posix()}",
                      "查看 Blender stderr 排查")
        return rpt.finish(int(ExitCode.ENGINE_INTERNAL_ERROR))

    if proc.returncode not in (int(ExitCode.SUCCESS), int(ExitCode.ASSET_VALIDATION_FAIL)):
        rpt.add_error("BLENDER_CRASH", f"Blender 异常退出码 {proc.returncode}",
                      "查看 stderr 尾部输出")
        rpt.details["stderr_tail"] = (proc.stderr or "")[-2000:]
        return rpt.finish(int(ExitCode.ENGINE_INTERNAL_ERROR))

    if dst.is_file():
        rpt.artifacts.append(dst.as_posix())

    code = ExitCode.ASSET_VALIDATION_FAIL if rpt.has_error else ExitCode.SUCCESS
    return rpt.finish(int(code))
