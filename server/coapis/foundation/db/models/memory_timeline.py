# -*- coding: utf-8 -*-
"""Memory-domain model: memory_timelines (dream signal promotion target).

Table shape follows ``tech_docs/记忆系统整合设计方案.md`` §5.2:

* one row per promoted signal — ``signal_type`` ∈
  ``{decision, preference, goal, conversation}``;
* ``dedup_key`` = sha256(user_id|session_id|signal_type|normalized_content)
  — UNIQUE, so repeated dream runs and backfills never duplicate;
* timestamps are Unix floats (same convention as ``memories``);
* hard-deleted after retention (no soft-delete UI planned for this table).
"""

from __future__ import annotations

from typing import Optional

from sqlalchemy import Float, Index, Integer, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from ..base import BaseRow


class MemoryTimeline(BaseRow):
    __tablename__ = "memory_timelines"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True, nullable=False)
    user_id: Mapped[str] = mapped_column(Text, nullable=False, default="")
    agent_id: Mapped[Optional[str]] = mapped_column(Text)
    session_id: Mapped[Optional[str]] = mapped_column(Text)
    signal_type: Mapped[str] = mapped_column(Text, nullable=False, default="conversation")
    content: Mapped[Optional[str]] = mapped_column(Text)
    source: Mapped[Optional[str]] = mapped_column(Text)
    dedup_key: Mapped[Optional[str]] = mapped_column(Text)
    importance: Mapped[float] = mapped_column(Float, nullable=False, default=0.5)
    created_at: Mapped[Optional[float]] = mapped_column(Float)
    updated_at: Mapped[Optional[float]] = mapped_column(Float)
    deleted_at: Mapped[Optional[float]] = mapped_column(Float)
    # 晋升标记：NULL = 未晋升；非 NULL = 已写入 memories（晋升防重唯一依据）。
    promoted_at: Mapped[Optional[float]] = mapped_column(Float)

    __table_args__ = (
        UniqueConstraint("dedup_key", name="uq_mtl_dedup_key"),
        Index("ix_mtl_user_created", "user_id", "created_at"),
        Index("ix_mtl_signal_type", "signal_type"),
    )
