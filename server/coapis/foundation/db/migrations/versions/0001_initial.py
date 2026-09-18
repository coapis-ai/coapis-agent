# -*- coding: utf-8 -*-
"""Initial schema for the unified data layer (13 community tables).

The DDL is generated from the SQLAlchemy models (``Base.metadata``), which
mirror the legacy ``community_schema.sql`` column-for-column. The upgrade
is **idempotent**:

* fresh database  → creates all 13 tables + indexes from the models;
* legacy database → tables already exist with the identical schema, so the
  upgrade only verifies that named indexes are present (no-op in practice).

This lets a single ``alembic upgrade head`` serve both brand-new
installations and databases created by the pre-SQLAlchemy ``migrations.py``
path, with zero data movement.

Revision ID: 0001
Revises:
Create Date: 2026-09-17
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = "0001"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _tables():
    # Imported here so the models are registered on Base.metadata.
    import coapis.foundation.db.models  # noqa: F401
    from coapis.foundation.db.base import Base

    return Base.metadata.sorted_tables


def upgrade() -> None:
    bind = op.get_bind()
    existing = set(sa.inspect(bind).get_table_names())

    for table in _tables():
        if table.name in existing:
            # Legacy DB: table exists with the identical schema.
            for idx in table.indexes:
                idx.create(bind, checkfirst=True)
            continue
        table.create(bind, checkfirst=True)
        for idx in table.indexes:
            idx.create(bind, checkfirst=True)


def downgrade() -> None:
    bind = op.get_bind()
    for table in reversed(_tables()):
        table.drop(bind, checkfirst=True)
