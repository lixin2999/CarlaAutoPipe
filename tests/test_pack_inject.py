"""pack / inject：正斜杠归一化、注入落地、幂等跳过、快照备份与回滚。"""

from __future__ import annotations

import json
import tarfile
import zipfile
from pathlib import Path

import pytest

from carla_asset.constants import ExitCode
from carla_asset.inject import (compute_diff, detect_target_layout,
                                inject_package, read_package)
from carla_asset.inject import _backup_files, _rollback
from carla_asset.pack import build_package, compute_fingerprint

REL_FILES = [
    "Content/Carla/Blueprints/Vehicles/Su7/BP_Su7.uasset",
    "Content/Carla/Blueprints/Vehicles/Su7/Su7_FrontWheel.uasset",
    "Content/Carla/Static/Vehicles/Su7/SK_Su7.uasset",
]


def _dest_rel(rel: str) -> str:
    """注入时包内 "Content/" 前缀被剥离后拼到 CarlaUE4/Content 下。"""
    return rel.split("/", 1)[1]


def _pack_win(staged_content, make_settings):
    settings = make_settings()
    rpt = build_package("su7", str(staged_content), platform="win",
                        settings=settings)
    assert rpt.exit_code == int(ExitCode.SUCCESS), rpt.issues
    return settings, Path(rpt.artifacts[0])


# ---------------------------------------------------------------------------
# pack
# ---------------------------------------------------------------------------
def test_pack_win_zip_posix_entries(staged_content, make_settings):
    settings, pkg = _pack_win(staged_content, make_settings)
    assert pkg.suffix == ".zip" and pkg.is_file()
    with zipfile.ZipFile(pkg) as zf:
        names = zf.namelist()
    assert all("\\" not in n for n in names)          # ★无返回斜杠
    assert all(n.startswith("su7/") for n in names)
    for rel in REL_FILES:
        assert f"su7/{rel}" in names
    # 旁挂 meta 指纹与包名
    meta_zip = pkg.with_suffix(pkg.suffix + ".meta.zip")
    assert meta_zip.is_file()
    with zipfile.ZipFile(meta_zip) as zf:
        meta = json.loads(zf.read("su7/package.meta.json"))
    assert meta["pkg_name"] == "su7"
    assert len(meta["fingerprint"]) == 64
    assert all("\\" not in f for f in meta["files"])


def test_pack_linux_tar_gz(staged_content, make_settings):
    settings = make_settings()
    rpt = build_package("su7", str(staged_content), platform="linux",
                        settings=settings)
    assert rpt.exit_code == int(ExitCode.SUCCESS)
    pkg = Path(rpt.artifacts[0])
    assert pkg.name == "su7.tar.gz"
    with tarfile.open(pkg) as tf:
        names = tf.getnames()
    assert all("\\" not in n for n in names)
    assert "su7/Content/Carla/Static/Vehicles/Su7/SK_Su7.uasset" in names


def test_pack_missing_src(make_settings):
    rpt = build_package("x", "no/such/dir", settings=make_settings())
    assert rpt.exit_code == int(ExitCode.ENVIRONMENT_ERROR)
    assert rpt.issues[0].code == "ENV_SOURCE_MISSING"


def test_pack_archives_manifest(tmp_path, staged_content, make_settings):
    mft = tmp_path / "su7.json"
    mft.write_text(json.dumps({"vehicle": {"model": "su7"}}), encoding="utf-8")
    rpt = build_package("su7", str(staged_content), manifest_path=str(mft),
                        settings=make_settings())
    assert rpt.exit_code == int(ExitCode.SUCCESS)
    archived = staged_content / "_manifest" / "su7.json"   # 原始清单随包归档
    assert archived.is_file()


def test_fingerprint_deterministic_and_order_free():
    a = compute_fingerprint([("x/y", "d1"), ("a/b", "d2")])
    b = compute_fingerprint([("a/b", "d2"), ("x/y", "d1")])   # 内部排序
    assert a == b
    assert a != compute_fingerprint([("x/y", "d1"), ("a/b", "d3")])


# ---------------------------------------------------------------------------
# inject 纯函数
# ---------------------------------------------------------------------------
def test_detect_target_layout_release(fake_carla_root):
    layout = detect_target_layout(fake_carla_root)
    assert layout["ue_dir"] == fake_carla_root / "CarlaUE4"
    assert layout["content"] == fake_carla_root / "CarlaUE4" / "Content"
    assert layout["paks"] == fake_carla_root / "CarlaUE4" / "Saved" / "Paks"


def test_detect_target_layout_source_build(tmp_path):
    root = tmp_path / "CarlaSrc"
    (root / "Content").mkdir(parents=True)
    layout = detect_target_layout(root)
    assert layout["content"] == root / "Content"


def test_compute_diff_added_vs_overwritten(tmp_path):
    (tmp_path / "Carla").mkdir()
    (tmp_path / "Carla" / "exists.uasset").write_bytes(b"old")
    diff = compute_diff(["Carla/exists.uasset", "Carla/new.uasset"], tmp_path)
    assert diff["overwritten"] == ["Carla/exists.uasset"]
    assert diff["added"] == ["Carla/new.uasset"]


# ---------------------------------------------------------------------------
# inject 全流程（tmp_path 模拟 Release 目录）
# ---------------------------------------------------------------------------
def test_inject_overlay_and_idempotent(staged_content, fake_carla_root, make_settings):
    settings, pkg = _pack_win(staged_content, make_settings)
    content = fake_carla_root / "CarlaUE4" / "Content"

    rpt = inject_package(str(pkg), carla_root=str(fake_carla_root), settings=settings)
    assert rpt.exit_code == int(ExitCode.SUCCESS), rpt.issues
    assert rpt.details["mode"] == "content_overlay"
    assert rpt.details["diff"]["added"] == len(REL_FILES)
    for rel in REL_FILES:
        assert content.joinpath(*_dest_rel(rel).split("/")).is_file()

    # 重复注入：指纹一致 → 幂等跳过（退出码 0 + INFO 提示）
    rpt2 = inject_package(str(pkg), carla_root=str(fake_carla_root), settings=settings)
    assert rpt2.exit_code == int(ExitCode.SUCCESS)
    assert any(i.code == "INJECT_IDEMPOTENT_SKIP" for i in rpt2.issues)

    # --force 强制重注
    rpt3 = inject_package(str(pkg), carla_root=str(fake_carla_root),
                          force=True, settings=settings)
    assert rpt3.exit_code == int(ExitCode.SUCCESS)
    assert not any(i.code == "INJECT_IDEMPOTENT_SKIP" for i in rpt3.issues)


def test_inject_backup_and_rollback(staged_content, fake_carla_root, make_settings):
    settings, pkg = _pack_win(staged_content, make_settings)
    content = fake_carla_root / "CarlaUE4" / "Content"
    target = content.joinpath(*_dest_rel(REL_FILES[0]).split("/"))
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(b"ORIGINAL")                     # 预置将被覆盖的同名文件

    rpt = inject_package(str(pkg), carla_root=str(fake_carla_root),
                         rollback_on_fail=True, settings=settings)
    assert rpt.exit_code == int(ExitCode.SUCCESS)
    assert _dest_rel(REL_FILES[0]) in rpt.details["overwritten_files"]
    assert target.read_bytes() != b"ORIGINAL"

    # 快照存在于 _backup/<pkg>_<ts>/，含 _origin.json 与原始内容
    backups = list(Path(settings.backup_dir).glob("su7_*"))
    assert backups, "应生成快照备份"
    origin = json.loads((backups[0] / "_origin.json").read_text(encoding="utf-8"))
    assert origin["files"] == [_dest_rel(REL_FILES[0])]
    assert backups[0].joinpath(*_dest_rel(REL_FILES[0]).split("/")).read_bytes() == b"ORIGINAL"

    # 回滚恢复注入前状态
    from carla_asset.report import Report
    _rollback(backups[0], content, Report(command="inject"))
    assert target.read_bytes() == b"ORIGINAL"


def test_inject_pak_channel(staged_content, fake_carla_root, make_settings):
    settings = make_settings()
    pak = staged_content.parent / "su7_content.pak"
    pak.write_bytes(b"\x5A\x00\x00\x00fakepak")
    rpt = inject_package(str(pak), carla_root=str(fake_carla_root), settings=settings)
    assert rpt.exit_code == int(ExitCode.SUCCESS), rpt.issues
    assert rpt.details["mode"] == "pak"
    dest = fake_carla_root / "CarlaUE4" / "Saved" / "Paks" / pak.name
    assert dest.is_file()


def test_inject_pak_idempotent_skip_and_force(staged_content, fake_carla_root, make_settings):
    """V1.0.1 回归：pak 通路指纹为内容哈希，二次注入幂等跳过，--force 重注。"""
    settings = make_settings()
    pak = staged_content.parent / "su7_content.pak"
    pak.write_bytes(b"\x5A\x00\x00\x00fakepak")
    rpt1 = inject_package(str(pak), carla_root=str(fake_carla_root), settings=settings)
    assert rpt1.exit_code == int(ExitCode.SUCCESS), rpt1.issues
    assert rpt1.details["fingerprint"]     # ★真实内容指纹，非 (名字, "pak") 占位

    rpt2 = inject_package(str(pak), carla_root=str(fake_carla_root), settings=settings)
    assert rpt2.exit_code == int(ExitCode.SUCCESS)
    assert any(i.code == "INJECT_IDEMPOTENT_SKIP" for i in rpt2.issues)

    rpt3 = inject_package(str(pak), carla_root=str(fake_carla_root),
                          force=True, settings=settings)
    assert rpt3.exit_code == int(ExitCode.SUCCESS)
    assert not any(i.code == "INJECT_IDEMPOTENT_SKIP" for i in rpt3.issues)

    # 内容变更 → 指纹变化 → 不得幂等跳过（记录与比对同算法）
    pak.write_bytes(b"\x5A\x00\x00\x00CHANGED")
    rpt4 = inject_package(str(pak), carla_root=str(fake_carla_root), settings=settings)
    assert not any(i.code == "INJECT_IDEMPOTENT_SKIP" for i in rpt4.issues)


def test_inject_missing_carla_root(staged_content, make_settings):
    settings, pkg = _pack_win(staged_content, make_settings)
    rpt = inject_package(str(pkg), carla_root=str(settings.report_dir) + "/nope",
                         settings=settings)
    assert rpt.exit_code == int(ExitCode.ENVIRONMENT_ERROR)
    assert rpt.issues[0].code == "ENV_CARLA_ROOT_MISSING"


def test_inject_missing_pkg(make_settings, fake_carla_root):
    rpt = inject_package("dist/nope.zip", carla_root=str(fake_carla_root),
                         settings=make_settings())
    assert rpt.exit_code == int(ExitCode.ENVIRONMENT_ERROR)
    assert rpt.issues[0].code == "ENV_PKG_MISSING"


def test_inject_corrupt_zip(tmp_path, fake_carla_root, make_settings):
    bad = tmp_path / "broken.zip"
    bad.write_bytes(b"not a zip at all")
    rpt = inject_package(str(bad), carla_root=str(fake_carla_root),
                         settings=make_settings())
    assert rpt.exit_code == int(ExitCode.ASSET_VALIDATION_FAIL)
    assert rpt.issues[0].code == "PKG_CORRUPT"


def test_read_package_rejects_traversal(tmp_path):
    pkg = tmp_path / "evil.tar.gz"
    with tarfile.open(pkg, "w:gz") as tf:
        info = tarfile.TarInfo("../escape.txt")
        info.size = 1
        tf.addfile(info, fileobj=Path(__file__).open("rb"))
    try:
        read_package(pkg, tmp_path / "work")
        assert False, "应拒绝 .. 越界条目"
    except ValueError as e:
        assert "非法路径" in str(e)


def test_read_package_rejects_zip_traversal(tmp_path):
    """V1.0.1 回归：zip 与 tar 同款路径穿越预检（恶意包不得写出 workdir）。"""
    pkg = tmp_path / "evil.zip"
    with zipfile.ZipFile(pkg, "w") as zf:
        zf.writestr("../escape.txt", "pwned")
    with pytest.raises(ValueError, match="非法路径"):
        read_package(pkg, tmp_path / "work")
    assert not (tmp_path / "escape.txt").exists()


def test_inject_zip_traversal_reports_corrupt(tmp_path, fake_carla_root, make_settings):
    pkg = tmp_path / "evil.zip"
    with zipfile.ZipFile(pkg, "w") as zf:
        zf.writestr("../escape.txt", "pwned")
    rpt = inject_package(str(pkg), carla_root=str(fake_carla_root),
                         settings=make_settings())
    assert rpt.exit_code == int(ExitCode.ASSET_VALIDATION_FAIL)
    assert rpt.issues[0].code == "PKG_CORRUPT"


def test_backup_files_noop_without_overwrites(make_settings):
    settings = make_settings()
    assert _backup_files(Path("x"), [], "pkg", settings, Path("y")) is None
