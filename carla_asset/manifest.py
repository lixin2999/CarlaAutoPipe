"""Manifest 契约层：Schema 校验、make/model 强制小写归一化、交叉一致性检查。

工程纪律（V1.2 §6.4）：make/model 在 Manifest 中可任意书写，但注入蓝图库与
生态调用时强制全小写。所有校验失败映射退出码 1（ASSET_VALIDATION_FAIL）。
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Optional, Tuple

from jsonschema import Draft7Validator

from .constants import BLUEPRINT_PARENT
from .report import Report

from .config import REPO_ROOT

SCHEMA_DIR = REPO_ROOT / "schemas"

_validator_cache = {}


def _load_schema(kind: str) -> dict:
    if kind not in _validator_cache:
        schema_file = SCHEMA_DIR / f"{kind}.schema.json"
        if not schema_file.is_file():
            raise FileNotFoundError(f"Schema 文件缺失: {schema_file.as_posix()}")
        _validator_cache[kind] = json.loads(schema_file.read_text(encoding="utf-8"))
    return _validator_cache[kind]


def find_error_line(manifest_path: Path, keyword: str) -> Optional[int]:
    """在 Manifest 原文中定位包含关键字的行号（GUI 高亮跳转用）。"""
    try:
        for idx, line in enumerate(
                manifest_path.read_text(encoding="utf-8").splitlines(), start=1):
            if keyword in line:
                return idx
    except OSError:
        return None
    return None


def validate_manifest(manifest_path: str | Path, kind: str,
                      report: Optional[Report] = None) -> Tuple[bool, dict]:
    """对 Manifest 执行 JSON Schema + 交叉一致性校验。

    :param kind: "vehicle" 或 "map"
    :returns: (是否通过, 归一化后的 Manifest dict)
    """
    path = Path(str(manifest_path).replace("\\", "/"))
    rpt = report if report is not None else Report(command="manifest")

    if not path.is_file():
        rpt.add_error("MFT_NOT_FOUND", f"Manifest 文件不存在: {path.as_posix()}",
                      "检查 --manifest 参数路径", path.as_posix())
        return False, {}

    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as e:
        rpt.add_error("MFT_BAD_JSON", f"Manifest JSON 解析失败: {e}",
                      "检查 JSON 语法（逗号/引号/括号配对）", path.as_posix(), e.lineno)
        return False, {}

    schema = _load_schema(kind)
    validator = Draft7Validator(schema)
    errors = sorted(validator.iter_errors(data), key=lambda e: list(e.absolute_path))
    for err in errors:
        field = "/".join(str(p) for p in err.absolute_path) or "(root)"
        line = find_error_line(path, field.split("/")[-1] if "/" in field else field)
        rpt.add_error("MFT_SCHEMA_FAIL",
                      f"Schema 校验失败 [{field}]: {err.message}",
                      "对照 schemas/ 目录下对应 Schema 修正该字段",
                      path.as_posix(), line)

    # ---- 交叉一致性校验（Schema 无法表达的部分） ----
    if kind == "vehicle":
        v = data.get("vehicle", {})
        make, model = str(v.get("make", "")), str(v.get("model", ""))
        # 车轮数与骨骼/象限一致性提示
        if v.get("wheels") == 2 and v.get("base_type") not in ("motorcycle", "bicycle"):
            rpt.add_warning("VEH_WHEEL_BASETYPE",
                            "两轮车辆的 base_type 建议为 motorcycle/bicycle",
                            "确认动力学模板选择正确", path.as_posix())
        if (data.get("registration") or {}).get("blueprint_parent") not in (None, BLUEPRINT_PARENT):
            rpt.add_error("VEH_REDLINE_PARENT",
                          f"蓝图父类必须为 {BLUEPRINT_PARENT}（绝对红线）",
                          "修改 registration.blueprint_parent", path.as_posix())
        # 归一化：强制小写（工程纪律）
        if make:
            v["make"] = make.lower()
        if model:
            v["model"] = model.lower()
        data["vehicle"] = v
    elif kind == "map":
        m = data.get("map", {})
        xodr = Path(str(m.get("xodr_path", "")).replace("\\", "/")).name
        fbx = Path(str(m.get("terrain_fbx_path", "")).replace("\\", "/")).stem
        # FBX 与 XODR 文件名一致性（ERROR 级，V1.2 §4.1 地图校验项）
        if xodr and fbx and xodr.rsplit(".", 1)[0].lower() != fbx.lower():
            rpt.add_error("MAP_XODR_FBX_NAME_MISMATCH",
                          f"XODR 文件名 ({xodr}) 与地形 FBX 名称 ({fbx}) 不一致",
                          "重命名使两者主文件名相同（不区分大小写）", path.as_posix())
        if m.get("track") == "custom_material" and not m.get("texture_dir"):
            rpt.add_error("MAP_CUSTOM_TEX_DIR",
                          "自定义材质轨必须声明 texture_dir 以校验纹理完整性",
                          "在 map.texture_dir 中填写纹理目录", path.as_posix())
        if m.get("track") == "custom_material" and m.get("material_adapt", True):
            rpt.add_warning("MAP_CUSTOM_ADAPT_ON",
                            "自定义材质轨建议关闭 material_adapt",
                            '设置 "material_adapt": false', path.as_posix())

    return not rpt.has_error, data


def vehicle_asset_id(manifest: dict) -> str:
    """生成 vehicle.<make>.<model> 检索标识（全小写，生态兼容）。"""
    v = manifest["vehicle"]
    return f"vehicle.{v['make'].lower()}.{v['model'].lower()}"


def blueprint_names(manifest: dict) -> dict:
    """按命名规范（V1.2 附录）派生全套资产名，ModelName 首字母大写。"""
    v = manifest["vehicle"]
    model = v["model"].lower()
    model_name = model[:1].upper() + model[1:]
    return {
        "vehicle_bp": f"BP_{model_name}",
        "anim_bp": f"AnimBP_{model_name}",
        "front_wheel_bp": f"{model_name}_FrontWheel",
        "rear_wheel_bp": f"{model_name}_RearWheel",
        "physics_asset": f"{model_name}_PhysicsAsset",
        "skeletal_mesh": f"SK_{model_name}",
        "blueprint_dir": f"/Game/Carla/Blueprints/Vehicles/{model_name}/",
    }
