# -*- coding: utf-8 -*-
"""B2 读接口：``GET /api/chats/{chat_id}/resources``。

盯三件事：清单形状（kind/path/title/role/size）、归属（非管理员读不到别人的
会话资源）、以及台账坏了时接口必须返回空清单而不是 500。
"""
from __future__ import annotations

import time

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from coapis.app.routers import chats as chats_router
from coapis.foundation.db.base import Base
from coapis.foundation.db.engine import (
    get_engine,
    get_session,
    init_engine,
    reset_engine,
)
from coapis.foundation.db.models.user import User
from coapis.foundation.resource_ledger import ResourceLedger


class _Spec:
    def __init__(self, chat_id: str, user_id: str):
        self.id = chat_id
        self.user_id = user_id


class _CM:
    def __init__(self, chats: dict):
        self._chats = chats

    async def get_chat(self, chat_id: str):
        return self._chats.get(chat_id)


@pytest.fixture()
def env(tmp_path, monkeypatch):
    init_engine(f"sqlite:///{tmp_path / 'res.db'}")
    Base.metadata.create_all(get_engine())
    ws = tmp_path / "workspaces"
    (ws / "alice" / "files").mkdir(parents=True)
    (ws / "alice" / "files" / "plan.md").write_text("# 方案", encoding="utf-8")
    import coapis.constant as const

    monkeypatch.setattr(const, "WORKSPACES_DIR", ws)

    ledger = ResourceLedger(workspaces_dir=str(ws))
    monkeypatch.setattr(
        "coapis.foundation.resource_ledger.get_resource_ledger",
        lambda: ledger,
    )

    with get_session() as s:
        for name in ("alice", "bob"):
            s.add(
                User(
                    id=f"u_{name}",
                    username=name,
                    password_hash="x",
                    salt="x",
                    created_at=time.time(),
                )
            )

    key = ledger.register(
        owner_scope="user",
        owner_id="alice",
        kind="file",
        path="files/plan.md",
        title="plan.md",
    )
    ledger.attach_ref(
        resource_key=key, referrer_kind="chat", referrer_id="chat-1", role="producer"
    )
    key2 = ledger.register(
        owner_scope="user",
        owner_id="alice",
        kind="web",
        path="https://www.dghx.gov.cn/gh/index.html",
        title="深圳市空间规划",
    )
    ledger.attach_ref(
        resource_key=key2,
        referrer_kind="chat",
        referrer_id="chat-1",
        role="reference",
    )

    def _fake_current_user(request):
        return (
            getattr(request.state, "username", "alice"),
            getattr(request.state, "role", "user") == "admin",
        )

    async def _fake_cm(request, agent_id=""):
        return _CM({"chat-1": _Spec("chat-1", "alice"), "chat-9": _Spec("chat-9", "bob")})

    monkeypatch.setattr(chats_router, "_get_current_user", _fake_current_user)
    monkeypatch.setattr(chats_router, "_get_chat_manager", _fake_cm)
    # 权限闸门在测试里放行（归属校验由端点自己做）
    from coapis.app.permissions import decorators as perm_dec

    monkeypatch.setattr(perm_dec, "_perform_permission_check", lambda *a, **k: None)

    app = FastAPI()

    @app.middleware("http")
    async def _auth(request, call_next):
        request.state.username = request.query_params.get("as", "alice")
        request.state.role = request.query_params.get("role", "user")
        return await call_next(request)

    app.include_router(chats_router.router, prefix="/api")
    return TestClient(app), ledger


def _get(client, chat_id, as_user="alice", role="user"):
    return client.get(
        f"/api/chats/{chat_id}/resources", params={"as": as_user, "role": role}
    )


def test_lists_files_and_web_with_roles(env):
    client, _ = env
    r = _get(client, "chat-1")
    assert r.status_code == 200
    body = r.json()
    assert body["total"] == 2
    by_kind = {i["kind"]: i for i in body["items"]}
    assert by_kind["file"]["role"] == "producer"
    assert by_kind["file"]["path"] == "files/plan.md"
    assert by_kind["file"]["size"] == len("# 方案".encode())
    assert by_kind["file"]["exists"] is True
    assert by_kind["web"]["title"] == "深圳市空间规划"
    assert by_kind["web"]["role"] == "reference"


def test_other_chat_empty(env):
    client, _ = env
    r = _get(client, "chat-2")
    assert r.status_code == 200
    assert r.json()["items"] == []


def test_cross_user_chat_returns_404(env):
    client, _ = env
    r = _get(client, "chat-9", as_user="alice", role="user")
    assert r.status_code == 404


def test_admin_can_read_other_users_chat(env):
    client, ledger = env
    key = ledger.register(
        owner_scope="user",
        owner_id="bob",
        kind="file",
        path="files/secret.md",
        title="secret.md",
    )
    ledger.attach_ref(
        resource_key=key, referrer_kind="chat", referrer_id="chat-9", role="producer"
    )
    r = _get(client, "chat-9", as_user="admin", role="admin")
    assert r.status_code == 200
    assert r.json()["items"][0]["path"] == "files/secret.md"


def test_ledger_failure_degrades_to_empty(env, monkeypatch):
    client, ledger = env

    def _boom(*a, **k):
        raise RuntimeError("ledger down")

    monkeypatch.setattr(ledger, "list_resources_for_chat", _boom)
    monkeypatch.setattr(ledger, "count_resources_for_chat", _boom)
    r = _get(client, "chat-1")
    assert r.status_code == 200
    assert r.json() == {"items": [], "total": 0, "offset": 0, "limit": 200}


def test_pagination(env):
    client, ledger = env
    for i in range(5):
        k = ledger.register(
            owner_scope="user",
            owner_id="alice",
            kind="web",
            path=f"https://example.com/p{i}",
        )
        ledger.attach_ref(
            resource_key=k,
            referrer_kind="chat",
            referrer_id="chat-1",
            role="reference",
        )
    page1 = _get(client, "chat-1").json()
    assert page1["total"] == 7  # 2 条 fixture + 5 条新增
    limited = client.get(
        "/api/chats/chat-1/resources", params={"as": "alice", "limit": 3, "offset": 0}
    ).json()
    assert len(limited["items"]) == 3
    assert limited["total"] == 7


def test_two_path_conventions_collapse_to_one_row(env):
    """同一文件被两种口径登记时不得分裂成两行。

    文件台账钩子写 files 根相对路径（``plan.md``），会话采集器写工作区相对
    （``files/plan.md``）。两行并存时前端资源条会出现「同一文件两条、其中一条
    显示已删除」。
    """
    client, ledger = env
    ledger.register(
        owner_scope="user",
        owner_id="alice",
        kind="file",
        path="plan.md",
        source="hook",
        path_form="files_root",
    )
    ledger.register(
        owner_scope="user",
        owner_id="alice",
        kind="file",
        path="files/plan.md",
        title="plan.md",
        source="turn:write_file",
        path_form="workspace",
    )
    rows = ledger.list_resources_for_chat(
        owner_scope="user",
        owner_id="alice",
        chat_id="chat-1",
    )
    assert len([r for r in rows if r["kind"] == "file"]) == 1
    body = _get(client, "chat-1").json()
    files = [i for i in body["items"] if i["kind"] == "file"]
    assert len(files) == 1
    assert files[0]["path"] == "files/plan.md"
    assert files[0]["exists"] is True


def test_legacy_bare_ledger_path_is_returned_workspace_relative(env):
    """存量裸路径（files 根相对的历史行）必须补成 ``files/`` 前缀。

    前端 ``toMyfilesParams`` 按首段决定分类，裸路径 ``media/x.png`` 会被当成
    media 分类而 404。
    """
    client, ledger = env
    key = ledger.register(
        owner_scope="user",
        owner_id="alice",
        kind="file",
        path="media/x.png",
    )
    ledger.attach_ref(
        resource_key=key,
        referrer_kind="chat",
        referrer_id="chat-1",
        role="reference",
    )
    body = _get(client, "chat-1").json()
    item = [i for i in body["items"] if i["path"].endswith("x.png")][0]
    assert item["path"] == "files/media/x.png"


def test_legacy_split_rows_merge_into_one_with_strongest_role(env):
    """存量分裂行（同一文件两种口径 + 两个角色）必须合并成一行。

    写入口径统一之前，文件钩子写 ``x.md``（files 根相对）、采集器写
    ``files/x.md``（工作区相对），同一文件算出两个 key、留下两行；会话对两行
    分别留了 reference / producer 引用。读侧不合并，资源条就会显示「同一文件
    两条、其中一条已删除」，且折叠行的计数比展开后的条数多。

    这里绕过 ``register`` 直接写库，模拟**存量**未换算的历史行（``register``
    现在会把两种口径换算成同一行，测不到历史形态）。
    """
    client, ledger = env
    from coapis.foundation.db.engine import get_session
    from coapis.foundation.db.models.resources import Resource, ResourceRef

    now = time.time()
    with get_session() as s:
        for key, path, source in (
            ("legacy-key", "split.md", "hook"),
            ("modern-key", "files/split.md", "turn:write_file"),
        ):
            s.add(
                Resource(
                    resource_key=key,
                    owner_scope="user",
                    owner_id="alice",
                    kind="file",
                    path=path,
                    title="split.md",
                    status="draft",
                    source=source,
                    first_seen_at=now,
                    last_seen_at=now,
                    updated_at=now,
                )
            )
        for key, role in (("legacy-key", "reference"), ("modern-key", "producer")):
            s.add(
                ResourceRef(
                    resource_key=key,
                    referrer_kind="chat",
                    referrer_id="chat-split",
                    role=role,
                    created_at=now,
                )
            )

    rows = ledger.list_resources_for_chat(
        owner_scope="user", owner_id="alice", chat_id="chat-split"
    )
    assert len(rows) == 1
    assert rows[0]["role"] == "producer"
    assert rows[0]["path"] == "files/split.md"
    assert rows[0]["ref_count"] == 2
    # 计数与清单同源：折叠行写的数字必须等于展开后的条数
    assert ledger.count_resources_for_chat(
        owner_scope="user", owner_id="alice", chat_id="chat-split"
    ) == 1

    body = _get(client, "chat-split").json()
    assert body["total"] == 1
    assert len(body["items"]) == 1
    assert body["items"][0]["role"] == "producer"
    assert body["items"][0]["ref_count"] == 2
