# -*- coding: utf-8 -*-
"""token_usage: 逐轮明细列（QwenPaw 借鉴 · 批次 B1）.

台账口径（实施方案 §5）：**每轮一行（不是每供应商聚合一行）**——
tokens/cost 取模型响应的真值，永不写 0；缺 provider/session/chat/turn/
latency 中的任何一项，行落库时**必须带 NULL**（诚实缺项）。
没有 turn 维，逐轮 usage 无处落；没有 latency，判官的 2000ms 尺子没有
输入；没有 stream_interrupted，中断收口（B2）没有可观测面。

存量行**不回填**：历史行没有轮号/延迟可考，NULL 就诚实写着 NULL——
读面对新列的过滤只匹配相等值，NULL 行只出现在旧聚合面，不出现在
逐轮面（未知不等于零）。

Revision ID: 0026_usage_turn_columns
Revises: 0025_resource_ref_turn
Create Date: 2026-11-13
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0026_usage_turn_columns"
down_revision: Union[str, None] = "0025_resource_ref_turn"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_NEW_COLUMNS = {
    "provider_id": sa.Column("provider_id", sa.String(64), nullable=True),
    "session_id": sa.Column("session_id", sa.String(255), nullable=True),
    "chat_id": sa.Column("chat_id", sa.String(255), nullable=True),
    "turn_index": sa.Column("turn_index", sa.Integer(), nullable=True),
    "latency_ms": sa.Column("latency_ms", sa.Integer(), nullable=True),
    "stream_interrupted": sa.Column("stream_interrupted", sa.Boolean(), nullable=True),
    "cost_cents": sa.Column("cost_cents", sa.Integer(), nullable=True),
}


def _existing_columns(table: str) -> set:
    insp = sa.inspect(op.get_bind())
    return {c["name"] for c in insp.get_columns(table)}


def _existing_indexes(table: str) -> set:
    insp = sa.inspect(op.get_bind())
    return {i["name"] for i in insp.get_indexes(table)}


def upgrade() -> None:
    cols = _existing_columns("token_usage")
    for name, col in _NEW_COLUMNS.items():
        if name not in cols:
            op.add_column("token_usage", col)
    if "idx_token_usage_scope" not in _existing_indexes("token_usage"):
        op.create_index(
            "idx_token_usage_scope",
            "token_usage",
            ["username", "session_id", "chat_id", "turn_index"],
        )


def downgrade() -> None:
    if "idx_token_usage_scope" in _existing_indexes("token_usage"):
        op.drop_index("idx_token_usage_scope", table_name="token_usage")
    cols = _existing_columns("token_usage")
    for name in _NEW_COLUMNS:
        if name in cols:
            op.drop_column("token_usage", name)
