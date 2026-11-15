# -*- coding: utf-8 -*-
"""decision_events 补 purpose/session_id/payload 三列（B3 治理接线）。

实证的断点（2026-11-15 在 dev 真库 /apps/ai/coapis-dev/system/coapis.db 实测）：

* ``decision_events`` 真实列里**没有** ``purpose`` / ``session_id`` /
  ``payload``；
* 治理事件视图 ``governance/events.py`` 的 SQL 查 ``session_id`` /
  ``evidence`` / ``rationale`` / ``updated_at`` 四个不存在的列 —— 查询
  抛异常被 ``_query_rows`` 吞掉，视图恒空。台账 364 行在库里，看板 0 行。
* 写侧同理：``ledger_contract.write_ledger`` 收了 purpose/session_id/payload
  参数，``DecisionResult.to_row()`` 不输出、``bus._LEDGER_COLUMNS`` 白名单
  不含 → **参数在落库前就被丢弃**，弃权原因码进不了台账。

本迁移把读侧要的列建出来；写侧接线在同批次（types.to_row /
bus._LEDGER_COLUMNS / ledger_contract）。存量行不回填（未知不等于零）。

Revision ID: 0028_ledger_governance_columns
Revises: 0027_approval_intents
Create Date: 2026-11-15
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0028_ledger_governance_columns"
down_revision: Union[str, None] = "0027_approval_intents"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


#: 本次新增列。全部 NOT NULL + 默认空 —— 与本表既有红线一致：
#: 老行读出为 ''（未知），不引入可空列，读侧省掉 None 处理。
#: payload 存 JSON **文本**（裸 SQL 写入方 dumps、读侧 loads），
#: 不依赖 SQLAlchemy 的 JSON 适配器 —— 台账写入走的是裸 INSERT。
_NEW_COLUMNS = {
    "purpose": sa.Text(),
    "session_id": sa.Text(),
    "payload": sa.Text(),
}


def _existing_columns() -> set:
    return {
        r["name"]
        for r in sa.inspect(op.get_bind()).get_columns("decision_events")
    }


def upgrade() -> None:
    have = _existing_columns()
    for name, typ in _NEW_COLUMNS.items():
        if name in have:
            continue
        op.add_column(
            "decision_events",
            sa.Column(name, typ, nullable=False, server_default=""),
        )
    if "ix_decision_events_session" not in {
        r["name"] for r in sa.inspect(op.get_bind()).get_indexes("decision_events")
    }:
        op.create_index(
            "ix_decision_events_session",
            "decision_events",
            ["session_id", "created_at"],
        )


def downgrade() -> None:
    ins = sa.inspect(op.get_bind())
    index_names = {r["name"] for r in ins.get_indexes("decision_events")}
    if "ix_decision_events_session" in index_names:
        op.drop_index("ix_decision_events_session", table_name="decision_events")
    have = _existing_columns()
    for name in _NEW_COLUMNS:
        if name in have:
            op.drop_column("decision_events", name)
