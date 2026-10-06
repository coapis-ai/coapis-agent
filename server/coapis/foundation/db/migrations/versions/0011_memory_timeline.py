# -*- coding: utf-8 -*-
"""Add the memory timeline table (dream signal promotion target).

Revision ID: 0011
Revises: 0010
Create Date: 2026-10-06

Shape follows tech_docs/记忆系统整合设计方案.md §5.2:
one row per promoted signal (decision / preference / goal / conversation),
scoped by user (+ optional agent/session), deduplicated via dedup_key so
repeated dream runs / backfills never create duplicates.
Timestamps are Unix floats (same convention as the memories table).
"""

from alembic import op
import sqlalchemy as sa

revision = "0011"
down_revision = "0010"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Idempotency guard: 0001 generates DDL from Base.metadata, so on a
    # fresh DB the memory_timelines table (and its indexes) already exist
    # before this migration runs. Skip wholesale when the table is present
    # (same pattern as 0006_file_records).
    if "memory_timelines" in sa.inspect(op.get_bind()).get_table_names():
        return

    op.create_table(
        "memory_timelines",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("user_id", sa.Text(), nullable=False, server_default=""),
        sa.Column("agent_id", sa.Text(), nullable=True),
        sa.Column("session_id", sa.Text(), nullable=True),
        sa.Column("signal_type", sa.Text(), nullable=False, server_default="conversation"),
        sa.Column("content", sa.Text(), nullable=True),
        sa.Column("source", sa.Text(), nullable=True),
        sa.Column("dedup_key", sa.Text(), nullable=True),
        sa.Column("importance", sa.Float(), nullable=False, server_default="0.5"),
        sa.Column("created_at", sa.Float(), nullable=True),
        sa.Column("updated_at", sa.Float(), nullable=True),
        sa.Column("deleted_at", sa.Float(), nullable=True),
    # 晋升标记（设计 §5.2/§6）：NULL = 未晋升；非 NULL = 已写入 memories，
    # 是晋升防重的唯一依据 —— 重复 dream / backfill 不得二次晋升。
    sa.Column("promoted_at", sa.Float(), nullable=True),
    )
    op.create_index("ix_mtl_user_created", "memory_timelines", ["user_id", "created_at"])
    op.create_index("ix_mtl_signal_type", "memory_timelines", ["signal_type"])
    op.create_index("uq_mtl_dedup_key", "memory_timelines", ["dedup_key"], unique=True)


def downgrade() -> None:
    op.drop_index("uq_mtl_dedup_key", table_name="memory_timelines")
    op.drop_index("ix_mtl_signal_type", table_name="memory_timelines")
    op.drop_index("ix_mtl_user_created", table_name="memory_timelines")
    op.drop_table("memory_timelines")
