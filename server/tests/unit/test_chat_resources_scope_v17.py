"""v17 · F7/F8 端点层用例：聊天资源清单的「会话作用域」与台账时刻对账。

对应小蜜蜂 2026-11-05 两条硬要求：
 · 「在会话窗口的右侧增加一列 200px 的宽度，上半部分表示当前会话的内容，
   下面部分表示当前聊天」→ 同一端点必须支持 scope=chat|session，且两块
   共用同一份合并/排序口径（不许两条路两把尺子）；
 · 「聊天中生成的 xlsx，对话里说生成了，会话资源中没展示 / 更新时间不对」
   → 台账时刻能被磁盘真实 mtime 刷新（update_activity）。
"""
from __future__ import annotations

import time
from types import SimpleNamespace

import pytest
from fastapi import FastAPI, Request
from fastapi.testclient import TestClient

from coapis.app.routers import chats
from coapis.foundation.db import get_session, init_engine, reset_engine
from coapis.foundation.db.base import Base
from coapis.foundation.resource_ledger import ResourceLedger

AGENT = "default"


class _CM:
    """ChatManager 桩：get_chat 必给；list_chats 可选（模拟老形状）。"""

    def __init__(self, chats_map: dict, peers: dict | None = None):
        self._chats = chats_map
        self._peers = peers  # chat_id -> [同会话的 chat_id]

    async def get_chat(self, chat_id: str):
        return self._chats.get(chat_id)

    async def list_chats(self, user_id=None):
        if self._peers is None:
            raise AttributeError("list_chats")
        out = []
        for cid, group in (self._peers or {}).items():
            if chat_belongs(group, user_id):
                spec = self._chats.get(cid)
                if spec is not None:
                    out.append(spec)
        return out


def chat_belongs(group, user_id):
    return True


def _spec(chat_id: str, user_id: str, session_id: str = ""):
    return SimpleNamespace(id=chat_id, user_id=user_id, session_id=session_id)


def _auth(username: str) -> dict:
    return {"Authorization": f"Bearer {username}"}


@pytest.fixture()
def env(tmp_path, monkeypatch):
    """临时工作区 + 临时台账库 + 只挂 chats 路由的 app（与 B2 用例同一口径）。"""
    init_engine(f"sqlite:///{tmp_path / 'ledger.db'}")
    Base.metadata.create_all(_engine())

    ws = tmp_path / "workspaces"
    (ws / "alice" / "files").mkdir(parents=True)
    (ws / "alice" / "files" / "plan.md").write_text("A", encoding="utf-8")
    (ws / "alice" / "files" / "b.xlsx").write_bytes(b"xlsx")

    import coapis.constant as const

    monkeypatch.setattr(const, "WORKSPACES_DIR", ws)
    led = ResourceLedger(workspaces_dir=str(ws))
    monkeypatch.setattr(
        "coapis.foundation.resource_ledger.get_resource_ledger",
        lambda: led,
    )

    cm = _CM({"chats-1": _spec("chats-1", "alice")})

    async def _mgr(request, agent_id=None):
        return cm

    monkeypatch.setattr(chats, "_get_chat_manager", _mgr)

    # 权限闸门在测试里放行（归属校验由端点自己做，见 B2 用例同一口径）
    from coapis.app.permissions import decorators as perm_dec

    monkeypatch.setattr(perm_dec, "_perform_permission_check", lambda *a, **k: None)

    app = FastAPI()
    app.include_router(chats.router, prefix="/api")

    @app.middleware("http")
    async def _auth_mw(request: Request, call_next):
        request.state.user_id = request.headers.get("Authorization", "").replace("Bearer ", "")
        request.state.username = request.state.user_id
        return await call_next(request)

    with TestClient(app) as client:
        yield client, led, cm
    reset_engine()


def _engine():
    from coapis.foundation.db import get_engine

    return get_engine()


def _attach(ledger, path, *, ref_kind, ref_id, role="producer"):
    key = ledger.register(kind="file", owner_scope="user", owner_id="alice", path=path)
    ledger.attach_ref(resource_key=key, referrer_kind=ref_kind, referrer_id=ref_id)
    return key


def test_scope_session_lists_session_refs(env, monkeypatch):
    """上半区（scope=session）出会话级引用；下半区（chat）看不到它。"""
    client, led, cm = env
    _attach(led, "files/plan.md", ref_kind="session", ref_id="sess-9")
    cm._chats["chats-1"] = _spec("chats-1", "alice", "sess-9")

    body = client.get(
        "/api/chats/chats-1/resources?agent_id=default&scope=session",
        headers=_auth("alice"),
    ).json()
    assert "files/plan.md" in {it["path"] for it in body["items"]}
    assert body["total"] == len(body["items"])

    chat_body = client.get(
        "/api/chats/chats-1/resources?agent_id=default",
        headers=_auth("alice"),
    ).json()
    assert "files/plan.md" not in {it["path"] for it in chat_body["items"]}


def test_scope_session_includes_peer_chats(env, monkeypatch):
    """会话作用域 = session 引用 + 同会话其他聊天的引用（一次合并，不分两块）。"""
    client, led, cm = env
    cm._chats["chats-2"] = _spec("chats-2", "alice", "sess-7")
    cm._chats["chats-1"] = _spec("chats-1", "alice", "sess-7")
    cm._peers = {"chats-1": True, "chats-2": True}
    _attach(led, "files/plan.md", ref_kind="chat", ref_id="chats-2")
    _attach(led, "files/b.xlsx", ref_kind="session", ref_id="sess-7")

    body = client.get(
        "/api/chats/chats-1/resources?agent_id=default&scope=session",
        headers=_auth("alice"),
    ).json()
    paths = {it["path"] for it in body["items"]}
    assert paths == {"files/plan.md", "files/b.xlsx"}
    assert body["total"] == 2


def test_scope_param_falls_back_to_chat(env, monkeypatch):
    """非法 scope 值不抛错：回落 chat（老前端不传 scope 行为不变）。"""
    client, led, cm = env
    _attach(led, "files/plan.md", ref_kind="chat", ref_id="chats-1")
    cm._chats["chats-1"] = _spec("chats-1", "alice")
    body = client.get(
        "/api/chats/chats-1/resources?agent_id=default&scope=nonsense",
        headers=_auth("alice"),
    ).json()
    assert "files/plan.md" in {it["path"] for it in body["items"]}


def test_scope_session_survives_manager_without_list_chats(env, monkeypatch):
    """老 ChatManager（list_chats 抛错）：上半区只按 session 引用出，不整块空掉。"""
    client, led, cm = env
    _attach(led, "files/plan.md", ref_kind="session", ref_id="sess-10")
    cm._chats["chats-1"] = _spec("chats-1", "alice", "sess-10")
    cm._peers = None  # list_chats 抛 AttributeError

    body = client.get(
        "/api/chats/chats-1/resources?agent_id=default&scope=session",
        headers=_auth("alice"),
    ).json()
    assert "files/plan.md" in {it["path"] for it in body["items"]}


def test_sort_ruler_and_paging_same_ruler(env, monkeypatch):
    """排序尺子=显示口径（updated_at 倒序），分页在排序之后切。"""
    client, led, cm = env
    keys = [
        _attach(led, "files/plan.md", ref_kind="chat", ref_id="chats-1"),
        _attach(led, "files/b.xlsx", ref_kind="chat", ref_id="chats-1"),
    ]
    # 明确拉开两条的更新时间（xlsx 是"刚生成的那份"，必须在最前）
    now = time.time()
    led.update_activity(keys[0], updated_at=now - 3600, size=10)
    led.update_activity(keys[1], updated_at=now, size=20)
    cm._chats["chats-1"] = _spec("chats-1", "alice")

    page1 = client.get(
        "/api/chats/chats-1/resources?agent_id=default&sort_by=updated_at&limit=1&offset=0",
        headers=_auth("alice"),
    ).json()
    page2 = client.get(
        "/api/chats/chats-1/resources?agent_id=default&sort_by=updated_at&limit=1&offset=1",
        headers=_auth("alice"),
    ).json()
    assert page1["items"][0]["path"].endswith("b.xlsx")
    assert page2["items"][0]["path"].endswith("plan.md")
    assert page1["total"] == page2["total"] == 2


def test_update_activity_never_breaks_listing(env, monkeypatch):
    """台账对账失败（未登记 key）绝不影响列表：列表照出，不 500。"""
    client, led, cm = env
    _attach(led, "files/plan.md", ref_kind="chat", ref_id="chats-1")
    cm._chats["chats-1"] = _spec("chats-1", "alice")
    assert led.update_activity("file:__no_such__.md") is False
    body = client.get(
        "/api/chats/chats-1/resources?agent_id=default",
        headers=_auth("alice"),
    ).json()
    assert len(body["items"]) == 1
