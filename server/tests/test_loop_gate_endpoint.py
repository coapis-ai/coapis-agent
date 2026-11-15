# -*- coding: utf-8 -*-
"""GET /api/decisions/loop-gates 端点测试（B4b：闸触发按门分桶可见）。

对应实施方案 v1 §7.3 验收 2：触发次数按门分桶写进台账，治理页可见。
关键口径（v15 定下的规矩）：**十门零值补齐**——"从没触发"与"没数据"
必须分得开。
"""
from __future__ import annotations

import json
import time
from datetime import datetime, timezone
from itertools import count

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import text
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request

from coapis.agents.loop_gates import GATE_CODES, GATE_LABELS
from coapis.foundation.db import init_engine, reset_engine
from coapis.foundation.db.base import BaseRow
from coapis.foundation.db.engine import get_session


@pytest.fixture()
def client(tmp_path, monkeypatch):
    engine = init_engine(f"sqlite:///{tmp_path}/lg_api.db")
    BaseRow.metadata.create_all(engine)

    from coapis.app.routers import decisions as decisions_mod

    seq = count(1)
    holder = {"user": "alice", "role": "admin"}

    def _add(user="alice", chat="c1", gate="dup", action="block", n=1,
             reason=None, agent="default"):
        with get_session() as s:
            for _ in range(int(n)):
                # 台账真实列只有 20 个（实测 `_LEDGER_COLUMNS` 里没有
                # purpose、也没有 payload）；闸码按闸链写入格式放进
                # reason 前缀 `[闸码] 白话`，造数必须照真实落点来。
                s.execute(
                    text(
                        "INSERT INTO decision_events "
                        "(event_id, source, action, reason, hit_layer, "
                        " user_id, agent_id, chat_id, turn, created_at) "
                        "VALUES (:id,'loop_gate',:a,:r,'rule',:u,:ag,:c,1,:ts)"
                    ),
                    {
                        "id": f"lg{next(seq)}", "a": action,
                        "r": reason or f"[{gate}] {GATE_LABELS.get(gate, gate)}",
                        "u": user, "ag": agent, "c": chat,
                        # created_at 是 Float 列（epoch 秒）——造数必须
                        # 与真实落点一致，否则窗口过滤的测试是假的。
                        "ts": time.time(),
                    },
                )
            s.commit()

    app = FastAPI()

    class _Identity(BaseHTTPMiddleware):
        async def dispatch(self, request, call_next):
            request.state.username = holder["user"]
            request.state.role = holder["role"]
            return await call_next(request)

    app.add_middleware(_Identity)
    app.include_router(decisions_mod.router, prefix="/api/decisions")
    yield TestClient(app), holder, _add
    reset_engine()


def _buckets(payload):
    return {row["gate"]: row for row in payload["gates"]}


def test_all_ten_gates_zero_filled(client):
    c, _, _ = client
    payload = c.get("/api/decisions/loop-gates").json()
    assert payload["total_hits"] == 0
    assert len(payload["gates"]) == len(GATE_CODES), "十门必须零值补齐"
    assert set(_buckets(payload)) == set(GATE_CODES)
    for row in payload["gates"]:
        assert row["hits"] == 0
        assert row["label"] == GATE_LABELS[row["gate"]]
    assert payload["active_gates"] == 0


def test_bucket_per_gate(client):
    c, _, add = client
    add(gate="dup", action="block", n=3)
    add(gate="dup", action="hint", n=2)
    add(gate="stagnant", action="finalize", n=1)
    add(gate="empty", action="block", n=4)

    payload = c.get("/api/decisions/loop-gates").json()
    b = _buckets(payload)
    assert b["dup"]["hits"] == 5
    assert b["dup"]["actions"] == {"block": 3, "hint": 2}
    assert b["stagnant"]["hits"] == 1
    assert b["empty"]["hits"] == 4
    assert b["oscillate"]["hits"] == 0
    assert payload["total_hits"] == 10
    assert payload["active_gates"] == 3
    # 排序按命中降序
    assert payload["gates"][0]["hits"] >= payload["gates"][-1]["hits"]


def test_labels_are_plain_language(client):
    c, _, add = client
    add(gate="dup", n=1)
    row = _buckets(c.get("/api/decisions/loop-gates").json())["dup"]
    assert row["label"] == "同参数重复调用同一工具"
    assert "同参数" in row["label"]


def test_scopes_to_owner_for_non_admin(client):
    c, holder, add = client
    add(user="alice", gate="dup", n=2)
    add(user="bob", gate="stagnant", n=7)
    holder["user"], holder["role"] = "bob", "user"
    payload = c.get("/api/decisions/loop-gates").json()
    assert payload["total_hits"] == 7
    b = _buckets(payload)
    assert b["stagnant"]["hits"] == 7
    assert b["dup"]["hits"] == 0

    holder["role"] = "admin"
    payload = c.get("/api/decisions/loop-gates").json()
    assert payload["total_hits"] == 9, "管理员看全量"


def test_chat_filter(client):
    c, _, add = client
    add(chat="c1", gate="dup", n=2)
    add(chat="c2", gate="dup", n=5)
    payload = c.get("/api/decisions/loop-gates?chat_id=c2").json()
    assert payload["total_hits"] == 5
    assert all(r["chat_id"] == "c2" for r in payload["recent"])


def test_recent_rows_carry_plain_reason(client):
    c, _, add = client
    add(gate="round", n=1, reason="[round] 本轮调用预算已用尽")
    payload = c.get("/api/decisions/loop-gates?recent_limit=5").json()
    assert payload["recent"]
    row = payload["recent"][0]
    assert row["gate"] == "round"
    assert "本轮调用预算已用尽" in row["reason"]
    assert row["created_at"]


def test_threshold_flag_visible(client):
    """阈值配置化后，当前生效值必须让治理页看见（不能是黑箱）。"""
    c, _, _ = client
    flags = c.get("/api/decisions/loop-gates").json()["enabled"]
    assert flags["round_budget"] == 0, "默认不拦（只计数）"
    assert flags["stop_phrase"] is False, "停止句门默认关"
    assert flags["dedup"] == 2 and flags["stagnation_similarity"] == 5


def test_threshold_flag_follows_env(client, monkeypatch):
    monkeypatch.setenv("COAPIS_LOOP_GATE_ROUND_BUDGET", "9")
    monkeypatch.setenv("COAPIS_LOOP_GATE_STOP_PHRASE", "1")
    flags = client[0].get("/api/decisions/loop-gates").json()["enabled"]
    assert flags["round_budget"] == 9
    assert flags["stop_phrase"] is True


def test_unknown_gate_code_reported_not_dropped(client):
    """台账里出现未登记闸码时，必须显式暴露而不是静默吞掉。"""
    c, _, add = client
    add(gate="ghost_gate", n=3)
    payload = c.get("/api/decisions/loop-gates").json()
    assert payload["unknown_gates"] == {"ghost_gate": 3}
    assert payload["total_hits"] == 3
    assert len(payload["gates"]) == len(GATE_CODES)


def test_window_filter(client):
    c, _, add = client
    add(gate="dup", n=2)
    assert c.get("/api/decisions/loop-gates?days=1").json()["total_hits"] == 2
    assert c.get("/api/decisions/loop-gates?days=90").json()["total_hits"] == 2


def test_out_of_window_rows_are_excluded(client):
    """窗口外的旧行必须筛掉（epoch 口径；用 datetime 比较会全量漏筛）。"""
    c, _, add = client
    with get_session() as s:
        s.execute(
            text(
                "INSERT INTO decision_events "
                "(event_id, source, action, reason, hit_layer, "
                " user_id, agent_id, chat_id, turn, created_at) "
                "VALUES (:id,'loop_gate','block',:r,'rule'," 
                "'alice','default','c1',1,:ts)"
            ),
            {
                "id": "lg-old", "r": "[dup] 同参数重复调用同一工具",
                "ts": time.time() - 40 * 86400.0,
            },
        )
        s.commit()
    add(gate="dup", n=2)
    assert c.get("/api/decisions/loop-gates?days=7").json()["total_hits"] == 2
    assert c.get("/api/decisions/loop-gates?days=90").json()["total_hits"] == 3
