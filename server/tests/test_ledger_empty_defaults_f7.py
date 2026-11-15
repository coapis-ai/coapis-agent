"""v20 F7：台账文本列的空串默认值必须是真空串。

回归来源（实测 2026-11-15 dev v1.2.32）：ORM 写 ``server_default=text("''")``
时，SQLite 渲染出的 DDL 是 ``DEFAULT ''''''`` —— 默认值变成"两个单引号字符"。
凡不显式传这些列的写入，落库都是 ``''`` 而非空串：dev 实测 dirty_band 364/369
行、zero_reason 146 行被污染，所有"非空即有值"的统计被假值骗过。
"""
from __future__ import annotations

import pathlib

import pytest
import sqlalchemy as sa
from sqlalchemy import create_engine, text

from coapis.foundation.db.models.decision import DecisionEvent

_MODEL_FILE = (
    pathlib.Path(__file__).resolve().parents[1]
    / "coapis" / "foundation" / "db" / "models" / "decision.py"
)

_TEXT_COLS = (
    "source", "complexity", "action", "reason", "hit_layer", "model",
    "user_id", "chat_id", "input_hash", "judgment",
    "origin", "zero_reason", "dirty_band",
)


def test_no_quoted_empty_server_default():
    """模式级护栏：源码里不许再出现 server_default=text("''")。"""
    src = _MODEL_FILE.read_text(encoding="utf-8")
    q = chr(39)
    bad = 'server_default=text("' + q * 2 + '")'
    assert bad not in src, (
        "server_default=text(\"\x27\x27\") 在 SQLite 下会渲染成 DEFAULT \x27\x27\x27\x27\x27\x27，"
        "落库值是两字符字面量而非空串"
    )


@pytest.fixture()
def sqlite_table():
    engine = create_engine("sqlite://")
    DecisionEvent.__table__.create(engine)
    yield engine
    engine.dispose()


def test_ddl_default_is_plain_empty_string(sqlite_table):
    """DDL 里不许出现 '''''' 这种被二次转义的默认值。"""
    with sqlite_table.connect() as conn:
        ddl = conn.execute(
            text("SELECT sql FROM sqlite_master WHERE name='decision_events'")
        ).scalar()
    assert "''''''" not in ddl


def test_insert_without_values_yields_true_empty(sqlite_table):
    """不传这些列时，落库必须是空串（长度 0），不是两字符字面量。"""
    with sqlite_table.connect() as conn:
        conn.execute(
            text(
                "INSERT INTO decision_events (event_id, source, created_at) "
                "VALUES (:id, :src, :ts)"
            ),
            {"id": "e1", "src": "tool_gate", "ts": 1.0},
        )
        row = conn.execute(
            text(
                "SELECT origin, dirty_band, zero_reason, input_hash, judgment, "
                "complexity, action, hit_layer, model, user_id, chat_id "
                "FROM decision_events WHERE event_id = 'e1'"
            )
        ).one()
    values = row[:11]
    bad = [v for v in values if v not in ("", None)]
    assert not bad, f"这些列必须落成真空串，实际: {bad!r}"
    assert row[0] == "" and len(row[0]) == 0
