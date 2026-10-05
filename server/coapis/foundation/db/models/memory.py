# -*- coding: utf-8 -*-
"""Memory-domain model: memories (unified long-term memory ledger).

Table shape follows ``tech_docs/记忆能力升级-社区版可执行方案_v1.md`` §3.2:

* ``scope`` ∈ ``{user, agent, workspace}``;
* ``dedup_key`` = sha256(scope:category:title:normalized_content) —
  UNIQUE on its own (it encodes scope/category/title/content), so
  identical memories collapse into one row (importance takes the max,
  created_at keeps the earliest);
* ``deleted_at`` soft-delete (NULL = alive), mirroring the scene table
  convention.
"""

from __future__ import annotations

from typing import Optional

from sqlalchemy import Float, Index, Integer, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from ..base import BaseRow


class Memory(BaseRow):
    __tablename__ = "memories"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True, nullable=False)
    scope: Mapped[str] = mapped_column(Text, nullable=False, default="user")
    user_id: Mapped[str] = mapped_column(Text, nullable=False)
    agent_id: Mapped[Optional[str]] = mapped_column(Text)
    workspace_id: Mapped[Optional[str]] = mapped_column(Text)
    category: Mapped[str] = mapped_column(Text, nullable=False, default="fact")
    title: Mapped[Optional[str]] = mapped_column(Text)
    content: Mapped[Optional[str]] = mapped_column(Text)
    source: Mapped[Optional[str]] = mapped_column(Text)
    dedup_key: Mapped[Optional[str]] = mapped_column(Text)
    importance: Mapped[float] = mapped_column(Float, nullable=False, default=0.5)
    created_at: Mapped[Optional[float]] = mapped_column(Float)
    updated_at: Mapped[Optional[float]] = mapped_column(Float)
    deleted_at: Mapped[Optional[float]] = mapped_column(Float)

    __table_args__ = (
        UniqueConstraint("dedup_key", name="uq_memories_dedup_key"),
        Index("ix_memories_scope_user", "scope", "user_id"),
        Index("ix_memories_category", "category"),
        Index("ix_memories_created", "created_at"),
    )
