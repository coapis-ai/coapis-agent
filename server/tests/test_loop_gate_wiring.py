# -*- coding: utf-8 -*-
"""循环闸接线测试 —— 闸链在 mixin 侧只观察、不改变现成判定行为。

对应实施方案 v1 §7.3 验收 1/2：五道门独立可测；触发按门分桶入账。
本文件专测**接线面**（mixin/react 侧），纯闸逻辑见 test_loop_gates.py。
"""
from __future__ import annotations

import inspect

import pytest

from coapis.agents.loop_gates import (
    GATE_DUPLICATE,
    GATE_EMPTY_STREAK,
    GATE_PLAN_DRIFT,
    GATE_STAGNATION,
    GATE_STOP_PHRASE,
    GATE_OSCILLATION,
    LoopGateChain,
)


def test_mixin_exposes_gate_observers():
    from coapis.agents.tool_guard_mixin import ToolGuardMixin

    for name in ("_loop_gates", "_observe_loop_dedup", "_observe_loop_round",
                 "_observe_loop_plan_drift"):
        assert hasattr(ToolGuardMixin, name), name


def test_react_exposes_gate_observers():
    from coapis.agents.react_agent import CoApisAgent

    for name in ("_observe_loop_reasoning", "_observe_loop_stop_phrase",
                 "_reset_loop_gates"):
        assert hasattr(CoApisAgent, name), name


def test_dedup_observer_counts_gates_without_raising():
    """mixin 的观察方法：闸链异常不得外泄。"""
    from coapis.agents.tool_guard_mixin import ToolGuardMixin

    obj = object.__new__(ToolGuardMixin)
    obj._loop_gate_chain = LoopGateChain(ledger_enabled=False)

    ToolGuardMixin._observe_loop_dedup(obj, "[DEDUP] 相同参数已调用过", "write_file")
    ToolGuardMixin._observe_loop_dedup(obj, "[EMPTY-STREAK] 连续空结果", "read_file")
    ToolGuardMixin._observe_loop_dedup(obj, "普通结果文本", "read_file")
    hits = obj._loop_gate_chain.hits()
    assert hits[GATE_DUPLICATE] == 1
    assert hits[GATE_EMPTY_STREAK] == 1
    assert sum(hits.values()) == 2


def test_round_observer_default_off_counts_only():
    from coapis.agents.tool_guard_mixin import ToolGuardMixin

    obj = object.__new__(ToolGuardMixin)
    obj._loop_gate_chain = LoopGateChain(ledger_enabled=False)
    for _ in range(25):
        assert ToolGuardMixin._observe_loop_round(obj, "read_file") is False
    assert obj._loop_gate_chain.round_calls() == 25
    assert obj._loop_gate_chain.round_calls() == 25


def test_round_observer_blocks_when_budget_set():
    from coapis.agents.loop_gates import GateThresholds
    from coapis.agents.tool_guard_mixin import ToolGuardMixin

    obj = object.__new__(ToolGuardMixin)
    obj._loop_gate_chain = LoopGateChain(
        ledger_enabled=False, thresholds=GateThresholds(round_budget=3),
    )
    assert ToolGuardMixin._observe_loop_round(obj, "read_file") is False
    assert ToolGuardMixin._observe_loop_round(obj, "read_file") is False
    assert ToolGuardMixin._observe_loop_round(obj, "read_file") is True
    assert obj._loop_gate_chain.hits()["round"] == 1


def test_plan_drift_observer_counts_out_of_scope():
    from coapis.agents.tool_guard_mixin import ToolGuardMixin

    class _Decision:
        approved_scope = {"paths": ["/apps/ai/x"]}

    obj = object.__new__(ToolGuardMixin)
    obj._loop_gate_chain = LoopGateChain(ledger_enabled=False)
    # 范围内 → 不计
    ToolGuardMixin._observe_loop_plan_drift(
        obj, "write_file", _Decision(), {"file_path": "/apps/ai/x/a.py"},
    )
    assert obj._loop_gate_chain.hits()[GATE_PLAN_DRIFT] == 0
    # 越界 → 计一次
    ToolGuardMixin._observe_loop_plan_drift(
        obj, "write_file", _Decision(), {"file_path": "/etc/passwd"},
    )
    assert obj._loop_gate_chain.hits()[GATE_PLAN_DRIFT] == 1
    # 无路径 → 宁漏不误伤
    ToolGuardMixin._observe_loop_plan_drift(obj, "write_file", _Decision(), {})
    assert obj._loop_gate_chain.hits()[GATE_PLAN_DRIFT] == 1


def test_gate_observers_survive_chain_failure():
    """闸链取用失败（异常）时，观察方法必须静默跳过，绝不影响主流程。"""
    from coapis.agents.tool_guard_mixin import ToolGuardMixin

    class Boom(ToolGuardMixin):
        def _loop_gates(self):
            raise RuntimeError("chain down")

    obj = Boom.__new__(Boom)
    assert ToolGuardMixin._observe_loop_round(obj, "write_file") is False
    ToolGuardMixin._observe_loop_plan_drift(obj, "write_file", None)
    ToolGuardMixin._observe_loop_dedup(obj, "[DEDUP] x", "write_file")


def test_react_reset_flushes_and_rezeros():
    from coapis.agents.react_agent import CoApisAgent

    obj = object.__new__(CoApisAgent)
    obj._request_context = {"session_id": "s1", "chat_id": "c1"}
    obj._loop_gate_chain = LoopGateChain(ledger_enabled=False)
    obj._loop_gate_chain.observe_reasoning("[LOOP-OSCILLATING] 来回切换")
    assert obj._loop_gate_chain.round_calls() == 0

    CoApisAgent._reset_loop_gates(obj)
    assert obj._loop_gate_chain.hits()[GATE_OSCILLATION] == 1
    assert obj._loop_gate_chain.session_id == "s1"
    obj._loop_gate_chain.observe_round("read_file")
    assert obj._loop_gate_chain.round_calls() == 1
    CoApisAgent._reset_loop_gates(obj)
    assert obj._loop_gate_chain.round_calls() == 0


def test_react_reasoning_observer_maps_detector_verdicts():
    from coapis.agents.react_agent import CoApisAgent

    obj = object.__new__(CoApisAgent)
    obj._loop_gate_chain = LoopGateChain(ledger_enabled=False)
    CoApisAgent._observe_loop_reasoning(obj, "continue")
    CoApisAgent._observe_loop_reasoning(obj, "force_text_only")
    CoApisAgent._observe_loop_reasoning(obj, "force_exit")
    hits = obj._loop_gate_chain.hits()
    assert hits[GATE_STAGNATION] == 2
    assert hits[GATE_OSCILLATION] == 0


def test_stop_phrase_observer_off_by_default():
    from coapis.agents.react_agent import CoApisAgent

    obj = object.__new__(CoApisAgent)
    obj._loop_gate_chain = LoopGateChain(ledger_enabled=False)
    CoApisAgent._observe_loop_stop_phrase(
        obj, "已完成，我继续写文件", ["write_file"],
    )
    assert obj._loop_gate_chain.hits()[GATE_STOP_PHRASE] == 0


def test_wiring_is_observe_only(tmp_path):
    """接线处不得携带判定逻辑：mixin 侧只允许 observe_* 调用。"""
    import coapis.agents.tool_guard_mixin as tg

    src = inspect.getsource(tg)
    for banned in ("from .loop_gates import gate_stop_phrase",
                   "gate_round_budget(", "gate_plan_drift("):
        assert banned not in src, banned
    assert src.count("_observe_loop_") >= 4


def test_react_wiring_has_no_second_judgement():
    import coapis.agents.react_agent as ra

    src = inspect.getsource(ra)
    assert "ReasoningLoopDetector" in src          # 判定仍由现成件做
    assert src.count("gate_stop_phrase(") == 0     # 不引入第二套判定
