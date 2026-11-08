# -*- coding: utf-8 -*-
"""memories: add session_id（知识沉淀 · 方案 v3 问题 #8 溯源）。

长期记忆此前只有 ``user_id``，无法回答"这条是哪次会话沉淀下来的"。
晋升链路（时间线 → 记忆）里 ``session_id`` 就躺在候选行上，写入侧丢掉了它。

补一列 + 一个索引，存量行保持 NULL（不回填：老会话无法追溯，批准口径同
0013 的 ``chat_id``）。

Revision ID: 0023
Revises: 0022
Create Date: 2026-11-08
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0023_memory_session_id"
down_revision: Union[str, None] = "0022_ledger_band_hygiene"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_TABLE = "memories"
_COLUMN = "session_id"
_INDEX = "ix_memories_session"


def _existing_columns() -> set:
    insp = sa.inspect(op.get_bind())
    if not insp.has_table(_TABLE):
        return set()
    return {c["name"] for c in insp.get_columns(_TABLE)}


def _existing_indexes() -> set:
    insp = sa.inspect(op.get_bind())
    if not insp.has_table(_TABLE):
        return set()
    return {i["name"] for i in insp.get_indexes(_TABLE)}


def upgrade() -> None:
    cols = _existing_columns()
    if _COLUMN not in cols:
        op.add_column(_TABLE, sa.Column(_COLUMN, sa.Text(), nullable=True))
    if _INDEX not in _existing_indexes():
        op.create_index(_INDEX, _TABLE, [_COLUMN])


def downgrade() -> None:
    if _INDEX in _existing_indexes():
        op.drop_index(_INDEX, table_name=_TABLE)
    if _COLUMN in _existing_columns():
        with op.batch_alter_table(_TABLE) as batch_op:
            batch_op.drop_column(_COLUMN)
