# -*- coding: utf-8 -*-
"""Add the unified long-term memory ledger (memories table).

Revision ID: 0010
Revises: 0007
Create Date: 2026-10-06

Shape follows tech_docs/记忆能力升级-社区版可执行方案_v1.md §3.2:
scope (user/agent/workspace) + owner ids + category/title/content/source
+ dedup_key UNIQUE + importance + timestamps + soft delete.
"""

from alembic import op
import sqlalchemy as sa

revision = "0010"
down_revision = "0007"
branch_labels = None
depends_on = None


def upgrade() -> None:
    conn = op.get_bind()
    # Timestamps are epoch seconds (Float) on ALL dialects — the ORM
    # model (foundation/db/models/memory.py) declares Float, so a
    # dialect-specific DateTime would drift from the application layer
    # on fresh Postgres installs.
    ts_type = sa.Float()

    # Idempotency guard: 0001 generates DDL from Base.metadata, so on a
    # fresh DB the memories table (and its indexes) already exist before
    # this migration runs. Skip wholesale when the table is present
    # (same pattern as 0006_file_records).
    if "memories" in sa.inspect(conn).get_table_names():
        return

    op.create_table(
        "memories",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("scope", sa.Text(), nullable=False, server_default="user"),
        sa.Column("user_id", sa.Text(), nullable=False, server_default=""),
        sa.Column("agent_id", sa.Text(), nullable=True),
        sa.Column("workspace_id", sa.Text(), nullable=True),
        sa.Column("category", sa.Text(), nullable=False, server_default="fact"),
        sa.Column("title", sa.Text(), nullable=True),
        sa.Column("content", sa.Text(), nullable=True),
        sa.Column("source", sa.Text(), nullable=True),
        sa.Column("dedup_key", sa.Text(), nullable=True),
        sa.Column("importance", sa.Float(), nullable=False, server_default="0.5"),
        sa.Column("created_at", ts_type, nullable=True),
        sa.Column("updated_at", ts_type, nullable=True),
        sa.Column("deleted_at", ts_type, nullable=True),
    )
    op.create_index("ix_memories_scope_user", "memories", ["scope", "user_id"])
    op.create_index("ix_memories_category", "memories", ["category"])
    op.create_index("ix_memories_created", "memories", ["created_at"])
    op.create_index(
        "uq_memories_dedup_key", "memories", ["dedup_key"], unique=True
    )


def downgrade() -> None:
    op.drop_index("uq_memories_dedup_key", table_name="memories")
    op.drop_index("ix_memories_created", table_name="memories")
    op.drop_index("ix_memories_category", table_name="memories")
    op.drop_index("ix_memories_scope_user", table_name="memories")
    op.drop_table("memories")
