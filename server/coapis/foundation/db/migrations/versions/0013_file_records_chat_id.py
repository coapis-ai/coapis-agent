# -*- coding: utf-8 -*-
"""file_records: add chat_id (per-chat file attribution).

``session_id`` stores the channel-resolved form (``console:alice``), which
identifies a user's console session but not a single chat. The frontend
filters "files of this chat" by the chat UUID, so the ledger needs a column
that actually holds it.

Rows written before this migration keep ``chat_id = NULL`` and are
intentionally NOT backfilled: per-chat filtering only covers files produced
from now on (approved decision D2).

Revision ID: 0013
Revises: 0012
Create Date: 2026-10-10
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0013"
down_revision: Union[str, None] = "0012"
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
    if "chat_id" not in cols:
        op.add_column("file_records", sa.Column("chat_id", sa.Text(), nullable=True))
    if "idx_file_records_chat" not in idxs:
        op.create_index("idx_file_records_chat", "file_records", ["chat_id"])


def downgrade() -> None:
    op.drop_index("idx_file_records_chat", table_name="file_records")
    op.drop_column("file_records", "chat_id")
