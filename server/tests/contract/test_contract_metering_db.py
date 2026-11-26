"""真实落库契约：没有会话归属的计量也必须成行。

为什么必须打真库：既有计量契约测试全部 monkeypatch 掉 save_token_usage，
于是 token_usage.user_id NOT NULL 这个约束从来没被碰过——探测/转写/判官
后台补判这些"没有 user_id"的链路，实际是整行被 IntegrityError 丢掉，
测试却全绿。本文件用真 SQLite 复现并锁死。
"""
from __future__ import annotations

import pytest

from coapis.foundation.db.base import Base
from coapis.foundation.db.engine import get_engine, init_engine, reset_engine
from coapis.token_usage.recorder import (
    SOURCE_MANAGEMENT,
    SOURCE_TRANSCRIPTION,
    record_llm_usage,
)


@pytest.fixture()
def real_db(tmp_path):
    """真 SQLite + 真表结构，用完复位引擎。"""
    db_path = tmp_path / "metering.db"
    init_engine(f"sqlite:///{db_path}")
    Base.metadata.create_all(get_engine())
    yield get_engine()
    reset_engine()


def _rows() -> list[tuple]:
    from sqlalchemy import text
    with get_engine().connect() as conn:
        return [
            (r[0], r[1], r[2], r[3])
            for r in conn.execute(text(
                "select source, user_id, input_tokens, output_tokens from token_usage"
            ))
        ]


def test_usage_without_user_id_still_lands(real_db) -> None:
    """探测/转写这类链路没有 user_id，行不能因此被丢掉。"""
    record_llm_usage(
        model="probe-model",
        source=SOURCE_MANAGEMENT,
        input_tokens=123,
        output_tokens=45,
        latency_ms=10,
    )
    rows = _rows()
    assert len(rows) == 1, (
        "无 user_id 的计量没落库：user_id NOT NULL 会把整行吞掉，"
        "台账看起来像『这条链路从不花钱』"
    )
    assert rows[0][0] == SOURCE_MANAGEMENT
    assert rows[0][1] == "", "无归属应写成空串，不是 None"
    assert rows[0][2] == 123 and rows[0][3] == 45


def test_usage_with_user_id_keeps_identity(real_db) -> None:
    """有归属时照常带上 user_id / agent_id。"""
    record_llm_usage(
        model="chat-model",
        source="chat",
        input_tokens=10,
        output_tokens=5,
        user_id="u-1",
        agent_id="a-1",
    )
    from sqlalchemy import text
    with get_engine().connect() as conn:
        row = conn.execute(text(
            "select user_id, agent_id, source from token_usage"
        )).fetchone()
    assert (row[0], row[1], row[2]) == ("u-1", "a-1", "chat")


def test_transcription_source_is_distinct(real_db) -> None:
    """转写用量要能单独查出来，不能混进 chat。"""
    record_llm_usage(
        model="whisper-1",
        source=SOURCE_TRANSCRIPTION,
        input_tokens=0,
        output_tokens=168,
    )
    assert _rows()[0][0] == SOURCE_TRANSCRIPTION
