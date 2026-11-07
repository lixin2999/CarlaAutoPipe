"""CLI 参数解析契约（V1.4 §5.1）与 GUI 薄壳可导入性检查。"""

from __future__ import annotations

import pytest

from carla_asset.cli import build_parser


def parse(*argv):
    return build_parser().parse_args(list(argv))


def test_seven_subcommands_registered():
    sp = build_parser()
    choices = sp._subparsers._group_actions[0].choices  # noqa: SLF001
    for name in ("validate", "rig", "build-vehicle", "build-map",
                 "pack", "inject", "smoke"):
        assert name in choices


def test_validate_args():
    a = parse("validate", "--type", "map", "--input", "a.fbx",
              "--xodr", "a.xodr", "--report", "r.json")
    assert a.type == "map" and a.input == "a.fbx" and a.report == "r.json"


def test_rig_args():
    a = parse("rig", "--fbx", "in.fbx", "--out", "out.fbx", "--mirror-y")
    assert a.fbx == "in.fbx" and a.out == "out.fbx" and a.mirror_y is True


@pytest.mark.parametrize("cmd", ["build-vehicle", "build-map"])
def test_build_common_args(cmd):
    a = parse(cmd, "--manifest", "m.json", "--dry-run", "--batch-size", "8")
    assert a.manifest == "m.json" and a.dry_run and a.batch_size == 8


def test_build_vehicle_skip_factory():
    assert parse("build-vehicle", "--manifest", "m", "--skip-factory").skip_factory


def test_build_map_skip_navmesh():
    assert parse("build-map", "--manifest", "m", "--skip-navmesh").skip_navmesh


def test_pack_defaults():
    a = parse("pack", "--pkg", "su7", "--src", "out/su7")
    assert a.platform == "win" and a.format == "zip"


def test_inject_args():
    a = parse("inject", "--pkg", "d/su7.zip", "--rollback-on-fail", "--force",
              "--carla-root", "D:/CARLA")
    assert a.rollback_on_fail and a.force and a.carla_root == "D:/CARLA"


def test_smoke_args():
    a = parse("smoke", "--type", "vehicle", "--name", "xiaomi.su7",
              "--port", "2001", "--batch", "manifests")
    assert a.name == "xiaomi.su7" and a.port == 2001 and a.batch == "manifests"


@pytest.mark.parametrize("argv", [
    ["validate"],                              # 缺 --type/--input
    ["validate", "--type", "bus", "--input"],  # type 非法枚举
    ["rig", "--fbx", "only.fbx"],              # 缺 --out
    ["inject"],                                # 缺 --pkg
    ["nonsense"],                              # 未知子命令
])
def test_bad_args_exit_with_parser_error(argv):
    with pytest.raises(SystemExit) as e:
        parse(*argv)
    assert e.value.code == 2                   # argparse 用法错误固定返回 2


def test_version_exits_zero():
    with pytest.raises(SystemExit) as e:
        parse("--version")
    assert e.value.code == 0


# ---------------------------------------------------------------------------
# GUI 薄壳：仅静态检查可导入性与参数翻译（无显示环境不启动事件循环）
# ---------------------------------------------------------------------------
pytest.importorskip("PyQt5", reason="GUI 依赖 PyQt5")


@pytest.fixture(scope="module")
def qapp_instance():
    import os
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PyQt5.QtWidgets import QApplication
    app = QApplication.instance() or QApplication([])
    yield app


def test_gui_step_inputs_translation(qapp_instance):
    from gui.main_window import StepInputs
    cases = {
        "validate": ("assets/a.fbx", ["validate", "--type", "vehicle",
                                      "--input", "assets/a.fbx"]),
        "rig": ("a.fbx;b.fbx", ["rig", "--fbx", "a.fbx", "--out", "b.fbx"]),
        "build": ("m.json", ["build-vehicle", "--manifest", "m.json"]),
        "pack": ("su7;out/su7", ["pack", "--pkg", "su7", "--src", "out/su7",
                                 "--platform", "win"]),
        "inject": ("d/su7.zip", ["inject", "--pkg", "d/su7.zip",
                                 "--rollback-on-fail"]),
        "smoke": ("xiaomi.su7", ["smoke", "--type", "vehicle",
                                 "--name", "xiaomi.su7"]),
    }
    for step, (raw, expected) in cases.items():
        widget = StepInputs(step)
        widget.pathEdit.setText(raw)
        widget.extra.setChecked(False)
        assert widget.build_args() == expected, step


def test_gui_incomplete_input_rejected(qapp_instance):
    from gui.main_window import StepInputs
    assert StepInputs("rig").build_args() is None          # 缺输出路径
    assert StepInputs("validate").build_args() is None     # 空输入


def test_gui_env_check_mapping(qapp_instance):
    from gui.env_check import STEP_ENV, blocked_steps, env_status
    status = env_status()
    blocked = blocked_steps(status)
    assert set(blocked) == set(STEP_ENV)
    # pack 不依赖外部二进制，任何环境下都不应被禁用
    assert blocked["pack"] == []


def test_gui_confirm_dialog_accepts_int_counts(qapp_instance):
    from gui.confirm_dialog import ConfirmDiffDialog
    dlg = ConfirmDiffDialog("t", {"added": 3, "overwritten": 1})
    # 摘要模式（计数）能正常构建控件即通过
    assert dlg.layout() is not None
