# -*- coding: utf-8 -*-
"""file_records enrich: title / status / updated_at / description (deliverables ledger).

Adds the four columns required by the deliverables-ledger upgrade (approved
plan C1, batch 2 of the memory consolidation design):

* ``title``       — human-readable name (derived from filename at write time)
* ``status``      — draft / delivered / archived (defaults to ``draft``)
* ``updated_at``  — Unix epoch float, set whenever status/title/desc change
* ``description`` — optional free-form notes

Append-only semantics are preserved: status changes UPDATE the newest row
of a ``(user_id, file_path)`` pair; no DELETE is ever issued.

Revision ID: 0012
Revises: 0011
Create Date: 2026-10-06
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0012"
down_revision: Union[str, None] = "0011"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _existing_columns(table: str) -> set:
    insp = sa.inspect(op.get_bind())
    return {c["name"] for c in insp.get_columns(table)}


def _existing_indexes(table: str) -> set:
    insp = sa.inspect(op.get_bind())
    return {i["name"] for i in insp.get_indexes(table)}


def upgrade() -> None:
    cols = _existing_columns("file_records")
    idxs = _existing_indexes("file_records")
    if "title" not in cols:
        op.add_column("file_records", sa.Column("title", sa.Text(), nullable=True))
    if "status" not in cols:
        op.add_column(
            "file_records",
            sa.Column("status", sa.Text(), server_default="draft", nullable=False),
        )
    if "updated_at" not in cols:
        op.add_column("file_records", sa.Column("updated_at", sa.REAL(), nullable=True))
    if "description" not in cols:
        op.add_column("file_records", sa.Column("description", sa.Text(), nullable=True))
    if "idx_file_records_status" not in idxs:
        op.create_index("idx_file_records_status", "file_records", ["status"])


def downgrade() -> None:
    op.drop_index("idx_file_records_status", table_name="file_records")
    op.drop_column("file_records", "description")
    op.drop_column("file_records", "updated_at")
    op.drop_column("file_records", "status")
    op.drop_column("file_records", "title")
