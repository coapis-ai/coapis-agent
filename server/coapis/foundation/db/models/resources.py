# -*- coding: utf-8 -*-
"""Resource contract tables: ``resources`` + ``resource_refs`` (R1, migration 0015).

Two tables, deliberately **not** merged into ``file_records``:

* ``file_records`` is an **append-only event stream** ("a write happened"),
  never DELETE, read paths dedupe by ``file_path`` keeping the newest row.
* ``resources`` is a **state table** ("what this resource is now, who
  references it"), and ``resource_refs`` is the **only** source of reference
  counts.

Mixing the two would break the "never DELETE" contract and every existing
read path (chat_id filtering, deliverables, stats), so a new table is used.

**Reference counts are derived from ``resource_refs``; there is no redundant
count column.** A denormalised counter drifts from the relation table and the
drift is undetectable.

``resource_key`` includes the owner component. This is the direct lesson of
the P0 fixed in migration 0014: ``memories.dedup_key`` was
``sha256(scope|category|title|content)`` with **no owner** while the UNIQUE
constraint is global — two agents producing the same result collided on
INSERT (crashing the nightly dream) and ``add()``'s global lookup collapsed
the second writer's row into the first writer's, mis-attributing ownership.
Any "global UNIQUE + owner-less key" combination is a design defect.

Timestamps are epoch floats in REAL columns (the user-domain convention,
matching ``file_records`` / ``token_usage``).
"""

from __future__ import annotations

import hashlib
from typing import Optional

from sqlalchemy import Float, Index, Integer, Text, text
from sqlalchemy.orm import Mapped, mapped_column

from ..base import BaseRow

#: Owner scopes. Mirrors the memory-scope convention already in the codebase.
VALID_OWNER_SCOPES = frozenset({"user", "agent", "workspace"})

#: Resource kinds.
VALID_KINDS = frozenset({"file", "db", "kb", "mcp", "web"})

#: Status lifecycle (frozen state machine, §6 of the contract).
VALID_STATUSES = frozenset({"draft", "official", "orphan", "archived", "deleted"})

#: Referrer kinds for ``resource_refs``.
VALID_REFERRER_KINDS = frozenset({"session", "chat", "agent", "user", "scene"})

#: Referrer roles.
VALID_ROLES = frozenset({"reference", "producer", "consumer"})


def make_resource_key(owner_scope: str, owner_id: str, kind: str, path: str) -> str:
    """Stable resource identity. **Owner is a component** (see module docstring).

    Normalising the path keeps separators consistent so the same file under
    the same owner maps to exactly one key on SQLite and PostgreSQL.
    """
    norm_path = str(path).replace("\\", "/").strip().lower()
    raw = "|".join([owner_scope, owner_id, kind, norm_path])
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


class Resource(BaseRow):
    __tablename__ = "resources"

    id: Mapped[int] = mapped_column(
        Integer, primary_key=True, autoincrement=True, nullable=False
    )
    resource_key: Mapped[str] = mapped_column(Text, unique=True, nullable=False)
    owner_scope: Mapped[str] = mapped_column(Text, nullable=False)
    owner_id: Mapped[str] = mapped_column(Text, nullable=False)
    kind: Mapped[str] = mapped_column(Text, nullable=False)
    path: Mapped[str] = mapped_column(Text, nullable=False)
    title: Mapped[Optional[str]] = mapped_column(Text)
    status: Mapped[str] = mapped_column(
        Text, nullable=False, default="draft", server_default=text("'draft'")
    )
    size_bytes: Mapped[int] = mapped_column(
        Integer, default=0, server_default=text("0")
    )
    # 交付版本号（方案 §12.4 L1 版本徽标）：首次登记=1；再次登记时**大小变了**
    # （内容真的换了）才 +1；同一份内容被反复引用不算新版。规则只写在 register。
    version: Mapped[int] = mapped_column(
        Integer, default=1, server_default=text("1")
    )
    #: 这一行是怎么来的：``hook``（工具调用时登记）/ ``backfill``（巡检补登记
    #: 的台账上线前存量）/ ``reconcile``。写入后不再改写——来源是历史事实。
    source: Mapped[str] = mapped_column(
        Text, nullable=False, default="hook", server_default=text("'hook'")
    )
    #: Written by the sweep only: does the file exist on the filesystem?
    fs_present: Mapped[int] = mapped_column(
        Integer, default=1, server_default=text("1")
    )
    first_seen_at: Mapped[Optional[float]] = mapped_column(Float)
    last_seen_at: Mapped[Optional[float]] = mapped_column(Float)
    updated_at: Mapped[Optional[float]] = mapped_column(Float)
    #: Soft delete (mirrors the memories convention); FS is never touched.
    deleted_at: Mapped[Optional[float]] = mapped_column(Float)

    __table_args__ = (
        Index("idx_resources_owner", "owner_scope", "owner_id"),
        Index("idx_resources_kind", "kind"),
        Index("idx_resources_status", "status"),
        Index("idx_resources_fs", "fs_present"),
    )


class ResourceRef(BaseRow):
    __tablename__ = "resource_refs"

    id: Mapped[int] = mapped_column(
        Integer, primary_key=True, autoincrement=True, nullable=False
    )
    resource_key: Mapped[str] = mapped_column(Text, nullable=False)
    referrer_kind: Mapped[str] = mapped_column(Text, nullable=False)
    referrer_id: Mapped[str] = mapped_column(Text, nullable=False)
    role: Mapped[str] = mapped_column(
        Text, nullable=False, default="reference", server_default=text("'reference'")
    )
    created_at: Mapped[Optional[float]] = mapped_column(Float)

    __table_args__ = (
        Index("idx_resource_refs_key", "resource_key"),
        Index("idx_resource_refs_referrer", "referrer_kind", "referrer_id"),
    )
