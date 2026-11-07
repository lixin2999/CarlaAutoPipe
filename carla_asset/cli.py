"""carla-asset CLI 统一入口（详细设计 V1.4 §5.1）。

::

    carla-asset validate      --type vehicle|map --input <path> [--report=<file.json>]
    carla-asset rig           --fbx=<in> --out=<out> [--mirror-y] [--report=...]
    carla-asset build-vehicle --manifest=<path> [--dry-run] [--skip-factory] [--batch-size=N]
    carla-asset build-map     --manifest=<path> [--dry-run] [--skip-navmesh]
    carla-asset pack          --pkg=<name> --src=<dir> [--platform=win|linux] [--format=zip|pak]
    carla-asset inject        --pkg=<path> [--rollback-on-fail] [--force]
    carla-asset smoke         --type vehicle|map --name <name> [--batch=<dir>]

退出码即契约：0/1/2/3（见 constants.ExitCode）。GUI 通过 subprocess 调用本
CLI，仅解析 --report 写出的 JSON 文件。
"""

from __future__ import annotations

import argparse
import sys
from typing import Optional, List

from . import __version__
from .constants import ExitCode
from .report import Report


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="carla-asset",
        description="CARLA 车辆与地图资产自动化导入工具系统 CLI")
    p.add_argument("--version", action="version", version=f"carla-asset {__version__}")
    p.add_argument("--settings", help="settings.json 路径（默认 configs/settings.json）")
    sub = p.add_subparsers(dest="command", required=True)

    def add_report(sp):
        sp.add_argument("--report", help="JSON 报告输出路径（GUI/CI 消费）")

    sp = sub.add_parser("validate", help="Blender 后台前置资产校验")
    sp.add_argument("--type", choices=["vehicle", "map"], required=True)
    sp.add_argument("--input", required=True, help="FBX 资产路径")
    sp.add_argument("--xodr", help="XODR 路网路径（地图校验必用）")
    sp.add_argument("--manifest", help="关联 Manifest（交叉一致性校验）")
    add_report(sp)

    sp = sub.add_parser("rig", help="自动绑骨到 CARLA 标准五骨骨架")
    sp.add_argument("--fbx", required=True, help="输入 FBX 路径")
    sp.add_argument("--out", required=True, help="合规 FBX 输出路径")
    sp.add_argument("--mirror-y", action="store_true", help="Y 轴镜像修正（防左右镜像）")
    add_report(sp)

    for name, kind in (("build-vehicle", "vehicle"), ("build-map", "map")):
        sp = sub.add_parser(name, help=f"引擎侧 {kind} 构建（UE Commandlet）")
        sp.add_argument("--manifest", required=True)
        sp.add_argument("--dry-run", action="store_true", help="仅校验不落地")
        if kind == "vehicle":
            sp.add_argument("--skip-factory", action="store_true",
                            help="跳过 VehicleFactory 注册（降级通道 B）")
        else:
            sp.add_argument("--skip-navmesh", action="store_true",
                            help="跳过导航网格生成")
        sp.add_argument("--batch-size", type=int,
                        help="批量导入分片大小，每 N 个资产执行一次 GC 防 OOM")
        add_report(sp)

    sp = sub.add_parser("pack", help="平台差异化打包")
    sp.add_argument("--pkg", required=True, help="包名（如 su7）")
    sp.add_argument("--src", required=True, help="待打包目录（Content/Carla 结构）")
    sp.add_argument("--manifest", help="归档进包内的 Manifest 路径")
    sp.add_argument("--platform", choices=["win", "linux"], default="win")
    sp.add_argument("--format", choices=["zip", "pak"], default="zip",
                    help="linux 平台 zip 自动产出官方通路 tar.gz")
    add_report(sp)

    sp = sub.add_parser("inject", help="Release 版幂等注入（快照备份+回滚）")
    sp.add_argument("--pkg", required=True, help="资产包路径（zip/tar.gz/pak）")
    sp.add_argument("--carla-root", help="目标 CARLA 安装目录（默认取配置）")
    sp.add_argument("--rollback-on-fail", action="store_true",
                    help="注入失败自动回滚至上一稳定版本")
    sp.add_argument("--force", action="store_true", help="忽略幂等指纹强制重注入")
    add_report(sp)

    sp = sub.add_parser("smoke", help="注入后冒烟验证（车辆八项/地图六项）")
    sp.add_argument("--type", choices=["vehicle", "map"], required=True)
    sp.add_argument("--name", help="vehicle 形如 xiaomi.su7；map 形如 Town10")
    sp.add_argument("--batch", help="批量回归：扫描目录内全部 Manifest JSON")
    sp.add_argument("--host", default="127.0.0.1")
    sp.add_argument("--port", type=int, default=2000)
    add_report(sp)

    sp = sub.add_parser("doctor", help="环境自检（GUI 启动自检同源）")
    add_report(sp)
    return p


def _dispatch(args: argparse.Namespace) -> Report:
    from .config import Settings
    settings = Settings.load(args.settings)

    if args.command == "validate":
        from .validate import run_validate
        return run_validate(args.type, args.input, xodr_path=args.xodr,
                            manifest_path=args.manifest, settings=settings)
    if args.command == "rig":
        from .rig import run_rig
        return run_rig(args.fbx, args.out, mirror_y=args.mirror_y, settings=settings)
    if args.command == "build-vehicle":
        from .builder import build_asset
        return build_asset("vehicle", args.manifest, dry_run=args.dry_run,
                           skip_factory=args.skip_factory,
                           batch_size=args.batch_size, settings=settings)
    if args.command == "build-map":
        from .builder import build_asset
        return build_asset("map", args.manifest, dry_run=args.dry_run,
                           skip_navmesh=args.skip_navmesh,
                           batch_size=args.batch_size, settings=settings)
    if args.command == "pack":
        from .pack import build_package
        return build_package(args.pkg, args.src, manifest_path=args.manifest,
                             platform=args.platform, fmt=getattr(args, "format", "zip"),
                             settings=settings)
    if args.command == "inject":
        from .inject import inject_package
        return inject_package(args.pkg, carla_root=args.carla_root,
                              rollback_on_fail=args.rollback_on_fail,
                              force=args.force, settings=settings)
    if args.command == "smoke":
        from .smoke import run_smoke
        if not args.name and not args.batch:
            rpt = Report(command="smoke")
            rpt.add_error("SMOKE_NO_TARGET", "必须提供 --name 或 --batch",
                          "示例: carla-asset smoke --type vehicle --name xiaomi.su7")
            return rpt.finish(int(ExitCode.ASSET_VALIDATION_FAIL))
        return run_smoke(args.type, args.name or "", batch_dir=args.batch,
                         host=args.host, port=args.port, settings=settings)
    if args.command == "doctor":
        rpt = Report(command="doctor")
        checks = settings.check()
        rpt.details["checks"] = checks
        for item in checks:
            if not item["ok"]:
                rpt.add_warning(f"ENV_{item['key'].upper()}",
                                item["message"], item["suggestion"])
        return rpt.finish(int(ExitCode.SUCCESS))
    raise SystemExit(f"未知命令: {args.command}")


def _print_human(rpt: Report) -> None:
    """标准输出仅供人看；GUI 不解析本输出（薄壳契约）。"""
    print(f"[carla-asset] command={rpt.command} exit={rpt.exit_code}")
    for i in rpt.issues:
        loc = f" @{i.file}" if i.file else ""
        print(f"  {i.level:<7} [{i.code}]{loc} {i.message}")
        if i.suggestion:
            print(f"          ↳ 建议: {i.suggestion}")
    if rpt.duration_sec is not None:
        print(f"[carla-asset] 耗时 {rpt.duration_sec}s")


def main(argv: Optional[List[str]] = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        rpt = _dispatch(args)
    except KeyboardInterrupt:
        print("已取消", file=sys.stderr)
        return int(ExitCode.ENGINE_INTERNAL_ERROR)
    except Exception as e:                                # noqa: BLE001
        rpt = Report(command=getattr(args, "command", "unknown"))
        rpt.add_error("CLI_UNEXPECTED", f"未预期异常: {e!r}",
                      "查看完整堆栈: 设置环境变量 CARLA_ASSET_DEBUG=1 后重试")
        if __import__("os").environ.get("CARLA_ASSET_DEBUG"):
            import traceback
            traceback.print_exc()
        rpt.finish(int(ExitCode.ENGINE_INTERNAL_ERROR))

    _print_human(rpt)
    if getattr(args, "report", None):
        out = rpt.save(args.report)
        print(f"[carla-asset] JSON 报告: {out.as_posix()}")
    return int(rpt.exit_code)


if __name__ == "__main__":
    sys.exit(main())
