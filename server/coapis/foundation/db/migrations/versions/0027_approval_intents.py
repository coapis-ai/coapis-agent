# -*- coding: utf-8 -*-
"""approval_intents: 审批意图台账表（B2 · 方案 v1 §4 验收 5）.

审批队列是内存态，裁决取走即消失 —— 实测 dev：审批卡的裁决在盘上
0 行，"用户选了哪种、为什么、超时几次"无从统计，看板只有"当前几张卡"。
本表把一次审批请求的完整生命周期落成一行（入队→裁决/超时/清理），
台账侧可按会话、按裁决、按用户聚合。

存量不回填：历史裁决已随进程消失，无从得知，台账从建表后开始计数
（未知不等于零，也不等于批准）。

Revision ID: 0027_approval_intents
Revises: 0026_usage_turn_columns
Create Date: 2026-11-15
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0027_approval_intents"
down_revision: Union[str, None] = "0026_usage_turn_columns"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _existing_tables() -> set:
    return set(sa.inspect(op.get_bind()).get_table_names())


def upgrade() -> None:
    if "approval_intents" in _existing_tables():
        return
    op.create_table(
        "approval_intents",
        sa.Column("request_id", sa.Text(), nullable=False),
        sa.Column("session_id", sa.Text(), nullable=False, server_default=""),
        sa.Column("root_session_id", sa.Text(), nullable=False, server_default=""),
        sa.Column("user_id", sa.Text(), nullable=False, server_default=""),
        sa.Column("agent_id", sa.Text(), nullable=False, server_default=""),
        sa.Column("channel", sa.Text(), nullable=False, server_default=""),
        sa.Column("tool_name", sa.Text(), nullable=False, server_default=""),
        # severity 与 ToolGuardSeverity 同尺子（档位文本，不造数值刻度）
        sa.Column("severity", sa.Text(), nullable=False, server_default=""),
        sa.Column("findings_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("timeout_seconds", sa.Float(), nullable=False, server_default="60"),
        sa.Column("decision", sa.Text(), nullable=False, server_default=""),
        sa.Column("decided_by", sa.Text(), nullable=False, server_default=""),
        sa.Column("decide_source", sa.Text(), nullable=False, server_default=""),
        # 系统采纳结果（applied / refused:<原因> / auto / 空=未收场）。
        # 与 decision（用户意图）分列：用户点了批准而系统拒绝时两列各说各的。
        sa.Column("outcome", sa.Text(), nullable=False, server_default=""),
        sa.Column("why", sa.Text(), nullable=True),
        sa.Column("created_at", sa.Float(), nullable=False, server_default="0"),
        sa.Column("resolved_at", sa.Float(), nullable=True),
        sa.PrimaryKeyConstraint("request_id", name="pk_approval_intents"),
    )
    op.create_index(
        "ix_approval_intents_session", "approval_intents",
        ["session_id", "created_at"],
    )
    op.create_index(
        "ix_approval_intents_decision", "approval_intents",
        ["decision", "created_at"],
    )
    op.create_index(
        "ix_approval_intents_user", "approval_intents",
        ["user_id", "created_at"],
    )


def downgrade() -> None:
    if "approval_intents" not in _existing_tables():
        return
    op.drop_index("ix_approval_intents_user", table_name="approval_intents")
    op.drop_index("ix_approval_intents_decision", table_name="approval_intents")
    op.drop_index("ix_approval_intents_session", table_name="approval_intents")
    op.drop_table("approval_intents")
