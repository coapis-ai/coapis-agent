# -*- coding: utf-8 -*-
"""判断中枢唯一 LLM 出口（gateway.py）单元测试（v14 §5 B1/B2）。

覆盖：
- L0 前置门：总开关 / 岗位开关 / 熔断 / 每轮调用上限
- L1 缓存命中
- L2 单飞（同题并发只打一次）
- L3 硬类型校验（非 chat 拒绝）、无模型、超时、传输失败
- L3 成功：参数走 provider 层、消费流取全文、台账记 action/cost/tokens
- L4 降级：规则兜底出结论
- 失败计数进熔断；不重试
"""
from __future__ import annotations

import asyncio
import time

import pytest

from coapis.decision import gateway as gw
from coapis.decision.breaker import reset_breakers
from coapis.decision.cache import reset_judgment_cache
from coapis.decision.config import DecisionHubConfig
from coapis.decision.bus import DecisionBus, set_bus
from coapis.decision.types import DecisionResult


# ---------------- 测试替身 ----------------


class RecordingBus:
    """台账替身：只记录，不碰数据库。"""

    def __init__(self) -> None:
        self.rows: list[dict] = []

    def emit(self, event: DecisionResult, **kw) -> bool:
        self.rows.append(
            {
                "source": event.source,
                "complexity": event.complexity,
                "action": event.action,
                "reason": event.reason,
                "hit_layer": event.hit_layer,
                "model": event.model,
                "latency_ms": event.latency_ms,
                "cost": event.cost,
                "tokens": event.tokens,
                "user_id": event.user_id,
                "agent_id": event.agent_id,
                "chat_id": event.chat_id,
                "outcome": event.outcome,
            },
        )
        return True


class FakeModel:
    """流式模型替身：每个 chunk 携带累计全文（agentscope 语义）。"""

    def __init__(self, text: str, *, usage=None, delay: float = 0.0,
                 boom: Exception | None = None) -> None:
        self.text = text
        self.usage = usage
        self.delay = delay
        self.boom = boom
        self.calls = 0
        self.last_kwargs: dict = {}

    async def _gen(self):
        class _Chunk:
            def __init__(self, content, usage):
                self.content = content
                self.usage = usage

        accumulated = ""
        for ch in self.text:
            accumulated += ch
            yield _Chunk([{"type": "text", "text": accumulated}], self.usage)

    async def __call__(self, messages, **kwargs):
        self.calls += 1
        self.last_kwargs = kwargs
        if self.boom is not None:
            raise self.boom
        if self.delay:
            await asyncio.sleep(self.delay)
        return await self._gen().__anext__() if False else self._gen()


class FakeProvider:
    provider_type = "openai"

    def __init__(self, model: FakeModel, *, models=None, base_url="",
                 kwargs=None) -> None:
        self.model = model
        self.base_url = base_url
        self.models = models if models is not None else [
            type("M", (), {"id": "m1", "type": "chat", "pricing": {}})(),
        ]
        self._kwargs = kwargs if kwargs is not None else {
            "temperature": 0.7, "top_p": 0.95, "max_tokens": 4096,
            "none_key": None, "empty_key": {},
        }

    def get_effective_generate_kwargs(self, model_id):
        return dict(self._kwargs)

    def get_chat_model_instance(self, model_id):
        return self.model


class FakeManager:
    def __init__(self, provider) -> None:
        self.provider = provider

    def get_provider(self, provider_id):
        return self.provider


# ---------------- 夹具 ----------------

_DEFAULT_SLOT = object()


@pytest.fixture(autouse=True)
def _clean(monkeypatch):
    reset_breakers()
    reset_judgment_cache()
    gw.reset_judge_gateway()
    bus = RecordingBus()
    set_bus(bus)  # type: ignore[arg-type]
    yield
    gw.reset_judge_gateway()
    reset_breakers()
    reset_judgment_cache()


def hub(**kw) -> DecisionHubConfig:
    base = dict(enabled=True, llm_timeout_ms=1000.0, llm_max_tokens=512)
    base.update(kw)
    return DecisionHubConfig.from_dict(base).normalized()


def wire(monkeypatch, model, *, slot=_DEFAULT_SLOT, provider=None):
    """把网关的模型解析接到替身上（传模型，自动套一层 provider）。"""
    from coapis.providers import provider_manager as pm

    prov = provider if provider is not None else FakeProvider(model)
    monkeypatch.setattr(
        pm.ProviderManager, "get_instance",
        staticmethod(lambda: FakeManager(prov)),
        raising=True,
    )
    if slot is _DEFAULT_SLOT:
        slot = {"provider_id": "p1", "model": "m1"}
    monkeypatch.setattr(
        gw, "get_judgment_provider_config",
        lambda user_id=None, agent_id=None: dict(slot),
        raising=True,
    )


SCOPE = {"user_id": "u1", "agent_id": "a1", "chat_id": "c1", "turn": 1}


async def test_l0_hub_disabled_falls_back_to_rule(monkeypatch):
    calls = {"n": 0}

    def rule():
        calls["n"] += 1
        return "L1"

    reply = await gw.get_judge_gateway().judge(
        purpose="plan_gate", system="s", user="u",
        parse=lambda t: "L3", rule_fallback=rule, hub=hub(enabled=False),
    )
    assert reply.value == "L1"
    assert reply.hit_layer == gw.LAYER_DISABLED
    assert calls["n"] == 1


async def test_l0_post_disabled(monkeypatch):
    reply = await gw.get_judge_gateway().judge(
        purpose="plan_gate", system="s", user="u",
        parse=lambda t: "L3", rule_fallback=lambda: "L1",
        hub=hub(plan_gate_enabled=False),
    )
    assert reply.hit_layer == gw.LAYER_DISABLED
    assert reply.value == "L1"


async def test_l0_budget_cap_stops_third_call(monkeypatch):
    model = FakeModel("L2")
    wire(monkeypatch, model)
    scope = {"user_id": "u1", "agent_id": "a1", "chat_id": "c9", "turn": 7}
    h = hub(judge_max_calls_per_turn=2, posts={"skill_trigger": True})

    async def one(tag):
        return await gw.get_judge_gateway().judge(
            purpose="skill_trigger", system="sys-" + tag, user="u",
            parse=lambda t: True, rule_fallback=lambda: False,
            describe=lambda v: "hit", hub=h, scope=scope,
        )

    r1 = await one("1")
    r2 = await one("2")
    r3 = await one("3")
    assert r1.from_llm and r2.from_llm
    assert r3.hit_layer == gw.LAYER_BUDGET
    assert model.calls == 2, "每轮 LLM 判断必须封顶"


async def test_l1_cache_hit_skips_llm(monkeypatch):
    model = FakeModel("L2")
    wire(monkeypatch, model)
    h = hub()
    for _ in range(2):
        reply = await gw.get_judge_gateway().judge(
            purpose="plan_gate", system="s", user="u",
            parse=lambda t: "L2", rule_fallback=lambda: "L1",
            describe=lambda v: v, hub=h, scope=SCOPE,
        )
    assert model.calls == 1
    assert reply.source == "cache"
    assert reply.hit_layer == gw.LAYER_CACHE
    assert reply.value == "L2"


async def test_l2_single_flight_merges_same_prompt(monkeypatch):
    model = FakeModel("L2", delay=0.05)
    wire(monkeypatch, model)
    h = hub()

    async def one():
        return await gw.get_judge_gateway().judge(
            purpose="plan_gate", system="s", user="u",
            parse=lambda t: "L2", rule_fallback=lambda: "L1",
            describe=lambda v: v, hub=h,
            scope={"user_id": "u1", "agent_id": "a1", "chat_id": "c2", "turn": 1},
        )

    r1, r2 = await asyncio.gather(one(), one())
    assert model.calls == 1, "同题并发必须合并成一次调用"
    assert r1.ok and r2.ok
    sources = {r1.source, r2.source}
    assert "llm" in sources and "inflight" in sources


async def test_l3_rejects_non_chat_model(monkeypatch):
    """生产 P0 的根治：槽位解析出嵌入模型时绝不"取第一个模型"。"""
    model = FakeModel("L2")
    emb = FakeProvider(model, models=[
        type("M", (), {"id": "m1", "type": "embedding", "pricing": {}})(),
    ])
    wire(monkeypatch, model, provider=emb)
    h = hub()
    reply = await gw.get_judge_gateway().judge(
        purpose="plan_gate", system="s", user="u",
        parse=lambda t: "L2", rule_fallback=lambda: "L1",
        describe=lambda v: v, hub=h, scope=SCOPE,
    )
    assert model.calls == 0, "非聊天模型绝不能被调用"
    assert reply.hit_layer == gw.LAYER_NOT_CHAT
    assert "非聊天模型" in reply.reason
    assert reply.value == "L1"


async def test_l3_no_model_configured(monkeypatch):
    model = FakeModel("L2")
    wire(monkeypatch, model, slot={})
    reply = await gw.get_judge_gateway().judge(
        purpose="plan_gate", system="s", user="u",
        parse=lambda t: "L2", rule_fallback=lambda: "L1",
        hub=hub(), scope=SCOPE,
    )
    assert reply.hit_layer == gw.LAYER_NO_MODEL
    assert reply.value == "L1"


async def test_l3_timeout_counts_into_breaker_and_degrades(monkeypatch):
    model = FakeModel("L2", delay=1.0)
    wire(monkeypatch, model)
    h = hub(llm_timeout_ms=100.0)
    reply = await gw.get_judge_gateway().judge(
        purpose="plan_gate", system="s", user="u",
        parse=lambda t: "L2", rule_fallback=lambda: "L1",
        hub=h, scope=SCOPE,
    )
    assert reply.hit_layer == gw.LAYER_TIMEOUT
    assert reply.value == "L1"
    assert model.calls == 1, "超时不得重试"

    # 连续失败到阈值（默认 3）后熔断打开，不再打模型
    for _ in range(2):
        await gw.get_judge_gateway().judge(
            purpose="plan_gate", system="s-x", user="u",
            parse=lambda t: "L2", rule_fallback=lambda: "L1",
            hub=h, scope={"user_id": "u1", "agent_id": "a1",
                          "chat_id": "c3", "turn": 1},
        )
    assert model.calls == 3, "熔断打开前共 3 次调用"
    reply = await gw.get_judge_gateway().judge(
        purpose="plan_gate", system="s-y", user="u",
        parse=lambda t: "L2", rule_fallback=lambda: "L1",
        hub=h, scope={"user_id": "u1", "agent_id": "a1",
                      "chat_id": "c4", "turn": 1},
    )
    assert reply.hit_layer == gw.LAYER_BREAKER
    assert model.calls == 3, "熔断打开后必须直接降级"


async def test_l3_transport_error_degrades(monkeypatch):
    model = FakeModel("", boom=RuntimeError("boom"))
    wire(monkeypatch, model)
    reply = await gw.get_judge_gateway().judge(
        purpose="plan_gate", system="s", user="u",
        parse=lambda t: "L2", rule_fallback=lambda: "L1",
        hub=hub(), scope=SCOPE,
    )
    assert reply.hit_layer == gw.LAYER_TRANSPORT
    assert reply.value == "L1"


async def test_l3_success_uses_provider_kwargs_and_records_ledger(monkeypatch):
    usage = type("U", (), {"input_tokens": 11, "output_tokens": 7})()
    model = FakeModel("L3", usage=usage)
    wire(monkeypatch, model)
    h = hub()
    reply = await gw.get_judge_gateway().judge(
        purpose="plan_gate", system="s", user="u",
        parse=lambda t: t.strip(), rule_fallback=lambda: "L1",
        describe=lambda v: "判级" + v, hub=h, scope=SCOPE,
    )
    assert reply.from_llm and reply.value == "L3"
    # 参数基座来自 provider，网关只追加白名单键
    assert model.last_kwargs["temperature"] == 0.7
    assert model.last_kwargs["top_p"] == 0.95
    assert model.last_kwargs["max_tokens"] == 512
    # 消毒：None 与空容器不发
    assert "none_key" not in model.last_kwargs
    assert "empty_key" not in model.last_kwargs

    from coapis.decision.bus import get_bus

    rows = get_bus().rows  # RecordingBus
    assert len(rows) == 1
    row = rows[0]
    assert row["source"] == "plan_gate"
    assert row["hit_layer"] == gw.LAYER_LLM
    assert row["action"] == "判级L3"
    assert row["tokens"] == 18
    assert row["model"] == "m1"
    assert row["user_id"] == "u1"
    assert row["chat_id"] == "c1"
    # 台账不存提示词与结论原文
    assert "s" not in (row["action"] or "")


async def test_parse_failure_counts_into_breaker_and_degrades(monkeypatch):
    model = FakeModel("完全不是结论")
    wire(monkeypatch, model)

    def parse(text):
        return None

    reply = await gw.get_judge_gateway().judge(
        purpose="plan_gate", system="s", user="u",
        parse=parse, rule_fallback=lambda: "L1",
        describe=lambda v: v, hub=hub(), scope=SCOPE,
    )
    assert reply.hit_layer == gw.LAYER_PARSE_FAIL
    assert reply.value == "L1"

    from coapis.decision.breaker import get_breaker

    # 解析失败计入熔断：连续到阈值后该岗位直接降级
    for i in range(2):
        await gw.get_judge_gateway().judge(
            purpose="plan_gate", system="s%d" % i, user="u",
            parse=parse, rule_fallback=lambda: "L1",
            hub=hub(),
            scope={"user_id": "u1", "agent_id": "a1",
                   "chat_id": "p%d" % i, "turn": 1},
        )
    br = get_breaker("judge-model")
    assert br.state_of("judge-model") == "open"


async def test_thinking_param_shape_per_endpoint(monkeypatch):
    provider = FakeProvider(FakeModel("L2"), base_url="https://dashscope.aliyuncs.com/x")
    assert gw.JudgeGateway._thinking_kwargs(provider, False) == {"enable_thinking": False}

    ollama = FakeProvider(FakeModel("L2"), base_url="http://localhost:11434")
    ollama.provider_type = "ollama"
    assert gw.JudgeGateway._thinking_kwargs(ollama, False) == {
        "chat_template_kwargs": {"thinking": False},
    }

    other = FakeProvider(FakeModel("L2"), base_url="https://api.example.com/v1")
    assert gw.JudgeGateway._thinking_kwargs(other, False) == {}
    assert gw.JudgeGateway._thinking_kwargs(other, True) == {}


async def test_ledger_never_stores_prompt_text(monkeypatch):
    secret = "请把这段机密原文写进台账"
    model = FakeModel("L2")
    wire(monkeypatch, model)
    await gw.get_judge_gateway().judge(
        purpose="plan_gate", system=secret, user=secret,
        parse=lambda t: "L2", rule_fallback=lambda: "L1",
        describe=lambda v: v, hub=hub(), scope=SCOPE,
    )
    from coapis.decision.bus import get_bus

    for row in get_bus().rows:
        blob = " ".join(str(v) for v in row.values())
        assert secret not in blob
