# -*- coding: utf-8 -*-
"""批次 B5：``GET /api/chats/page`` 真分页端点。

左栏原来一次拉 200 条会话（实测 279 行全挂载 + 切会话阻塞 5.8s），改成
"首屏 20 条、滚到底再要下一页"后，分页语义必须由后端保证：

* ``total`` 是**过滤后的总数**，不是本页条数 —— 前端靠它判断"还有没有下一页"；
* 排序在分页前完成（updated_at 倒序），页与页之间不重叠、不丢条目；
* ``limit`` 有上限，``offset`` 越界返回空页而不是 500；
* 归属隔离：bob 翻页翻不到 alice 的会话。
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from coapis.app.routers import chats as chats_router
from coapis.app.runner.models import ChatSpec


def _spec(
    chat_id: str,
    user_id: str,
    updated: datetime,
    name: str,
    channel: str = "console",
) -> ChatSpec:
    return ChatSpec(
        id=chat_id,
        name=name,
        session_id=f"sess-{chat_id}",
        user_id=user_id,
        channel=channel,
        updated_at=updated,
        created_at=updated - timedelta(days=1),
        meta={},
    )


class _FakeChatManager:
    """内存版 chat manager：只实现分页端点用到的两个方法。"""

    def __init__(self, specs):
        self._specs = {s.id: s for s in specs}

    async def list_chats(self, user_id=None, channel=None):
        # 方法名/签名必须与真实 ChatManager.list_chats(user_id, channel) 对齐：
        # 端点调的是 list_chats(channel=...)，桩叫 get_all_chats 会直接
        # AttributeError，整片测试红掉却看不出是桩的问题。
        out = list(self._specs.values())
        if user_id is not None:
            out = [s for s in out if s.user_id == user_id]
        if channel:
            # 与真实 repo 对齐（chat_metadata/base.py:108 ``if channel:``）：
            # 空串表示"不过滤"，不是"channel == ''"。
            out = [s for s in out if s.channel == channel]
        return out

    def get_chat(self, chat_id):
        return self._specs.get(chat_id)


def _make_client(specs):
    # 生产里 ``_get_current_user`` 是**同步**函数（读 request.state），
    # 桩函数必须同为同步：写成 async 会让端点拿到一个协程对象，
    # 解包 ``username, is_admin = ...`` 直接炸（真实调用方是同步调用）。
    def _fake_current_user(request):
        return (
            getattr(request.state, "username", "alice"),
            getattr(request.state, "role", "user") == "admin",
        )

    async def _fake_cm(request, agent_id=""):
        # 生产里会话隔离来自**每个用户自己的 agent workspace**：
        # ``_get_chat_manager(request, agent_id)`` 取到的是"这个请求者能碰的那个工作区"，
        # 所以 manager 天然只返回该用户的会话。桩必须照这个语义按请求者过滤，
        # 否则测出来的是"共享池分页"，不是生产行为。admin 可跨工作区 → 看全量。
        user = getattr(request.state, "username", "alice")
        role = getattr(request.state, "role", "user")
        if role == "admin":
            return _FakeChatManager(specs)
        return _FakeChatManager([s for s in specs if s.user_id == user])

    import coapis.app.routers.chats as mod

    original_user = mod._get_current_user
    original_cm = mod._get_chat_manager
    mod._get_current_user = _fake_current_user
    mod._get_chat_manager = _fake_cm

    from coapis.app.permissions import decorators as perm_dec

    original_check = perm_dec._perform_permission_check
    perm_dec._perform_permission_check = lambda *a, **k: None

    app = FastAPI()

    @app.middleware("http")
    async def _auth(request, call_next):
        request.state.username = request.query_params.get("as", "alice")
        request.state.role = request.query_params.get("role", "user")
        return await call_next(request)

    app.include_router(chats_router.router, prefix="/api")
    client = TestClient(app)

    def restore():
        mod._get_current_user = original_user
        mod._get_chat_manager = original_cm
        perm_dec._perform_permission_check = original_check

    return client, restore


@pytest.fixture()
def specs():
    base = datetime(2026, 10, 20, 12, 0, 0, tzinfo=timezone.utc)
    out = []
    for i in range(45):
        out.append(
            _spec(
                f"alice-{i:02d}",
                "alice",
                base + timedelta(minutes=i),
                f"会话 {i}",
                # 总数保持 45（其它用例断言它），每 15 条给 1 条 wecom：
                # alice 只有 console 时，"console=全部渠道"的断言观察不到
                # 第二个渠道，等于没测。
                channel="wecom" if i % 15 == 14 else "console",
            ),
        )
    for i in range(7):
        out.append(
            _spec(f"bob-{i:02d}", "bob", base + timedelta(hours=i), f"bob {i}"),
        )
    return out


def _page(client, limit=20, offset=0, as_user="alice", **extra):
    # 端点与 ``GET /chats`` 同语义：agent_id 必填（query 参数或 X-Agent-Id 头）。
    # 本树没有 ``resolve_user_default_agent``，不传就是 400。
    params = {"limit": limit, "offset": offset, "as": as_user, "agent_id": "default"}
    params.update(extra)
    return client.get("/api/chats/page", params=params)


def test_total_is_filtered_total_not_page_size(specs):
    client, restore = _make_client(specs)
    try:
        r = _page(client, limit=20, offset=0)
        assert r.status_code == 200
        body = r.json()
        assert body["total"] == 45, "total 必须是过滤后的总数"
        assert len(body["items"]) == 20
    finally:
        restore()


def test_pages_do_not_overlap_or_drop(specs):
    client, restore = _make_client(specs)
    try:
        seen = []
        for offset in (0, 20, 40):
            body = _page(client, limit=20, offset=offset).json()
            seen += [i["id"] for i in body["items"]]
        assert len(seen) == 45
        assert len(set(seen)) == 45, "页与页之间不得重叠或漏条目"
    finally:
        restore()


def test_sorted_desc_by_updated_before_paging(specs):
    client, restore = _make_client(specs)
    try:
        body = _page(client, limit=20, offset=0).json()
        stamps = [i["updated_at"] for i in body["items"]]
        assert stamps == sorted(stamps, reverse=True)
    finally:
        restore()


def test_offset_beyond_total_returns_empty_page(specs):
    client, restore = _make_client(specs)
    try:
        r = _page(client, limit=20, offset=200)
        assert r.status_code == 200
        body = r.json()
        assert body["items"] == []
        assert body["total"] == 45, "空页的 total 不能变成 0"
    finally:
        restore()


def test_limit_is_capped(specs):
    client, restore = _make_client(specs)
    try:
        r = _page(client, limit=500)
        assert r.status_code == 422, "limit 超过上限必须拒绝，不能全量返回"
        r2 = _page(client, limit=0)
        assert r2.status_code == 422, "limit=0 会让前端永远翻不动"
    finally:
        restore()


def test_ownership_isolation_across_pages(specs):
    client, restore = _make_client(specs)
    try:
        body = _page(client, limit=20, offset=0, as_user="bob").json()
        assert body["total"] == 7
        assert all(i["id"].startswith("bob-") for i in body["items"])
        # 翻到越界页也拿不到 alice 的会话
        body2 = _page(client, limit=20, offset=20, as_user="bob").json()
        assert body2["items"] == []
    finally:
        restore()


def test_channel_filter_semantics(specs):
    """channel 语义 = HEAD 语义（分页端点必须与 ``GET /chats`` 完全一致）。

    - ``console``/省略 = "默认视图" → **全部渠道**（左栏依赖它；把它当普通
      渠道过滤会让所有 wecom/discord 会话消失）
    - 其他值 = 按该渠道过滤
    - 不存在的渠道 → 0 条
    - 普通用户不被强制收敛（HEAD 无此逻辑；发明它会越权改写他人语义）
    """
    client, restore = _make_client(specs)
    try:
        # 不存在的渠道 → 0 条
        body = _page(client, limit=20, offset=0, role="admin", channel="nope").json()
        assert body["total"] == 0, body
        assert body["items"] == [], body

        # 真实渠道 → total 是该用户该渠道的条数
        body_wecom = _page(client, limit=20, offset=0, role="admin",
                           channel="wecom").json()
        expect = sum(1 for s in specs
                     if s.channel == "wecom" and s.user_id == "alice")
        assert body_wecom["total"] == expect, (body_wecom["total"], expect)

        # console = 默认视图 = 全部渠道（不是"只返回 console 渠道"）
        # 取满 100 条再断言渠道集合：limit=20 时按时间排序可能整页都是
        # console，那是取样问题，不是过滤问题。
        body_console = _page(client, limit=100, offset=0, channel="console").json()
        expect_all = sum(1 for s in specs if s.user_id == "alice")
        assert body_console["total"] == expect_all, (
            body_console["total"], expect_all,
        )
        channels = {i["channel"] for i in body_console["items"]}
        assert "wecom" in channels, channels

        # 省略 channel 与 console 等价
        body_default = _page(client, limit=20, offset=0).json()
        assert body_default["total"] == expect_all, (
            body_default["total"], expect_all,
        )
    finally:
        restore()


def test_page_route_not_swallowed_by_chat_id_route(specs):
    """/chats/page 必须注册在 /chats/{chat_id} 之前，否则 page 被当成 id。"""
    client, restore = _make_client(specs)
    try:
        r = _page(client, limit=5)
        assert r.status_code == 200
        assert "total" in r.json(), "命中了 /chats/{chat_id} 路由"
    finally:
        restore()


def test_agent_id_required_on_both_endpoints(specs):
    """回归锁：``/chats`` 与 ``/chats/page`` 都必须显式 agent_id（参数或头）。

    重构时这里凭空引用过一个不存在的 ``resolve_user_default_agent``，
    两个端点一起 500（``NameError``），主聊天列表整页打不开。
    """
    client, restore = _make_client(specs)
    try:
        for path in ("/api/chats", "/api/chats/page"):
            r = client.get(path, params={"as": "alice"})
            assert r.status_code == 400, (path, r.status_code, r.text[:120])
            assert "agent_id" in r.text, (path, r.text[:120])

        # 头传 agent_id 也算数
        r = client.get("/api/chats/page", params={"as": "alice"},
                       headers={"X-Agent-Id": "default"})
        assert r.status_code == 200, (r.status_code, r.text[:120])
        assert "total" in r.json(), r.text[:120]
    finally:
        restore()
