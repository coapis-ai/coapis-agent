# -*- coding: utf-8 -*-
"""resource_refs: add ``turn_id``（v26 · F5 「本轮」与「会话」分尺）.

采集器旧口径只写 chat 级引用，于是「本轮产出」只能按 chat 查 = 该会话全部
历史行；本轮补扫/文件钩子写的行与上一轮的文件混在一起（实测 dev 一个会话
122 行里，本轮真正产出的只有 4 个文件）。本列落"哪一轮触及了这个资源"，
本轮面按 turn_id 筛，会话面按 chat_id 筛。

存量行**不回填**：历史轮号无从得知，NULL 就诚实写着 NULL——读面对
``turn_id`` 的过滤只匹配相等值，NULL 行只出现在会话面，不出现在本轮面
（未知不等于本轮）。

Revision ID: 0025_resource_ref_turn
Revises: 0024_resource_category
Create Date: 2026-11-10
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0025_resource_ref_turn"
down_revision: Union[str, None] = "0024_resource_category"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _existing_columns(table: str) -> set:
    insp = sa.inspect(op.get_bind())
    return {c["name"] for c in insp.get_columns(table)}


def _existing_indexes(table: str) -> set:
    insp = sa.inspect(op.get_bind())
    return {i["name"] for i in insp.get_indexes(table)}


def upgrade() -> None:
    if "turn_id" not in _existing_columns("resource_refs"):
        op.add_column(
            "resource_refs",
            sa.Column("turn_id", sa.Text(), nullable=True),
        )
    if "idx_resource_refs_turn" not in _existing_indexes("resource_refs"):
        op.create_index(
            "idx_resource_refs_turn",
            "resource_refs",
            ["referrer_kind", "referrer_id", "turn_id"],
        )


def downgrade() -> None:
    if "idx_resource_refs_turn" in _existing_indexes("resource_refs"):
        op.drop_index("idx_resource_refs_turn", table_name="resource_refs")
    if "turn_id" in _existing_columns("resource_refs"):
        op.drop_column("resource_refs", "turn_id")
