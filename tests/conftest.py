"""pytest 公共夹具：sys.path、环境隔离、临时 Settings 构造。"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from carla_asset.config import Settings  # noqa: E402

ENV_KEYS = (
    "CARLA_ASSET_BLENDER", "CARLA_ASSET_UE_CMD", "CARLA_ASSET_UPROJECT",
    "CARLA_ASSET_CARLA_ROOT", "CARLA_ASSET_TEMPLATE_DIR",
    "CARLA_ASSET_DEBUG",
)


@pytest.fixture(autouse=True)
def isolated_env(monkeypatch, tmp_path):
    """屏蔽环境变量与仓库 settings.json，保证用例可复现。"""
    for key in ENV_KEYS:
        monkeypatch.delenv(key, raising=False)
    monkeypatch.setattr("carla_asset.config.DEFAULT_SETTINGS_FILE",
                        tmp_path / "no_such_settings.json")


@pytest.fixture
def make_settings(tmp_path):
    """返回构造临时 Settings 的工厂（产出目录全部落在 tmp_path 内）。"""
    def _make(**overrides):
        base = dict(
            manifest_dir=str(tmp_path / "manifests"),
            report_dir=str(tmp_path / "reports"),
            package_dir=str(tmp_path / "dist"),
            backup_dir=str(tmp_path / "_backup"),
            import_timeout_sec=60,
        )
        base.update(overrides)
        return Settings(**base)
    return _make


@pytest.fixture
def fake_carla_root(tmp_path):
    """构造 Release 版 CARLA 目录骨架：CarlaUE4/Content。"""
    root = tmp_path / "CARLA"
    (root / "CarlaUE4" / "Content").mkdir(parents=True)
    return root


@pytest.fixture
def staged_content(tmp_path):
    """构造 pack --src 暂存目录（Content/Carla 结构）。"""
    src = tmp_path / "staged"
    files = {
        "Content/Carla/Blueprints/Vehicles/Su7/BP_Su7.uasset": b"bp",
        "Content/Carla/Blueprints/Vehicles/Su7/Su7_FrontWheel.uasset": b"fw",
        "Content/Carla/Static/Vehicles/Su7/SK_Su7.uasset": b"sk",
    }
    for rel, content in files.items():
        p = src.joinpath(*rel.split("/"))
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(content)
    return src
