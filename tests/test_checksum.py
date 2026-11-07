"""黄金模板哈希：算法向量、排序无关性、忽略垃圾文件、与 Manifest 示例一致。"""

from __future__ import annotations

import hashlib

import pytest

from carla_asset.checksum import (collect_files, template_checksum,
                                  verify_checksum)

EMPTY_SHA256 = "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855"


def _reference_digest(files: dict) -> str:
    """按文档算法规范独立复现（与实现解耦）：files = {posix相对路径: bytes}。"""
    acc = hashlib.sha256()
    for rel in sorted(files):
        acc.update(rel.encode("utf-8"))
        acc.update(b"\x00")
        acc.update(hashlib.sha256(files[rel]).digest())
    return acc.hexdigest()


def test_empty_dir_matches_known_vector(tmp_path):
    # V1.2 文档示例向量：空目录 = 空输入 SHA-256
    assert template_checksum(tmp_path) == EMPTY_SHA256


def test_repo_sample_checksum_is_consistent(tmp_path):
    # 示例 Manifest 固化了空目录指纹：模板目录为空时预检应通过
    assert verify_checksum(tmp_path, EMPTY_SHA256.upper())[0]


def test_single_file_known_vector(tmp_path):
    (tmp_path / "a.txt").write_bytes(b"hello")
    expected = _reference_digest({"a.txt": b"hello"})
    assert template_checksum(tmp_path) == expected


def test_order_independent(tmp_path):
    files = {"b/2.txt": b"two", "a/1.txt": b"one", "root.txt": b"r"}
    for rel, content in files.items():  # 创建顺序与字典序无关
        p = tmp_path / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(content)
    assert template_checksum(tmp_path) == _reference_digest(files)


def test_content_change_changes_digest(tmp_path):
    p = tmp_path / "x.uasset"
    p.write_bytes(b"v1")
    d1 = template_checksum(tmp_path)
    p.write_bytes(b"v2")
    assert template_checksum(tmp_path) != d1


def test_ignored_system_files(tmp_path):
    (tmp_path / "real.txt").write_bytes(b"data")
    base = template_checksum(tmp_path)
    (tmp_path / ".DS_Store").write_bytes(b"junk")
    (tmp_path / "Thumbs.db").write_bytes(b"junk")
    sub = tmp_path / "Nested"
    sub.mkdir()
    (sub / "desktop.ini").write_bytes(b"junk")
    assert template_checksum(tmp_path) == base


def test_collect_files_posix_relative(tmp_path):
    (tmp_path / "dir" / "sub").mkdir(parents=True)
    (tmp_path / "dir" / "sub" / "f.txt").write_bytes(b"1")
    entries = collect_files(tmp_path)
    assert [rel for rel, _ in entries] == ["dir/sub/f.txt"]


def test_missing_dir_raises(tmp_path):
    with pytest.raises(FileNotFoundError):
        template_checksum(tmp_path / "nope")


def test_verify_mismatch(tmp_path):
    (tmp_path / "f").write_bytes(b"x")
    ok, actual = verify_checksum(tmp_path, "0" * 64)
    assert not ok
    assert actual == template_checksum(tmp_path)
