"""黄金模板目录 SHA-256 计算。

★与 UE 侧 TemplateHashGuard.cpp 采用完全一致的算法（V1.4 §4.3 绝对哈希卡点）：

1. 递归枚举目录下全部文件，忽略系统垃圾文件（.DS_Store / Thumbs.db / desktop.ini）；
2. 每个文件计算 SHA-256 二进制摘要（32 字节）；
3. 按 POSIX 风格相对路径字典序升序排序；
4. 累积字节流 = 对每个文件依次拼接 ``UTF8(相对路径) + 0x00 + 文件摘要(32B)``；
5. 对累积字节流再做一次 SHA-256，得到目录指纹（64 位小写十六进制）。

空目录的指纹即空输入的 SHA-256（e3b0c442...），与 Manifest 示例一致。
"""

from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Iterable, List, Tuple

# 计算指纹时忽略的文件名
IGNORED_FILENAMES = {".ds_store", "thumbs.db", "desktop.ini"}

CHUNK_SIZE = 1024 * 1024


def file_sha256(path: Path) -> bytes:
    """流式计算单文件 SHA-256 二进制摘要。"""
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(CHUNK_SIZE), b""):
            h.update(chunk)
    return h.digest()


def collect_files(root: Path) -> List[Tuple[str, Path]]:
    """枚举 (posix相对路径, 绝对路径) 列表并按相对路径排序。"""
    items: Iterable[Path] = (p for p in root.rglob("*")
                             if p.is_file() and p.name.lower() not in IGNORED_FILENAMES)
    entries = [(p.relative_to(root).as_posix(), p) for p in items]
    entries.sort(key=lambda e: e[0])
    return entries


def template_checksum(root: str | Path) -> str:
    """计算黄金模板目录指纹。目录不存在时抛 FileNotFoundError（调用方映射退出码 3）。"""
    root = Path(str(root).replace("\\", "/"))
    if not root.is_dir():
        raise FileNotFoundError(f"黄金模板目录不存在: {root.as_posix()}")

    acc = hashlib.sha256()
    for rel, abs_path in collect_files(root):
        acc.update(rel.encode("utf-8"))
        acc.update(b"\x00")
        acc.update(file_sha256(abs_path))
    return acc.hexdigest()


def verify_checksum(root: str | Path, expected_hex: str) -> Tuple[bool, str]:
    """比对目录指纹。返回 (是否一致, 实际指纹)。"""
    actual = template_checksum(root)
    return actual.lower() == (expected_hex or "").lower(), actual
