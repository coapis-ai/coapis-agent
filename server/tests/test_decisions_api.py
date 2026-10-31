# -*- coding: utf-8 -*-
"""判断中枢 API 测试（v14 §5.2 / U 批）。

覆盖三件事：台账按人隔离、统计口径正确、配置只收认识的键并落盘。
"""

from __future__ import annotations

import json
import uuid
import time
from datetime import datetime, timedelta

import pytest
from fastapi import FastAPI, Request
from fastapi.testclient import TestClient
from sqlalchemy import select

from coapis.app.routers import decisions as decisions_mod
from coapis.foundation.db import init_engine, reset_engine
from coapis.foundation.db.base import BaseRow
from coapis.foundation.db.engine import get_session
from coapis.foundation.db.models import DecisionEvent


def _add(user_id: str, chat_id: str, source: str, **kw) -> str:
    """按台账真实列建一行（列名与 bus._LEDGER_COLUMNS 逐字对齐）。

    测试当初是照着设计稿里的 ts/tokens_in/confidence 写的，那些列在库里
    不存在——测试全绿也证明不了线上台账能读出来。
    """
    ev = DecisionEvent(
        event_id=str(uuid.uuid4()),
        user_id=user_id,
        agent_id="a1",
        chat_id=chat_id,
        turn=kw.pop("turn", 1),
        source=source,
        complexity=kw.pop("complexity", "medium"),
        action=kw.pop("action", "level"),
        judgment=kw.pop("judgment", "medium"),
        reason=kw.pop("reason", None),
        hit_layer=kw.pop("hit_layer", "llm"),
        model=kw.pop("model", "glm-4.7"),
        latency_ms=kw.pop("latency_ms", 1200),
        cost=kw.pop("cost", 0.0012),
        tokens=kw.pop("tokens", 480),
        outcome=kw.pop("outcome", "pending"),
        rating=kw.pop("rating", None),
        input_hash=kw.pop("input_hash", None),
        created_at=kw.pop("created_at", time.time()),
    )
    with get_session() as s:
        s.add(ev)
        s.commit()
        return str(ev.event_id)


@pytest.fixture()
def client(tmp_path, monkeypatch):
    """两个身份（alice/user、root/admin）按需切换的最小 app。"""
    db = tmp_path / "d.db"
    engine = init_engine("sqlite:///%s" % db)
    BaseRow.metadata.create_all(engine)

    holder = {"user": "alice", "role": "user"}

    app = FastAPI()

    @app.middleware("http")
    async def _identity(request: Request, call_next):
        request.state.username = holder["user"]
        request.state.role = holder["role"]
        return await call_next(request)

    api = FastAPI().router  # 只要 include 逻辑，不启第二个 app
    api.include_router(decisions_mod.router, prefix="/decisions")
    app.include_router(api, prefix="/api")

    # 配置写盘落到临时目录，测试不碰真实 agent.json
    cfg_dir = tmp_path / "agents"
    cfg_dir.mkdir()
    payload = {"id": "default", "name": "default", "running_config": {},
               "decision_hub": {}}
    (cfg_dir / "default.json").write_text(json.dumps(payload), encoding="utf-8")

    def _load(agent_id: str):
        from coapis.config import AgentProfileConfig

        return AgentProfileConfig(**json.loads((cfg_dir / f"{agent_id}.json").read_text()))

    def _save(agent_id: str, cfg) -> None:
        (cfg_dir / f"{agent_id}.json").write_text(
            json.dumps(cfg.model_dump(mode="json"), ensure_ascii=False),
            encoding="utf-8",
        )

    monkeypatch.setattr("coapis.config.load_agent_config", _load)
    monkeypatch.setattr("coapis.config.save_agent_config", _save)

    yield TestClient(app), holder, cfg_dir
    reset_engine()


def test_list_scopes_to_owner(client):
    c, holder, _ = client
    _add("alice", "chat-a", "plan_gate")
    _add("bob", "chat-b", "plan_gate")

    rows = c.get("/api/decisions").json()
    assert rows["total"] == 1, "普通用户只能看到自己的判断"
    assert rows["items"][0]["user_id"] == "alice"

    holder["user"], holder["role"] = "root", "admin"
    rows = c.get("/api/decisions").json()
    assert rows["total"] == 2, "admin 看全量"


def test_list_filters_by_chat_and_source(client):
    c, _holder, _ = client
    _add("alice", "chat-a", "plan_gate")
    _add("alice", "chat-a", "acceptance", judgment="unmet", action="acceptance")
    _add("alice", "chat-b", "advisor")

    one = c.get("/api/decisions", params={"chat_id": "chat-a"}).json()
    assert one["total"] == 2
    acc = c.get("/api/decisions", params={"source": "acceptance"}).json()
    assert acc["total"] == 1 and acc["items"][0]["judgment"] == "unmet"
    assert c.get("/api/decisions", params={"chat_id": "nope"}).json()["total"] == 0


def test_stats_counts_real_judgments_and_degradations(client):
    c, _holder, _ = client
    _add("alice", "chat-a", "plan_gate", hit_layer="llm", outcome="hit")
    _add("alice", "chat-a", "plan_gate", hit_layer="timeout", outcome="miss",
         reason="超时 3000ms")
    _add("alice", "chat-a", "acceptance", hit_layer="no_model", action="acceptance")

    st = c.get("/api/decisions/stats", params={"days": 7}).json()
    by = {r["source"]: r for r in st["by_source"]}
    assert st["total"] == 3
    assert by["plan_gate"]["n"] == 2
    assert by["plan_gate"]["llm"] == 1
    assert by["plan_gate"]["degraded"] == 1
    assert by["plan_gate"]["timeouts"] == 1
    assert by["plan_gate"]["hit"] == 1
    assert by["acceptance"]["no_model"] == 1
    assert st["cost"] > 0


def test_rating_owner_only(client):
    c, holder, _ = client
    mine = _add("alice", "chat-a", "plan_gate")
    theirs = _add("bob", "chat-b", "plan_gate")

    ok = c.post(f"/api/decisions/{mine}/rating", params={"rating": 1, "outcome": "hit"})
    assert ok.status_code == 200
    with get_session() as s:
        ev = s.execute(
            select(DecisionEvent).where(DecisionEvent.event_id == mine)
        ).scalar_one()
    assert ev.rating == 1 and ev.outcome == "hit"

    bad = c.post(f"/api/decisions/{theirs}/rating", params={"rating": 0})
    assert bad.status_code == 404, "不能给别人家的判断刷分"
    assert c.post(f"/api/decisions/{mine}/rating", params={"rating": 9}).status_code == 422


def test_config_get_shape(client):
    c, _holder, _ = client
    cfg = c.get("/api/decisions/config").json()
    assert "config" in cfg and "judge" in cfg
    assert cfg["config"]["enabled"] is True
    assert set(cfg["sources"]) >= {"plan_gate", "advisor", "acceptance"}


def test_config_put_persists_known_keys_only(client):
    c, _holder, cfg_dir = client
    res = c.put("/api/decisions/config", json={
        "timeout_ms": 2500,
        "advisor_enabled": False,
        "judge_model": "glm-4.7",
    }).json()
    assert res["decision_hub"] == {"timeout_ms": 2500, "advisor_enabled": False}
    assert res["ignored"] == ["judge_model"], "未知键必须报告，不留死字段"
    saved = json.loads((cfg_dir / "a1.json").read_text())["decision_hub"]
    assert saved == {"timeout_ms": 2500, "advisor_enabled": False}

    assert c.put("/api/decisions/config", json={"nope": 1}).status_code == 400


def test_config_put_reaches_hub_config(client):
    """PUT 之后判官配置要**立刻**被网关读到——配置改了不生效等于没改。"""
    c, _holder, _ = client
    from coapis.decision.config import get_hub_config

    assert get_hub_config().timeout_ms != 2500
    c.put("/api/decisions/config", json={"timeout_ms": 2500})
    assert get_hub_config().timeout_ms == 2500
    c.put("/api/decisions/config", json={"timeout_ms": 3000})
    assert get_hub_config().timeout_ms == 3000


def test_router_registered_under_api_prefix():
    from coapis.app.routers import router as api_router

    paths = [getattr(r, "path", "") for r in api_router.routes]
    assert any(p.startswith("/decisions") for p in paths), paths
