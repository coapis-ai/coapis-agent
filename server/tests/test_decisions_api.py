# -*- coding: utf-8 -*-
"""判断中枢 API 测试（v14 §5.2 / U 批）。

覆盖三件事：台账按人隔离、统计口径正确、配置只收认识的键并落盘。
"""

from __future__ import annotations

import json
import uuid
import time
import types
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

    # 配置写盘落到临时目录，测试不碰真实部署目录
    cfg_dir = tmp_path / "agents"
    cfg_dir.mkdir()
    payload = {"id": "default", "name": "default", "running_config": {},
               "decision_hub": {}}
    (cfg_dir / "default.json").write_text(json.dumps(payload), encoding="utf-8")

    # v19 P2-3：PUT /decisions/config 挂了 judge:audit 闸门。权限模块没初始化
    # 时闸门是 fail-closed 的 503（不是放行），所以测试必须把权限系统摆出来。
    # 这里只提供"矩阵数据"（普通用户零授权），判定逻辑走真尺子
    # （admin 直通 / 矩阵查表），闸门语义本身由真代码执行。
    from coapis.app.permissions.manager import PermissionManager

    monkeypatch.setattr(
        PermissionManager, "_instance",
        types.SimpleNamespace(
            has_permission=lambda username, permission, role="user": role == "admin",
        ),
    )

    def _load(agent_id: str):
        from coapis.config.config import AgentProfileConfig

        return AgentProfileConfig(**json.loads((cfg_dir / f"{agent_id}.json").read_text()))

    def _save(agent_id: str, cfg) -> None:
        (cfg_dir / f"{agent_id}.json").write_text(
            json.dumps(cfg.model_dump(mode="json"), ensure_ascii=False),
            encoding="utf-8",
        )

    monkeypatch.setattr("coapis.config.load_agent_config", _load)
    monkeypatch.setattr("coapis.config.save_agent_config", _save)
    # 中枢配置落盘位置改到临时目录：写入侧与读取侧都走这一条路径
    hub_file = tmp_path / "hub" / "decision_hub.json"
    hub_file.parent.mkdir()
    monkeypatch.setattr("coapis.decision.config.hub_config_path", lambda: hub_file)

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
    c, holder, _cfg_dir = client
    # v19 P2-3：六岗配置是治理项，只有管理员能改（见 test_config_put_denied）
    holder["user"], holder["role"] = "root", "admin"
    res = c.put("/api/decisions/config?agent_id=a1", json={
        "timeout_ms": 2500,
        "advisor_enabled": False,
        # 判官模型是已知键（判官必须能指定纯文本模型，写死必翻车）
        "judge_model": "glm-4.7",
        # 未知键照旧拒收
        "judge_mode": "x",
    }).json()
    assert res["decision_hub"] == {
        "timeout_ms": 2500,
        "advisor_enabled": False,
        "judge_model": "glm-4.7",
    }
    assert res["ignored"] == ["judge_mode"], "未知键拒收，不写死字段"
    # 读回走读取侧那一条路径：落盘文件就是 get_hub_config() 读的那份，
    # 只有一份真相，测试不碰真实部署目录。
    from coapis.decision.config import get_hub_config, hub_config_path, reset_hub_config

    saved = json.loads(hub_config_path().read_text())
    # 落盘只认全名（别名在写入侧归一），读取侧与落盘段同名
    assert saved["llm_timeout_ms"] == 2500
    # advisor_enabled=False 归一成"每 N 轮复核 = 0"，即关闭
    assert saved["advisor_every_iters"] == 0
    assert saved.get("judge_model") == "glm-4.7", "判官模型必须落盘（F1：判官槽位）"
    assert "judge_mode" not in saved, "未知键不落盘"
    assert "timeout_ms" not in saved, "别名不落盘，只有一份键名"
    assert "advisor_enabled" not in saved, "别名不落盘，只有一份键名"

    reset_hub_config()
    assert get_hub_config().timeout_ms == 2500, "重启后仍生效（读盘，不靠进程内状态）"

    assert c.put("/api/decisions/config?agent_id=a1", json={"nope": 1}).status_code == 400



def test_config_put_reaches_hub_config(client):
    c, holder, _ = client
    holder["user"], holder["role"] = "root", "admin"  # v19 P2-3：管理员才能写
    from coapis.decision.config import get_hub_config

    # 基线值不假设（各环境环境变量不同），只验"改了立刻变"
    before = get_hub_config().timeout_ms
    c.put("/api/decisions/config?agent_id=a1", json={"timeout_ms": 2100})
    # 写入侧落盘 + 主动失效缓存：页面改完，网关下一轮就是新值
    assert get_hub_config().timeout_ms == 2100
    c.put("/api/decisions/config?agent_id=a1", json={"timeout_ms": 2600})
    assert get_hub_config().timeout_ms == 2600
    assert (before == 2100) is False


def test_config_put_denied_for_non_admin(client):
    """v19 P2-3：改判官配置改的是**整台部署**的判断行为，必须管理员 + 留痕。

    原先任何登录用户 PUT /decisions/config 都能把判官总开关关掉、把技能岗
    预算改成 1，落盘全局生效且零审计。闸门 = judge:audit（矩阵缺席即拒）。
    """
    c, holder, _ = client
    res = c.put("/api/decisions/config?agent_id=default", json={"enabled": False})
    assert res.status_code == 403, "普通用户不得改中枢配置"
    assert "judge:audit" in res.json()["detail"]
    # 拒绝必须真的没写下去（读的是本测试那份落盘文件，不碰全局缓存）
    from coapis.decision.config import hub_config_path

    path = hub_config_path()
    saved = json.loads(path.read_text()) if path.exists() else {}
    assert saved.get("enabled") is not False, "403 不许留下任何写入"
    holder["user"], holder["role"] = "root", "admin"
    assert c.put(
        "/api/decisions/config?agent_id=default", json={"enabled": True},
    ).status_code == 200



def _walk_router_paths(node):
    """摊平路由树。新版 FastAPI 把 include_router 存成 _IncludedRouter，
    生效路径要逐层展开——只看顶层会把 /api/decisions 看成不存在。"""
    out = set()
    stack = [node]
    seen = set()
    while stack:
        cur = stack.pop()
        if id(cur) in seen:
            continue
        seen.add(id(cur))
        for r in getattr(cur, "routes", []):
            getter = getattr(r, "effective_route_contexts", None)
            if callable(getter):
                for ctx in getter():
                    out.add(getattr(ctx, "path", ""))
                inner = getattr(r, "original_router", None)
                if inner is not None:
                    stack.append(inner)
                continue
            out.add(getattr(r, "path", ""))
    return out


def test_router_registered_under_api_prefix():
    """/decisions 必须真的挂进生产路由树——没挂载等于功能不存在。"""
    from coapis.app.routers import router as api_router

    hits = {p for p in _walk_router_paths(api_router) if "/decisions" in p}
    assert {
        "/decisions",
        "/decisions/stats",
        "/decisions/config",
        "/decisions/{event_id}/rating",
    } <= hits, sorted(hits)
