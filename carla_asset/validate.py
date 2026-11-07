"""validate 命令实现：拉起 Blender 后台前置校验（错误左移，V1.4 §4.2）。

流程：
1. 环境自检（blender_exe / 输入文件）→ 缺失返回退出码 3；
2. ``blender --background --python blender_scripts/validate_mesh.py -- <args>``；
3. 读取 Blender 侧写出的 JSON 报告并合并进统一 Report；
4. 存在 ERROR 级问题 → 退出码 1；Blender 进程异常 → 退出码 2。
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path
from typing import Optional

from .config import Settings, blender_scripts_dir
from .constants import ExitCode, Level
from .report import Report, environment_error

VALIDATE_SCRIPT = "validate_mesh.py"


def run_validate(asset_type: str, input_path: str, xodr_path: Optional[str] = None,
                 manifest_path: Optional[str] = None,
                 report: Optional[Report] = None,
                 settings: Optional[Settings] = None) -> Report:
    """执行 Blender 后台资产校验。asset_type: vehicle|map"""
    rpt = report or Report(command="validate")
    settings = settings or Settings.load()

    # -- 环境自检 ----------------------------------------------------------
    missing = settings.missing("blender_exe")
    if missing:
        return environment_error(
            "validate", "ENV_BLENDER_MISSING",
            f"未找到 Blender: {missing['message']}", missing["suggestion"])

    fbx = settings.resolve(input_path)
    if not fbx.is_file():
        return environment_error(
            "validate", "ENV_INPUT_MISSING",
            f"输入资产不存在: {fbx.as_posix()}",
            "检查 --input 参数（支持相对仓库根路径）")

    rpt.details["asset_type"] = asset_type
    rpt.details["input"] = fbx.as_posix()

    # -- 组装 Blender 命令 ---------------------------------------------------
    script = (blender_scripts_dir() / VALIDATE_SCRIPT).as_posix()
    out_json = fbx.with_name(f"{fbx.stem}.validate_report.json")
    cmd = [
        str(settings.path_of("blender_exe")), "--background", "--factory-startup",
        "--python", script, "--",
        "--type", asset_type,
        "--fbx", fbx.as_posix(),
        "--report", out_json.as_posix(),
    ]
    if xodr_path:
        cmd += ["--xodr", str(settings.resolve(xodr_path).as_posix())]
    if manifest_path:
        cmd += ["--manifest", str(settings.resolve(manifest_path).as_posix())]

    # -- 执行并回收报告 -------------------------------------------------------
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True,
                              timeout=settings.import_timeout_sec)
    except subprocess.TimeoutExpired:
        rpt.add_error("BLENDER_TIMEOUT",
                      f"Blender 校验超时（>{settings.import_timeout_sec}s）",
                      "资产过大可适当调大 import_timeout_sec")
        return rpt.finish(int(ExitCode.ENGINE_INTERNAL_ERROR))
    except OSError as e:
        rpt.add_error("BLENDER_SPAWN_FAIL", f"Blender 进程启动失败: {e}",
                      "检查 blender_exe 配置是否指向可执行文件")
        return rpt.finish(int(ExitCode.ENGINE_INTERNAL_ERROR))

    if out_json.is_file():
        _merge_blender_report(rpt, out_json)
    elif proc.returncode != 0:
        rpt.add_error("BLENDER_CRASH",
                      f"Blender 退出码 {proc.returncode}，且未生成报告文件",
                      "查看完整 stderr 输出排查脚本异常")
        rpt.details["stderr_tail"] = (proc.stderr or "")[-2000:]
        return rpt.finish(int(ExitCode.ENGINE_INTERNAL_ERROR))
    else:
        rpt.add_warning("BLENDER_NO_REPORT",
                        "Blender 未写出 JSON 报告（可能脚本版本不匹配）",
                        "确认 blender_scripts/validate_mesh.py 未被改动")

    if proc.returncode == int(ExitCode.ASSET_VALIDATION_FAIL) and not rpt.has_error:
        # Blender 侧判定有 ERROR 但报告缺项（解析失败/条目丢失）：兜底补一条，
        # 并附 stderr 尾部供定位
        rpt.add_error("VEH_VALIDATE_FAIL", "Blender 校验判定存在致命错误",
                      "参考报告卡片逐条修复")
        rpt.details["stderr_tail"] = (proc.stderr or "")[-2000:]

    code = ExitCode.ASSET_VALIDATION_FAIL if rpt.has_error else ExitCode.SUCCESS
    rpt.artifacts.append(out_json.as_posix())
    return rpt.finish(int(code))


def _merge_blender_report(rpt: Report, path: Path) -> None:
    """将 Blender 脚本产出的 JSON 报告合并到统一 Report。"""
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as e:
        rpt.add_warning("REPORT_PARSE_FAIL", f"解析 Blender 报告失败: {e}",
                        "报告文件可能损坏，重跑 validate")
        return
    for item in data.get("issues", []):
        level = item.get("level", Level.INFO)
        args = (item.get("code", "UNKNOWN"), item.get("message", ""),
                item.get("suggestion", ""))
        if level == Level.ERROR:
            rpt.add_error(*args, file=item.get("file"))
        elif level == Level.WARNING:
            rpt.add_warning(*args, file=item.get("file"))
        else:
            rpt.add_info(*args)
    rpt.details["blender_summary"] = data.get("summary", {})
