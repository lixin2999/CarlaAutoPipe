"""smoke 模块纯函数回归：JUnit XML 产出与转义（V1.0.1，CI Stage 4 门禁）。"""

from __future__ import annotations

import xml.etree.ElementTree as ET

from carla_asset.smoke import write_junit


RESULTS = [
    {
        "asset": 'vehicle.xia"omi/<su7>',
        "type": "vehicle",
        "passed": False,
        "items": [
            {"check": "blueprint_found", "passed": True, "detail": {"hit": 1}},
            {"check": "steering", "passed": False,
             "detail": {"yaw_delta_deg": -3.2, "expect": "steer=+1.0 => yaw 增大"}},
        ],
    },
]


def test_write_junit_valid_xml_with_escaping(tmp_path):
    path = tmp_path / "smoke.junit.xml"
    out = write_junit(RESULTS, path)
    assert out == path and path.is_file()
    # 含引号/尖括号的 asset/detail 不得破坏 XML 结构
    root = ET.parse(path).getroot()
    assert root.attrib["tests"] == "2"
    cases = root.findall("testcase")
    assert cases[0].find("failure") is None
    failure = cases[1].find("failure")
    assert failure is not None and "yaw" in failure.attrib["message"]


def test_write_junit_empty_results(tmp_path):
    path = tmp_path / "empty.junit.xml"
    write_junit([], path)
    root = ET.parse(path).getroot()
    assert root.attrib["tests"] == "0"
