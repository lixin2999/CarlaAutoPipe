"""环境配置解析与自检。

配置来源优先级：环境变量 > configs/settings.json > 内置默认值。
所有外部依赖（Blender / UE4Editor-Cmd / uproject / CARLA_ROOT / 黄金模板目录）
路径均可配置；检测缺失时由调用方返回退出码 3 并附修复指引（ENVIRONMENT_ERROR）。
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Optional

# 仓库根（carla_asset/ 的上级目录）
REPO_ROOT = Path(__file__).resolve().parent.parent

DEFAULT_SETTINGS_FILE = REPO_ROOT / "configs" / "settings.json"

# 环境变量覆盖映射
ENV_MAP = {
    "blender_exe": "CARLA_ASSET_BLENDER",
    "ue_cmd": "CARLA_ASSET_UE_CMD",
    "uproject": "CARLA_ASSET_UPROJECT",
    "carla_root": "CARLA_ASSET_CARLA_ROOT",
    "golden_template_dir": "CARLA_ASSET_TEMPLATE_DIR",
}


class SettingsError(RuntimeError):
    """settings.json 损坏/非法，调用方映射退出码 3（ENVIRONMENT_ERROR）。"""


@dataclass
class Settings:
    """运行配置。路径统一以 POSIX 字符串保存，使用时再转 Path。"""

    blender_exe: Optional[str] = None
    ue_cmd: Optional[str] = None
    uproject: Optional[str] = None
    carla_root: Optional[str] = None
    golden_template_dir: Optional[str] = None
    manifest_dir: str = "manifests"
    report_dir: str = "reports"
    package_dir: str = "Dist"
    backup_dir: str = "_backup"
    import_timeout_sec: int = 1800
    source_file: Optional[str] = field(default=None, repr=False)

    # --- 加载 -------------------------------------------------------------
    @classmethod
    def load(cls, settings_path: Optional[str | Path] = None) -> "Settings":
        """读取 settings.json（可选）并应用环境变量覆盖。"""
        data = {}
        path = Path(settings_path) if settings_path else DEFAULT_SETTINGS_FILE
        if path.is_file():
            import json
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError) as e:
                raise SettingsError(
                    f"settings.json 解析失败: {path.as_posix()} -> {e}；"
                    "请对照 configs/settings.example.json 修正语法，"
                    "或删除该文件回退默认配置") from e
            data.pop("$comment", None)
        # 相对路径按仓库根解析
        for key in ("manifest_dir", "report_dir", "package_dir", "backup_dir"):
            if key in data and not Path(data[key]).is_absolute():
                data[key] = str((REPO_ROOT / data[key]).as_posix())
        inst = cls(**{k: v for k, v in data.items() if k in cls.__dataclass_fields__})
        inst.source_file = path.as_posix() if path.is_file() else None
        # 环境变量覆盖
        for attr, env in ENV_MAP.items():
            val = os.environ.get(env)
            if val:
                setattr(inst, attr, Path(val).as_posix())
        return inst

    # --- 路径辅助 -----------------------------------------------------------
    def path_of(self, key: str) -> Optional[Path]:
        val = getattr(self, key, None)
        return Path(val) if val else None

    def resolve(self, p: str | Path) -> Path:
        """将相对路径按仓库根解析为绝对路径。"""
        p = Path(str(p).replace("\\", "/"))
        return p if p.is_absolute() else (REPO_ROOT / p)

    # --- 环境自检 -----------------------------------------------------------
    def check(self) -> List[dict]:
        """逐项检测外部依赖，返回 [{key, ok, path, message, suggestion}]。

        GUI 启动自检与 CLI 各命令前置检查共用本函数。
        """
        results = []
        checks = [
            ("blender_exe", "Blender",
             "安装 Blender 3.x 并在 settings.json 配置 blender_exe，或设置环境变量 CARLA_ASSET_BLENDER",
             ("validate", "rig")),
            ("ue_cmd", "UE4Editor-Cmd",
             "安装 UE 4.26（CARLA 源码构建环境）并配置 ue_cmd，或设置环境变量 CARLA_ASSET_UE_CMD",
             ("build-vehicle", "build-map")),
            ("uproject", "CarlaUE4.uproject",
             "获取 CARLA 0.9.16 源码工程并配置 uproject，或设置环境变量 CARLA_ASSET_UPROJECT",
             ("build-vehicle", "build-map")),
            ("golden_template_dir", "黄金模板目录",
             "部署 /Game/Carla/Blueprints/Vehicles/_Template 到本地并配置 golden_template_dir",
             ("build-vehicle",)),
            ("carla_root", "CARLA_ROOT",
             "安装 CARLA 0.9.16（Release 或源码）并配置 carla_root，或设置环境变量 CARLA_ASSET_CARLA_ROOT",
             ("inject", "smoke")),
        ]
        for key, label, suggestion, commands in checks:
            p = self.path_of(key)
            ok = bool(p and Path(p).exists())
            results.append({
                "key": key,
                "label": label,
                "ok": ok,
                "path": Path(p).as_posix() if p else None,
                "used_by": list(commands),
                "message": f"{label} 就绪" if ok else f"{label} 未配置或路径不存在",
                "suggestion": "" if ok else suggestion,
            })
        return results

    def missing(self, key: str) -> Optional[dict]:
        """返回指定依赖的检测项（不存在/未配置时），否则 None。"""
        for item in self.check():
            if item["key"] == key and not item["ok"]:
                return item
        return None


def blender_scripts_dir() -> Path:
    """Blender 脚本目录（仓库内 blender_scripts/）。"""
    return REPO_ROOT / "blender_scripts"
