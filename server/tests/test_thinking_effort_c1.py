# -*- coding: utf-8 -*-
"""C1：思考开支消费判档结论（§4.4④ 消灭双头决策）。

锁死三件事：
1. 判档结论带出 effort，判档与思考开支是**同一个结论**（同一次调用）；
2. effort → 各家 provider 的形状（适配层消费，不停在没人读的键上）；
3. 形状落到**承载请求参数的真模型**上，轮后还原，跨轮不粘滞。
"""

from __future__ import annotations

import asyncio

import pytest

from coapis.agents.plan_gate import ComplexityClassifier
from coapis.agents.utils.thinking_budget import (
    apply_thinking_shape,
    complexity_to_effort,
    effort_shape,
    resolve_thinking_target,
    restore_thinking_shape,
)


@pytest.fixture
def asyncio_run():
    """同步测试里跑协程（与 test_decision_hub_phase1 的夹具同款）。"""

    def _run(coro):
        loop = asyncio.new_event_loop()
        try:
            return loop.run_until_complete(coro)
        finally:
            loop.close()

    return _run


# ---------------------------------------------------------------- 同一结论


def test_rule_passthrough_records_effort(asyncio_run):
    """规则直通也要记录 effort——两条路共用同一把尺子。"""
    text = "第一步登录系统，第二步查询订单，第三步导出报表，第四步发送邮件，并汇总统计结果，给出依据"
    clf = ComplexityClassifier()
    ComplexityClassifier._effort_cache.clear()
    assert clf.classify(text) == "complex"  # 规则层判 complex
    asyncio_run(clf.classify_smart(text))  # 规则命中 complex → 直通，零次判断
    assert ComplexityClassifier.pop_effort(text) == "high"


def test_rule_passthrough_simple_records_minimal(asyncio_run):
    """规则判 simple → effort minimal（§4.4④默认不思考），不是 high。"""
    text = "查今天的销售数据"
    clf = ComplexityClassifier()
    ComplexityClassifier._effort_cache.clear()
    asyncio_run(clf.classify_smart(text))
    assert ComplexityClassifier.pop_effort(text) == "minimal"


def test_pop_effort_miss_returns_none():
    ComplexityClassifier._effort_cache.clear()
    assert ComplexityClassifier.pop_effort("没判过的一句话") is None


def test_effort_cache_is_consumed_once_keyed_by_query():
    ComplexityClassifier._effort_cache.clear()
    ComplexityClassifier.remember_effort("  做个新系统  ", "high")
    assert ComplexityClassifier.pop_effort("做个新系统") == "high"
    ComplexityClassifier._effort_cache.clear()


def test_complexity_to_effort_mapping():
    assert complexity_to_effort("simple") == "minimal"
    assert complexity_to_effort("normal") == "low"
    assert complexity_to_effort("complex") == "high"
    # 兼容层：未知档位按 minimal（关思考）——既有行为，不静默放大开支
    assert complexity_to_effort("没见过的词") == "minimal"


# ---------------------------------------------------------------- 形状映射


def test_shape_off_for_ollama_is_template_switch():
    shape = effort_shape("minimal", "ollama")
    assert shape["thinking_budget_hint"] == 0
    assert shape["generate_kwargs"]["chat_template_kwargs"] == {"enable_thinking": False}
    assert shape["reasoning_effort"] == "low"


def test_shape_high_for_ollama_carries_budget():
    shape = effort_shape("high", "ollama")
    kwargs = shape["generate_kwargs"]["chat_template_kwargs"]
    assert kwargs["enable_thinking"] is True
    assert kwargs["thinking_budget"] > 0


def test_shape_dashscope_uses_top_level_enable_thinking():
    shape = effort_shape("minimal", "dashscope_compatible")
    assert shape["generate_kwargs"]["enable_thinking"] is False
    assert "chat_template_kwargs" not in shape["generate_kwargs"]


def test_shape_anthropic_and_gemini_use_native_attrs():
    assert effort_shape("minimal", "anthropic")["model_attrs"]["thinking"] == {
        "type": "disabled",
    }
    assert effort_shape("high", "anthropic")["model_attrs"]["thinking"]["type"] == "enabled"
    assert effort_shape("minimal", "gemini")["model_attrs"]["thinking_config"]["thinking_budget"] == 0
    assert effort_shape("high", "gemini")["model_attrs"]["thinking_config"]["thinking_budget"] > 0


def test_unknown_provider_sends_no_shape_keys():
    """宁可不关思考，也不能把主链打挂（官方 OpenAI 发未知键会 400）。"""
    shape = effort_shape("minimal", "openai")
    assert shape["generate_kwargs"] == {}
    assert shape["model_attrs"] == {}
    # 官方 OpenAI 没有关思考的原生键：minimal = 最小预算（reasoning_effort=low）
    assert shape["reasoning_effort"] == "low"
    assert shape["thinking_budget_hint"] == 0
    assert effort_shape("minimal", None)["generate_kwargs"] == {}


def test_shape_budget_tiers_monotonic():
    hints = [
        effort_shape(effort, "ollama")["thinking_budget_hint"]
        for effort in ("minimal", "low", "medium", "high")
    ]
    assert hints[0] == 0
    assert hints[0] < hints[1] < hints[2] < hints[3]


# ---------------------------------------------------------------- 落到真模型


class _Inner:
    def __init__(self):
        self.generate_kwargs = {"temperature": 0.3}


class _Outer:
    """模拟包装层：只有 _model 指向内层（和窗口/用量包装同构）。"""

    def __init__(self, inner):
        self._model = inner


def test_resolve_target_walks_wrappers():
    inner = _Inner()
    assert resolve_thinking_target(_Outer(_Outer(inner))) is inner


def test_apply_writes_to_inner_and_restores():
    inner = _Inner()
    model = _Outer(inner)
    restore = apply_thinking_shape(model, "minimal", "ollama")
    # 写在内层（承载请求参数的对象），不是包装层
    assert inner.generate_kwargs["chat_template_kwargs"]["enable_thinking"] is False
    assert inner.reasoning_effort == "low"  # Ollama 只认 low/medium/high
    assert restore["target"] is inner
    assert not hasattr(model, "reasoning_effort")

    restore_thinking_shape(restore)
    assert inner.generate_kwargs == {"temperature": 0.3}
    assert not hasattr(inner, "reasoning_effort")


def test_apply_merges_existing_template_kwargs():
    inner = _Inner()
    inner.generate_kwargs["chat_template_kwargs"] = {"use": False}
    apply_thinking_shape(inner, "high", "ollama")
    merged = inner.generate_kwargs["chat_template_kwargs"]
    assert merged["use"] is False  # 原有键不丢
    assert merged["enable_thinking"] is True


def test_apply_never_raises_on_frozen_target():
    class Frozen:
        __slots__ = ()

    restore = apply_thinking_shape(Frozen(), "high", "ollama")
    assert restore["effort"] == "high"
    restore_thinking_shape(restore)


# ---------------------------------------------------------------- 台账记录


def test_rule_action_records_thinking(tmp_path):
    """§4.5③：思考开支写进行动的 action（台账能还原现场）。"""
    from coapis.decision import DecisionHubConfig, set_bus
    from coapis.decision.bus import DecisionBus
    from coapis.foundation.db import get_session_factory, init_engine, reset_engine
    from coapis.foundation.db.base import BaseRow
    from coapis.foundation.db.models.decision import DecisionEvent  # noqa: F401

    engine = init_engine("sqlite:///%s" % (tmp_path / "ledger.db"))
    BaseRow.metadata.create_all(engine)
    bus = DecisionBus(DecisionHubConfig.from_dict({"ledger_enabled": True}))
    set_bus(bus)
    try:
        clf = ComplexityClassifier()
        clf.set_ledger_scope({"user_id": "u", "agent_id": "a", "chat_id": "c"})
        clf.record_ledger("complex", action="规则判级为complex")
        with get_session_factory()() as s:
            rows = list(s.query(DecisionEvent).all())
    finally:
        reset_engine()
    assert len(rows) == 1
    row = rows[0]
    assert "thinking:high" in row.action
    assert row.source == "plan_gate"
    assert row.hit_layer == "rule"
    assert row.user_id == "u" and row.agent_id == "a" and row.chat_id == "c"


def test_effort_cache_ttl_expiry():
    import time as _t

    ComplexityClassifier._effort_cache.clear()
    ComplexityClassifier.remember_effort("旧问题", "high")
    key = "旧问题"
    stamp = ComplexityClassifier._effort_cache[key][1]
    ComplexityClassifier._effort_cache[key] = ("high", stamp - 10_000)
    assert ComplexityClassifier.pop_effort("旧问题") is None
    ComplexityClassifier._effort_cache.clear()


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-q"]))
