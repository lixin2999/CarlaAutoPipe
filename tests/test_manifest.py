"""Manifest Schema 校验、小写归一化、交叉一致性单测。"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from carla_asset.constants import ExitCode
from carla_asset.manifest import (blueprint_names, vehicle_asset_id,
                                  validate_manifest)
from carla_asset.report import Report

_REPO = Path(__file__).resolve().parent.parent
REPO_MANIFEST = _REPO / "manifests" / "vehicles" / "su7.json"
REPO_MAP_MANIFEST = _REPO / "manifests" / "maps" / "town10.json"


def _vehicle_doc(**overrides):
    doc = {
        "target_carla": "0.9.16",
        "vehicle": {
            "make": "xiaomi", "model": "su7", "class": "car",
            "generation": 1, "wheels": 4, "base_type": "car",
            "mesh": {"unit": "cm", "forward_axis": "+X", "up_axis": "+Z"},
            "physics_asset": {
                "body_type": "SingleConvexHull", "wheel_primitive": "Sphere",
                "wheel_physics_type": "Kinematic", "generate_hit_events": True,
            },
        },
        "registration": {
            "vehicle_factory_path":
                "/Game/Carla/Blueprints/Vehicles/VehicleFactory.VehicleFactory",
            "blueprint_parent": "BaseVehiclePawn", "skip_factory": False,
        },
        "golden_template_checksum": (
            "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855"),
    }
    v = doc["vehicle"]
    for key, value in overrides.items():
        if key in v and not isinstance(v[key], dict):
            v[key] = value
        else:
            doc[key] = value
    return doc


def _write(tmp_path, doc, name="m.json"):
    p = tmp_path / name
    p.write_text(json.dumps(doc, ensure_ascii=False), encoding="utf-8")
    return p


def test_repo_sample_vehicle_passes():
    rpt = Report(command="test")
    ok, data = validate_manifest(REPO_MANIFEST, "vehicle", rpt)
    assert ok, rpt.issues
    assert data["vehicle"]["model"] == "su7"


def test_repo_sample_map_passes():
    rpt = Report(command="test")
    ok, _ = validate_manifest(REPO_MAP_MANIFEST, "map", rpt)
    assert ok, rpt.issues


def test_missing_file(tmp_path):
    rpt = Report(command="test")
    ok, _ = validate_manifest(tmp_path / "nope.json", "vehicle", rpt)
    assert not ok
    assert any(i.code == "MFT_NOT_FOUND" and i.level == "ERROR" for i in rpt.issues)


def test_bad_json(tmp_path):
    p = tmp_path / "bad.json"
    p.write_text("{ not json ", encoding="utf-8")
    rpt = Report(command="test")
    ok, _ = validate_manifest(p, "vehicle", rpt)
    assert not ok
    assert any(i.code == "MFT_BAD_JSON" for i in rpt.issues)


def test_schema_violation_wheels(tmp_path):
    p = _write(tmp_path, _vehicle_doc(wheels=6))
    rpt = Report(command="test")
    ok, _ = validate_manifest(p, "vehicle", rpt)
    assert not ok
    err = next(i for i in rpt.issues if i.level == "ERROR")
    assert err.code == "MFT_SCHEMA_FAIL"
    assert err.file.endswith("m.json")


def test_redline_blueprint_parent(tmp_path):
    doc = _vehicle_doc()
    doc["registration"]["blueprint_parent"] = "Pawn"
    rpt = Report(command="test")
    ok, _ = validate_manifest(_write(tmp_path, doc), "vehicle", rpt)
    assert not ok  # Schema const 与交叉校验双重拦截


@pytest.mark.parametrize("make,model", [
    ("Xiaomi", "SU7"), ("XIAOMI", "Su7"), ("xiaomi", "su7")])
def test_lowercase_normalization(tmp_path, make, model):
    rpt = Report(command="test")
    ok, data = validate_manifest(_write(tmp_path, _vehicle_doc(make=make, model=model)),
                                 "vehicle", rpt)
    assert ok
    assert data["vehicle"]["make"] == "xiaomi"
    assert data["vehicle"]["model"] == "su7"
    assert vehicle_asset_id(data) == "vehicle.xiaomi.su7"


def test_two_wheel_basetype_warning(tmp_path):
    rpt = Report(command="test")
    ok, _ = validate_manifest(_write(tmp_path, _vehicle_doc(wheels=2, base_type="car")),
                              "vehicle", rpt)
    assert ok  # WARNING 不阻断
    assert any(i.level == "WARNING" and i.code == "VEH_WHEEL_BASETYPE" for i in rpt.issues)


def test_map_xodr_fbx_mismatch(tmp_path):
    doc = {
        "target_carla": "0.9.16",
        "map": {
            "map_name": "Town11",
            "xodr_path": "raw/maps/town11/Town11.xodr",
            "terrain_fbx_path": "raw/maps/town11/terrain.fbx",
            "navmesh_settings": {"enable_vehicle_nav": True,
                                 "enable_pedestrian_nav": True},
        },
    }
    rpt = Report(command="test")
    ok, _ = validate_manifest(_write(tmp_path, doc), "map", rpt)
    assert not ok
    assert any(i.code == "MAP_XODR_FBX_NAME_MISMATCH" for i in rpt.issues)


def test_map_custom_material_requires_texture_dir(tmp_path):
    doc = {
        "target_carla": "0.9.16",
        "map": {
            "map_name": "Town12",
            "track": "custom_material",
            "xodr_path": "raw/maps/town12/Town12.xodr",
            "terrain_fbx_path": "raw/maps/town12/Town12.fbx",
            "material_adapt": False,
            "navmesh_settings": {"enable_vehicle_nav": True,
                                 "enable_pedestrian_nav": False},
        },
    }
    rpt = Report(command="test")
    ok, _ = validate_manifest(_write(tmp_path, doc), "map", rpt)
    assert not ok
    assert any(i.code == "MAP_CUSTOM_TEX_DIR" for i in rpt.issues)


def test_blueprint_names_convention():
    _, data = validate_manifest(REPO_MANIFEST, "vehicle")
    names = blueprint_names(data)
    assert names["vehicle_bp"] == "BP_Su7"
    assert names["anim_bp"] == "AnimBP_Su7"
    assert names["front_wheel_bp"] == "Su7_FrontWheel"
    assert names["physics_asset"] == "Su7_PhysicsAsset"
    assert names["skeletal_mesh"] == "SK_Su7"
    assert names["blueprint_dir"] == "/Game/Carla/Blueprints/Vehicles/Su7/"


def test_report_exit_after_schema_fail(tmp_path):
    rpt = Report(command="build-vehicle")
    ok, _ = validate_manifest(_write(tmp_path, _vehicle_doc(wheels=3)), "vehicle", rpt)
    assert not ok
    rpt.finish(int(ExitCode.ASSET_VALIDATION_FAIL))
    assert rpt.exit_code == 1
