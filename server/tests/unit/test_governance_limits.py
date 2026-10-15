"""治理地基（片1）单元测试：限制单一来源 + 六档阶梯 + 截断地板。

对应实施方案：docs/03-技术方案/限制治理与文档长上下文_实施方案_20260729.md 片1
验收标准：限制集中一处、超限自动截断。
"""

from __future__ import annotations

import pytest

from coapis.governance import (
    GovernanceUnavailable,
    Limit,
    LimitKind,
    LimitLedger,
    Tier,
    choose_tier,
    ledger_for_agent,
    truncate_head_tail,
)


# ---------------------------------------------------------------------------
# 六档阶梯
# ---------------------------------------------------------------------------


def _limit(budget: int, hard: int | None = None) -> Limit:
    return Limit(
        kind=LimitKind.TOOL_RESULT_BYTES,
        budget=budget,
        hard=hard,
        source="test",
        unit="chars",
    )


@pytest.mark.parametrize(
    ("size", "expected"),
    [
        (500, Tier.L0_FULL),  # 预算内
        (1500, Tier.L1_HEAD_TAIL),  # 1.5 倍
        (5_000, Tier.L2_SEGMENTED),  # 5 倍
        (20_000, Tier.L3_SUMMARY),  # 20 倍
        (100_000, Tier.L4_SPLIT),  # 100 倍
    ],
)
def test_choose_tier_ladder(size: int, expected: Tier) -> None:
    """规模逐级放大时，档位按 L0→L1→L2→L3→L4 递进。"""
    plan = choose_tier(size, _limit(1000))
    assert plan.tier is expected


def test_choose_tier_hard_cap_refuses() -> None:
    """超过硬顶落到 L5：拒绝，但必须给出人类可执行的下一步。"""
    plan = choose_tier(50_000, _limit(1000, hard=30_000))
    assert plan.tier is Tier.L5_REFUSE
    assert plan.is_refusal
    assert plan.note  # 必须可见
    assert plan.action == "refuse_with_next_steps"


def test_choose_tier_never_raises_on_zero_budget() -> None:
    """预算为 0/负数是配置异常，治理层不得抛异常、不得除零。"""
    plan = choose_tier(10, _limit(0))
    assert plan.tier in {t for t in Tier}


def test_choose_tier_skips_split_when_not_allowed() -> None:
    """调用点无法分治时，L4 降级为 L5 并说明原因。"""
    plan = choose_tier(100_000, _limit(1000), allow_split=False)
    assert plan.tier is Tier.L5_REFUSE
    assert "无法分片" in plan.note


def test_choose_tier_full_has_no_note() -> None:
    """预算内不打扰用户：无说明、动作是 full。"""
    plan = choose_tier(10, _limit(1000))
    assert plan.is_full
    assert plan.note == ""
    assert plan.action == "full"


def test_choose_tier_negative_size_is_full() -> None:
    """规模异常（负数）按最小处理，不得报错。"""
    assert choose_tier(-5, _limit(1000)).is_full


# ---------------------------------------------------------------------------
# 截断地板（接入现成截断函数）
# ---------------------------------------------------------------------------


def test_truncate_head_tail_passthrough_under_budget() -> None:
    text = "a" * 100
    assert truncate_head_tail(text, 200) == text


def test_truncate_head_tail_keeps_both_ends() -> None:
    """截断后必须同时保留头部与尾部内容，并标注省略规模。"""
    text = "HEAD" + "x" * 10_000 + "TAIL"
    out = truncate_head_tail(text, 500)
    assert len(out) < len(text)
    assert out.startswith("HEAD")
    assert "TAIL" in out


def test_truncate_head_tail_empty_safe() -> None:
    assert truncate_head_tail("", 100) == ""


def test_truncate_head_tail_zero_budget_safe() -> None:
    """预算为 0 不得清空内容（至少保留 1 字符），不得抛异常。"""
    out = truncate_head_tail("abc", 0)
    assert len(out) >= 1


# ---------------------------------------------------------------------------
# 限制单一来源
# ---------------------------------------------------------------------------


class _Ctx:
    max_input_length = 100_000
    reserve_ratio = 0.2
    max_compact_message_bytes = 40_000


class _Prune:
    pruning_recent_msg_max_bytes = 3_000
    pruning_old_msg_max_bytes = 1_000


class _Running:
    max_iters = 40


def test_ledger_from_config_reads_all_kinds() -> None:
    """台账必须把配置里的限制一处读全，出处可追溯。"""
    ledger = LimitLedger.from_config(
        running_config=_Running(),
        context_config=_Ctx(),
        pruning_config=_Prune(),
    )
    assert ledger.limit(LimitKind.CONTEXT_TOKENS).budget == 80_000
    assert ledger.limit(LimitKind.TOOL_RESULT_BYTES).budget == 3_000
    assert ledger.limit(LimitKind.ROUNDS).budget == 40
    assert "tool_result_pruning" in ledger.limit(LimitKind.TOOL_RESULT_BYTES).source


def test_ledger_missing_config_does_not_raise() -> None:
    """配置缺失是常态：台账构建不得抛异常，缺的类别不登记。"""
    ledger = LimitLedger.from_config()
    with pytest.raises(GovernanceUnavailable):
        ledger.limit(LimitKind.TOOL_RESULT_BYTES)


def test_ledger_budget_of_falls_back() -> None:
    """薄接线场景：台账缺类别时取默认值，不抛异常。"""
    ledger = LimitLedger.from_config()
    assert ledger.budget_of(LimitKind.TOOL_RESULT_BYTES, 1234) == 1234


def test_ledger_records_and_reports_remaining() -> None:
    ledger = LimitLedger.from_config(running_config=_Running())
    rounds = ledger.limit(LimitKind.ROUNDS)
    assert rounds.hard == 40
    ledger.record(LimitKind.ROUNDS, 15)
    assert ledger.remaining(LimitKind.ROUNDS) == 25
    ledger.record(LimitKind.ROUNDS, 30)
    assert ledger.remaining(LimitKind.ROUNDS) == 0  # 不得为负


def test_ledger_explain_is_human_readable() -> None:
    ledger = LimitLedger.from_config(pruning_config=_Prune())
    text = ledger.explain(LimitKind.TOOL_RESULT_BYTES)
    assert "3000" in text and "tool_result_pruning" in text


def test_ledger_for_agent_caches_by_config_identity() -> None:
    """同一配置对象复用同一台账实例，避免每轮重建。"""
    run, ctx, prune = _Running(), _Ctx(), _Prune()
    assert ledger_for_agent(run, ctx, prune) is ledger_for_agent(run, ctx, prune)
    assert ledger_for_agent(run, ctx, _Prune()) is not ledger_for_agent(run, ctx, prune)


def test_ledger_reset_clears_usage() -> None:
    ledger = LimitLedger.from_config(running_config=_Running())
    ledger.record(LimitKind.ROUNDS, 5)
    ledger.reset()
    assert ledger.remaining(LimitKind.ROUNDS) == 40
