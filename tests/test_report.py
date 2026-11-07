"""统一 JSON 报告模型：序列化往返、路径归一、退出码推断。"""

from __future__ import annotations

from carla_asset.constants import ExitCode, Level, REPORT_SCHEMA_VERSION
from carla_asset.report import Report, environment_error


def test_issue_path_normalized_to_posix():
    r = Report(command="validate")
    r.add_error("X", "msg", "fix", file="assets\\vehicles\\su7.fbx")
    assert r.issues[0].file == "assets/vehicles/su7.fbx"


def test_finish_infers_validation_fail():
    r = Report(command="validate")
    r.add_error("X", "boom")
    r.finish()
    assert r.exit_code == int(ExitCode.ASSET_VALIDATION_FAIL)


def test_finish_explicit_code_wins():
    r = Report(command="inject")
    r.add_error("X", "boom")
    r.finish(int(ExitCode.ENGINE_INTERNAL_ERROR))
    assert r.exit_code == 2


def test_warning_only_stays_success():
    r = Report(command="rig")
    r.add_warning("W", "harmless")
    r.finish()
    assert r.exit_code == int(ExitCode.SUCCESS)
    assert r.counts()[Level.WARNING] == 1


def test_environment_error_factory():
    r = environment_error("validate", "ENV_BLENDER_MISSING", "no blender", "install it")
    assert r.exit_code == int(ExitCode.ENVIRONMENT_ERROR)
    assert r.issues[0].code == "ENV_BLENDER_MISSING"
    assert r.duration_sec is not None


def test_save_load_roundtrip(tmp_path):
    r = Report(command="build-vehicle", asset_name="vehicle.xiaomi.su7")
    r.add_error("TPL_HASH_MISMATCH", "哈希不符", "恢复模板", "manifests/vehicles/su7.json", 35)
    r.add_info("OK", "done")
    r.artifacts.append("reports/su7.engine.json")
    r.details["engine_exit_code"] = 3
    r.finish(int(ExitCode.ENVIRONMENT_ERROR))

    path = r.save(tmp_path / "sub" / "report.json")   # 自动建父目录
    assert path.is_file()

    loaded = Report.load(path)
    assert loaded.command == "build-vehicle"
    assert loaded.asset_name == "vehicle.xiaomi.su7"
    assert loaded.exit_code == 3
    assert loaded.duration_sec == r.duration_sec
    assert loaded.details["engine_exit_code"] == 3
    assert len(loaded.issues) == 2
    assert loaded.issues[0].line == 35
    assert loaded.issues[0].suggestion == "恢复模板"
    assert loaded.issues[1].level == Level.INFO


def test_saved_json_contains_schema_version(tmp_path):
    import json
    p = Report(command="pack").save(tmp_path / "r.json")
    data = json.loads(p.read_text(encoding="utf-8"))
    assert data["schema_version"] == REPORT_SCHEMA_VERSION
    assert "issue_counts" in data
