"""车轮聚类识别与象限排序纯算法单测（V1.2 §4.1）。"""

from __future__ import annotations

import pytest

from carla_asset.geoalgo import (assign_wheel_quadrants, bbox_dims,
                                 bbox_volume, ground_contact_ok,
                                 is_disc_shaped, is_wheel_candidate)

# 典型车轮包围盒：直径 70cm（X≈Z），厚度 25cm（Y），单位 cm
WHEEL_DIMS = (70.0, 25.0, 70.0)
BODY_DIMS = (450.0, 180.0, 120.0)


def test_bbox_dims_and_volume():
    dims = bbox_dims((-35, -12.5, -35), (35, 12.5, 35))
    assert dims == pytest.approx((70.0, 25.0, 70.0))
    assert bbox_volume(dims) == pytest.approx(70 * 25 * 70)


def test_disc_shape_detection():
    assert is_disc_shaped(WHEEL_DIMS)
    assert not is_disc_shaped(BODY_DIMS)        # 车身：扁平长方体
    assert not is_disc_shaped((70, 70, 70))     # 立方体：Y 不薄
    assert not is_disc_shaped((0, 10, 0))       # 退化包围盒


def test_volume_ratio_window():
    total = bbox_volume(BODY_DIMS)              # 9,720,000 cm³
    wheel = bbox_volume(WHEEL_DIMS)             # 122,500 cm³ → 占比 ≈ 1.26%
    assert is_wheel_candidate(WHEEL_DIMS, wheel, total)
    # 占比低于 0.8%：太小的装饰件不算车轮
    assert not is_wheel_candidate(WHEEL_DIMS, total * 0.001, total)
    # 占比高于 5%：大件不算车轮
    assert not is_wheel_candidate(WHEEL_DIMS, total * 0.08, total)
    # 非盘状即使占比合适也排除
    assert not is_wheel_candidate(BODY_DIMS, total * 0.02, total)
    # 总体积非法
    assert not is_wheel_candidate(WHEEL_DIMS, 100, 0)


def test_four_wheel_quadrants():
    centers = [(90, 80, -35), (90, -80, -35), (-90, 80, -35), (-90, -80, -35)]
    result = assign_wheel_quadrants(centers)
    assert result["FL"] == (90, 80, -35)     # +X 车头，+Y 左
    assert result["FR"] == (90, -80, -35)
    assert result["RL"] == (-90, 80, -35)
    assert result["RR"] == (-90, -80, -35)


def test_two_wheel_quadrants():
    centers = [(60, 5, -30), (-60, 5, -30)]
    result = assign_wheel_quadrants(centers)
    assert set(result) == {"FL", "RL"}


def test_invalid_count_raises():
    with pytest.raises(ValueError):
        assign_wheel_quadrants([(1, 1, 0), (-1, -1, 0), (0, 0, 0)])


def test_quadrant_conflict_raises():
    with pytest.raises(ValueError):
        assign_wheel_quadrants([(90, 80, -35), (91, 81, -35),
                                (-90, 80, -35), (-90, -80, -35)])


def test_ground_contact():
    assert ground_contact_ok(-0.5, 35)       # 最低点略低于原点，容差内
    assert ground_contact_ok(0.0, 35)
    assert not ground_contact_ok(-50.0, 35)  # 陷地 50cm，致命
