# -*- coding: utf-8 -*-
"""Create the file_records ledger table.

Append-only ledger of files materialized in user workspaces
(``workspaces/{username}/files/...``). Written by the file-write hooks
(upload / write_file / edit_file / append_file) and the reconcile sweep
(source='reconcile'); read paths deduplicate by file_path.

Timestamps follow the user-domain convention: Unix epoch floats (REAL).

Revision ID: 0006
Revises: 0005
Create Date: 2026-09-30
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = "0006"
down_revision: Union[str, None] = "0005"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Guard: on a fresh database, 0001 already created file_records from the
    # current ORM models — a blind create_table would raise "table already
    # exists". Legacy databases lack the table and get the full DDL.
    bind = op.get_bind()
    if "file_records" in sa.inspect(bind).get_table_names():
        return
    op.create_table(
        "file_records",
        sa.Column(
            "id", sa.Integer(), primary_key=True, autoincrement=True,
            nullable=False,
        ),
        sa.Column("user_id", sa.Text(), nullable=False),
        sa.Column("session_id", sa.Text()),
        sa.Column("agent_id", sa.Text()),
        sa.Column("file_path", sa.Text(), nullable=False),
        sa.Column("size_bytes", sa.Integer(), server_default=sa.text("0")),
        sa.Column("source", sa.Text(), nullable=False),
        sa.Column("created_at", sa.Float()),
        sa.Index("idx_file_records_user", "user_id"),
        sa.Index("idx_file_records_session", "session_id"),
        sa.Index("idx_file_records_created", "created_at"),
    )


def downgrade() -> None:
    op.drop_table("file_records")
