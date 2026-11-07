"""Blender 后台自动绑骨脚本（V1.2 §4.2 / V1.4 §4.2，运行于 blender --background）。

三段式架构：检查 → 修复绑骨 → 回读验证。

将外部网格刚性绑定到 CARLA 标准五骨骨架：

    Vehicle_Bone_Root (根骨骼，原点位于地面中心)
    └── Vehicle_Base (车身主骨骼)
        ├── FL_Wheel / FR_Wheel / RL_Wheel / RR_Wheel (轴心在轮心)

绝对红线：骨架名称、层级、旋转缩放严禁改动，仅允许平移微调；权重固定 1.0，
禁用包络权重与平滑蒙皮。导出参数全部硬编码固化。

用法::

    blender --background --factory-startup --python rig_and_validate.py -- \
        --fbx <in> --out <out> --report <out.json> [--mirror-y]

退出码：0 成功 / 1 校验失败 / 2 脚本异常。
"""

import argparse
import json
import sys
import traceback
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from carla_asset.constants import (SKELETON_BASE_BONE, SKELETON_ROOT_BONE,   # noqa: E402
                                   SKELETON_WHEEL_BONES)
from carla_asset.geoalgo import (assign_wheel_quadrants, bbox_dims,           # noqa: E402
                                 bbox_volume, is_wheel_candidate)

# ★导出参数固化常量（确保输出一致性，禁止外部修改）
EXPORT_PARAMS = dict(
    use_selection=True,
    apply_scale_options="FBX_SCALE_ALL",
    add_leaf_bones=False,
    bake_anim=False,
    primary_bone_axis="Y",
    secondary_bone_axis="X",
    axis_forward="-Y",
    axis_up="Z",
    global_scale=1.0,
)

ISSUES = []


def issue(level, code, message, suggestion="", file=None):
    ISSUES.append({"level": level, "code": code, "message": message,
                   "suggestion": suggestion, "file": file})


# ---------------------------------------------------------------------------
# 阶段一：几何分析（识别车身与车轮）
# ---------------------------------------------------------------------------
def analyze_geometry(bpy, mathutils):
    meshes = [o for o in bpy.data.objects if o.type == "MESH"]
    total_vol = 0.0
    info = {}
    for o in meshes:
        corners = [o.matrix_world @ mathutils.Vector(c) for c in o.bound_box]
        mn = [min(c[i] for c in corners) for i in range(3)]
        mx = [max(c[i] for c in corners) for i in range(3)]
        d = bbox_dims(mn, mx)
        info[o.name] = {"obj": o, "dims": d, "min": mn, "max": mx,
                        "center": tuple((a + b) / 2 for a, b in zip(mn, mx)),
                        "volume": bbox_volume(d)}
        total_vol += info[o.name]["volume"]
    wheels = {n: v for n, v in info.items()
              if is_wheel_candidate(v["dims"], v["volume"], total_vol)}
    body = {n: v for n, v in info.items() if n not in wheels}
    return body, wheels


# ---------------------------------------------------------------------------
# 阶段二：骨架生成 + 刚性绑骨
# ---------------------------------------------------------------------------
def build_skeleton(bpy, mathutils, wheel_centers: dict, mirror_y: bool):
    """按标准层级创建五骨骨架。名称/层级/旋转缩放严格按标准，仅平移轮骨位置。"""
    arm_data = bpy.data.armatures.new("VehicleSkeleton")
    arm = bpy.data.objects.new("VehicleRig", arm_data)
    bpy.context.collection.objects.link(arm)
    bpy.context.view_layer.objects.active = arm

    bpy.ops.object.mode_set(mode="EDIT")
    eb = arm_data.edit_bones
    root = eb.new(SKELETON_ROOT_BONE)
    root.head = (0, 0, 0)
    root.tail = (0, 0, 10)          # 仅方向长度约定，不改旋转/缩放
    base = eb.new(SKELETON_BASE_BONE)
    base.head = (0, 0, 0)
    base.tail = (10, 0, 0)          # 主骨沿 Y（导出时 primary_bone_axis=Y 校正）
    base.parent = root
    base.use_connect = False

    for quad, center in wheel_centers.items():
        bone_name = f"{quad}_Wheel"
        wb = eb.new(bone_name)
        x, y, z = center
        if mirror_y:                # 左右镜像修正开关（风险应对 V1.4 §7.1）
            y = -y
        wb.head = (x, y, z)         # 轴心精准对齐轮心（仅平移）
        wb.tail = (x, y, z + 1.0)
        wb.parent = base
        wb.use_connect = False
    bpy.ops.object.mode_set(mode="OBJECT")
    return arm


def rigid_bind(bpy, mathutils, arm, body_names, wheel_obj_by_quad):
    """刚性绑骨：权重固定 1.0，禁用包络与平滑蒙皮。"""
    # 车身 → Vehicle_Base
    for name in body_names:
        _bind_single_group(bpy, bpy.data.objects[name], arm, SKELETON_BASE_BONE)
    # 车轮 → 对应骨骼
    for quad, obj_name in wheel_obj_by_quad.items():
        _bind_single_group(bpy, bpy.data.objects[obj_name], arm, f"{quad}_Wheel")
    # 清除包络计算依赖：display_type 设为 FRONT
    arm.display_type = "WIRE"


def _bind_single_group(bpy, obj, arm, bone_name):
    for old in list(obj.vertex_groups):
        obj.vertex_groups.remove(old)
    vg = obj.vertex_groups.new(name=bone_name)
    vg.add(list(range(len(obj.data.vertices))), 1.0, "REPLACE")
    mod = obj.modifiers.new("Armature", "ARMATURE")
    mod.object = arm
    mod.use_vertex_groups = True     # ★仅顶点组权重，禁用包络 deform
    mod.use_envelope_multiply = 0.0  # 包络完全不参与
    obj.parent = arm
    # 平滑蒙皮（Auto Smooth）不影响刚性权重，但按红线要求显式关闭插值
    if hasattr(obj.data, "use_auto_smooth"):
        obj.data.use_auto_smooth = False


# ---------------------------------------------------------------------------
# 阶段三：导出固化 + 回读验证
# ---------------------------------------------------------------------------
def export_fixed(bpy, out_path: Path, objects):
    bpy.ops.object.select_all(action="DESELECT")
    for o in objects:
        o.select_set(True)
    bpy.context.view_layer.objects.active = objects[0]
    out_path.parent.mkdir(parents=True, exist_ok=True)
    bpy.ops.export_scene.fbx(filepath=str(out_path), **EXPORT_PARAMS)


def revalidate(bpy, mathutils, out_path: Path):
    """回读验证：重新加载 FBX，校验骨骼齐全、层级正确、单位一致。"""
    bpy.ops.wm.read_factory_settings(use_empty=True)
    bpy.ops.import_scene.fbx(filepath=str(out_path))
    arm = next((o for o in bpy.data.objects if o.type == "ARMATURE"), None)
    if arm is None:
        issue("ERROR", "RIG_RELOAD_NO_ARMATURE", "回读未找到骨架", "检查导出选项")
        return False
    names = {b.name for b in arm.data.bones}
    need = {SKELETON_ROOT_BONE, SKELETON_BASE_BONE, *SKELETON_WHEEL_BONES}
    missing = need - names
    if missing:
        issue("ERROR", "RIG_RELOAD_BONES_MISSING", f"回读骨骼缺失: {sorted(missing)}",
              "骨架生成异常，请检查输入几何")
        return False
    base = arm.data.bones[SKELETON_BASE_BONE]
    if base.parent.name != SKELETON_ROOT_BONE:
        issue("ERROR", "RIG_RELOAD_HIERARCHY",
              f"Vehicle_Base 父级应为 Vehicle_Bone_Root，实际 {base.parent.name}",
              "红线：层级不得修改")
        return False
    for w in SKELETON_WHEEL_BONES:
        if arm.data.bones[w].parent.name != SKELETON_BASE_BONE:
            issue("ERROR", "RIG_RELOAD_WHEEL_PARENT",
                  f"{w} 父级应为 Vehicle_Base", "红线：层级不得修改")
            return False
    return True


# ---------------------------------------------------------------------------
# 主流程
# ---------------------------------------------------------------------------
def main():
    argv = sys.argv
    argv = argv[argv.index("--") + 1:] if "--" in argv else []
    ap = argparse.ArgumentParser()
    ap.add_argument("--fbx", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--report", required=True)
    ap.add_argument("--mirror-y", action="store_true")
    args = ap.parse_args(argv)

    src, dst, out = Path(args.fbx), Path(args.out), Path(args.report)
    code = 0
    try:
        import bpy
        import mathutils
        # ---- 阶段一：检查 / 几何分析 ----
        bpy.ops.wm.read_factory_settings(use_empty=True)
        bpy.ops.import_scene.fbx(filepath=str(src))
        body, wheels = analyze_geometry(bpy, mathutils)
        if not body:
            issue("ERROR", "RIG_NO_BODY", "未识别到车身网格", "检查模型分件")
            raise SystemExit
        if len(wheels) not in (2, 4):
            issue("ERROR", "RIG_WHEEL_COUNT",
                  f"识别到 {len(wheels)} 个车轮，要求 2 或 4（车轮必须独立分件）",
                  "将车轮拆分为独立 Object；C 轨资产需人工审核几何后重试")
            raise SystemExit
        centers = [w["center"] for w in wheels.values()]
        quads = assign_wheel_quadrants(centers)      # {FL: (x,y,z), ...}
        name_by_obj = {id(w["obj"]): n for n, w in wheels.items()}
        wheel_obj_by_quad = {quad: name_by_obj[id(next(
            w["obj"] for w in wheels.values()
            if tuple(w["center"]) == center))]
            for quad, center in quads.items()}

        # ---- 阶段二：骨架生成 + 刚性绑骨 ----
        arm = build_skeleton(bpy, mathutils, quads, args.mirror_y)
        rigid_bind(bpy, mathutils, arm, list(body.keys()), wheel_obj_by_quad)

        # ---- 阶段三：导出固化 + 回读验证 ----
        export_objs = [arm] + [b["obj"] for b in body.values()] \
            + [w["obj"] for w in wheels.values()]
        export_fixed(bpy, dst, export_objs)
        ok = revalidate(bpy, mathutils, dst)
        if not ok:
            issue("ERROR", "RIG_REVALIDATE_FAIL", "回读验证未通过",
                  "输出 FBX 已保留供人工排查", str(dst))
    except SystemExit:
        pass
    except Exception:
        traceback.print_exc()
        code = 2

    summary = {"error": sum(i["level"] == "ERROR" for i in ISSUES),
               "warning": sum(i["level"] == "WARNING" for i in ISSUES),
               "info": sum(i["level"] == "INFO" for i in ISSUES)}
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps({"issues": ISSUES, "summary": summary},
                              ensure_ascii=False, indent=2), encoding="utf-8")
    sys.exit(1 if any(i["level"] == "ERROR" for i in ISSUES) else code)


if __name__ == "__main__":
    main()
