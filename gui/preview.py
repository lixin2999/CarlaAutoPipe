"""注入差异预览：GUI 二次确认前展示真实的新增/覆盖清单。

只读复用 CLI 核心包的公开函数（read_package / detect_target_layout /
compute_diff / _build_fingerprint），不承载业务逻辑、不写任何目标文件，
符合薄壳契约（V1.4 §5.2：业务逻辑唯一实现在 CLI 与 Commandlet）。
"""

from __future__ import annotations

import tempfile
import zipfile
import tarfile
from pathlib import Path
from typing import Optional

REPO_ROOT = Path(__file__).resolve().parent.parent


def preview_diff(pkg_path: str,
                 carla_root: Optional[str] = None) -> Optional[dict]:
    """解包到临时目录并比对目标布局，返回 {"added": [...], "overwritten": [...]}。

    任何异常（包损坏、CARLA_ROOT 缺失、目录探测失败）返回 None，
    调用方明示"预览不可用"。
    """
    from carla_asset.config import Settings
    from carla_asset.inject import (_content_files,
                                     compute_diff, detect_target_layout,
                                     read_package)

    settings = Settings.load()
    root_str = carla_root or settings.carla_root
    if not root_str or not Path(root_str).is_dir():
        return None
    pkg = settings.resolve(pkg_path)
    if not pkg.is_file():
        return None
    carla = Path(root_str)
    layout = detect_target_layout(carla)

    with tempfile.TemporaryDirectory(prefix="carla_preview_") as tmp:
        try:
            content_root, _meta = read_package(pkg, Path(tmp))
        except (ValueError, zipfile.BadZipFile, tarfile.TarError, OSError):
            return None
        # pak 通路：Saved/Paks 下单文件
        if pkg.name.lower().endswith(".pak"):
            return compute_diff([content_root.name], layout["paks"])
        entries = _content_files(content_root)
        rel = [e.split("/", 1)[1] if e.startswith("Content/") else e
               for e in entries]
        # 散装通路预览需要 Content 目录（import_sh 目标同为 Content/）
        if layout["content"] is None:
            return None
        return compute_diff(rel, layout["content"])
