# -*- coding: utf-8 -*-
"""Declarative base for the unified SQLAlchemy data layer.

All 13 community tables are mapped here. Models mirror the existing
``community_schema.sql`` **column-for-column** so that:

* existing dev/prod databases need **zero data migration** (types,
  defaults and names match exactly);
* the dict contracts returned by repositories are byte-identical to the
  legacy sqlite3 implementations.

Timestamp convention (inherited from the legacy schema, deliberately kept):

* user-domain tables (users / user_settings / user_preferences / api_keys /
  audit_logs / point_transactions / token_usage) store epoch **floats** in
  ``REAL`` columns — the API/frontend contract is ``new Date(ts * 1000)``;
* M1 domain tables (tags / scenes / user_scene_settings / external_bindings /
  external_systems) store ISO-8601 **text** in ``TEXT`` columns.

Both representations are portable across SQLite and PostgreSQL (REAL ↔
DOUBLE PRECISION, TEXT ↔ TEXT), satisfying the dialect-neutrality
requirement without touching any consumer.
"""

from __future__ import annotations

from typing import Any

from sqlalchemy.orm import DeclarativeBase


class Base(DeclarativeBase):
    """Declarative base for all unified data-layer models.

    No custom naming convention: every index is explicitly named (matching
    the legacy schema exactly) and unique constraints stay unnamed so
    SQLite creates its standard auto-indexes — identical to the legacy DDL.
    """


class BaseRow(Base):
    """Abstract base with dict round-trip helpers.

    ``to_dict()`` returns every column of the table with its native Python
    value (str / int / float / None) — identical to the legacy
    ``dict(sqlite3.Row)`` output.
    """

    __abstract__ = True

    def to_dict(self) -> dict[str, Any]:
        # c.name = DB column name (dict key, matches legacy dict(row));
        # c.key  = Python attribute name (e.g. ``metadata_``).
        return {c.name: getattr(self, c.key) for c in self.__table__.columns}
