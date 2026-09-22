# -*- coding: utf-8 -*-
"""B-tier runtime-domain models: token_usage_daily / permissions_config.

These two tables were historically created only by the legacy raw-DDL path
(``community_schema.sql`` via ``migrations._create_schema``, and only if that
script ran) — they never lived on ``Base.metadata``, so a fresh database
built purely with ``alembic upgrade head`` was missing them.  Registering
them here brings every community table under Alembic's single source of truth:

* :func:`migrations.env` / ``0001_initial._tables()`` read the whole package,
  so both tables are now created on fresh installs and backfilled (IF NOT
  EXISTS) on legacy databases — no extra revision needed.

Column shapes mirror ``community_schema.sql`` exactly (verified line-by-line
on 2026-09-21 against every consumer: the B-tier JSON migrations in
``migrations.py``, ``token_usage/`` runtime writers and
``app/permissions/manager.py`).

Timestamps: ``date`` is ISO date text (YYYY-MM-DD), ``last_updated`` is ISO
datetime text (naive local) — matching the raw-SQL consumers exactly.
"""

from __future__ import annotations

from typing import Optional

from sqlalchemy import Integer, Text, text
from sqlalchemy.orm import Mapped, mapped_column

from ..base import BaseRow


class TokenUsageDaily(BaseRow):
    """Daily per-(provider, model) token aggregate (B tier)."""

    __tablename__ = "token_usage_daily"

    # NOTE: ``date`` is a reserved word in some dialects — the column name is
    # kept as-is to match legacy DDL; access via attribute works fine.
    date: Mapped[str] = mapped_column(Text, primary_key=True, nullable=False)
    provider_id: Mapped[str] = mapped_column(Text, primary_key=True, nullable=False)
    model_name: Mapped[str] = mapped_column(Text, primary_key=True, nullable=False)

    # Legacy DDL: ``INTEGER DEFAULT 0`` (nullable + server default), mirrored.
    prompt_tokens: Mapped[Optional[int]] = mapped_column(
        Integer, default=0, server_default=text("0")
    )
    completion_tokens: Mapped[Optional[int]] = mapped_column(
        Integer, default=0, server_default=text("0")
    )
    call_count: Mapped[Optional[int]] = mapped_column(
        Integer, default=0, server_default=text("0")
    )

    # Legacy DDL: ``TEXT NOT NULL DEFAULT ''`` — mirrored exactly.
    last_updated: Mapped[str] = mapped_column(
        Text, nullable=False, default="", server_default=text("''")
    )


class PermissionsConfig(BaseRow):
    """Key/value permission configuration (B tier).

    The single seed row ``key='all'`` holds the whole permissions dict as a
    JSON string; it is written by :func:`migrations._migrate_permissions` and
    read/written by :mod:`coapis.app.permissions.manager`.  Legacy DDL has no
    timestamp column — do not add one without an explicit migration.
    """

    __tablename__ = "permissions_config"

    # NOTE: ``key`` is a reserved Declarative attribute name; the DB column
    # stays ``key`` (same convention as :class:`MigrationState`).
    key_: Mapped[str] = mapped_column("key", Text, primary_key=True)
    # Legacy DDL: ``TEXT NOT NULL DEFAULT '{}'`` — mirrored exactly.
    value: Mapped[str] = mapped_column(
        "value", Text, nullable=False, default="{}", server_default=text("'{}'")
    )

