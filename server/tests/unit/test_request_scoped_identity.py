# -*- coding: utf-8 -*-
"""请求级身份注入（B2：身份随请求走，不随连接走）单元测试。

覆盖：
- RequestIdentityRegistry 登记/查询/释放/TTL 过期/容量淘汰
- jsonrpc_id_of_request 从 httpx 请求体取 JSON-RPC id
- _IdentityTaggingWriteStream 在调用方任务里按请求 id 登记身份
- make_request_identity_hook 按请求 id 反查身份注入出站头
- 共享连接 + 并发多用户竞态：两个用户的请求各带各的 token（串号回归测试）
- 结构守卫：client 实例上不得再有共享身份格子
"""

import asyncio
import json

import httpx
import pytest
from mcp.shared.session import SessionMessage
from mcp.types import JSONRPCMessage, JSONRPCRequest

from coapis.app import external_identity as ei
from coapis.app.mcp.stateful_client import (
    HttpStatefulClient,
    StdIOStatefulClient,
    _IdentityTaggingWriteStream,
)

OA_URL = "https://oa.example.com/mcp"


@pytest.fixture()
def oa_system(monkeypatch):
    """把 OA 伪装成已配置外部系统，并把 token 解析固定为 tok_<user>。"""
    monkeypatch.setattr(
        ei,
        "find_external_system",
        lambda url: (
            {"provider_id": "oa", "auth_mode": "pass_through"}
            if str(url).startswith(OA_URL)
            else None
        ),
    )

    async def _fake_outbound(url, source="mcp"):
        user = ei.get_identity_username()
        if not user:
            raise ei.IdentityError("no_user", "无用户上下文")
        return {"authorization": f"Bearer tok_{user}"}

    monkeypatch.setattr(ei, "outbound_headers", _fake_outbound)


def _mk_session_message(request_id):
    return SessionMessage(
        message=JSONRPCMessage(
            JSONRPCRequest(
                jsonrpc="2.0",
                id=request_id,
                method="tools/call",
                params={"name": "demo", "arguments": {}},
            ),
        ),
    )


class _FakeStream:
    """内存版 write_stream：记录投递的消息 + 生命周期调用。"""

    def __init__(self):
        self.sent = []
        self.entered = 0
        self.exited = 0
        self.closed = 0

    async def send(self, message):
        self.sent.append(message)

    async def __aenter__(self):
        self.entered += 1
        return self

    async def __aexit__(self, *exc):
        self.exited += 1
        return False

    async def aclose(self):
        self.closed += 1

    def only_method_on_inner(self):
        return "inner"


# ───────────────────────── registry ─────────────────────────


class TestRegistry:
    def test_tag_lookup_release(self):
        reg = ei.RequestIdentityRegistry()
        reg.tag(1, "alice")
        assert reg.lookup(1) == "alice"
        assert len(reg) == 1
        reg.release(1)
        assert reg.lookup(1) is None
        assert len(reg) == 0

    def test_two_users_same_registry(self):
        reg = ei.RequestIdentityRegistry()
        reg.tag(1, "alice")
        reg.tag(2, "bob")
        assert (reg.lookup(1), reg.lookup(2)) == ("alice", "bob")

    def test_none_username_recorded_as_no_owner(self):
        reg = ei.RequestIdentityRegistry()
        reg.tag(0, None)
        assert reg.lookup(0) is None

    def test_ttl_expiry(self):
        reg = ei.RequestIdentityRegistry(max_age=0.0)
        reg.tag(1, "alice")
        assert reg.lookup(1) is None

    def test_capacity_eviction_bounded(self):
        reg = ei.RequestIdentityRegistry(max_entries=8)
        for i in range(50):
            reg.tag(i, f"u{i}")
        assert len(reg) <= 8

    def test_clear(self):
        reg = ei.RequestIdentityRegistry()
        reg.tag(1, "a")
        reg.tag(2, "b")
        reg.clear()
        assert len(reg) == 0


# ───────────────────────── id 提取 ─────────────────────────


class TestJsonRpcId:
    def test_post_json_body_with_id(self):
        req = httpx.Request(
            "POST",
            OA_URL,
            content=json.dumps(
                {"jsonrpc": "2.0", "id": 7, "method": "tools/call"},
            ).encode(),
        )
        assert ei.jsonrpc_id_of_request(req) == 7

    def test_string_id(self):
        req = httpx.Request(
            "POST",
            OA_URL,
            content=json.dumps({"jsonrpc": "2.0", "id": "abc"}).encode(),
        )
        assert ei.jsonrpc_id_of_request(req) == "abc"

    def test_notification_without_id(self):
        req = httpx.Request(
            "POST",
            OA_URL,
            content=json.dumps(
                {"jsonrpc": "2.0", "method": "notifications/initialized"},
            ).encode(),
        )
        assert ei.jsonrpc_id_of_request(req) is None

    def test_get_request_ignored(self):
        assert ei.jsonrpc_id_of_request(httpx.Request("GET", OA_URL)) is None

    def test_non_json_ignored(self):
        req = httpx.Request("POST", OA_URL, content=b"not json")
        assert ei.jsonrpc_id_of_request(req) is None

    def test_empty_body_ignored(self):
        req = httpx.Request("POST", OA_URL, content=b"")
        assert ei.jsonrpc_id_of_request(req) is None


# ───────────────────────── 发送侧代理 ─────────────────────────


class TestTaggingStream:
    def test_tags_caller_from_contextvar(self):
        async def run():
            inner = _FakeStream()
            reg = ei.RequestIdentityRegistry()
            proxy = _IdentityTaggingWriteStream(inner, reg, "oa")
            token = ei._CURRENT_IDENTITY_USER.set("alice")
            try:
                await proxy.send(_mk_session_message(1))
            finally:
                ei._CURRENT_IDENTITY_USER.reset(token)
            assert reg.lookup(1) == "alice"
            assert len(inner.sent) == 1  # 消息照常投递

        asyncio.run(run())

    def test_no_contextvar_records_no_owner(self):
        async def run():
            inner = _FakeStream()
            reg = ei.RequestIdentityRegistry()
            proxy = _IdentityTaggingWriteStream(inner, reg, "oa")
            await proxy.send(_mk_session_message(0))
            assert reg.lookup(0) is None

        asyncio.run(run())

    def test_notification_not_tagged(self):
        async def run():
            inner = _FakeStream()
            reg = ei.RequestIdentityRegistry()
            proxy = _IdentityTaggingWriteStream(inner, reg, "oa")
            msg = SessionMessage(
                message=JSONRPCMessage(
                    json.loads('{"jsonrpc":"2.0","method":"x"}'),
                ),
            )
            await proxy.send(msg)
            assert len(reg) == 0

        asyncio.run(run())

    def test_lifecycle_and_attr_delegation(self):
        async def run():
            inner = _FakeStream()
            proxy = _IdentityTaggingWriteStream(inner, ei.RequestIdentityRegistry())
            async with proxy:
                pass
            await proxy.aclose()
            assert inner.entered == 1 and inner.exited == 1
            assert inner.closed == 1
            assert proxy.only_method_on_inner() == "inner"

        asyncio.run(run())


# ───────────────────────── 注入钩子 ─────────────────────────


class TestHook:
    def test_injects_owner_of_the_request(self, oa_system):
        async def run():
            reg = ei.RequestIdentityRegistry()
            reg.tag(3, "carol")
            seen = {}

            def handler(request):
                seen["auth"] = request.headers.get("authorization")
                return httpx.Response(200, json={"ok": True})

            async with httpx.AsyncClient(
                transport=httpx.MockTransport(handler),
                event_hooks={"request": [ei.make_request_identity_hook(reg)]},
            ) as client:
                await client.post(OA_URL, json={"jsonrpc": "2.0", "id": 3})
            assert seen["auth"] == "Bearer tok_carol"
            assert len(reg) == 0  # 用完即弃

        asyncio.run(run())

    def test_internal_url_untouched(self, oa_system):
        async def run():
            reg = ei.RequestIdentityRegistry()
            reg.tag(1, "alice")
            seen = {}

            def handler(request):
                seen["auth"] = request.headers.get("authorization")
                return httpx.Response(200, json={"ok": True})

            async with httpx.AsyncClient(
                transport=httpx.MockTransport(handler),
                event_hooks={"request": [ei.make_request_identity_hook(reg)]},
            ) as client:
                await client.post("http://127.0.0.1:8809/mcp", json={"id": 1})
            assert seen["auth"] is None

        asyncio.run(run())

    def test_untracked_request_passes_bare(self, oa_system):
        async def run():
            reg = ei.RequestIdentityRegistry()
            seen = {}

            def handler(request):
                seen["auth"] = request.headers.get("authorization")
                return httpx.Response(200, json={"ok": True})

            async with httpx.AsyncClient(
                transport=httpx.MockTransport(handler),
                event_hooks={"request": [ei.make_request_identity_hook(reg)]},
            ) as client:
                await client.post(OA_URL, json={"jsonrpc": "2.0", "id": 99})
            assert seen["auth"] is None

        asyncio.run(run())


# ─────────────────── 共享连接并发竞态（串号回归） ───────────────────


class TestSharedConnectionRace:
    def test_two_users_on_one_connection_get_their_own_token(self, oa_system):
        """复现真实拓扑：1 条共享连接 + 两个用户并发调用。

        两个调用方都先完成身份登记（制造旧实现里"后写者赢"的竞态窗口），
        再各自发请求；断言每个请求带的是自己用户的 token。
        """

        async def run():
            reg = ei.RequestIdentityRegistry()
            inner = _FakeStream()
            proxy = _IdentityTaggingWriteStream(inner, reg, "oa")
            seen = {}

            def handler(request):
                payload = json.loads(request.content)
                seen[payload["id"]] = request.headers.get("authorization")
                return httpx.Response(200, json={"jsonrpc": "2.0", "id": payload["id"], "result": {}})

            async with httpx.AsyncClient(
                transport=httpx.MockTransport(handler),
                event_hooks={"request": [ei.make_request_identity_hook(reg)]},
            ) as client:
                a_ready = asyncio.Event()
                b_ready = asyncio.Event()

                async def caller(rid, user, my_event, other_event):
                    token = ei._CURRENT_IDENTITY_USER.set(user)
                    try:
                        # 发送侧登记（运行在调用方任务里，ContextVar 可用）
                        await proxy.send(_mk_session_message(rid))
                        my_event.set()
                        await other_event.wait()  # 竞态窗口：两人都登记完
                        await client.post(
                            OA_URL,
                            json={
                                "jsonrpc": "2.0",
                                "id": rid,
                                "method": "tools/call",
                            },
                        )
                    finally:
                        ei._CURRENT_IDENTITY_USER.reset(token)

                await asyncio.gather(
                    caller(1, "alice", a_ready, b_ready),
                    caller(2, "bob", b_ready, a_ready),
                )

            assert seen[1] == "Bearer tok_alice"
            assert seen[2] == "Bearer tok_bob"
            assert len(reg) == 0

        asyncio.run(run())

    def test_interleaved_calls_never_leak(self, oa_system):
        """10 个用户交替调用：每个请求的身份必须与请求 id 一一对应。"""

        async def run():
            reg = ei.RequestIdentityRegistry()
            proxy = _IdentityTaggingWriteStream(_FakeStream(), reg, "oa")
            seen = {}

            def handler(request):
                payload = json.loads(request.content)
                seen[payload["id"]] = request.headers.get("authorization")
                return httpx.Response(200, json={"ok": True})

            async with httpx.AsyncClient(
                transport=httpx.MockTransport(handler),
                event_hooks={"request": [ei.make_request_identity_hook(reg)]},
            ) as client:
                async def caller(rid, user):
                    token = ei._CURRENT_IDENTITY_USER.set(user)
                    try:
                        await proxy.send(_mk_session_message(rid))
                        await asyncio.sleep(0)  # 强制交错
                        await client.post(OA_URL, json={"jsonrpc": "2.0", "id": rid})
                    finally:
                        ei._CURRENT_IDENTITY_USER.reset(token)

                await asyncio.gather(
                    *[caller(i, f"u{i}") for i in range(1, 11)],
                )

            for i in range(1, 11):
                assert seen[i] == f"Bearer tok_u{i}"

        asyncio.run(run())


# ─────────────────── 结构守卫：不得有共享身份格子 ───────────────────


class TestNoSharedIdentitySlot:
    @pytest.mark.parametrize(
        "cls,kwargs",
        [
            (
                StdIOStatefulClient,
                {"name": "n", "command": "true"},
            ),
            (
                HttpStatefulClient,
                {"name": "n", "transport": "streamable_http", "url": OA_URL},
            ),
        ],
    )
    def test_client_has_no_per_instance_identity_slot(self, cls, kwargs):
        client = cls(**kwargs)
        for forbidden in ("_call_identity", "_pending_identity_headers"):
            assert not hasattr(client, forbidden), (
                f"{cls.__name__} 上又出现了共享身份格子 {forbidden}："
                "共享连接上多用户并发会串号，身份必须按请求携带"
            )

    def test_registry_is_per_connection(self):
        client = HttpStatefulClient(
            name="n",
            transport="streamable_http",
            url=OA_URL,
        )
        assert client._identity_registry is None  # 连接期才创建

    def test_sse_factory_uses_registry(self, oa_system):
        reg = ei.RequestIdentityRegistry()
        factory = ei.create_identity_httpx_client_factory(identity_registry=reg)
        client = factory(headers={"a": "b"}, timeout=1.0)
        hooks = client._event_hooks["request"]
        assert len(hooks) == 1
        asyncio.run(client.aclose())
