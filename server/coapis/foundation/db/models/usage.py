# -*- coding: utf-8 -*-
"""Usage-domain models: point_transactions / token_usage.

Mirrors ``community_schema.sql`` exactly (see ``models/user.py`` header for
the nullability / default conventions).
"""

from __future__ import annotations

from typing import Optional

from sqlalchemy import Index, Integer, REAL, Text, text
from sqlalchemy.orm import Mapped, mapped_column

from ..base import BaseRow


class PointTransaction(BaseRow):
    __tablename__ = "point_transactions"

    id: Mapped[int] = mapped_column(
        Integer, primary_key=True, autoincrement=True, nullable=False
    )
    user_id: Mapped[str] = mapped_column(Text, nullable=False)
    amount: Mapped[int] = mapped_column(Integer, nullable=False)
    balance_after: Mapped[int] = mapped_column(Integer, nullable=False)
    transaction_type: Mapped[str] = mapped_column(Text, nullable=False)
    description: Mapped[Optional[str]] = mapped_column(Text)
    reference_id: Mapped[Optional[str]] = mapped_column(Text)
    created_at: Mapped[Optional[float]] = mapped_column(REAL)

    __table_args__ = (Index("idx_points_user", "user_id"),)


class TokenUsage(BaseRow):
    __tablename__ = "token_usage"

    id: Mapped[int] = mapped_column(
        Integer, primary_key=True, autoincrement=True, nullable=False
    )
    user_id: Mapped[str] = mapped_column(Text, nullable=False)
    username: Mapped[Optional[str]] = mapped_column(Text)
    agent_id: Mapped[Optional[str]] = mapped_column(Text)
    model: Mapped[str] = mapped_column(Text, nullable=False)
    input_tokens: Mapped[Optional[int]] = mapped_column(
        Integer, default=0, server_default=text("0")
    )
    output_tokens: Mapped[Optional[int]] = mapped_column(
        Integer, default=0, server_default=text("0")
    )
    total_tokens: Mapped[Optional[int]] = mapped_column(
        Integer, default=0, server_default=text("0")
    )
    cost_cents: Mapped[Optional[float]] = mapped_column(
        REAL, default=0.0, server_default=text("0")
    )
    created_at: Mapped[Optional[float]] = mapped_column(REAL)

    __table_args__ = (
        Index("idx_token_usage_user", "user_id"),
        Index("idx_token_usage_created", "created_at"),
    )
