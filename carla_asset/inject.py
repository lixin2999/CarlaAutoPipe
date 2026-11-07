"""inject 模块：Release 版幂等注入 + 快照回滚（V1.4 §4.5 / V1.2 §4.7）。

注入通路（已确认的官方标准路径）：

| 平台    | 方式                                        | 生效路径                     |
| ------- | ------------------------------------------- | ---------------------------- |
| Linux   | .tar.gz 放入 CARLA_ROOT/Import/ 执行 ImportAssets.sh | 解压到 CarlaUE4/Content/  |
| Windows | .zip 解压覆盖到 CARLA_ROOT                   | CarlaUE4/Content/ 对应目录   |
| 通用 Pak| .pak 直接复制                                | CarlaUE4/Saved/Paks/         |

核心机制：
- 目标目录自动探测（Content/Carla 与 Saved/Paks）；
- 幂等：包指纹与 ``_injected/<pkg>.json`` 记录一致时直接跳过；
- 注入前快照备份将被覆盖的文件至 ``_backup/<pkg>_<ts>/``，失败自动回滚；
- ★跨平台路径统一 pathlib + as_posix()，防止反斜杠导致 Asset Registry 解析失败。
"""

from __future__ import annotations

import json
import shutil
import subprocess
import tarfile
import tempfile
import zipfile
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from .checksum import file_sha256
from .config import Settings
from .constants import ExitCode
from .pack import PKG_SCHEMA_VERSION, compute_fingerprint
from .report import Report, environment_error

INJECTED_DB_DIR = "_injected"


def _build_fingerprint(content_root: Path, entries: List[str]) -> str:
    """包内容指纹（★流式哈希，避免大资产整文件读入内存）。

    记录与比对必须共用本函数（同一算法、同一数据来源），严禁在其他位置另算，
    否则会出现指纹失真导致幂等跳过失效（V1.4 §4.5 / 既往缺陷复盘）。
    """
    return compute_fingerprint([
        (rel, file_sha256(content_root.joinpath(*rel.split("/"))).hex())
        for rel in entries])


# ---------------------------------------------------------------------------
# 纯函数（可单测）
# ---------------------------------------------------------------------------
def detect_target_layout(carla_root: Path) -> Dict[str, Path]:
    """探测 CARLA 目录结构，返回关键子路径。缺失的键为 None。"""
    carla_root = Path(carla_root)
    # Release 版: <root>/CarlaUE4/Content；源码构建: <root>/Content
    ue_dir = carla_root / "CarlaUE4" if (carla_root / "CarlaUE4").is_dir() else carla_root
    return {
        "ue_dir": ue_dir,
        "content": ue_dir / "Content" if (ue_dir / "Content").is_dir() else None,
        "paks": ue_dir / "Saved" / "Paks",
        "import": carla_root / "Import",
        "import_sh": carla_root / "ImportAssets.sh",
    }


def compute_diff(entries: List[str], target_root: Path) -> Dict[str, List[str]]:
    """对比包内 POSIX 相对路径清单与目标目录，产出差异清单 {added, overwritten}。

    GUI 风险操作二次确认（差异清单展示）与注入前备份共用。
    """
    added, overwritten = [], []
    for rel in entries:
        # 目标存在性比对统一用正斜杠切分后逐段 join，避免 Windows 反斜杠混入
        dest = target_root.joinpath(*rel.split("/")) if "/" in rel else target_root / rel
        (overwritten if dest.exists() else added).append(rel)
    return {"added": added, "overwritten": overwritten}


def read_package(pkg_path: Path, workdir: Path) -> Tuple[Path, Optional[dict]]:
    """解包 zip/tar.gz 到 workdir；pak 直接返回文件本身。

    :returns: (内容根目录或 pak 文件, package.meta 或 None)
    """
    name = pkg_path.name.lower()
    if name.endswith(".pak"):
        return pkg_path, None
    if name.endswith(".zip"):
        with zipfile.ZipFile(pkg_path) as zf:
            # 安全解压：与 tar 同款预检，拒绝绝对路径与 .. 条目（防路径穿越）
            for member in zf.namelist():
                mp = Path(member)
                if mp.is_absolute() or ".." in mp.parts:
                    raise ValueError(f"包内存在非法路径条目: {member}")
            zf.extractall(workdir)
    elif name.endswith((".tar.gz", ".tgz")):
        with tarfile.open(pkg_path, "r:gz") as tf:
            # 安全解压：拒绝绝对路径与 .. 条目
            for member in tf.getmembers():
                mp = Path(member.name)
                if mp.is_absolute() or ".." in mp.parts:
                    raise ValueError(f"包内存在非法路径条目: {member.name}")
            tf.extractall(workdir)
    elif pkg_path.is_dir():
        workdir = pkg_path
    else:
        raise ValueError(f"不支持的包格式: {pkg_path.name}")
    # 包可能以单层 <pkg>/ 目录打包：顶层仅一个目录且无散落文件时下钻一层
    top_dirs = [p for p in workdir.iterdir() if p.is_dir()]
    top_files = [p for p in workdir.iterdir() if p.is_file()]
    root = top_dirs[0] if (len(top_dirs) == 1 and not top_files) else workdir
    meta_file = None
    for cand in (root / "package.meta.json", root / f"{root.name}.package.meta.json",
                 workdir / "package.meta.json"):
        if cand.is_file():
            meta_file = cand
            break
    # 兼容旁挂 meta zip
    if meta_file is None:
        for sib in pkg_path.parent.glob(pkg_path.stem + "*.meta.zip"):
            with zipfile.ZipFile(sib) as zf:
                member = next((n for n in zf.namelist()
                               if n.endswith("package.meta.json")), None)
                if member:
                    meta_file = workdir / "package.meta.json"
                    meta_file.write_bytes(zf.read(member))
                    break
    meta = json.loads(meta_file.read_text(encoding="utf-8")) if meta_file else None
    return root, meta


def _content_files(root: Path) -> List[str]:
    """列出注入根下全部文件的 POSIX 相对路径（排除元数据与归档 Manifest）。"""
    out = []
    for p in sorted(root.rglob("*")):
        if not p.is_file():
            continue
        rel = p.relative_to(root).as_posix()
        if rel == "package.meta.json" or rel.startswith("_manifest/"):
            continue
        out.append(rel)
    return out


# ---------------------------------------------------------------------------
# 注入主流程
# ---------------------------------------------------------------------------
def inject_package(pkg_path: str, carla_root: Optional[str] = None,
                   rollback_on_fail: bool = False, force: bool = False,
                   report: Optional[Report] = None,
                   settings: Optional[Settings] = None) -> Report:
    """执行 Release 版注入。"""
    rpt = report or Report(command="inject")
    settings = settings or Settings.load()

    root_str = carla_root or settings.carla_root
    if not root_str or not Path(root_str).is_dir():
        return environment_error(
            "inject", "ENV_CARLA_ROOT_MISSING",
            f"CARLA_ROOT 未配置或不存在: {root_str or '(未配置)'}",
            "在 settings.json 配置 carla_root 或设置环境变量 CARLA_ASSET_CARLA_ROOT")
    carla = Path(root_str)
    pkg = settings.resolve(pkg_path)
    if not pkg.exists():
        return environment_error("inject", "ENV_PKG_MISSING",
                                 f"资产包不存在: {pkg.as_posix()}",
                                 "检查 --pkg 参数，或先执行 pack 命令")

    layout = detect_target_layout(carla)
    rpt.details["carla_root"] = carla.as_posix()

    with tempfile.TemporaryDirectory(prefix="carla_inject_") as tmp:
        try:
            content_root, meta = read_package(pkg, Path(tmp))
        except (ValueError, zipfile.BadZipFile, tarfile.TarError) as e:
            rpt.add_error("PKG_CORRUPT", f"资产包解析失败: {e}", "重新打包或校验包完整性")
            return rpt.finish(int(ExitCode.ASSET_VALIDATION_FAIL))

        pkg_name = (meta or {}).get("pkg_name") or pkg.stem.split(".")[0]
        is_pak = pkg.name.lower().endswith(".pak")

        # -- 统一指纹：pak 为 (文件名, 内容 sha256)，散装为逐文件内容摘要 -------
        if is_pak:
            entries = [content_root.name]
            fingerprint = compute_fingerprint(
                [(content_root.name, file_sha256(content_root).hex())])
        else:
            entries = _content_files(content_root)
            fingerprint = _build_fingerprint(content_root, entries)
            if meta and meta.get("fingerprint"):
                fingerprint = meta["fingerprint"]

        # -- 幂等：指纹一致且未 --force 则跳过（pak / 散装通路共用） -----------
        db = _read_injected_db(carla, pkg_name)
        if db and db.get("fingerprint") == fingerprint and not force:
            rpt.add_info("INJECT_IDEMPOTENT_SKIP",
                         f"包 {pkg_name} 指纹与已注入版本一致，跳过（--force 可强制重注）",
                         "")
            rpt.details["fingerprint"] = fingerprint
            return rpt.finish(int(ExitCode.SUCCESS))

        # -- pak 通路：直接放 Saved/Paks/ -----------------------------------
        if is_pak:
            dest_dir = layout["paks"]
            dest_dir.mkdir(parents=True, exist_ok=True)
            target = dest_dir / content_root.name
            diff = compute_diff(entries, dest_dir)
            rpt.details["mode"] = "pak"
            rpt.details["diff"] = diff
            backup = _backup_files(dest_dir, diff["overwritten"], pkg_name, settings, carla)
            try:
                _copy_into(content_root.parent, dest_dir, [content_root.name])
            except OSError as e:
                _rollback(backup, dest_dir, rpt)
                rpt.add_error("INJECT_FAIL", f"pak 复制失败: {e}", "检查目标目录写权限")
                return rpt.finish(int(ExitCode.ENGINE_INTERNAL_ERROR))
            _record_injected(carla, pkg_name, fingerprint)   # 与上方比对值同源同算法
            rpt.artifacts.append(target.as_posix())
            rpt.details["fingerprint"] = fingerprint
            rpt.asset_name = pkg_name
            return rpt.finish(int(ExitCode.SUCCESS))

        # -- Linux 官方通路：Import/ + ImportAssets.sh ------------------------
        if (pkg.name.lower().endswith((".tar.gz", ".tgz"))
                and layout["import_sh"].is_file()):
            # 注入前快照将被覆盖的目标文件（ImportAssets.sh 解压至 Content/ 同名项），
            # 失败时可回滚；tar 包内条目带 <pkg>/ 前缀，剥除后与 Content 相对路径对齐
            rel_entries = [e.split("/", 1)[1] for e in entries]
            backup = None
            if layout["content"] is not None:
                diff = compute_diff(rel_entries, layout["content"])
                rpt.details["diff"] = {k: len(v) for k, v in diff.items()}
                backup = _backup_files(layout["content"], diff["overwritten"],
                                       pkg_name, settings, carla)
            layout["import"].mkdir(parents=True, exist_ok=True)
            shutil.copy2(pkg, layout["import"] / pkg.name)
            try:
                proc = subprocess.run(["bash", str(layout["import_sh"])],
                                      capture_output=True, text=True,
                                      timeout=settings.import_timeout_sec,
                                      cwd=str(carla))
            except subprocess.TimeoutExpired:
                if rollback_on_fail:
                    _rollback(backup, layout["content"] or carla, rpt)
                rpt.add_error("IMPORT_SH_TIMEOUT",
                              f"ImportAssets.sh 超时（>{settings.import_timeout_sec}s）",
                              "调大 import_timeout_sec；Windows 运行机请改用 zip 通路")
                return rpt.finish(int(ExitCode.ENGINE_INTERNAL_ERROR))
            except OSError as e:
                rpt.add_error("ENV_BASH_MISSING",
                              f"无法启动 bash 执行 ImportAssets.sh: {e}",
                              "Linux 运行端需 bash 环境；Windows 运行机请改用 zip 通路")
                return rpt.finish(int(ExitCode.ENVIRONMENT_ERROR))
            if proc.returncode != 0:
                if rollback_on_fail:
                    _rollback(backup, layout["content"] or carla, rpt)
                else:
                    rpt.add_info("ROLLBACK_SKIPPED", "未启用 --rollback-on-fail，快照保留",
                                 f"快照位置: {(backup.as_posix() if backup else '无')}")
                rpt.add_error("IMPORT_SH_FAIL",
                              f"ImportAssets.sh 退出码 {proc.returncode}",
                              proc.stderr[-500:] if proc.stderr else "查看脚本输出")
                return rpt.finish(int(ExitCode.ENGINE_INTERNAL_ERROR))
            rpt.details["mode"] = "import_sh"
        else:
            # -- Windows / 通用：散装 .uasset 覆盖到 Content/ ------------------
            if layout["content"] is None:
                return environment_error(
                    "inject", "ENV_CONTENT_DIR_MISSING",
                    f"未探测到 Content 目录: {layout['ue_dir'].as_posix()}",
                    "确认 CARLA_ROOT 指向 CarlaUE4 所在安装目录")
            dest = layout["content"]
            rel_entries = entries
            # 包内已含 Content/ 前缀时避免二次拼接
            if all(e.startswith("Content/") for e in rel_entries):
                src_base = content_root / "Content"
                rel_entries = [e.split("/", 1)[1] for e in rel_entries]
            else:
                src_base = content_root
            diff = compute_diff(rel_entries, dest)
            rpt.details["mode"] = "content_overlay"
            rpt.details["diff"] = {k: len(v) for k, v in diff.items()}
            rpt.details["overwritten_files"] = diff["overwritten"]
            backup = _backup_files(dest, diff["overwritten"], pkg_name, settings, carla)
            try:
                _copy_tree_overlay(src_base, dest, rel_entries)
            except OSError as e:
                # 文件级复制失败一律回滚，避免半注入状态
                _rollback(backup, dest, rpt)
                rpt.add_error("INJECT_FAIL", f"资产复制失败: {e}",
                              "检查目标目录写权限与磁盘空间")
                return rpt.finish(int(ExitCode.ENGINE_INTERNAL_ERROR))
            # 指纹沿用前文统一计算值（含 meta 优先），禁止另算，否则幂等比对失真

        _record_injected(carla, pkg_name, fingerprint)
        rpt.details["fingerprint"] = fingerprint
        rpt.asset_name = pkg_name
        return rpt.finish(int(ExitCode.SUCCESS))


# ---------------------------------------------------------------------------
# 内部工具
# ---------------------------------------------------------------------------
def _copy_tree_overlay(src_root: Path, dest_root: Path, rel_entries: List[str]) -> None:
    """按 POSIX 相对路径清单逐文件覆盖复制（★全程 pathlib，无字符串反斜杠拼接）。"""
    for rel in rel_entries:
        src = src_root.joinpath(*rel.split("/"))
        dest = dest_root.joinpath(*rel.split("/"))
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, dest)


def _copy_into(src_parent: Path, dest_dir: Path, names: List[str]) -> None:
    for n in names:
        shutil.copy2(src_parent / n, dest_dir / n)


def _backup_files(dest_root: Path, rel_files: List[str], pkg_name: str,
                  settings: Settings, carla_root: Path) -> Optional[Path]:
    """将被覆盖文件快照备份至 <repo>/_backup/<pkg>_<ts>/，返回备份目录。"""
    if not rel_files:
        return None
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    backup = settings.resolve(settings.backup_dir) / f"{pkg_name}_{ts}"
    for rel in rel_files:
        src = dest_root.joinpath(*rel.split("/"))
        if src.is_file():
            dst = backup.joinpath(*rel.split("/"))
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src, dst)
    (backup / "_origin.json").write_text(json.dumps({
        "dest_root": dest_root.as_posix(),
        "files": rel_files,
    }, ensure_ascii=False, indent=2), encoding="utf-8")
    return backup


def _rollback(backup: Optional[Path], dest_root: Path, rpt: Report) -> None:
    """从快照恢复被覆盖文件（失败自动回滚至上一稳定版本）。"""
    if backup is None or not backup.is_dir():
        rpt.add_info("ROLLBACK_NOOP", "无备份快照（本次注入未覆盖任何文件），无需回滚", "")
        return
    origin = backup / "_origin.json"
    if not origin.is_file():
        return
    meta = json.loads(origin.read_text(encoding="utf-8"))
    root = Path(meta["dest_root"])
    restored = 0
    for rel in meta["files"]:
        src = backup.joinpath(*rel.split("/"))
        if src.is_file():
            dst = root.joinpath(*rel.split("/"))
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src, dst)
            restored += 1
    rpt.add_info("ROLLBACK_DONE", f"已回滚 {restored} 个文件至注入前状态",
                 f"快照位置: {backup.as_posix()}")


def _injected_db_path(carla_root: Path, pkg_name: str) -> Path:
    return carla_root / INJECTED_DB_DIR / f"{pkg_name}.json"


def _read_injected_db(carla_root: Path, pkg_name: str) -> Optional[dict]:
    p = _injected_db_path(carla_root, pkg_name)
    if p.is_file():
        try:
            return json.loads(p.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            return None
    return None


def _record_injected(carla_root: Path, pkg_name: str, fingerprint: str) -> None:
    db = _injected_db_path(carla_root, pkg_name)
    db.parent.mkdir(parents=True, exist_ok=True)
    db.write_text(json.dumps({
        "pkg_name": pkg_name,
        "fingerprint": fingerprint,
        "schema_version": PKG_SCHEMA_VERSION,
        "injected_at": datetime.now().isoformat(timespec="seconds"),
    }, ensure_ascii=False, indent=2), encoding="utf-8")
