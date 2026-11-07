"""纯几何算法层（无 bpy 依赖，可单测；Blender 脚本与 CLI 共用）。

包含车轮聚类识别与象限排序等核心算法（V1.2 §4.1）：
- 盘状度：包围盒 X≈Z ≫ Y；
- 体积占比：0.8% ~ 5%；
- 象限排序：按 (+X 前 / -X 后, +Y 左 / -Y 右) 分为 FL/FR/RL/RR。
"""

from __future__ import annotations

from typing import Dict, List, Sequence, Tuple

from .constants import (WHEEL_DISKNESS_Y_RATIO, WHEEL_VOLUME_RATIO_MAX,
                        WHEEL_VOLUME_RATIO_MIN)


def bbox_dims(min_corner: Sequence[float],
              max_corner: Sequence[float]) -> Tuple[float, float, float]:
    """包围盒三轴尺寸 (dx, dy, dz)。"""
    return tuple(abs(max_corner[i] - min_corner[i]) for i in range(3))  # type: ignore[return-value]


def bbox_volume(dims: Sequence[float]) -> float:
    dx, dy, dz = dims
    return max(dx, 0.0) * max(dy, 0.0) * max(dz, 0.0)


def is_disc_shaped(dims: Sequence[float]) -> bool:
    """盘状度判定：X≈Z（圆形轮面）且 Y 显著小于 X/Z（厚度）。

    车头方向为 +X，车辆左右为 Y 轴——车轮厚度沿 Y。
    """
    dx, dy, dz = dims
    if dx <= 0 or dz <= 0:
        return False
    xz_close = abs(dx - dz) / max(dx, dz) <= 0.25          # X≈Z
    thin = (dy / ((dx + dz) / 2.0)) <= WHEEL_DISKNESS_Y_RATIO  # Y ≪ X,Z
    return xz_close and thin


def is_wheel_candidate(dims: Sequence[float], volume: float,
                       total_volume: float) -> bool:
    """双重特征：盘状度 + 体积占比 0.8%~5%。"""
    if total_volume <= 0:
        return False
    ratio = volume / total_volume
    return is_disc_shaped(dims) and WHEEL_VOLUME_RATIO_MIN <= ratio <= WHEEL_VOLUME_RATIO_MAX


def assign_wheel_quadrants(centers: List[Tuple[float, float, float]]
                           ) -> Dict[str, Tuple[float, float, float]]:
    """将识别出的车轮中心按象限排序为 FL/FR/RL/RR。

    约定（与 CARLA 标准骨架一致）：+X 为车头方向，+Y 为车辆左侧。
    - FL: x>0, y>0    FR: x>0, y<0
    - RL: x<0, y>0    RR: x<0, y<0
    :raises ValueError: 车轮数量不是 2 或 4，或象限冲突
    """
    if len(centers) not in (2, 4):
        raise ValueError(f"车轮数量必须为 2 或 4，实际 {len(centers)}")
    result: Dict[str, Tuple[float, float, float]] = {}
    for c in centers:
        front = c[0] >= 0
        left = c[1] >= 0
        if len(centers) == 4:
            key = ("FL" if left else "FR") if front else ("RL" if left else "RR")
        else:  # 两轮车：FL/RL（左侧前后），保持与骨架骨骼子集一致
            key = "FL" if front else "RL"
        if key in result:
            raise ValueError(f"车轮象限冲突：{key} 出现多次， centers={centers}")
        result[key] = c
    expected = (["FL", "FR", "RL", "RR"] if len(centers) == 4 else ["FL", "RL"])
    if sorted(result) != sorted(expected):
        raise ValueError(f"车轮象限不完整，期望 {expected}，实际 {sorted(result)}")
    return result


def ground_contact_ok(min_z: float, wheel_radius: float,
                      tolerance_cm: float = 2.0) -> bool:
    """原点接地校验：轮胎最低点应约等于 0（|min_z| ≤ tolerance）。"""
    return abs(min_z) <= tolerance_cm
