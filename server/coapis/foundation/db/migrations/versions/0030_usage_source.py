# -*- coding: utf-8 -*-
"""token_usage: 调用来源列（source）.

台账此前只记「谁用了多少」，不记「哪条链路用的」。实测 930 行里只有聊天
主链的三个模型名，决策模型、进化引擎、标题生成、语音转写的调用**一条都不
在表里**——不是漏记几个字段，而是整条链路绕过了记账包装器。

补 source 列后，同一张表能按来源对账：
    chat          聊天主轮（agentscope 包装器）
    decision      决策模型（判官）
    evolution     进化引擎（dream / digest / 经验抽取 / 跨智能体）
    title         会话标题生成
    transcription 语音转写
    compression   上下文压缩摘要
    management    供应商连通性探测（管理动作，非用户用量）

存量行**不回填**：历史行无法反推来源，NULL 就诚实写着 NULL——
读面对 source 的过滤只匹配相等值，旧行只出现在总量面，不出现在
分来源面（未知不等于零）。

Revision ID: 0030_usage_source
Revises: 0029_clean_literal_empty
Create Date: 2026-11-25
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0030_usage_source"
down_revision: Union[str, None] = "0029_clean_literal_empty"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _existing_columns(table: str) -> set:
    insp = sa.inspect(op.get_bind())
    return {c["name"] for c in insp.get_columns(table)}


def _existing_indexes(table: str) -> set:
    insp = sa.inspect(op.get_bind())
    return {i["name"] for i in insp.get_indexes(table)}


def upgrade() -> None:
    cols = _existing_columns("token_usage")
    if "source" not in cols:
        op.add_column(
            "token_usage",
            sa.Column("source", sa.String(32), nullable=True),
        )
    if "idx_token_usage_source" not in _existing_indexes("token_usage"):
        op.create_index(
            "idx_token_usage_source",
            "token_usage",
            ["source", "created_at"],
        )


def downgrade() -> None:
    if "idx_token_usage_source" in _existing_indexes("token_usage"):
        op.drop_index("idx_token_usage_source", table_name="token_usage")
    if "source" in _existing_columns("token_usage"):
        op.drop_column("token_usage", "source")
