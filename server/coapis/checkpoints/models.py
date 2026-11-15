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

"""检查点数据类（B5-A 最小版）。

三个对象就是这一层的全部语言：

* ``Checkpoint``   —— 某一刻工作区的**只读指纹清单**（相对路径 -> sha256/size）；
* ``DiffResult``   —— 一个文件"检查点 vs 当下"的差异；
* ``RestorePlan``  —— 预览产物：将要恢复什么、保留什么、工作区多出来什么、
  缺哪些块。**预览即计划**，计划不落盘。

不建数据库表（B5-A 明确不做），全部走 JSON 清单文件；``to_dict`` 就是
对外契约，前端直接吃。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Optional

#: 检查点种类：manual = 用户/智能体主动创建；pre_restore = 恢复前自动生成。
KIND_MANUAL = "manual"
KIND_PRE_RESTORE = "pre_restore"

#: 差异种类。
DIFF_CHANGED = "changed"  # 两边都有，哈希不同
DIFF_MISSING = "missing"  # 检查点里有，当下工作区没有
DIFF_EXTRA = "extra"  # 当下工作区有，检查点里没有（恢复不动它）
DIFF_UNCHANGED = "unchanged"  # 哈希一致，恢复不动它


@dataclass
class Checkpoint:
    """一次工作区快照的指纹清单。"""

    checkpoint_id: str
    username: str
    created_at: float
    files: dict[str, dict[str, Any]] = field(default_factory=dict)
    session: Optional[str] = None
    note: str = ""
    kind: str = KIND_MANUAL
    pre_restore_of: Optional[str] = None
    store_root: str = ""

    # ── 计算属性 ──────────────────────────────────────────────────────
    @property
    def file_count(self) -> int:
        return len(self.files)

    @property
    def total_size(self) -> int:
        return sum(int(v.get("size") or 0) for v in self.files.values())

    # ── 序列化 ────────────────────────────────────────────────────────
    def to_dict(self, *, include_files: bool = True) -> dict[str, Any]:
        out: dict[str, Any] = {
            "checkpoint_id": self.checkpoint_id,
            "username": self.username,
            "created_at": float(self.created_at),
            "session": self.session,
            "note": self.note,
            "kind": self.kind,
            "pre_restore_of": self.pre_restore_of,
            "file_count": self.file_count,
            "total_size": self.total_size,
        }
        if include_files:
            out["files"] = {k: dict(v) for k, v in self.files.items()}
        return out

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> "Checkpoint":
        return cls(
            checkpoint_id=str(raw["checkpoint_id"]),
            username=str(raw.get("username") or ""),
            created_at=float(raw.get("created_at") or 0.0),
            files={
                str(k): dict(v)
                for k, v in (raw.get("files") or {}).items()
            },
            session=raw.get("session"),
            note=str(raw.get("note") or ""),
            kind=str(raw.get("kind") or KIND_MANUAL),
            pre_restore_of=raw.get("pre_restore_of"),
            store_root=str(raw.get("store_root") or ""),
        )

    def to_summary(self) -> dict[str, Any]:
        """列表用的摘要（不带文件明细）。"""
        return self.to_dict(include_files=False)


@dataclass
class DiffResult:
    """单个文件的差异。"""

    rel: str
    kind: str
    sha_checkpoint: Optional[str] = None
    sha_current: Optional[str] = None
    size_checkpoint: Optional[int] = None
    size_current: Optional[int] = None

    @property
    def will_restore(self) -> bool:
        """这次恢复会不会动这个文件（changed / missing 才动）。"""
        return self.kind in (DIFF_CHANGED, DIFF_MISSING)

    def to_dict(self) -> dict[str, Any]:
        return {
            "rel": self.rel,
            "kind": self.kind,
            "sha_checkpoint": self.sha_checkpoint,
            "sha_current": self.sha_current,
            "size_checkpoint": self.size_checkpoint,
            "size_current": self.size_current,
            "will_restore": self.will_restore,
        }


@dataclass
class RestorePlan:
    """回滚预览（dry_run 产物）——只读，绝不落盘。"""

    checkpoint_id: str
    username: str
    diffs: list[DiffResult] = field(default_factory=list)
    missing_blobs: list[str] = field(default_factory=list)
    dry_run: bool = True
    created_at: float = 0.0
    reason: str = ""
    #: 台账口径的版次（rel -> 第几版）。台账不可用时为空表。
    ledger_versions: dict[str, int] = field(default_factory=dict)

    # ── 分组 ──────────────────────────────────────────────────────────
    @property
    def to_restore(self) -> list[DiffResult]:
        return [d for d in self.diffs if d.will_restore]

    @property
    def unchanged(self) -> list[DiffResult]:
        return [d for d in self.diffs if d.kind == DIFF_UNCHANGED]

    @property
    def extras(self) -> list[DiffResult]:
        return [d for d in self.diffs if d.kind == DIFF_EXTRA]

    @property
    def writable(self) -> bool:
        """计划可执行 = 需要的内容块都在（缺块就必须整体中止，绝不半恢复）。"""
        return not self.missing_blobs

    @property
    def restore_bytes(self) -> int:
        return sum(
            int(d.size_checkpoint or 0) for d in self.diffs if d.will_restore
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "checkpoint_id": self.checkpoint_id,
            "username": self.username,
            "dry_run": bool(self.dry_run),
            "created_at": float(self.created_at),
            "writable": self.writable,
            "reason": self.reason,
            "file_count": len(self.diffs),
            "to_restore_count": len(self.to_restore),
            "unchanged_count": len(self.unchanged),
            "extra_count": len(self.extras),
            "restore_bytes": self.restore_bytes,
            "missing_blobs": list(self.missing_blobs),
            "ledger_versions": dict(self.ledger_versions),
            "diffs": [d.to_dict() for d in self.diffs],
        }


@dataclass
class RestoreOutcome:
    """执行恢复的结果（含自动生成的"恢复前检查点"）。"""

    checkpoint_id: str
    pre_restore_checkpoint_id: Optional[str]
    restored: list[str] = field(default_factory=list)
    skipped: list[str] = field(default_factory=list)
    ledger_registered: list[str] = field(default_factory=list)
    total_bytes: int = 0

    def to_dict(self) -> dict[str, Any]:
        return {
            "checkpoint_id": self.checkpoint_id,
            "pre_restore_checkpoint_id": self.pre_restore_checkpoint_id,
            "restored": list(self.restored),
            "skipped": list(self.skipped),
            "ledger_registered": list(self.ledger_registered),
            "total_bytes": int(self.total_bytes),
        }
