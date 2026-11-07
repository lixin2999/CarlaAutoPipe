"""启动环境自检：复用 CLI 同源的 Settings.check()（不复制业务逻辑）。"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Dict, List

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from carla_asset.config import Settings  # noqa: E402

# 步骤 → 依赖的环境键（缺失即禁用对应步骤并给指引）；键与 main_window.STEPS 对齐
STEP_ENV = {
    "validate": ["blender_exe"],
    "rig": ["blender_exe"],
    "build": ["ue_cmd", "uproject", "golden_template_dir"],
    "register": ["ue_cmd", "uproject", "golden_template_dir"],
    "pack": [],
    "inject": ["carla_root"],
    "smoke": ["carla_root"],
}


def env_status() -> Dict[str, dict]:
    """返回 {key: 检测项} 映射。"""
    return {item["key"]: item for item in Settings.load().check()}


def blocked_steps(status: Dict[str, dict]) -> Dict[str, List[str]]:
    """返回 {step: [缺失项 message/suggestion, ...]}；空列表代表该步骤可用。"""
    result = {}
    for step, keys in STEP_ENV.items():
        problems = []
        for k in keys:
            item = status.get(k, {})
            if not item.get("ok", False):
                problems.append(f"{item.get('message', k)} — {item.get('suggestion', '')}")
        result[step] = problems
    return result
