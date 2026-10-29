# -*- coding: utf-8 -*-
"""decision_events: 智能判断中枢台账表（一期 A1）。

系统内部每一次判断（技能触发兜底判 / 计划闸门 / 意图分类 / 复杂度判级）
都要能回答「花了多少钱、准不准、在哪个岗位失效」。此前这些判断跑完就蒸发
（日志级别 debug，生产 INFO 看不见），台账无从谈起。

本表由 ``coapis.decision.bus`` 写入，读侧供「判断中枢」看板聚合六岗健康度。

Revision ID: 0018
Revises: 0017
Create Date: 2026-10-28
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0018"
down_revision: Union[str, None] = "0017"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _existing_tables() -> set:
    insp = sa.inspect(op.get_bind())
    return set(insp.get_table_names())


def upgrade() -> None:
    if "decision_events" in _existing_tables():
        return
    op.create_table(
        "decision_events",
        sa.Column("event_id", sa.Text(), nullable=False),
        sa.Column("source", sa.Text(), nullable=False, server_default=""),
        sa.Column("complexity", sa.Text(), nullable=False, server_default=""),
        sa.Column("action", sa.Text(), nullable=False, server_default=""),
        sa.Column("reason", sa.Text(), nullable=False, server_default=""),
        sa.Column("hit_layer", sa.Text(), nullable=False, server_default=""),
        sa.Column("model", sa.Text(), nullable=False, server_default=""),
        sa.Column("latency_ms", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("cost", sa.Float(), nullable=False, server_default="0"),
        sa.Column("tokens", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("user_id", sa.Text(), nullable=False, server_default=""),
        sa.Column("agent_id", sa.Text(), nullable=False, server_default=""),
        sa.Column("chat_id", sa.Text(), nullable=False, server_default=""),
        sa.Column("outcome", sa.Text(), nullable=False, server_default="pending"),
        sa.Column("created_at", sa.Float(), nullable=False, server_default="0"),
        sa.PrimaryKeyConstraint("event_id"),
    )
    op.create_index(
        "ix_decision_events_source_created",
        "decision_events",
        ["source", "created_at"],
    )
    op.create_index(
        "ix_decision_events_user_created",
        "decision_events",
        ["user_id", "created_at"],
    )
    op.create_index("ix_decision_events_chat", "decision_events", ["chat_id"])


def downgrade() -> None:
    if "decision_events" not in _existing_tables():
        return
    op.drop_index("ix_decision_events_chat", table_name="decision_events")
    op.drop_index("ix_decision_events_user_created", table_name="decision_events")
    op.drop_index("ix_decision_events_source_created", table_name="decision_events")
    op.drop_table("decision_events")
