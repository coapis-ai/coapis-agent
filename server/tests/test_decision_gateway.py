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
from coapis.decision.rubric import LEVELS
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
        gw, "get_judge_provider_config",
        lambda cfg=None, user_id=None, agent_id=None, **_kw: dict(slot),
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
    # 额度按岗位分池（v15 G10）：全局 cap 里给验收留的预留不能被普通岗吃掉，
    # 要看普通岗本身的封顶就把预留设为 0，尺子才是这一岗的池子。
    h = hub(judge_max_calls_per_turn=2, judge_reserve_acceptance=0,
            posts={"skill_trigger": True})

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


async def test_acceptance_reserve_survives_other_posts(monkeypatch):
    """普通岗把池子打空，验收岗仍必须拿得到自己的判断额度。

    验收是闭环的最后一环：它饿死，outcome 就永远是 pending，
    整套「判断→验收→学习」的账本断在最后一格。
    """
    model = FakeModel("L2")
    wire(monkeypatch, model)
    # 验收岗的调用名是 acceptance（hub_acceptance.py:161 就这么传，
    # config.POSTS 里也在册）：预留配额按调用名认人。这里若写成 verify，
    # 预留判断（purpose == acceptance）永远不成立，测的是"预留没生效"，
    # 而不是"预留有没有生效"。
    h = hub(judge_max_calls_per_turn=3, judge_reserve_acceptance=2,
            posts={"skill_trigger": True, "acceptance": True})

    async def one(purpose, tag):
        return await gw.get_judge_gateway().judge(
            purpose=purpose, system="sys-" + tag, user="u",
            parse=lambda t: "L2", rule_fallback=lambda: "L1",
            describe=lambda v: v, hub=h, scope=SCOPE,
        )

    for i in range(4):  # 把 skill_trigger 自己的池（3-2=1）反复打死
        await one("skill_trigger", f"s{i}")
    used_by_skill = model.calls
    assert used_by_skill == 1, "普通岗只能用 cap 减预留后的池子"

    res = await one("acceptance", "a1")
    assert res.from_llm, "验收岗被普通岗饿死：预留额度没起作用"
    assert model.calls == used_by_skill + 1


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

    # 连续失败到阈值后熔断打开，不再打模型。阈值是可调配置（v14 批次3 把
    # 默认值从 3 提到 5，避免一次软超时就把判官锁死 60s）——测试跟着配置走，
    # 不钉死字面量，否则调一次配置就红一片。
    from coapis.decision import get_hub_config as _cfg

    nth = _cfg().breaker_failure_threshold
    # 每轮用独立会话：预算闸门按 (会话, 岗位) 计数，共用一个会话会让预算先于
    # 熔断把调用挡住，那就测不到熔断本身。
    opened = False
    for i in range(nth * 3):
        reply = await gw.get_judge_gateway().judge(
            purpose="plan_gate", system="s-%d" % i, user="u",
            parse=lambda t: "L2", rule_fallback=lambda: "L1",
            hub=h, scope={"user_id": "u1", "agent_id": "a1",
                          "chat_id": "c%d" % i, "turn": 1},
        )
        if reply.hit_layer == gw.LAYER_BREAKER:
            opened = True
            break
    assert opened, "连续超时后必须熔断"
    # 一次超时恰好记 1 次失败：前台那颗、以及超时后派出去的后台补判那颗，都是
    # 一次真打模型 + 一次失败（v14 批次3：超时不重试、改后台补判，补判同样
    # 计入熔断——这是设计，补判也失败才说明这个源真的坏了）。所以熔断恰好在
    # 累计 nth 次模型调用处打开：既不提前锁死，也不多打。
    assert model.calls == nth, \
        "熔断打开时模型调用数应恰为阈值 %d，实为 %d" % (nth, model.calls)
    calls_at_open = model.calls
    for i in range(2):
        reply = await gw.get_judge_gateway().judge(
            purpose="plan_gate", system="s-after%d" % i, user="u",
            parse=lambda t: "L2", rule_fallback=lambda: "L1",
            hub=h, scope={"user_id": "u1", "agent_id": "a1",
                          "chat_id": "after%d" % i, "turn": 1},
        )
        assert reply.hit_layer == gw.LAYER_BREAKER
    assert model.calls == calls_at_open, "熔断打开后必须直接降级，不再打模型"


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

    # 解析失败计入熔断：连续到阈值后该岗位直接降级。
    # 阈值是可调配置（v14 批次3 把默认 3 提到 5——一次软超时不该把判官锁死
    # 60s），循环次数跟着配置走，不钉字面量，否则调一次配置就红一片。
    from coapis.decision import get_hub_config as _cfg

    for i in range(_cfg().breaker_failure_threshold - 1):
        await gw.get_judge_gateway().judge(
            purpose="plan_gate", system="s%d" % i, user="u",
            parse=parse, rule_fallback=lambda: "L1",
            hub=hub(),
            scope={"user_id": "u1", "agent_id": "a1",
                   "chat_id": "p%d" % i, "turn": 1},
        )
    # 熔断按岗位分闸（v15 G7）：plan_gate 数到自己闸开，别的岗位不受牵连。
    # 以前全局一把闸时，验收岗把判官判挂会让 tool_gate 在冷却期内一律闭闸，
    # 而 dev 里最容易填满连败计数的恰恰是 tool_gate。尺子必须跟着闸一起分。
    key = gw._breaker_key("plan_gate")
    other = gw._breaker_key("tool_gate")
    br = get_breaker(key)
    assert br.state_of(key) == "open"
    assert get_breaker(other).state_of(other) == "closed"


async def test_thinking_param_shape_per_endpoint(monkeypatch):
    provider = FakeProvider(FakeModel("L2"), base_url="https://dashscope.aliyuncs.com/x")
    assert gw.JudgeGateway._thinking_kwargs(provider, False) == {"enable_thinking": False}

    ollama = FakeProvider(FakeModel("L2"), base_url="http://localhost:11434")
    ollama.provider_type = "ollama"
    # 模板变量名是模板自己的字段，vLLM/llama.cpp 都吃 ``enable_thinking``；
    # 旧的 ``{"thinking": ...}`` 是判官自己发明的第二把尺子，已随单一真相源作废。
    assert gw.JudgeGateway._thinking_kwargs(ollama, False) == {
        "chat_template_kwargs": {"enable_thinking": False},
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


async def _drain_bg_tasks() -> None:
    """等后台补判任务跑完（测试要看见迟到入账，不能靠运气）。"""
    pending = list(gw._BG_TASKS)
    if pending:
        await asyncio.gather(*pending, return_exceptions=True)


async def test_soft_timeout_degrades_then_background_rejudges(monkeypatch):
    """软超时：主链立刻降级先走，判官后台跑完照常入账（v14 §批次3）。

    这条同时钉住一个 dev 实测过的 P0：后台任务里引用主流程的局部名
    （breaker）会 NameError，补判全灭且「Task exception was never retrieved」。
    """
    model = FakeModel("complex")
    model.delay = 0.4
    wire(monkeypatch, model)
    h = hub(judge_soft_ms=80.0, llm_timeout_ms=5000.0, ledger_enabled=True)

    got = await gw.get_judge_gateway().judge(
        purpose="plan_gate", system="s", user="u",
        parse=lambda t: t.strip().lower() if t.strip().lower() in LEVELS else None,
        rule_fallback=lambda: "simple",
        describe=lambda v: v, hub=h, scope=SCOPE,
    )
    # 主链：立刻降级，降级原因写的是「判断超时」，值是规则兜底给的合法档位
    assert got.hit_layer == gw.LAYER_TIMEOUT
    assert "判断超时" in (got.reason or "")
    assert got.value == "simple" and got.value in LEVELS

    from coapis.decision.bus import get_bus

    n_before = len(get_bus().rows)
    await _drain_bg_tasks()
    rows = get_bus().rows[n_before:]
    # 后台补判必须入账，且写的是模型真判的 complex（不是降级值）
    assert any(
        r.get("hit_layer") == "llm" and r.get("complexity") == "complex" for r in rows
    ), rows
    assert any("软超时后台补记" in str(r.get("reason") or "") for r in rows), rows


# ---------------- D-A（2026-11-05 拍板）：未配置判官 = 零成本直判 ----------------
#
# 口径反转的落点。旧口径「判官没配就借用会话激活模型」在 dev 台账留下 184 行
# 真判（avg 4448ms → 超时 105 / 熔断 24 / 预算吃光 61，损耗 44%，最坏 16963ms），
# 本质是拿用户的对话模型赌一次判断。新口径：判官槽位空 = 判官不上岗，在 L0
# 前置门直接按规则返回，零调用、零耗时、不占预算、不进熔断。


def _no_slot(monkeypatch):
    """判官槽位置空（等价于用户没配决策模型）。"""
    monkeypatch.setattr(
        gw, "get_judge_provider_config", lambda *a, **k: None, raising=True,
    )


async def test_no_judge_slot_abstains_without_touching_model(monkeypatch):
    """槽位空：规则直判、耗时近零、model 字段空、台账 hit_layer=no_model。"""
    _no_slot(monkeypatch)
    calls = {"n": 0}

    def rule():
        calls["n"] += 1
        return "L1"

    reply = await gw.get_judge_gateway().judge(
        purpose="plan_gate", system="s", user="u",
        parse=lambda t: "L3", rule_fallback=rule, hub=hub(), scope=SCOPE,
    )
    assert reply.hit_layer == gw.LAYER_NO_MODEL
    assert reply.value == "L1" and calls["n"] == 1
    assert not reply.model, "未配置判官时台账不能记着任何模型"
    assert reply.latency_ms < 200, "配置缺失必须零成本直判，不许去撞模型"
    from coapis.decision.bus import get_bus

    rows = get_bus().rows
    assert rows and rows[-1]["hit_layer"] == "no_model"
    # 台账契约把空值写成哨兵 "none"；关键是绝不能记成某个真模型名（借模型
    # 的旧口径就是在这列上留下 184 行对话模型，把判官战绩算成对话模型战绩）
    assert str(rows[-1]["model"]) in ("", "none", "None", "NoneType")


async def test_no_judge_slot_never_consumes_turn_budget(monkeypatch):
    """模型岗额度只 1 次：未配置判官连判 3 次，次次直判，撞不到预算门。"""
    _no_slot(monkeypatch)
    h = hub(judge_max_calls_per_turn=1, judge_reserve_acceptance=0)
    scope = {"user_id": "u1", "agent_id": "a1", "chat_id": "c77", "turn": 77}
    layers = [
        (await gw.get_judge_gateway().judge(
            purpose="plan_gate", system="s", user="u",
            parse=lambda t: "L3", rule_fallback=lambda: "L1", hub=h, scope=scope,
        )).hit_layer
        for _ in range(3)
    ]
    assert layers == [gw.LAYER_NO_MODEL] * 3, (
        "配置缺失不该走到预算/熔断门前：%s" % layers
    )


async def test_no_judge_slot_does_not_pollute_breaker(monkeypatch):
    """没配判官不能记成判断失败：否则判官一上线就被历史熔断掐死。"""
    _no_slot(monkeypatch)
    scope = {"user_id": "u1", "agent_id": "a1", "chat_id": "c78", "turn": 78}
    for _ in range(5):
        reply = await gw.get_judge_gateway().judge(
            purpose="tool_gate", system="s", user="u",
            parse=lambda t: "allow", rule_fallback=lambda: "ask",
            hub=hub(), scope=scope,
        )
        assert reply.hit_layer == gw.LAYER_NO_MODEL
    # 现在把判官配上：必须立刻真判，不能被前面 5 次「没模型」记成的失败熔断
    model = FakeModel("allow")
    wire(monkeypatch, model)
    reply = await gw.get_judge_gateway().judge(
        purpose="tool_gate", system="s", user="u",
        parse=lambda t: "allow", rule_fallback=lambda: "ask",
        hub=hub(), scope=scope,
    )
    assert reply.hit_layer == gw.LAYER_LLM, (
        "未配置期间的直判被记成了失败，判官上线即熔断：%s" % reply.hit_layer
    )
    assert model.calls == 1


def test_no_model_is_not_counted_as_a_judged_attempt():
    """no_model 必须在真判断层白名单之外（配置状态 ≠ 判官败绩）。"""
    assert gw.LAYER_NO_MODEL not in gw.JUDGED_LAYERS
