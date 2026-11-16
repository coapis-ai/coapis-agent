# -*- coding: utf-8 -*-
"""循环闸（loop gates）单测 —— 每门独立可测 + 分桶计数 + 台账节流。

对应实施方案 v1 §7.3 验收 1/2：五道门每门独立单测；触发次数按门分桶
写进台账（岗位 loop_gate，purpose=闸码）。
"""
from __future__ import annotations

import pytest

from coapis.agents.loop_gates import (
    GATE_CODES,
    GATE_DUP_GLOBAL,
    GATE_DUPLICATE,
    GATE_EMPTY_STREAK,
    GATE_LABELS,
    GATE_OSCILLATION,
    GATE_PLAN_DRIFT,
    GATE_STAGNATION,
    GATE_STRATEGY,
    GATE_STOP_PHRASE,
    GATE_ROUND_BUDGET,
    LEDGER_SOURCE,
    GateThresholds,
    LoopGateChain,
    attribute_dedup,
    attribute_reasoning,
    gate_plan_drift,
    gate_round_budget,
    gate_stop_phrase,
)


# ---------------------------------------------------------------- 归因（纯函数）
def test_attribute_dedup_covers_all_real_markers():
    cases = [
        ("[TOOL-GUARD] 工具 'x' 已连续调用 3 次", GATE_DUPLICATE, "hint"),
        ("[DEDUP] 工具 'x' 相同参数已调用过", GATE_DUPLICATE, "block"),
        ("[DEDUP-GLOBAL] 工具 'x' 参数变形重复", GATE_DUP_GLOBAL, "block"),
        ("[策略阻断] 工具 'x' 连续 3 次调用均未产生有效结果", GATE_STRATEGY, "block"),
        ("[策略提示] 工具 'x' 连续调用", GATE_STRATEGY, "hint"),
        ("[EMPTY-STREAK] 工具 'x' 连续 2 次调用均返回空结果", GATE_EMPTY_STREAK, "block"),
    ]
    for text, gate, action in cases:
        got_gate, got_action = attribute_dedup(text)
        assert got_gate == gate, text
        assert got_action == action, text


def test_attribute_dedup_unknown_returns_observe():
    assert attribute_dedup("") == ("", "observe")
    assert attribute_dedup("普通工具结果") == ("", "observe")
    assert attribute_dedup(None) == ("", "observe")


def test_attribute_reasoning_markers():
    assert attribute_reasoning("[FORCE-EXIT] 思考已停滞") == (GATE_STAGNATION, "finalize")
    assert attribute_reasoning("[LOOP-STAGNANT] 思考重复") == (GATE_STAGNATION, "force_text_only")
    assert attribute_reasoning("[LOOP-OSCILLATING] 来回切换") == (GATE_OSCILLATION, "force_text_only")
    assert attribute_reasoning("正常思考") == ("", "observe")


# ---------------------------------------------------------------- 停止句门
def test_stop_phrase_hits_write_tools_only():
    assert gate_stop_phrase("已完成，我来写个文件", "write_file") is True
    assert gate_stop_phrase("任务完成", "execute_shell_command") is True
    assert gate_stop_phrase("The task is completed", "edit_file") is True


def test_stop_phrase_ignores_read_tools_and_empty():
    assert gate_stop_phrase("已完成", "read_file") is False
    assert gate_stop_phrase("", "write_file") is False
    assert gate_stop_phrase("我还在分析", "write_file") is False


def test_stop_phrase_gate_off_by_default(monkeypatch):
    # 默认关（灰度口径）：环境变量未设时档位为 off
    monkeypatch.delenv("COAPIS_LOOP_GATE_STOP_PHRASE", raising=False)
    assert GateThresholds.from_env().stop_phrase_mode == "off"
    chain = LoopGateChain(ledger_enabled=False)
    assert chain.observe_stop_phrase("已完成", tool_name="write_file") is None


def test_stop_phrase_shadow_records_but_does_not_block(monkeypatch):
    """shadow 档：命中要入账（否则攒不出点亮依据），但 action 不是阻断动作。"""
    monkeypatch.delenv("COAPIS_LOOP_GATE_STOP_PHRASE", raising=False)
    chain = LoopGateChain(
        thresholds=GateThresholds(stop_phrase_mode="shadow"),
        ledger_enabled=False,
    )
    verdict = chain.observe_stop_phrase("已完成", tool_name="write_file")
    assert verdict is not None
    assert verdict.action == "observe"
    # enforce 才是禁写动作；两档的差别只在 action，不在"要不要记一笔"。
    hard = LoopGateChain(
        thresholds=GateThresholds(stop_phrase_mode="enforce"),
        ledger_enabled=False,
    )
    got = hard.observe_stop_phrase("已完成", tool_name="write_file")
    assert got is not None and got.action == "force_text_only"


def test_stop_phrase_mode_ignores_garbage(monkeypatch):
    """档位写错时熄火：灰度期宁可没数据，也不能因拼错字符串判死写操作。"""
    chain = LoopGateChain(
        thresholds=GateThresholds(stop_phrase_mode="shaddow"),
        ledger_enabled=False,
    )
    assert chain.observe_stop_phrase("已完成", tool_name="write_file") is None


def test_effective_lets_hub_override_env_but_not_default_value(monkeypatch):
    """A2 验收：hub 配过的值能盖 env；hub 停在默认值时不能把 env 静音。"""
    from coapis.decision.config import DecisionHubConfig

    monkeypatch.setenv("COAPIS_LOOP_GATE_STAGNANT", "7")
    # hub 未配置该键（值仍是 DEFAULTS 的 5）→ 保留 env 的 7
    hub_plain = DecisionHubConfig.from_dict({"posts": {}})
    assert GateThresholds.effective(hub_plain).stagnation_similarity == 7
    # hub 显式配了 3（离开了默认值）→ 压在 env 之上
    hub_wired = DecisionHubConfig.from_dict(
        {"loop_gate_stagnant": 3, "loop_gate_stop_phrase_mode": "shadow",
         "posts": {}},
    )
    eff = GateThresholds.effective(hub_wired)
    assert eff.stagnation_similarity == 3
    assert eff.stop_phrase_mode == "shadow"
    # hub=None 等价纯 env，且不碰配置文件
    assert GateThresholds.effective().stagnation_similarity == 7


def test_stop_phrase_env_switch_still_means_enforce(monkeypatch):
    """旧旋钮 COAPIS_LOOP_GATE_STOP_PHRASE=1 继续有效，语义 = enforce。"""
    monkeypatch.setenv("COAPIS_LOOP_GATE_STOP_PHRASE", "1")
    assert GateThresholds.from_env().stop_phrase_mode == "enforce"


# ---------------------------------------------------------------- 预算门
def test_round_budget_gate_threshold_semantics():
    assert gate_round_budget(3, 0) is False       # 0 = 不拦
    assert gate_round_budget(3, 5) is False
    assert gate_round_budget(5, 5) is True
    assert gate_round_budget(9, 5) is True


def test_round_budget_chain_counts_and_hits_once_budget_set():
    chain = LoopGateChain(ledger_enabled=False, thresholds=GateThresholds(round_budget=3))
    assert chain.observe_round() is None
    assert chain.observe_round() is None
    verdict = chain.observe_round()
    assert verdict is not None and verdict.gate == GATE_ROUND_BUDGET
    assert verdict.action == "finalize"
    assert chain.round_calls() == 3
    chain.new_round()
    assert chain.round_calls() == 0


def test_round_budget_chain_default_off():
    chain = LoopGateChain(ledger_enabled=False)
    for _ in range(30):
        assert chain.observe_round() is None
    assert chain.round_calls() == 30


# ---------------------------------------------------------------- 计划范围门
def test_plan_drift_gate_semantics():
    assert gate_plan_drift(None, "write_file", "/a/b") is False
    assert gate_plan_drift({}, "write_file", "/a/b") is False
    assert gate_plan_drift({"paths": []}, "write_file", "/a/b") is False
    assert gate_plan_drift({"paths": ["/apps/ai/x"]}, "write_file", "/apps/ai/x/f.py") is False
    assert gate_plan_drift({"paths": ["/apps/ai/x"]}, "write_file", "/etc/passwd") is True
    assert gate_plan_drift({"paths": ["/apps/ai/x"]}, "write_file", "") is False


def test_plan_drift_chain_hit():
    chain = LoopGateChain(ledger_enabled=False)
    assert chain.observe_plan_drift({"paths": ["/apps/ai/x"]}, path="/etc/y") is None or True
    verdict = chain.observe_plan_drift({"paths": ["/apps/ai/x"]}, path="/etc/y")
    assert verdict is not None
    assert verdict.gate == GATE_PLAN_DRIFT and verdict.action == "block"


# ---------------------------------------------------------------- 分桶计数
def test_hits_bucket_per_gate():
    chain = LoopGateChain(ledger_enabled=False)
    chain.observe_dedup("[DEDUP] 相同参数已调用过", tool_name="write_file")
    chain.observe_dedup("[DEDUP] 相同参数已调用过", tool_name="write_file")
    chain.observe_dedup("[EMPTY-STREAK] 连续空结果", tool_name="read_file")
    chain.observe_reasoning("[LOOP-STAGNANT] 思考重复")
    hits = chain.hits()
    assert hits[GATE_DUPLICATE] == 2
    assert hits[GATE_EMPTY_STREAK] == 1
    assert hits[GATE_STAGNATION] == 1
    assert hits[GATE_OSCILLATION] == 0
    assert chain.total_hits() == 4
    assert set(hits) == set(GATE_CODES)


def test_labels_cover_every_gate_code():
    for code in GATE_CODES:
        assert code in GATE_LABELS and GATE_LABELS[code]


# ---------------------------------------------------------------- 台账落点
def test_ledger_one_row_per_trigger_by_default(monkeypatch):
    """默认粒度 1：每次触发明细一行，治理页读到的就是真实触发次数。"""
    rows: list[dict] = []

    def fake_write_ledger(**kwargs):
        rows.append(kwargs)
        return True

    monkeypatch.setattr(
        "coapis.decision.ledger_contract.write_ledger", fake_write_ledger,
    )
    chain = LoopGateChain(ledger_enabled=True, session_id="s1", chat_id="c1",
                          user_id="u1", agent_id="a1")
    for _ in range(5):
        chain.observe_dedup("[DEDUP] 相同参数已调用过", tool_name="write_file")
    assert len(rows) == 5, rows
    row = rows[0]
    assert row["source"] == LEDGER_SOURCE == "loop_gate"
    assert row["purpose"] == GATE_DUPLICATE
    assert row["hit_layer"] == "rule"
    assert GATE_LABELS[GATE_DUPLICATE] in row["reason"]
    assert row["session_id"] == "s1" and row["chat_id"] == "c1"
    # 已写平，收尾无补记
    assert chain.flush() == 0
    assert len(rows) == 5


def test_ledger_throttle_groups_at_env_granularity(monkeypatch):
    """节流粒度 >1：每门每 N 次一行；未满阈值的门由 flush 补记。"""
    import coapis.agents.loop_gates as mod

    monkeypatch.setattr(mod, "_LEDGER_EVERY", 3)
    rows: list[dict] = []

    def fake_write_ledger(**kwargs):
        rows.append(kwargs)
        return True

    monkeypatch.setattr(
        "coapis.decision.ledger_contract.write_ledger", fake_write_ledger,
    )
    chain = LoopGateChain(ledger_enabled=True, session_id="s1")
    for _ in range(7):
        chain.observe_dedup("[DEDUP] 相同参数已调用过", tool_name="write_file")
    assert len(rows) == 2, rows          # 第 3、第 6 次各一行
    assert all(r["purpose"] == GATE_DUPLICATE for r in rows)
    # 未达阈值的门（dup 余 1、oscillate 1 次）在 flush 时全部补记
    chain.observe_reasoning("[LOOP-OSCILLATING] 来回切换")
    assert len(rows) == 2
    assert chain.flush() == 2
    assert len(rows) == 4
    assert [r["purpose"] for r in rows[2:]] == [GATE_DUPLICATE, GATE_OSCILLATION]
    # 补记后账面写平，二次收尾不重复写
    assert chain.flush() == 0


def test_ledger_write_failure_never_raises(monkeypatch):
    def boom(**kwargs):
        raise RuntimeError("db down")

    monkeypatch.setattr("coapis.decision.ledger_contract.write_ledger", boom)
    chain = LoopGateChain(ledger_enabled=True)
    for _ in range(7):
        v = chain.observe_dedup("[DEDUP] x", tool_name="write_file")
        assert v is not None
    assert chain.hits()[GATE_DUPLICATE] == 7


def test_ledger_disabled_writes_nothing(monkeypatch):
    calls: list[dict] = []
    monkeypatch.setattr(
        "coapis.decision.ledger_contract.write_ledger",
        lambda **kw: calls.append(kw) or True,
    )
    chain = LoopGateChain(ledger_enabled=False)
    for _ in range(20):
        chain.observe_dedup("[DEDUP] x")
    chain.flush()
    assert calls == []


# ---------------------------------------------------------------- 阈值口径
def test_thresholds_defaults_match_existing_hardcoded_constants():
    """D9：阈值配置化后默认值必须与现常量逐字一致，否则行为会变。"""
    from coapis.agents.utils.tool_call_guard import (
        _EXACT_DEDUP_THRESHOLD,
        _EMPTY_RESULT_BLOCK,
        _REASONING_SIMILAR_THRESHOLD,
        _REASONING_FORCE_EXIT,
        _SESSION_WARN,
    )
    monkey_none = GateThresholds.from_env()
    assert monkey_none.exact_dedup == _EXACT_DEDUP_THRESHOLD
    assert monkey_none.empty_streak == _EMPTY_RESULT_BLOCK
    assert monkey_none.session_warn == _SESSION_WARN
    assert monkey_none.stagnation_similarity == _REASONING_SIMILAR_THRESHOLD
    assert monkey_none.stagnation_force_exit == _REASONING_FORCE_EXIT


def test_thresholds_env_override(monkeypatch):
    monkeypatch.setenv("COAPIS_LOOP_GATE_DEDUP", "4")
    monkeypatch.setenv("COAPIS_LOOP_GATE_STAGNANT", "9")
    cfg = GateThresholds.from_env()
    assert cfg.exact_dedup == 4
    assert cfg.stagnation_similarity == 9


def test_gate_verdict_blocking_actions():
    chain = LoopGateChain(ledger_enabled=False)
    v = chain.observe_dedup("[DEDUP] x")
    assert v.is_blocking is True
    v2 = chain.observe_dedup("[TOOL-GUARD] 连续调用")
    assert v2.is_blocking is False
    assert v2.gate == GATE_DUPLICATE
