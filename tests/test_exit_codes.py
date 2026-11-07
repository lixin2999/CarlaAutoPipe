"""退出码契约单测：0/1/2/3 全路径映射（无 Blender/UE/CARLA 环境下的行为固化）。"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from carla_asset import cli
from carla_asset.builder import build_asset
from carla_asset.constants import ExitCode

EMPTY_SHA256 = "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855"


# ---------------------------------------------------------------------------
# CLI：环境缺失 → 退出码 3（本机无 Blender/UE/CARLA 的既定行为）
# ---------------------------------------------------------------------------
def test_cli_validate_no_blender(tmp_path):
    rpt_file = tmp_path / "r.json"
    code = cli.main(["validate", "--type", "vehicle", "--input", "x.fbx",
                     "--report", str(rpt_file)])
    assert code == int(ExitCode.ENVIRONMENT_ERROR)
    data = json.loads(rpt_file.read_text(encoding="utf-8"))
    assert data["exit_code"] == 3
    assert data["issues"][0]["code"] == "ENV_BLENDER_MISSING"
    assert data["issues"][0]["suggestion"]          # 必须附修复指引


def test_cli_rig_no_blender():
    assert cli.main(["rig", "--fbx", "a.fbx", "--out", "b.fbx"]) == 3


def test_cli_inject_no_carla_root():
    assert cli.main(["inject", "--pkg", "nope.zip"]) == 3


def test_cli_pack_missing_src():
    assert cli.main(["pack", "--pkg", "p", "--src", "no/such/dir"]) == 3


def test_cli_smoke_no_carla_lib():
    try:
        import carla  # noqa: F401
        pytest.skip("本机装有 carla 库，无法模拟 ENV_CARLA_API_MISSING")
    except ImportError:
        pass
    code = cli.main(["smoke", "--type", "vehicle", "--name", "xiaomi.su7"])
    assert code == int(ExitCode.ENVIRONMENT_ERROR)


def test_cli_smoke_no_target():
    code = cli.main(["smoke", "--type", "vehicle"])
    assert code == int(ExitCode.ASSET_VALIDATION_FAIL)


def test_cli_doctor_reports_all_checks(tmp_path):
    rpt_file = tmp_path / "doctor.json"
    code = cli.main(["doctor", "--report", str(rpt_file)])
    assert code == int(ExitCode.SUCCESS)          # doctor 本身永不失败
    data = json.loads(rpt_file.read_text(encoding="utf-8"))
    keys = {c["key"] for c in data["details"]["checks"]}
    assert {"blender_exe", "ue_cmd", "uproject", "carla_root",
            "golden_template_dir"} <= keys
    # 未配置环境下除 carla_root 外全部不就绪
    assert all(not c["ok"] for c in data["details"]["checks"])


def test_cli_unexpected_exception_maps_to_2(monkeypatch):
    def boom(*a, **kw):
        raise RuntimeError("simulated bug")
    monkeypatch.setattr(cli, "_dispatch", boom)
    assert cli.main(["validate", "--type", "vehicle", "--input", "x"]) == 2


# ---------------------------------------------------------------------------
# builder：Manifest 校验左移 + 哈希卡点 + 引擎退出码映射
# ---------------------------------------------------------------------------
@pytest.fixture
def ue_env(tmp_path):
    """伪造 UE 环境素材：ue_cmd / uproject / 模板目录均为真实存在的文件。"""
    ue = tmp_path / "UE4Editor-Cmd.exe"
    up = tmp_path / "CarlaUE4.uproject"
    template = tmp_path / "_Template"
    template.mkdir()
    ue.write_bytes(b"stub")
    up.write_bytes(b"{}")
    return {"ue": str(ue), "up": str(up), "template": str(template)}


def _engine_settings(make_settings, ue_env):
    return make_settings(ue_cmd=ue_env["ue"], uproject=ue_env["up"],
                         golden_template_dir=ue_env["template"])


def _manifest(tmp_path, checksum=EMPTY_SHA256):
    src = Path(__file__).resolve().parent.parent / "manifests" / "vehicles" / "su7.json"
    doc = json.loads(src.read_text(encoding="utf-8"))
    doc["golden_template_checksum"] = checksum
    p = tmp_path / "su7.json"
    p.write_text(json.dumps(doc), encoding="utf-8")
    return p


def test_builder_bad_manifest_fails_before_env(tmp_path):
    p = tmp_path / "bad.json"
    p.write_text('{"target_carla": "9.9.9"}', encoding="utf-8")
    rpt = build_asset("vehicle", str(p))
    assert rpt.exit_code == int(ExitCode.ASSET_VALIDATION_FAIL)  # 1 优先于 3
    assert any(i.code == "MFT_SCHEMA_FAIL" for i in rpt.issues)


def test_builder_no_env_returns_3(tmp_path):
    rpt = build_asset("vehicle", str(_manifest(tmp_path)))
    assert rpt.exit_code == int(ExitCode.ENVIRONMENT_ERROR)
    assert rpt.issues[0].code.startswith("ENV_")


def test_builder_template_hash_gate(tmp_path, ue_env, make_settings):
    # 模板目录被“污染”（非空）→ 与清单固化的空目录指纹不符 → 绝对卡点
    (Path(ue_env["template"]) / "leaked.uasset").write_bytes(b"x")
    rpt = build_asset("vehicle", str(_manifest(tmp_path)),
                      settings=_engine_settings(make_settings, ue_env))
    assert rpt.exit_code == int(ExitCode.ENVIRONMENT_ERROR)
    err = next(i for i in rpt.issues if i.code == "TPL_HASH_MISMATCH")
    assert "golden_template_checksum" in err.suggestion


def test_builder_dry_run_passes(tmp_path, ue_env, make_settings):
    rpt = build_asset("vehicle", str(_manifest(tmp_path)), dry_run=True,
                      settings=_engine_settings(make_settings, ue_env))
    assert rpt.exit_code == int(ExitCode.SUCCESS)
    assert any(i.code == "BUILD_DRY_RUN" for i in rpt.issues)
    assert "engine_cmd" in rpt.details


class _FakeProc:
    def __init__(self, returncode, out="", err=""):
        self.returncode, self.stdout, self.stderr = returncode, out, err


@pytest.mark.parametrize("engine_code,expect,err_code", [
    (0, 0, None),
    (1, 1, "ENGINE_VALIDATE_FAIL"),
    (2, 2, "ENGINE_INTERNAL"),
    (3, 3, "ENGINE_ENV_ERROR"),
    (-1073741819, 2, "ENGINE_CRASH"),        # Windows 访问违例
])
def test_builder_exit_code_mapping(tmp_path, ue_env, make_settings,
                                   monkeypatch, engine_code, expect, err_code):
    monkeypatch.setattr("carla_asset.builder.subprocess.run",
                        lambda *a, **kw: _FakeProc(engine_code))
    rpt = build_asset("vehicle", str(_manifest(tmp_path)),
                      settings=_engine_settings(make_settings, ue_env))
    assert rpt.exit_code == expect
    assert rpt.details["engine_exit_code"] == engine_code
    if err_code:
        assert any(i.code == err_code for i in rpt.issues)


def test_builder_spawn_failure_maps_to_2(tmp_path, ue_env, make_settings, monkeypatch):
    def raise_os(*a, **kw):
        raise OSError("CreateProcess failed")
    monkeypatch.setattr("carla_asset.builder.subprocess.run", raise_os)
    rpt = build_asset("vehicle", str(_manifest(tmp_path)),
                      settings=_engine_settings(make_settings, ue_env))
    assert rpt.exit_code == int(ExitCode.ENGINE_INTERNAL_ERROR)
    assert any(i.code == "ENGINE_SPAWN_FAIL" for i in rpt.issues)
