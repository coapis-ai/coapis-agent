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


# ── P3：抽屉「引用 / 产出」筛选（role 参数）──────────────────
def _add_chat_file(ledger, path, role):
    """给 chat-1 挂一个文件，角色由调用方指定。"""
    key = ledger.register(
        owner_scope="user",
        owner_id="alice",
        kind="file",
        path=path,
        title=path.rsplit("/", 1)[-1],
    )
    ledger.attach_ref(
        resource_key=key,
        referrer_kind="chat",
        referrer_id="chat-1",
        role=role,
    )
    return key


def _by_role(client, role_group):
    body = client.get(
        "/api/chats/chat-1/resources", params={"as": "alice", "role": role_group}
    ).json()
    return body, {i["path"] for i in body["items"]}


def test_role_filter_splits_reference_from_produced(env):
    """「引用 / 产出」各看各的：总数必须等于页内条数（折叠计数与展开同源）。"""
    client, ledger = env
    _add_chat_file(ledger, "files/in.md", "reference")
    _add_chat_file(ledger, "files/out.md", "producer")

    body, paths = _by_role(client, "reference")
    assert body["total"] == len(body["items"])
    assert paths == {"files/in.md", "https://www.dghx.gov.cn/gh/index.html"}
    assert all(i["role"] == "reference" for i in body["items"])

    body, paths = _by_role(client, "produced")
    assert body["total"] == len(body["items"])
    assert paths == {"files/plan.md", "files/out.md"}
    assert all(i["role"] in ("producer", "export") for i in body["items"])


def test_export_role_counts_as_produced(env):
    """导出件算「产出」——与前端「本轮产出」条的分组口径同一把尺子。"""
    client, ledger = env
    _add_chat_file(ledger, "files/report.pdf", "export")
    assert "files/report.pdf" in _by_role(client, "produced")[1]
    assert "files/report.pdf" not in _by_role(client, "reference")[1]


def test_unknown_role_returns_everything(env):
    """非法 role 不得把清单变空（参数永远不是清空清单的理由）。"""
    client, _ = env
    all_total = _get(client, "chat-1").json()["total"]
    body, _ = _by_role(client, "nonsense")
    assert body["total"] == all_total


def test_merged_row_shows_under_strongest_role_only(env):
    """同一文件的两种口径 + 两个角色合并成一行后，按强角色归入一侧。

    锁死既定口径：合并不复制行，`ref_count` 求和，「引用/产出」两侧不会把
    同一文件各显示一条。
    """
    client, ledger = env
    from coapis.foundation.db.models.resources import Resource, ResourceRef

    now = time.time()
    with get_session() as s:
        for key, path, source in (
            ("mkey-hook", "dual.md", "hook"),
            ("mkey-turn", "files/dual.md", "turn:write_file"),
        ):
            s.add(
                Resource(
                    resource_key=key,
                    owner_scope="user",
                    owner_id="alice",
                    kind="file",
                    path=path,
                    title="dual.md",
                    status="draft",
                    source=source,
                    first_seen_at=now,
                    last_seen_at=now,
                    updated_at=now,
                )
            )
        for key, role in (("mkey-hook", "reference"), ("mkey-turn", "producer")):
            s.add(
                ResourceRef(
                    resource_key=key,
                    referrer_kind="chat",
                    referrer_id="chat-dual",
                    role=role,
                    created_at=now,
                )
            )

    def _one(role_group):
        return client.get(
            "/api/chats/chat-dual/resources", params={"as": "alice", "role": role_group}
        ).json()

    produced = _one("produced")
    assert produced["total"] == 1
    assert produced["items"][0]["role"] == "producer"
    assert produced["items"][0]["ref_count"] == 2
    assert _one("reference")["total"] == 0
    assert _one("")["total"] == 1


# ── P4：聊天侧不显示已删除（软删）资源 ──────────────────────
def test_soft_deleted_resource_hidden_in_chat_list(env):
    """软删行不进聊天资源清单，也不进总数；台账管理面仍能看到。

    台账的删除是软删（只打 deleted_at，磁盘文件原地不动）。此前聊天侧
    include_deleted=True，「已删除」的行照进左栏下拉与答案条：灰的、点不开、
    下载 404，用户读成「东西坏了」。
    """
    client, ledger = env
    from coapis.foundation.db.models.resources import Resource

    key = _add_chat_file(ledger, "files/gone.md", "producer")
    with get_session() as s:
        s.query(Resource).filter(Resource.resource_key == key).update(
            {"status": "deleted", "deleted_at": time.time()}
        )

    body = _get(client, "chat-1").json()
    assert not [i for i in body["items"] if i["path"].endswith("gone.md")]
    assert body["total"] == len(body["items"])

    rows = ledger.list_resources_for_chat(
        owner_scope="user",
        owner_id="alice",
        chat_id="chat-1",
        include_deleted=True,
    )
    gone = [r for r in rows if str(r["path"]).endswith("gone.md")]
    assert len(gone) == 1
    assert gone[0]["deleted_at"]


def test_role_whitelist_matches_filter_ruler():
    """角色三层尺子（写入白名单 / 读侧筛选 / 优先级表）必须是同一套。

    写入侧 ``attach_ref`` 按 ``VALID_ROLES`` 丢行，读侧 ``role`` 筛选按
    ``_CHAT_ROLE_PRODUCED`` 归类——白名单少了哪个角色，那条筛选就永远筛不到
    东西（前端「产出」侧声明了 export，台账里却不可能有 export 行）。
    """
    from coapis.foundation.db.models.resources import VALID_ROLES
    from coapis.foundation.resource_ledger import ResourceLedger

    assert ResourceLedger._CHAT_ROLE_PRODUCED <= VALID_ROLES
    assert set(ResourceLedger._CHAT_ROLE_PRIORITY) <= VALID_ROLES
