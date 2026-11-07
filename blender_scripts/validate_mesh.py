"""Blender 后台前置校验脚本（运行于 ``blender --background --python`` 进程内）。

由 ``carla_asset/validate.py`` 拉起，错误分级（V1.2 §4.1）：
- ERROR   致命，阻断流程（非厘米制/轴向错误/车轮未独立/骨骼不符/原点未接地/非等比缩放）
- WARNING 严重，输出修复建议
- INFO    优化提示

用法（Blender 侧）::

    blender --background --factory-startup --python validate_mesh.py -- \
        --type vehicle --fbx <path> --report <out.json> [--xodr <path>] [--manifest <path>]

退出码：0 通过 / 1 存在 ERROR / 2 脚本自身异常。
纯算法复用 carla_asset.geoalgo（通过 sys.path 引入，保证与单元测试同一实现）。
"""

import argparse
import json
import math
import sys
import traceback
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from carla_asset.geoalgo import (assign_wheel_quadrants, bbox_dims,  # noqa: E402
                                 bbox_volume, is_wheel_candidate)

try:
    import mathutils          # 仅 Blender 进程内可用（validate_map 无 bpy 形参）
except ImportError:           # flake8 F821 守护：静态检查环境下允许缺失
    mathutils = None

ISSUES = []


def issue(level, code, message, suggestion="", file=None):
    ISSUES.append({"level": level, "code": code, "message": message,
                   "suggestion": suggestion, "file": file})


def has_error():
    return any(i["level"] == "ERROR" for i in ISSUES)


# ---------------------------------------------------------------------------
# 车辆校验
# ---------------------------------------------------------------------------
def validate_vehicle(bpy, fbx_path: Path, manifest: dict):
    # 1. 单位：读取 FBX 场景全局缩放，强制 1 单位 = 1 厘米
    scene = bpy.context.scene
    unit_scale = scene.unit_settings.scale_length
    if abs(unit_scale - 0.01) > 1e-6 and abs(unit_scale - 1.0) > 1e-6:
        issue("ERROR", "VEH_UNIT_NOT_CM",
              f"场景单位缩放 {unit_scale} 非厘米制（要求 1 单位 = 1 cm）",
              "在 Blender Scene>Units 中将 Unit Scale 设为 0.01 或 1.0(厘米场景)",
              str(fbx_path))

    # 2. 非等比缩放拦截（导致球形碰撞体失效）
    for obj in bpy.data.objects:
        if obj.type != "MESH":
            continue
        sx, sy, sz = obj.scale
        if not (math.isclose(sx, sy, rel_tol=0.01) and math.isclose(sy, sz, rel_tol=0.01)):
            issue("ERROR", "VEH_NON_UNIFORM_SCALE",
                  f"对象 {obj.name} 存在非等比缩放 ({sx:.3f},{sy:.3f},{sz:.3f})",
                  "应用缩放 Ctrl+A > Scale 后重新导出", str(fbx_path))

    # 3. 网格分件与车轮聚类识别
    meshes = [o for o in bpy.data.objects if o.type == "MESH"]
    if not meshes:
        issue("ERROR", "VEH_NO_MESH", "FBX 中无任何网格对象", "检查导出选项", str(fbx_path))
        return
    total_vol = 0.0
    dims_map = {}
    for o in meshes:
        corners = [o.matrix_world @ mathutils.Vector(c) for c in o.bound_box]
        mn = [min(c[i] for c in corners) for i in range(3)]
        mx = [max(c[i] for c in corners) for i in range(3)]
        d = bbox_dims(mn, mx)
        dims_map[o.name] = (d, mn, mx)
        total_vol += bbox_volume(d)

    wheels = [name for name, (d, _, _) in dims_map.items()
              if is_wheel_candidate(d, bbox_volume(d), total_vol)]
    declared = int((manifest.get("vehicle") or {}).get("wheels", 4)) if manifest else 4
    if len(wheels) not in (2, 4):
        issue("ERROR", "VEH_WHEELS_NOT_SPLIT",
              f"通过盘状度+体积占比识别到 {len(wheels)} 个车轮候选，"
              f"与声明值 {declared} 不符（要求车轮独立分件）",
              "将每个车轮拆分为独立 Object 后再导出 FBX", str(fbx_path))
    elif len(wheels) != declared:
        issue("ERROR", "VEH_WHEEL_COUNT_MISMATCH",
              f"识别车轮数 {len(wheels)} 与 Manifest wheels={declared} 不一致",
              "修正 Manifest 或模型分件", str(fbx_path))
    else:
        # 象限排序校验（FL/FR/RL/RR）
        centers = []
        for name in wheels:
            d, mn, mx = dims_map[name]
            centers.append(tuple((a + b) / 2 for a, b in zip(mn, mx)))
        try:
            assign_wheel_quadrants(centers)
        except ValueError as e:
            issue("WARNING", "VEH_WHEEL_QUADRANT", f"车轮象限排布异常: {e}",
                  "检查四轮是否位于标准象限（±X ±Y）", str(fbx_path))

    # 4. 骨骼合规性：对照标准五骨骨架
    from carla_asset.constants import (SKELETON_ALL_BONES, SKELETON_BASE_BONE,
                                       SKELETON_WHEEL_BONES)
    armatures = [o for o in bpy.data.objects if o.type == "ARMATURE"]
    if not armatures:
        issue("ERROR", "VEH_NO_SKELETON", "缺少骨架对象（要求标准五骨骨架）",
              "执行 carla-asset rig 自动绑骨，或按 VehicleSkeleton.fbx 标准绑骨",
              str(fbx_path))
    else:
        names = {b.name for b in armatures[0].data.bones}
        missing = [b for b in (SKELETON_BASE_BONE, *SKELETON_WHEEL_BONES[:declared - 2 + 2])
                   if b not in names] if declared == 4 else \
                  [b for b in (SKELETON_BASE_BONE, "FL_Wheel", "RL_Wheel") if b not in names]
        if missing:
            issue("ERROR", "VEH_BONES_MISSING",
                  f"骨骼缺失: {missing}（标准骨架: {list(SKELETON_ALL_BONES)}）",
                  "骨骼名称/层级必须完全匹配标准骨架（红线：不得改名）", str(fbx_path))

    # 5. 原点接地：全场最低点（轮胎底）应约等于 Z=0
    global_min_z = min(v[1][2] for v in dims_map.values())
    if abs(global_min_z) > 5.0:
        issue("ERROR", "VEH_ORIGIN_NOT_GROUNDED",
              f"轮胎最低点 Z={global_min_z:.1f}cm 偏离地面过远（要求≈0）",
              "将模型整体沿 Z 平移使轮胎接触地面后重导出", str(fbx_path))

    # 6. LOD 面数提示
    tris = sum(len(o.data.polygons) for o in meshes)
    if tris > 100000:
        issue("WARNING", "VEH_LOD0_POLY_HIGH",
              f"网格总三角面约 {tris}，超过 LOD0 建议上限 10 万",
              "减面或提供 LOD1/LOD2", str(fbx_path))

    # 7. 纹理命名规范
    for mat in bpy.data.materials:
        if not mat.use_nodes:
            continue
        for node in mat.node_tree.nodes:
            if node.type == "TEX_IMAGE" and node.image:
                nm = node.image.name
                if not any(s in nm for s in ("_Diff", "_Norm", "_Spec")):
                    issue("INFO", "VEH_TEX_NAMING",
                          f"纹理 {nm} 未按 T_CarPart_<Model>_<Type> 规范命名",
                          "建议后缀 _Diff/_Norm/_Spec")


def validate_map(bpy, fbx_path: Path, xodr_path: Path | None):
    import xml.etree.ElementTree as ET

    scene = bpy.context.scene
    if abs(scene.unit_settings.scale_length - 0.01) > 1e-6 and \
            abs(scene.unit_settings.scale_length - 1.0) > 1.0e-6:
        issue("ERROR", "MAP_UNIT_NOT_CM", "地图场景单位非厘米制",
              "Scene>Units 设为厘米", str(fbx_path))

    meshes = [o for o in bpy.data.objects if o.type == "MESH"]
    if not meshes:
        issue("ERROR", "MAP_NO_MESH", "地形 FBX 中无网格对象", "检查导出内容", str(fbx_path))
        return

    # 地形包围盒
    corners = []
    for o in meshes:
        corners += [o.matrix_world @ mathutils.Vector(c) for c in o.bound_box]
    mn = [min(c[i] for c in corners) for i in range(3)]
    mx = [max(c[i] for c in corners) for i in range(3)]

    # FBX 与 XODR 名称一致性
    if xodr_path:
        if not xodr_path.is_file():
            issue("ERROR", "MAP_XODR_MISSING", f"XODR 文件不存在: {xodr_path}",
                  "检查 --xodr 参数")
        else:
            if xodr_path.stem.lower() != fbx_path.stem.lower():
                issue("ERROR", "MAP_XODR_FBX_NAME_MISMATCH",
                      f"XODR({xodr_path.name}) 与 FBX({fbx_path.name}) 主文件名不一致",
                      "重命名保持一致", str(fbx_path))
            # 路网边界 vs 地形范围
            try:
                root = ET.parse(xodr_path).getroot()
                xs, ys = [], []
                for geo in root.iter("geometry"):
                    xs.append(float(geo.get("x", 0)))
                    ys.append(float(geo.get("y", 0)))
                if xs and ys:
                    pad = 100.0  # 1m 容差（厘米制）
                    in_x = mn[0] - pad <= min(xs) and max(xs) <= mx[0] + pad
                    in_y = mn[1] - pad <= min(ys) and max(ys) <= mx[1] + pad
                    if not (in_x and in_y):
                        issue("ERROR", "MAP_ROAD_OUT_OF_TERRAIN",
                              f"路网边界 X[{min(xs):.0f},{max(xs):.0f}] "
                              f"Y[{min(ys):.0f},{max(ys):.0f}] 超出地形范围 "
                              f"X[{mn[0]:.0f},{mx[0]:.0f}] Y[{mn[1]:.0f},{mx[1]:.0f}]",
                              "扩大地形或裁减路网", str(xodr_path))
            except ET.ParseError as e:
                issue("ERROR", "MAP_XODR_PARSE", f"XODR XML 解析失败: {e}",
                      "校验 XODR 文件语法", str(xodr_path))

    # 悬空顶点/非流形提示
    dangling = 0
    for o in meshes:
        if o.data and hasattr(o.data, "has_custom_normals"):
            pass
        for poly in o.data.polygons:
            if poly.area <= 1e-9:
                dangling += 1
    if dangling:
        issue("WARNING", "MAP_DEGENERATE_FACES",
              f"存在 {dangling} 个退化面（面积≈0）",
              "Mesh>Clean Up>Degenerate Dissolve 清理", str(fbx_path))


# ---------------------------------------------------------------------------
# 主流程
# ---------------------------------------------------------------------------
def main():
    argv = sys.argv
    argv = argv[argv.index("--") + 1:] if "--" in argv else []
    ap = argparse.ArgumentParser()
    ap.add_argument("--type", choices=["vehicle", "map"], required=True)
    ap.add_argument("--fbx", required=True)
    ap.add_argument("--report", required=True)
    ap.add_argument("--xodr")
    ap.add_argument("--manifest")
    args = ap.parse_args(argv)

    fbx = Path(args.fbx)
    out = Path(args.report)
    manifest = {}
    if args.manifest and Path(args.manifest).is_file():
        manifest = json.loads(Path(args.manifest).read_text(encoding="utf-8"))

    code = 0
    try:
        import bpy           # noqa: F401  仅 Blender 进程内可用
        bpy.ops.wm.read_factory_settings(use_empty=True)
        if not bpy.ops.import_scene.fbx(filepath=str(fbx)):
            issue("ERROR", "FBX_IMPORT_FAIL", f"FBX 导入失败: {fbx}",
                  "确认文件未损坏且为 FBX 2013+ 格式", str(fbx))
        else:
            if args.type == "vehicle":
                validate_vehicle(bpy, fbx, manifest)
            else:
                validate_map(bpy, fbx, Path(args.xodr) if args.xodr else None)
    except Exception:        # noqa: BLE001
        traceback.print_exc()
        code = 2

    summary = {"error": sum(i["level"] == "ERROR" for i in ISSUES),
               "warning": sum(i["level"] == "WARNING" for i in ISSUES),
               "info": sum(i["level"] == "INFO" for i in ISSUES)}
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps({"issues": ISSUES, "summary": summary},
                              ensure_ascii=False, indent=2), encoding="utf-8")
    sys.exit(1 if has_error() else code)


if __name__ == "__main__":
    main()
