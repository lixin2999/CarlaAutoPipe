"""pack 模块：平台差异化打包（V1.2 §4.7 / V1.4 §4.5）。

- Windows → .zip（可直接解压到 CARLA_ROOT）
- Linux   → .tar.gz（放入 Import/ 配合 ImportAssets.sh）
- pak     → 单文件包（委托 UnrealPak，无引擎环境时报退出码 3）

包内统一结构（与官方资产包兼容）::

    <pkg>/
    ├── manifest.json          # 原始 Manifest 归档（可复现可追溯）
    ├── files.txt              # 文件清单（POSIX 相对路径，正斜杠归一化）
    └── Content/Carla/...      # 或 Saved/Paks/xxx.pak

跨平台斜杠归一化：所有条目经 pathlib 计算并以 ``as_posix()`` 写出。
"""

from __future__ import annotations

import hashlib
import json
import shutil
import subprocess
import tarfile
import zipfile
from datetime import datetime, timezone
from pathlib import Path
from typing import List, Optional

from .checksum import file_sha256
from .config import Settings
from .constants import ExitCode
from .report import Report, environment_error

PKG_SCHEMA_VERSION = "1"


def compute_fingerprint(files: List[tuple]) -> str:
    """包内容指纹：sha256(排序后的 '相对路径:文件sha256' 串联)，注入幂等判定用。"""
    acc = hashlib.sha256()
    for rel, digest in sorted(files):
        acc.update(f"{rel}:{digest}".encode("utf-8"))
    return acc.hexdigest()


def collect_package_files(staging: Path) -> List[tuple]:
    """收集暂存目录内 (posix相对路径, 文件sha256) 列表（★流式哈希，防大资产整文件驻内存）。"""
    out = []
    for p in sorted(staging.rglob("*")):
        if p.is_file():
            out.append((p.relative_to(staging).as_posix(),
                        file_sha256(p)))
    return out


def build_package(pkg_name: str, source_dir: str, manifest_path: Optional[str] = None,
                  platform: str = "win", fmt: str = "zip",
                  report: Optional[Report] = None,
                  settings: Optional[Settings] = None) -> Report:
    """打包构建产物。

    :param pkg_name: 包名（如 su7 / town10）
    :param source_dir: 待打包目录（内部应为 Content/Carla/... 结构）
    :param platform: win|linux
    :param fmt: zip|pak（linux 下 zip 自动改产出 tar.gz，与官方注入通路一致）
    """
    rpt = report or Report(command="pack")
    settings = settings or Settings.load()
    src = settings.resolve(source_dir)
    if not src.is_dir():
        return environment_error("pack", "ENV_SOURCE_MISSING",
                                 f"待打包目录不存在: {src.as_posix()}",
                                 "先执行 build-vehicle/build-map 产出资产，"
                                 "或检查 --src 路径")

    out_dir = settings.resolve(settings.package_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    if fmt == "pak":
        return _pack_pak(pkg_name, src, out_dir, rpt, settings)

    # linux 目标强制 tar.gz（官方 ImportAssets.sh 通路），win 目标 zip
    use_tar = platform == "linux"
    suffix = ".tar.gz" if use_tar else ".zip"
    pkg_file = out_dir / f"{pkg_name}{suffix}"

    entries: List[tuple] = []
    if use_tar:
        with tarfile.open(pkg_file, "w:gz") as tar:
            for p in sorted(src.rglob("*")):
                if p.is_file():
                    rel = Path(pkg_name) / p.relative_to(src)
                    tar.add(p, arcname=rel.as_posix())     # ★正斜杠归一化
                    entries.append(rel.as_posix())
    else:
        with zipfile.ZipFile(pkg_file, "w", zipfile.ZIP_DEFLATED) as zf:
            for p in sorted(src.rglob("*")):
                if p.is_file():
                    rel = Path(pkg_name) / p.relative_to(src)
                    zf.write(p, arcname=rel.as_posix())    # ★正斜杠归一化
                    entries.append(rel.as_posix())

    # 归档 Manifest + 文件清单 + 指纹（可复现可追溯 / 注入幂等）
    side = _write_meta(pkg_name, src, manifest_path, entries, settings, rpt)
    if side:
        # 元数据旁挂 meta zip（tar.gz 不支持追加，zip 同样统一旁挂，便于人工分发）
        with zipfile.ZipFile(pkg_file.with_suffix(pkg_file.suffix + ".meta.zip"),
                             "w", zipfile.ZIP_DEFLATED) as zf:
            zf.write(side, arcname=f"{pkg_name}/package.meta.json")
    rpt.artifacts.append(pkg_file.as_posix())
    rpt.details["package"] = {
        "name": pkg_name, "platform": platform, "format": "tar.gz" if use_tar else "zip",
        "files": len(entries),
    }
    return rpt.finish(int(ExitCode.SUCCESS) if not rpt.has_error
                      else int(ExitCode.ASSET_VALIDATION_FAIL))


def _write_meta(pkg_name: str, src: Path, manifest_path: Optional[str],
                entries: List[str], settings: Settings, rpt: Report) -> Optional[Path]:
    """写出 package.meta.json（指纹/清单/Manifest 归档）。"""
    files = collect_package_files(src)
    meta = {
        "pkg_name": pkg_name,
        "schema_version": PKG_SCHEMA_VERSION,
        "created_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "fingerprint": compute_fingerprint(files),
        "files": (sorted(e.split("/", 1)[-1] for e in entries) if entries
                  else [f for f, _ in files]),
    }
    if manifest_path:
        mft = settings.resolve(manifest_path)
        if not mft.is_file():
            rpt.add_error("PACK_MANIFEST_MISSING",
                          f"Manifest 不存在，无法归档: {mft.as_posix()}",
                          "通过 --manifest 指定有效路径")
            return None
        meta["manifest_archived"] = json.loads(mft.read_text(encoding="utf-8"))
        # 同步归档一份原始文件
        archive = src / "_manifest" / mft.name
        archive.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(mft, archive)
    out = settings.resolve(settings.report_dir) / f"{pkg_name}.package.meta.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")
    return out


def _pack_pak(pkg_name: str, src: Path, out_dir: Path, rpt: Report,
              settings: Settings) -> Report:
    """pak 格式委托 UnrealPak 产出（需引擎环境，V1.2 里程碑 P3）。"""
    unrealpak = shutil.which("UnrealPak")
    if not unrealpak:
        engine_hint = settings.path_of("ue_cmd")
        if engine_hint:
            cand = Path(engine_hint).parent / "UnrealPak.bat"
            if cand.is_file():
                unrealpak = str(cand)
    if not unrealpak:
        _env_fail(rpt,
                  "未找到 UnrealPak 工具",
                  "pak 格式需要 UE 4.26 引擎环境（Engine/Binaries/Win64/UnrealPak.bat），"
                  "或改用 --format=zip 产出标准资产包")
        return rpt.finish(int(ExitCode.ENVIRONMENT_ERROR))
    pak_file = out_dir / f"{pkg_name}.pak"
    response = out_dir / f"{pkg_name}.resp"
    # UnrealPak 响应文件：每行 "src" "dest"，★dest 强制正斜杠
    lines = []
    for p in sorted(src.rglob("*")):
        if p.is_file():
            rel = p.relative_to(src).as_posix()
            lines.append(f'"{p.as_posix()}" "Content/Carla/{rel}"')
    response.write_text("\n".join(lines), encoding="utf-8")
    try:
        proc = subprocess.run(
            [unrealpak, str(pak_file), f"@{response}"],
            capture_output=True, text=True,
            timeout=settings.import_timeout_sec)
    except (subprocess.TimeoutExpired, OSError) as e:
        rpt.add_error("PAK_SPAWN_FAIL", f"UnrealPak 执行失败: {e}", "检查引擎环境")
        return rpt.finish(int(ExitCode.ENGINE_INTERNAL_ERROR))
    if proc.returncode != 0 or not pak_file.is_file():
        rpt.add_error("PAK_BUILD_FAIL", "UnrealPak 返回异常",
                      proc.stderr[-500:] if proc.stderr else "查看引擎日志")
        return rpt.finish(int(ExitCode.ENGINE_INTERNAL_ERROR))
    rpt.artifacts.append(pak_file.as_posix())
    return rpt.finish(int(ExitCode.SUCCESS))


def _env_fail(rpt: Report, message: str, suggestion: str) -> ExitCode:
    rpt.add_error("ENV_PAK_TOOL_MISSING", message, suggestion)
    return ExitCode.ENVIRONMENT_ERROR
