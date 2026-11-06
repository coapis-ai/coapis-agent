# -*- coding: utf-8 -*-
"""左栏会话列表的"可打开性"过滤（379d9e9 引入，此前 0 覆盖 → 整栏空白回归）。

规则本体：索引行活得比会话快照久（快照被清、工作区搬家、渠道改名），点开它
只能拿到 0 条消息 —— 列出来就是一份兑现不了的承诺。所以三条同时成立才丢：
快照**明确**缺失（判定未知 None 要留，否则会话路径配错 = 整栏清空）、会话不在
生成中（生成中还没落快照）、创建宽限期已过（刚建的会话还没来得及写快照）。

分页语义（58ab718 引入 `/api/chats/page`）必须和它咬合：过滤要跑在**切窗之前**，
`total` 只数**能打开**的行。反过来（先切窗后丢弃 + total 数候选集）会产出
"items 空 + total=70" 这种首屏 —— 左栏整块空白，页脚还说"共 70 条"。
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from fastapi import FastAPI
from fastapi.testclient import TestClient

from coapis.app.runner.models import ChatSpec

GRACE_MS = 30_000  # 与 chats.py 的 _ENTRY_CREATE_GRACE_MS 同口径


def _spec(chat_id, user_id, updated, name="会话", channel="console", status="idle"):
    return ChatSpec(
        id=chat_id,
        name=name,
        session_id=f"sess-{chat_id}",
        user_id=user_id,
        channel=channel,
        updated_at=updated,
        created_at=updated - timedelta(days=1),
        meta={},
        status=status,
    )


class _FakeChatManager:
    def __init__(self, specs):
        self._specs = {s.id: s for s in specs}

    async def list_chats(self, user_id=None, channel=None):
        out = list(self._specs.values())
        if user_id is not None:
            out = [s for s in out if s.user_id == user_id]
        if channel:
            out = [s for s in out if s.channel == channel]
        return out

    def get_chat(self, chat_id):
        return self._specs.get(chat_id)


class _FakeWorkspace:
    def __init__(self, ids):
        self._ids = set(ids)

    def get_generating_chat_ids(self):
        return set(self._ids)


def _make_client(specs, generating=()):
    """与 test_chats_pagination 同构：按请求者过滤工作区 + 权限桩。"""
    import coapis.app.routers.chats as mod
    from coapis.app.permissions import decorators as perm_dec

    def _fake_current_user(request):
        return (
            getattr(request.state, "username", "alice"),
            getattr(request.state, "role", "user") == "admin",
        )

    async def _fake_cm(request, agent_id=""):
        return _FakeChatManager(specs)

    original_user, original_cm = mod._get_current_user, mod._get_chat_manager
    original_check = perm_dec._perform_permission_check
    mod._get_current_user = _fake_current_user
    mod._get_chat_manager = _fake_cm
    perm_dec._perform_permission_check = lambda *a, **k: None

    app = FastAPI()
    # 生成中的会话由 stream 追踪提供（app.state.multi_agent_manager）
    app.state.multi_agent_manager = type(
        "M",
        (),
        {"get_workspaces": lambda self: [_FakeWorkspace(list(generating))]},
    )()

    @app.middleware("http")
    async def _auth(request, call_next):
        request.state.username = request.query_params.get("as", "alice")
        request.state.role = request.query_params.get("role", "user")
        return await call_next(request)

    app.include_router(mod.router, prefix="/api")
    client = TestClient(app)

    def restore():
        mod._get_current_user = original_user
        mod._get_chat_manager = original_cm
        perm_dec._perform_permission_check = original_check

    return client, restore


def _page(client, limit=10, offset=0, agent_id="default"):
    return client.get(
        "/api/chats/page",
        params={"limit": limit, "offset": offset, "as": "alice", "agent_id": agent_id},
    )


def _specs_n(n, base=None):
    base = base or datetime(2026, 10, 20, 12, 0, 0, tzinfo=timezone.utc)
    # 下标越小越新（updated_at 倒序后就是列表顺序）
    return [
        _spec(f"c{i:02d}", "alice", base - timedelta(days=i), f"chat-{i}")
        for i in range(n)
    ]


def _kill_snapshots(monkeypatch, ghost_chat_ids, calls=None):
    """把指定 **会话**（chat_id）判为"快照明确缺失"，其余判为存在。

    尺子现在会问两个键（chat_id 与 session_id），所以一条会话要"没快照"，
    得两个键都没有文件 —— 只杀一个键是测不出丢弃的（另一个键会短路成可打开）。
    """
    ghosts = set()
    for cid in ghost_chat_ids:
        ghosts.add(cid)
        ghosts.add("sess-%s" % cid)

    def _fake(session_obj, session_id, user_id):
        if calls is not None:
            calls.append(session_id)
        return False if session_id in ghosts else True

    import coapis.app.routers.chats as mod

    mod._session_file_exists = _fake
    return ghosts


# ── 用例 ──────────────────────────────────────────────────────────────


def test_rows_without_snapshot_are_dropped_before_the_slice(monkeypatch):
    """左栏整块空白的回归：先切窗后丢弃 → 首屏 items 空、total 说谎。

    30 条会话，最新的 10 条快照没了。旧实现切窗取到 10 条全被丢 → 返回空
    列表且 total=30（页脚显示"共 30 条"）。现在丢弃在切窗前：窗口从剩下
    20 条里取，total=20。
    """
    import coapis.app.routers.chats as mod

    original = mod._session_file_exists
    specs = _specs_n(30)
    client, restore = _make_client(specs)
    _kill_snapshots(monkeypatch, {f"c{i:02d}" for i in range(10)})
    try:
        body = _page(client, limit=10).json()
        assert body["total"] == 20, "total 只能数能打开的行"
        assert len(body["items"]) == 10, "窗口不得因丢弃而变短"
        ids = {i["id"] for i in body["items"]}
        assert ids == {f"c{i:02d}" for i in range(10, 20)}
    finally:
        mod._session_file_exists = original
        restore()


def test_all_ghosts_leaves_an_honest_empty_page(monkeypatch):
    """全场都没有快照时，items 与 total 必须一致地为 0（页脚不能再报 30）。"""
    import coapis.app.routers.chats as mod

    original = mod._session_file_exists
    specs = _specs_n(30)
    client, restore = _make_client(specs)
    _kill_snapshots(monkeypatch, {s.id for s in specs})
    try:
        body = _page(client, limit=10).json()
        assert body["items"] == []
        assert body["total"] == 0, "total 数候选集 = 页脚谎称有 30 条会话"
    finally:
        mod._session_file_exists = original
        restore()


def test_unknown_verdict_keeps_every_row(monkeypatch):
    """判定未知（None：没有会话存储/取路径炸了）必须保留。

    会话存储没配好时，"拿不准就当没有"会把整栏清空 —— 用户看到的就是"会话
    全没了"。宁列出打不开的行，也不能清空列表。
    """
    import coapis.app.routers.chats as mod

    original = mod._session_file_exists
    specs = _specs_n(12)
    client, restore = _make_client(specs)
    mod._session_file_exists = lambda *a, **k: None
    try:
        body = _page(client, limit=10).json()
        assert body["total"] == 12
        assert len(body["items"]) == 10
    finally:
        mod._session_file_exists = original
        restore()


def test_generating_chat_without_snapshot_stays_listed(monkeypatch):
    """生成中的会话还没有快照，必须照常出现在列表里（否则回复中会话消失）。"""
    import coapis.app.routers.chats as mod

    original = mod._session_file_exists
    specs = _specs_n(5)
    client, restore = _make_client(specs, generating=["c00"])
    _kill_snapshots(monkeypatch, {s.id for s in specs})
    try:
        body = _page(client, limit=10).json()
        ids = {i["id"] for i in body["items"]}
        assert ids == {"c00"}, "生成中的行要留下"
        assert body["items"][0]["generating"] is True
        assert body["total"] == 1
    finally:
        mod._session_file_exists = original
        restore()


def test_fresh_chat_inside_grace_window_stays_listed(monkeypatch):
    """刚创建几秒的会话还没写快照，宽限期内必须可见（否则新建会话当场消失）。"""
    import coapis.app.routers.chats as mod

    original = mod._session_file_exists
    now = datetime.now(timezone.utc)
    specs = [
        _spec("brand-new", "alice", now),
        _spec("old-ghost", "alice", now - timedelta(days=9)),
    ]
    client, restore = _make_client(specs)
    _kill_snapshots(monkeypatch, {s.id for s in specs})
    try:
        body = _page(client, limit=10).json()
        ids = {i["id"] for i in body["items"]}
        assert ids == {"brand-new"}, "宽限期内的新会话不能被当成空壳丢掉"
    finally:
        mod._session_file_exists = original
        restore()


def test_legacy_shared_session_key_stays_listed(monkeypatch):
    """尺子量错文件 = 整栏历史消失（企业版"左栏没了"的真凶）。

    读历史按 **chat_id** 取快照（get_session_state_dict(spec.id) →
    {user}_{chat_id}.json），而老索引行的 session_id 是**共享**旧键
    （企业版 dev 里 admin 的会话全是 "console:admin"）。只按 session_id 判定，
    量到的是一个从来没人打开的文件：企业 dev 实测按 session_id 命中 1 条、
    按 chat_id 命中 30 条 —— 30 条能打开的会话被判定成空壳，左栏清空。
    """
    import coapis.app.routers.chats as mod

    original = mod._session_file_exists
    specs = [
        _spec("c1", "alice", datetime(2026, 11, 1, tzinfo=timezone.utc)),
        _spec("c2", "alice", datetime(2026, 10, 31, tzinfo=timezone.utc)),
    ]
    # 索引行的 session_id 是共享旧键，快照按 chat_id 落盘
    for s in specs:
        s.session_id = "console:admin"
    client, restore = _make_client(specs)
    seen = []

    def _fake(session_obj, key, user_id):
        seen.append(key)
        return key in {"c1", "c2"}  # 只有 chat_id 口径有文件

    mod._session_file_exists = _fake
    try:
        body = _page(client, limit=10).json()
        assert body["total"] == 2, "按 chat_id 能打开的会话不能被判定成空壳"
        assert {i["id"] for i in body["items"]} == {"c1", "c2"}
        assert "c1" in seen and "console:admin" in seen, "两个键都要问"
    finally:
        mod._session_file_exists = original
        restore()


def test_openability_costs_one_check_per_candidate(monkeypatch):
    """成本口径（写死，防止改回"窗口内才检查"）：每个候选检查一次。

    分页要保证窗口非空，就必须对全部候选判定一次 —— 这是一次 stat/候选，
    换掉的是"首屏可能整页为空"。self-heal（会写盘）仍只跑窗口内的行。
    """
    import coapis.app.routers.chats as mod

    original_exists = mod._session_file_exists
    original_session = mod._get_session_for_chat
    specs = _specs_n(30)
    client, restore = _make_client(specs)
    exists_calls, session_calls = [], []

    def _counting_exists(session_obj, session_id, user_id):
        exists_calls.append(session_id)
        return True

    def _counting_session(chat_spec, request):
        session_calls.append(chat_spec.id)
        return original_session(chat_spec, request)

    mod._session_file_exists = _counting_exists
    mod._get_session_for_chat = _counting_session
    try:
        body = _page(client, limit=10).json()
        assert len(body["items"]) == 10
        assert len(session_calls) == 30, "一次判定 = 一次取会话，不做两遍"
        # 每个候选最多问两个键（chat_id 与 session_id）；命中即短路。
        assert 30 <= len(exists_calls) <= 60, "判定要覆盖全部候选，不能只查窗口"
    finally:
        mod._session_file_exists = original_exists
        mod._get_session_for_chat = original_session
        restore()


def _scoped_specs():
    """一个用户工作区里四种归属：本智能体 / 无 agent 的遗留行 / 遗留 default / 场景智能体。"""
    base = datetime(2026, 10, 20, 12, 0, 0, tzinfo=timezone.utc)

    def mk(cid, ag):
        return ChatSpec(
            id=cid,
            name=cid,
            session_id="sess-%s" % cid,
            user_id="alice",
            agent_id=ag,
            channel="console",
            updated_at=base,
            created_at=base - timedelta(days=1),
            meta={},
            status="idle",
        )

    return [
        mk("own", "user:alice"),
        mk("legacy-empty", ""),
        mk("legacy-default", "default"),
        mk("scene", "user_a1b2c3"),
    ]


def test_legacy_rows_stay_in_the_owner_root_agent_list(monkeypatch):
    """遗留行（agent_id 为空/``default``）属于用户自己的默认智能体。

    这些行写在 workspaces/{user}/chat/chats.json 里，读历史走该用户根会话
    存储，点开就有消息。按字面 id 匹配把它们排除在外，等于把用户的历史藏
    起来——社区 dev 实测：13 条能打开的会话只列出 4 条。
    """
    import coapis.app.routers.chats as mod

    original = mod._session_file_exists
    mod._session_file_exists = lambda *a, **k: True
    client, restore = _make_client(_scoped_specs())
    try:
        body = _page(client, limit=10, agent_id="user:alice").json()
        ids = {i["id"] for i in body["items"]}
        assert ids == {"own", "legacy-empty", "legacy-default"}, (
            "默认智能体的列表必须包含本工作区的遗留会话，且不含场景智能体的"
        )
        assert body["total"] == 3
    finally:
        mod._session_file_exists = original
        restore()


def test_legacy_rows_never_leak_into_a_scene_agent_list(monkeypatch):
    """反过来：场景智能体的列表只装它自己的会话。

    这条是 379d9e9 引入 scoping 的本意（点开别人 agent 的会话 = "session
    does not exist" 空壳），放宽遗留行时不能把它一起放宽掉。
    """
    import coapis.app.routers.chats as mod

    original = mod._session_file_exists
    mod._session_file_exists = lambda *a, **k: True
    client, restore = _make_client(_scoped_specs())
    try:
        body = _page(client, limit=10, agent_id="user_a1b2c3").json()
        ids = {i["id"] for i in body["items"]}
        assert ids == {"scene"}, "遗留行不能混进场景智能体的列表"
        assert body["total"] == 1
    finally:
        mod._session_file_exists = original
        restore()


def test_agent_scope_rule_directly():
    """尺子本体逐条钉住（工作区由**请求的 agent_id** 选出，与请求者身份无关）。

    遗留行（agent_id 为空 / ``default`` / ``global_default``）属于被读的那个
    工作区的根智能体；场景智能体的列表里永远不该出现它。
    """
    from coapis.app.routers.chats import _agent_scope_match as m

    # 精确匹配
    assert m("user:alice", "user:alice") is True
    assert m("user_a1b2c3", "user_a1b2c3") is True
    # 不带 agent 作用域 = 全放行（HEAD 语义，页脚/管理页要用全量）
    assert m("user_a1b2c3", "") is True
    # 遗留行：属于根智能体的列表
    for legacy in ("", "default", "global_default"):
        assert m(legacy, "user:alice") is True, "遗留会话必须回到用户自己的列表"
        assert m(legacy, "default") is True
        assert m(legacy, "") is True
    # 遗留行：不得混进场景智能体
    assert m("", "user_a1b2c3") is False
    assert m("default", "user_a1b2c3") is False
    # 场景智能体的会话不得出现在用户默认智能体列表里（379d9e9 的本意）
    assert m("user_a1b2c3", "user:alice") is False
    assert m("user_a1b2c3", "default") is False
