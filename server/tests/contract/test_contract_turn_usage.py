# -*- coding: utf-8 -*-
"""B1 契约锁：轮次 usage 与模型可用性台账。

写法的三条硬规矩（沿用 B0 的教训）：

1. **现状锁**锁当前可依赖行为；**目标锁**（``@B1``）锁本轮交付后的目标，
   交付后必须摘标记（本文件 5 条 @B1 已在 2026-11-14 B1 交付时全部摘除，
   摘后无剩余目标锁 —— 有新目标就再加，不许空挂）。
2. 断言只钉**已被调用方依赖**的形状，不钉实现细节。
3. 每张锁都注明"钉的是谁"，将来改签名的人能一眼看到会打断谁。
"""
from __future__ import annotations

import pathlib
import sys

import pytest

# 目录深度：server/tests/contract/<file>.py → repo 根要 parents[3]
# （B0 的 conftest 同款口径；parents[2] 会指到 server/ 下面）
REPO_ROOT = pathlib.Path(__file__).resolve().parents[3]
if str(REPO_ROOT / "server") not in sys.path:
    sys.path.insert(0, str(REPO_ROOT / "server"))

B1 = pytest.mark.xfail(
    strict=True,
    raises=(AttributeError, ImportError, KeyError, TypeError, AssertionError),
    reason="B1 未交付：轮次 usage / 可用性台账",
)

from coapis.providers.provider_model_availability import (  # noqa: E402
    AVAILABILITY_STATUSES,
    ProviderModelAvailabilityStore,
    get_availability_store,
    reason_of,
    record_model_result,
    record_model_result_safe,
    reset_availability_store,
)
from coapis.token_usage import turn_usage as tu  # noqa: E402


def _runner_mod():
    """runner 带相对导入，只能按包导入（importlib 单文件加载会炸）。"""
    from coapis.app.runner import runner as module

    return module


# ============================================================ 轮次 usage 面
def test_turn_usage_is_pure_computation_no_db():
    """架构红线：本模块**不自己开会话**（持久化归既有通路）。"""
    src = (
        REPO_ROOT / "server" / "coapis" / "token_usage" / "turn_usage.py"
    ).read_text(encoding="utf-8")
    assert "async_session_factory" not in src
    assert "session_factory" not in src
    assert "save_token_usage" not in src


def test_assistant_turn_count_is_role_based():
    """``turns`` 钉在 ``role == assistant`` 上（借鉴上游口径，写死防漂移）。"""
    msgs = [
        {"role": "user", "content": "a"},
        {"role": "assistant", "content": "b"},
        {"role": "tool", "content": "c"},
        {"role": "assistant", "content": "d"},
    ]
    assert tu.count_assistant_turns(msgs) == 2
    assert tu.count_assistant_turns([]) == 0


def test_resolve_turn_usage_accepts_chatusage_and_dict_and_none():
    """三种形状都要能吃：ChatUsage 对象、OpenAI dict、None。

    钉这个是因为上游自定义了 ``__getattr__``（缺键抛 **KeyError**），
    ``getattr(x, k, default)`` 兜不住 —— 这里必须静默兜住。
    """

    class FakeUsage:
        def __getattr__(self, name):  # 复刻 ChatUsage 的行为
            raise KeyError(name)

    msgs = [{"role": "user", "content": "x" * 40}, {"role": "assistant", "content": "y"}]

    obj = tu.resolve_turn_usage(
        response_usage=FakeUsage(),
        request_messages=msgs,
        max_input_tokens=8000,
    )
    assert obj.prompt_tokens > 0  # 估算兜底，不是 0 假象
    assert obj.completion_tokens == 0
    assert obj.turns == 1
    assert obj.max_input_tokens == 8000

    d = tu.resolve_turn_usage(
        response_usage={"prompt_tokens": 11, "completion_tokens": 7},
        request_messages=msgs,
        max_input_tokens=8000,
    )
    assert d.prompt_tokens == 11
    assert d.completion_tokens == 7
    assert d.total_tokens == 18

    n = tu.resolve_turn_usage(request_messages=msgs)
    assert n.max_input_tokens == 0
    assert n.use_ratio == 0.0  # 无上限 → 0（不猜满）


def test_resolve_never_raises_on_garbage():
    """收尾/解析路径**绝不抛异常**：解析函数的历史职责就是不中断流。"""
    for junk in (None, 0, "x", {"prompt_tokens": "abc"}, object()):
        usage = tu.resolve_turn_usage(
            response_usage=junk,
            request_messages=[{"role": "user", "content": "hi"}],
        )
        assert usage.total_tokens >= 0


def test_context_tokens_never_below_prompt_tokens():
    """上下文规模不可能小于本轮输入（借鉴上游的对账口径）。"""
    usage = tu.resolve_turn_usage(
        response_usage={"prompt_tokens": 900},
        request_messages=[{"role": "user", "content": "short"}],
    )
    assert usage.context_tokens >= usage.prompt_tokens


def test_write_turn_usage_meta_shape_and_zero_fill():
    """元数据形状：缺项写 0 而不是 None（前端/聚合都按整数读）。"""
    meta = tu.write_turn_usage_meta("sess-1", "chat-1", None, model_name="m")
    assert meta["model_name"] == "m"
    for key in (
        "prompt_tokens",
        "completion_tokens",
        "total_tokens",
        "context_tokens",
        "turns",
        "max_input_tokens",
    ):
        assert meta[key] == 0

    usage = tu.TurnUsage(prompt_tokens=5, completion_tokens=2, turns=1)
    filled = tu.write_turn_usage_meta("s", "c", usage, model_name="m")
    assert filled["total_tokens"] == 7


def test_write_turn_usage_meta_sanitizes_model_name():
    """模型名要清洗：换行/NUL 不能进元数据（借鉴上游 _safe_text）。"""
    meta = tu.write_turn_usage_meta(
        "s",
        "c",
        tu.TurnUsage(),
        model_name="evil\n\x00name",
    )
    assert "\n" not in meta["model_name"]
    assert "\x00" not in meta["model_name"]


def test_reconcile_from_stats_never_raises():
    """收尾对账在请求尾部：类型垃圾进来也只能返回全 0 结构。"""
    for junk in (None, [], {}, {"prompt_tokens": "abc"}, 123):
        meta = tu.reconcile_turn_completion_from_stats(junk, model_name="m")
        assert meta["total_tokens"] == 0
    good = tu.reconcile_turn_completion_from_stats(
        {"prompt_tokens": 3, "completion_tokens": 4},
        model_name="m",
    )
    assert good["total_tokens"] == 7


# --------------------------------- 目标锁：流式 usage 取真（本轮交付项）
def test_stream_usage_kwargs_is_flag_gated_and_keyed():
    """D16：注入参数由 feature flag 与 (provider, model) 降级记忆共同决定。"""
    kwargs = tu.stream_usage_kwargs("p1", "m1")
    assert kwargs == {"stream_options": {"include_usage": True}}

    tu.remember_stream_usage_unsupported("p1", "m1")
    assert tu.stream_usage_kwargs("p1", "m1") == {}
    assert tu.stream_usage_kwargs("p1", "other") != {}


def test_stream_flag_off_means_no_injection(monkeypatch):
    """应急阀门：``COAPIS_STREAM_USAGE=0`` 时一个参数都不注入。"""
    monkeypatch.setenv("COAPIS_STREAM_USAGE", "0")
    assert tu.stream_usage_kwargs("p-flag", "m-flag") == {}


def test_wrapper_marks_interrupted_turn_for_message_meta():
    """中断即时通道：写台账与落库消息不在同一调用里，靠它接力。"""
    tu.clear_turn_interrupted("chat-x")
    assert tu.turn_was_interrupted("chat-x") is False
    tu.mark_turn_interrupted("chat-x")
    assert tu.turn_was_interrupted("chat-x") is True
    tu.clear_turn_interrupted("chat-x")
    assert tu.turn_was_interrupted("chat-x") is False


def test_turn_annotation_carries_interrupted_meta():
    """落库元数据形状（前端显示的数据源）：``metadata["interrupted"]``。"""
    runner = _runner_mod()

    class Msg:
        def __init__(self, role):
            self.role = role
            self.metadata = {}

        def get_role(self):
            return self.role

    msgs = [Msg("user"), Msg("assistant"), Msg("assistant")]
    n = runner._annotate_turn_resources(
        msgs,
        [],
        [],
        turn_interrupted=True,
    )
    assert n >= 1
    assert msgs[-1].metadata.get("interrupted") is True
    # 未中断时不得留下键（前端按"有键=中断"读）
    fresh = Msg("assistant")
    runner._annotate_turn_resources([fresh], [], [], turn_interrupted=False)
    assert "interrupted" not in fresh.metadata


def test_wrapper_injects_stream_options_only_when_streaming():
    """注入只在底层真流式时发生（OpenAI 协议：非流式带 stream_options 非法）。"""
    from agentscope.model import ChatModelBase

    from coapis.token_usage.model_wrapper import TokenRecordingModelWrapper

    class StreamModel(ChatModelBase):
        def __init__(self):
            super().__init__(model_name="m-stream", stream=True)

        async def __call__(self, **kwargs):
            raise AssertionError("不该被调用")

    class BlockModel(ChatModelBase):
        def __init__(self):
            super().__init__(model_name="m-block", stream=False)

        async def __call__(self, **kwargs):
            raise AssertionError("不该被调用")

    assert TokenRecordingModelWrapper("p", StreamModel())._with_stream_usage(
        {},
    ) == {"stream_options": {"include_usage": True}}
    assert TokenRecordingModelWrapper("p", BlockModel())._with_stream_usage({}) == {}


# ====================================================== 可用性台账面
@pytest.fixture(autouse=True)
def _isolate_store():
    """单例隔离：测试之间不能互相看见。"""
    reset_availability_store()
    yield
    reset_availability_store()


def test_availability_key_is_provider_and_model_only():
    """键的口径钉死为 (provider_id, model)（D9：不加 workspace 维度）。"""
    store = get_availability_store()
    store.record("p1", "m1", "rate_limited", "429 too many requests")
    rec = store.get("p1", "m1")
    assert rec is not None
    assert rec.provider_id == "p1" and rec.model == "m1"
    assert store.get("p1", "m2") is None


def test_availability_status_vocabulary_is_frozen():
    """状态词表冻结（借鉴上游词汇 + 我方 auth）：可变容器=两把尺子入口。"""
    assert isinstance(AVAILABILITY_STATUSES, frozenset)
    assert {"ok", "rate_limited", "timeout", "auth", "unsupported"} <= set(
        AVAILABILITY_STATUSES,
    )


def test_availability_reason_without_record_is_ok():
    """**没观测过 = 没有证据说它坏**：无记录必须返回 ok，不猜坏。"""
    assert reason_of("never-seen", "never-seen") == "ok"


def test_availability_reason_carries_status_and_detail():
    store = get_availability_store()
    store.record("p2", "m2", "timeout", "connect timeout after 15s")
    reason = store.reason_of("p2", "m2")
    assert "timeout" in reason
    assert "connect timeout" in reason


def test_availability_records_consecutive_failures():
    """连续失败计数：台账只剩坏消息时，这个数就是运维的尺子。"""
    store = get_availability_store()
    store.record("p3", "m3", "rate_limited", "429")
    store.record("p3", "m3", "rate_limited", "429")
    rec = store.get("p3", "m3")
    assert rec is not None and rec.consecutive_failures == 2
    store.record("p3", "m3", "ok")
    rec = store.get("p3", "m3")
    assert rec is not None and rec.consecutive_failures == 0


def test_availability_unknown_status_degrades_not_raises():
    """状态越界不能抛异常：台账是观测物，不能反噬聊天主链。"""
    store = get_availability_store()
    rec = store.record("p4", "m4", "totally-made-up", "raw")
    assert rec.status == "unsupported"
    assert "totally-made-up" in rec.detail


def test_availability_snapshot_filters_by_provider():
    store = get_availability_store()
    store.record("pa", "m", "ok")
    store.record("pb", "m", "auth", "bad key")
    view = store.snapshot(["pb"]).to_dict()
    assert view["count"] == 1
    assert view["items"][0]["provider_id"] == "pb"


def test_record_safe_never_raises(monkeypatch):
    """安全版记账：内部炸了也必须静默（聊天请求不能因为记账失败而失败）。"""
    store = get_availability_store()

    def boom(*a, **k):
        raise RuntimeError("store exploded")

    monkeypatch.setattr(store, "record", boom)
    record_model_result_safe("p", "m", "ok")  # 不得抛


def test_breaker_reason_of_carries_note_and_state():
    """熔断原因 = 状态 + 计数 + 最近一次原因（判官台账的 reason 数据源）。"""
    from coapis.decision.breaker import CircuitBreaker

    br = CircuitBreaker(
        failure_threshold=2,
        cooldown_s=60.0,
        enabled=True,
    )
    key = "judge:verify"
    br.record_failure(key, "hard_timeout 15.0s model=local:m")
    reason = br.reason_of(key)
    assert "failures=1" in reason
    assert "hard_timeout" in reason
    br.record_failure(key, "hard_timeout 15.0s model=local:m")
    assert "breaker=open" in br.reason_of(key)
    br.record_success(key)
    # 恢复后原因必须清空（病因不能赖在台账里）
    assert "hard_timeout" not in br.reason_of(key)


def test_retryability_and_availability_share_one_classifier():
    """分类只有一把尺子：台账状态必须来自 :func:`_classify_failure`。"""
    from coapis.providers import retry_chat_model as r

    exc = type("E", (Exception,), {})()
    exc.status_code = 429
    assert r._availability_status_from_exc(exc) == "rate_limited"
    exc500 = type("E2", (Exception,), {})()
    exc500.status_code = 500
    assert r._availability_status_from_exc(exc500) == "unavailable"


def test_retry_hook_writes_ledger_on_exhaust(monkeypatch):
    """重试耗尽时必须写台账（B1-B 验收 2 的因：429 要留下 rate_limited）。"""
    from coapis.providers import retry_chat_model as r

    calls = []

    def fake(pid, model, status, detail=""):
        calls.append((pid, model, status, detail))

    import coapis.providers.provider_model_availability as pma

    monkeypatch.setattr(pma, "record_model_result_safe", fake)
    exc = type("E", (Exception,), {})()
    exc.status_code = 429
    r._record_availability_failure("provX:modelY", exc)
    assert calls == [("provX", "modelY", "rate_limited", str(exc)[:400])]
