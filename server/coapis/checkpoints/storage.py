# -*- coding: utf-8 -*-
# Copyright 2026 蜜蜂 & CoApis Contributors
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU Affero General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU Affero General Public License for more details.
#
# You should have received a copy of the GNU Affero General Public License
# along with this program.  If not, see <https://www.gnu.org/licenses/>.

"""内容寻址存储（B5-A 最小版）。

结构（全在一个用户工作区里，天然按人隔离，不碰数据卷系统目录）::

    workspaces/<user>/checkpoints/
        blobs/ab/abcdef...        # 内容块：sha256 前两位分桶
        manifests/<id>.json       # 检查点清单：相对路径 -> {sha256, size}
        index.json                # 全局索引（追加式，摘要级）

三条硬规矩：

* **只读快照**：blob 一旦写下永不改写（content-addressed，同哈希同内容），
  恢复是"用 blob 覆盖工作区文件"，不是"改 blob"；
* **``dry_run=True`` 只算不改**：本模块所有写函数在 dry_run 下**直接返回**，
  不建目录、不落文件、不碰索引——测试用盘上哈希自证；
* **写入原子**：临时文件 + ``os.replace``，不留半截文件。
"""

from __future__ import annotations

import json
import logging
import os
import time
import uuid
from pathlib import Path
from typing import Any, Iterable, Optional

from .models import Checkpoint

logger = logging.getLogger(__name__)

_INDEX_NAME = "index.json"
_BLOBS_DIR = "blobs"
_MANIFESTS_DIR = "manifests"
#: 内容块分桶前缀长度（16²=256 个桶，避免单目录爆文件）。
_BUCKET = 2
_CHUNK = 1 << 16


class BlobMissingError(FileNotFoundError):
    """索引指向的内容块不在盘上——恢复必须整体中止，绝不半恢复。"""


class CheckpointStore:
    """检查点仓库（内容寻址 + 清单 + 索引）。"""

    def __init__(self, store_root: Path | str) -> None:
        self.root = Path(store_root)
        self.blobs_dir = self.root / _BLOBS_DIR
        self.manifests_dir = self.root / _MANIFESTS_DIR
        self.index_file = self.root / _INDEX_NAME

    # ── 路径 ──────────────────────────────────────────────────────────
    def blob_path(self, digest: str) -> Path:
        d = _safe_digest(digest)
        return self.blobs_dir / d[:_BUCKET] / d

    def manifest_path(self, checkpoint_id: str) -> Path:
        return self.manifests_dir / ("%s.json" % _safe_id(checkpoint_id))

    # ── 内容块 ────────────────────────────────────────────────────────
    def has_blob(self, digest: str) -> bool:
        return self.blob_path(digest).is_file()

    def put_file(
        self, digest: str, src: Path | str, *, dry_run: bool = False
    ) -> bool:
        """把文件内容落成内容块；已存在则复用。返回**是否真的写了盘**。"""
        target = self.blob_path(digest)
        if target.is_file():
            return False
        if dry_run:
            return False
        _atomic_write(target, _read_bytes(src))
        return True

    def put_bytes(
        self, digest: str, data: bytes, *, dry_run: bool = False
    ) -> bool:
        target = self.blob_path(digest)
        if target.is_file():
            return False
        if dry_run:
            return False
        _atomic_write(target, data)
        return True

    def read_blob(self, digest: str) -> bytes:
        path = self.blob_path(digest)
        if not path.is_file():
            raise BlobMissingError(
                "检查点内容块缺失: %s（仓库不完整，恢复已整体中止）" % digest
            )
        return _read_bytes(path)

    # ── 清单 ──────────────────────────────────────────────────────────
    def write_manifest(
        self, checkpoint: Checkpoint, *, dry_run: bool = False
    ) -> Optional[Path]:
        path = self.manifest_path(checkpoint.checkpoint_id)
        if dry_run:
            return None
        payload = checkpoint.to_dict(include_files=True)
        payload["store_root"] = str(self.root)
        _atomic_write(
            path,
            json.dumps(payload, ensure_ascii=False, indent=2,
                       sort_keys=True).encode("utf-8"),
        )
        return path

    def read_manifest(self, checkpoint_id: str) -> Optional[dict[str, Any]]:
        path = self.manifest_path(checkpoint_id)
        if not path.is_file():
            return None
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            logger.warning("检查点清单读取失败 %s: %s", checkpoint_id, exc)
            return None
        return raw if isinstance(raw, dict) else None

    def load_checkpoint(self, checkpoint_id: str) -> Optional[Checkpoint]:
        raw = self.read_manifest(checkpoint_id)
        if raw is None:
            return None
        cp = Checkpoint.from_dict(raw)
        cp.store_root = str(self.root)
        return cp

    def iter_checkpoints(self) -> list[Checkpoint]:
        """按创建时间倒序读回全部检查点（清单文件即真相，索引只是目录）。"""
        out: list[Checkpoint] = []
        if not self.manifests_dir.is_dir():
            return out
        for path in sorted(self.manifests_dir.glob("*.json")):
            try:
                raw = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, ValueError) as exc:
                logger.warning("检查点清单跳过 %s: %s", path.name, exc)
                continue
            if not isinstance(raw, dict):
                continue
            try:
                cp = Checkpoint.from_dict(raw)
            except (KeyError, TypeError, ValueError):
                continue
            cp.store_root = str(self.root)
            out.append(cp)
        out.sort(key=lambda c: (float(c.created_at), c.checkpoint_id),
                 reverse=True)
        return out

    # ── 索引（摘要级，追加式） ─────────────────────────────────────────
    def append_index(
        self, checkpoint: Checkpoint, *, dry_run: bool = False
    ) -> None:
        """把摘要追加进全局索引。索引坏了不影响清单可读——它是目录不是真相。"""
        if dry_run:
            return
        entries = self.load_index()
        entry = checkpoint.to_summary()
        entry["manifest"] = "%s.json" % checkpoint.checkpoint_id
        entries.append(entry)
        _atomic_write(
            self.index_file,
            json.dumps(entries, ensure_ascii=False, indent=2).encode("utf-8"),
        )

    def load_index(self) -> list[dict[str, Any]]:
        if not self.index_file.is_file():
            return []
        try:
            raw = json.loads(self.index_file.read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            logger.warning("检查点索引读取失败: %s", exc)
            return []
        return raw if isinstance(raw, list) else []


# --------------------------------------------------------------------------- #
# helpers
# --------------------------------------------------------------------------- #


def new_checkpoint_id() -> str:
    return uuid.uuid4().hex


def _safe_digest(digest: str) -> str:
    d = str(digest or "").strip().lower()
    if len(d) != 64 or any(c not in "0123456789abcdef" for c in d):
        raise ValueError("非法内容哈希: %r" % digest)
    return d


def _safe_id(checkpoint_id: str) -> str:
    """清单文件名只收十六进制 id——挡住 ``../`` 之类的路径注入。"""
    i = str(checkpoint_id or "").strip()
    if not i or any(c not in "0123456789abcdef" for c in i):
        raise ValueError("非法检查点 id: %r" % checkpoint_id)
    if len(i) > 64:
        raise ValueError("非法检查点 id: %r" % checkpoint_id)
    return i


def _read_bytes(path: Path | str) -> bytes:
    with open(str(path), "rb") as fh:
        return fh.read()


def _atomic_write(target: Path, data: bytes) -> None:
    """临时文件 + ``os.replace``：要么完整落地，要么保持原样。"""
    target.parent.mkdir(parents=True, exist_ok=True)
    tmp = target.parent / (".tmp-%s-%s" % (os.getpid(), uuid.uuid4().hex))
    try:
        with open(str(tmp), "wb") as fh:
            fh.write(data)
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(str(tmp), str(target))
    finally:
        if tmp.exists():
            try:
                os.unlink(str(tmp))
            except OSError:  # pragma: no cover - 已被 replace 消费
                pass
