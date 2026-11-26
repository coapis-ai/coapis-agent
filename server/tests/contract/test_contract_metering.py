# -*- coding: utf-8 -*-
"""计量全覆盖契约（2026-11-25 用户拍板：只要调用模型就计量，免费收费一律）。

这些测试锁的是**结构性保证**，不是某次实现细节。每条都对应一个真实存在过
的漏记形态——写出来是为了让同类 bug 再犯时立刻红，而不是像这次一样：
台账照常增长、看起来一切正常，实际决策模型烧的 67457 tokens 一条都没进表。
"""
from __future__ import annotations

import asyncio

import pytest

from coapis.token_usage import db_writer
from coapis.token_usage.recorder import (
    SOURCE_DECISION,
    SOURCE_EVOLUTION,
    compute_cost_cents,
    extract_token_counts,
    guard_wrapper_metering,
    is_metered_by_wrapper,
    record_llm_usage,
    with_usage_metering,
)


@pytest.fixture
def captured(monkeypatch):
    """截获所有落库调用，返回 list[dict]。"""
    rows: list[dict] = []
    monkeypatch.setattr(db_writer, "save_token_usage", lambda **kw: rows.append(kw))
    return rows


# ---------------------------------------------------------------------------
# 1. 决策模型必须入账
# ---------------------------------------------------------------------------

def test_decision_call_is_meted(captured):
    """决策模型一次调用 → 台账一行，且带 source=decision。

    反证：此前 gateway 直调裸模型，decision_events 有 69 行真判、
    token_usage 对应 0 行。若接线被撤，本测试红。
    """
    record_llm_usage(
        model="qwen3.8-flash",
        source=SOURCE_DECISION,
        input_tokens=1200,
        output_tokens=300,
        user_id=7,
        username="alice",
        agent_id="agent-1",
        session_id="sess-1",
        provider_id="prov-1",
        latency_ms=16963,
    )
    assert len(captured) == 1
    row = captured[0]
    assert row["source"] == "decision"
    assert row["input_tokens"] == 1200
    assert row["output_tokens"] == 300
    assert row["total_tokens"] == 1500
    assert row["latency_ms"] == 16963


# ---------------------------------------------------------------------------
# 2. 免费/无定价模型：token 照记，成本诚实为 0
# ---------------------------------------------------------------------------

def test_free_model_still_meters_tokens(captured):
    """本地/免费模型没有定价 → cost=0 但 token 必须入账。

    这是用户诉求的核心：「无论免费、收费都应该计量」。若哪天有人写成
    「无定价就跳过」，本测试红。
    """
    class NoPricing:
        def list_models(self):
            return []

    cents = compute_cost_cents("my-local-llama", NoPricing(), 1000, 500)
    # 无匹配定价时回落全局默认表；关键是它是个数字、不是 None/异常
    assert isinstance(cents, float)

    record_llm_usage(
        model="my-local-llama",
        source=SOURCE_EVOLUTION,
        input_tokens=1000,
        output_tokens=500,
        cost_cents=0.0,
    )
    assert len(captured) == 1
    row = captured[0]
    assert row["total_tokens"] == 1500
    assert row["cost_cents"] == 0.0
    assert row["source"] == "evolution"


def test_zero_token_call_is_not_recorded(captured):
    """上游真没给用量（0/0）→ 不入账，也不编数。"""
    record_llm_usage(model="m", source="chat", input_tokens=0, output_tokens=0)
    assert captured == []


# ---------------------------------------------------------------------------
# 3. 去重闸门：上层已记账，底层钩子必须闭嘴
# ---------------------------------------------------------------------------

def test_wrapper_guard_prevents_double_record(captured):
    """包装器调用期间，底层钩子不得重复入账。

    反证：给底层 client 装钩子后，聊天主链会被记两次、用量直接翻倍。
    """
    class Completions:
        async def create(self, **kwargs):
            class Resp:
                usage = type("U", (), {"prompt_tokens": 10, "completion_tokens": 5})()
            return Resp()

    metered = with_usage_metering(
        type("Client", (), {"chat": type("Chat", (), {"completions": Completions()})()})(),
        lambda: {"source": "chat"},
    )

    async def run():
        # 正常路径：记一次
        await metered.chat.completions.create(model="m")
        assert len(captured) == 1

        # 在包装器保护下：只透传，不再记
        @guard_wrapper_metering
        async def inner_call():
            await metered.chat.completions.create(model="m")

        await inner_call()
        assert len(captured) == 1, "底层钩子在包装器内重复记账"

    asyncio.run(run())


def test_guard_flag_is_restored(captured):
    """闸门必须成对开关，不能泄漏到后续调用。"""
    @guard_wrapper_metering
    async def scoped():
        assert is_metered_by_wrapper() is True

    async def run():
        assert is_metered_by_wrapper() is False
        await scoped()
        assert is_metered_by_wrapper() is False

    asyncio.run(run())


# ---------------------------------------------------------------------------
# 4. 裸 SDK 客户端装钩子后自动入账（流式与非流式）
# ---------------------------------------------------------------------------

def test_metered_client_records_non_stream(captured):
    class Completions:
        async def create(self, **kwargs):
            class Resp:
                usage = type("U", (), {"prompt_tokens": 100, "completion_tokens": 42})()
            return Resp()

    metered = with_usage_metering(
        type("Client", (), {"chat": type("Chat", (), {"completions": Completions()})()})(),
        lambda: {"source": "evolution", "model": "evo-model"},
    )

    async def run():
        return await metered.chat.completions.create(model="ignored")

    asyncio.run(run())
    assert len(captured) == 1
    row = captured[0]
    assert row["model"] == "evo-model"
    assert row["source"] == "evolution"
    assert row["total_tokens"] == 142


def test_metered_client_records_stream_from_final_chunk(captured):
    """流式：从最后一个带 usage 的 chunk 收口，且必须透传所有 chunk。"""
    class Chunk:
        def __init__(self, usage=None):
            self.usage = usage

    class Completions:
        async def create(self, **kwargs):
            async def gen():
                yield Chunk()
                yield Chunk()
                yield Chunk(type("U", (), {"prompt_tokens": 7, "completion_tokens": 3})())
            return gen()

    metered = with_usage_metering(
        type("Client", (), {"chat": type("Chat", (), {"completions": Completions()})()})(),
        lambda: {"source": "chat"},
    )

    async def run():
        got = []
        async for chunk in await metered.chat.completions.create(
            model="m", stream=True,
        ):
            got.append(chunk)
        return got

    chunks = asyncio.run(run())
    assert len(chunks) == 3, "包装后必须原样透传 chunk"
    assert len(captured) == 1
    assert captured[0]["total_tokens"] == 10


def test_metered_client_passes_through_other_attributes(captured):
    """只拦 chat.completions.create，其余属性透传，对调用方零侵入。"""
    class Inner:
        def __init__(self):
            self.base_url = "http://x/v1"
            self.models = object()

    metered = with_usage_metering(Inner(), lambda: {"source": "chat"})
    assert metered.base_url == "http://x/v1"
    assert metered.models is not None


# ---------------------------------------------------------------------------
# 5. usage 提取兼容两种口径
# ---------------------------------------------------------------------------

def test_extract_usage_supports_openai_and_agentscope_naming():
    openai_like = type("R", (), {
        "usage": type("U", (), {"prompt_tokens": 11, "completion_tokens": 22})(),
    })()
    assert extract_token_counts(openai_like) == (11, 22)

    agentscope_like = type("R", (), {
        "usage": type("U", (), {"input_tokens": 33, "output_tokens": 44})(),
    })()
    assert extract_token_counts(agentscope_like) == (33, 44)

    assert extract_token_counts(None) == (0, 0)
    assert extract_token_counts(object()) == (0, 0)


# ---------------------------------------------------------------------------
# 6. 绕过 __init__ 的构造路径不得静默失败
# ---------------------------------------------------------------------------

def test_wrapper_without_init_still_records(captured):
    """用 __new__ 绕过 __init__ 也必须能记账。

    反证：本轮真实事故——测试用 __new__ 构造包装器，新加的 self._source
    不存在，AttributeError 被 except Exception: logger.debug 吞掉，
    表现是「台账正常增长」，实际整条链路无声失败。
    """
    from coapis.token_usage.model_wrapper import TokenRecordingModelWrapper

    wrapper = TokenRecordingModelWrapper.__new__(TokenRecordingModelWrapper)
    wrapper._provider_id = "p"
    wrapper.model_name = "m"
    wrapper.stream = False

    from coapis.config import session_context as sc
    sc.set_current_username("alice")
    sc.set_current_session_id("s1")

    wrapper._record_usage_to_db(
        7, 8, chat_id="s1", session_id="s1", turn_index=1,
        latency_ms=100, stream_interrupted=False,
    )
    assert len(captured) == 1, "绕过 __init__ 时记账被静默跳过"
    assert captured[0]["source"] == "chat"


# ---------------------------------------------------------------------------
# 7. 写入层真的把 source 带进 SQL
# ---------------------------------------------------------------------------

def test_db_writer_accepts_source():
    """save_token_usage 必须接受 source 关键字（列不存在会 TypeError）。"""
    import inspect

    sig = inspect.signature(db_writer.save_token_usage)
    assert "source" in sig.parameters
    sig2 = inspect.signature(db_writer.record_token_usage)
    assert "source" in sig2.parameters
