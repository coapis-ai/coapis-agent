# -*- coding: utf-8 -*-
"""migration_state — idempotency flags for one-shot data migrations."""

from __future__ import annotations

from typing import Optional

from sqlalchemy import REAL, Text
from sqlalchemy.orm import Mapped, mapped_column

from ..base import BaseRow


class MigrationState(BaseRow):
    __tablename__ = "migration_state"

    # NOTE: the Python attribute is ``key_`` because ``key`` is a reserved
    # Declarative attribute; the DB column stays ``key``.
    key_: Mapped[Optional[str]] = mapped_column(
        "key", Text, primary_key=True, nullable=True
    )
    value: Mapped[Optional[str]] = mapped_column(Text)
    updated_at: Mapped[Optional[float]] = mapped_column(REAL)
