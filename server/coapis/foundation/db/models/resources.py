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
#:
#: v25 · P3（2026-11-10）：白名单必须与**读侧/前端同一把尺子**。此前这里只有
#: reference/producer/consumer，而 ``resource_ledger._CHAT_ROLE_PRODUCED`` 与
#: 前端 ``chat.ts`` 的 role 类型都声明了 ``export``（``_CHAT_ROLE_PRIORITY``
#: 还有 ``attachment``）——写入侧 ``attach_ref`` 按本白名单**直接丢行**，
#: 于是「导出件」永远进不了台账，前端「产出」侧那条筛选尺子筛的是空气。
VALID_ROLES = frozenset(
    {"reference", "producer", "consumer", "attachment", "export"}
)

#: 类别尺子在 ``foundation/resource_category.py``（v20 · W1）：kind 回答
#: "从哪个子系统来"，category 回答"用户手里这是个什么东西"。列由 register
#: 写入，换算函数全仓唯一（``resolve_category``）。
VALID_CATEGORIES = frozenset(
    {
        "doc", "sheet", "slide", "pdf", "image", "media", "archive",
        "code", "web", "chat_record", "db_record", "kb_entry",
        "mcp_tool", "other",
    }
)


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
    #: v20 · W1：类别（resolve_category 换算）。迁移 0024。
    category: Mapped[str] = mapped_column(
        Text, nullable=False, default="other", server_default=text("'other'")
    )
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
        Index("idx_resources_category", "category"),
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
    #: 轮号（v26 · F5，拍板 D5）：``referrer_kind="chat"`` 的行带上"哪一轮"。
    #:
    #: 为什么需要：采集器旧口径只写 chat 级引用，于是「本轮产出」只能按 chat
    #: 查 = 该会话全部历史行——本轮补扫/文件钩子写的行与上一轮的文件混在
    #: 一起（实测 dev 一个会话 122 行里，本轮真正产出的只有 4 个文件）。
    #: 「本轮」按 turn_id 筛，「会话」按 chat_id 筛，两把尺子各归各位。
    #: 存量行为 NULL = 未知轮号：**只出现在会话面，不出现在本轮面**
    #: （未知不等于本轮，诚实比凑数重要）。
    turn_id: Mapped[Optional[str]] = mapped_column(Text)
    created_at: Mapped[Optional[float]] = mapped_column(Float)

    __table_args__ = (
        Index("idx_resource_refs_key", "resource_key"),
        Index("idx_resource_refs_referrer", "referrer_kind", "referrer_id"),
        Index("idx_resource_refs_turn", "referrer_kind", "referrer_id", "turn_id"),
    )
