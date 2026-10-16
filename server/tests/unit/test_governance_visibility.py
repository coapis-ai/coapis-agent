# -*- coding: utf-8 -*-
"""Tests for 治理片3：失败签名 + 停止原因透出。"""

from coapis.governance.visibility import (
    FailureKind,
    FailureLedger,
    StopLedger,
    StopReason,
    classify_failure,
    get_stop_ledger,
    signature_of_result,
)


def _result(name: str, text: str) -> dict:
    return {
        "type": "tool_result",
        "id": "t1",
        "name": name,
        "output": [{"type": "text", "text": text}],
    }


# ---------------------------------------------------------------------------
# 失败识别
# ---------------------------------------------------------------------------


def test_success_output_is_not_a_failure() -> None:
    assert signature_of_result(_result("read_file", "ok\nfile content")) is None


def test_plain_content_is_not_a_failure() -> None:
    assert signature_of_result(_result("read_file", "# 标题\n正文")) is None


def test_error_prefix_is_a_failure() -> None:
    sig = signature_of_result(_result("read_file", "Error: no such file: /tmp/a.md"))
    assert sig is not None
    assert sig.kind is FailureKind.NOT_FOUND
    assert sig.tool == "read_file"


def test_traceback_is_a_failure() -> None:
    text = (
        "Traceback (most recent call last):\n"
        '  File "x.py", line 1\nModuleNotFoundError: No module named "docx"'
    )
    sig = signature_of_result(_result("execute_shell_command", text))
    assert sig is not None
    assert sig.kind is FailureKind.DEPENDENCY


def test_classify_covers_main_kinds() -> None:
    cases = {
        "permission denied": FailureKind.PERMISSION,
        "HTTP 401 Unauthorized": FailureKind.AUTH,
        "request timed out": FailureKind.TIMEOUT,
        "input exceeds the maximum context length": FailureKind.SIZE,
        "unsupported file format": FailureKind.FORMAT,
        "command not found: pandoc": FailureKind.DEPENDENCY,
        "connection refused": FailureKind.NETWORK,
        "429 Too Many Requests": FailureKind.RATE_LIMIT,
        "operation cancelled by user": FailureKind.CANCELLED,
        "完全看不出类别的输出": FailureKind.UNKNOWN,
    }
    for text, expected in cases.items():
        assert classify_failure("tool", text) is expected, text


def test_fingerprint_ignores_volatile_target() -> None:
    """同一形状的失败（只换了文件）必须归成一个签名。"""
    a = signature_of_result(_result("read_file", "Error: no such file: /tmp/a.md"))
    b = signature_of_result(_result("read_file", "Error: no such file: /tmp/b.md"))
    assert a is not None and b is not None
    assert a == b


def test_fingerprint_separates_different_kinds() -> None:
    a = signature_of_result(_result("read_file", "Error: no such file: /tmp/a.md"))
    b = signature_of_result(_result("read_file", "Error: permission denied: /tmp/a.md"))
    assert a is not None and b is not None
    assert a.kind is not b.kind


# ---------------------------------------------------------------------------
# 失败台账 + 阶梯
# ---------------------------------------------------------------------------


def test_first_failure_does_not_escalate() -> None:
    ledger = FailureLedger()
    sig = signature_of_result(_result("read_file", "Error: no such file: /tmp/a.md"))
    assert sig is not None
    ledger.record(sig, "Error: no such file: /tmp/a.md")
    assert ledger.ladder_for(sig) is None


def test_repeated_failure_escalates_through_tiers() -> None:
    ledger = FailureLedger()
    sig = signature_of_result(_result("read_file", "Error: no such file: /tmp/a.md"))
    assert sig is not None
    tiers = []
    for _ in range(4):
        ledger.record(sig, "Error: no such file")
        plan = ledger.ladder_for(sig)
        tiers.append(None if plan is None else plan.tier)
    assert tiers[0] is None
    assert tiers[1] is not None and tiers[1].value.startswith("L1")
    assert tiers[2] is not None and tiers[2].value.startswith("L3")
    assert tiers[3] is not None and tiers[3].value.startswith("L5")


def test_escalation_note_names_the_next_step() -> None:
    ledger = FailureLedger()
    sig = signature_of_result(
        _result("read_file", "Error: file too large: /tmp/big.md"),
    )
    assert sig is not None
    for _ in range(2):
        ledger.record(sig, "too large")
    plan = ledger.ladder_for(sig)
    assert plan is not None
    assert "分段" in plan.note
    assert "2 次" in plan.reason


def test_context_note_is_prefixed_for_the_model() -> None:
    ledger = FailureLedger()
    sig = signature_of_result(_result("read_file", "Error: no such file: /tmp/a.md"))
    assert sig is not None
    for _ in range(2):
        ledger.record(sig, "x")
    plan = ledger.ladder_for(sig)
    assert plan is not None
    assert ledger.render_context_note(plan).startswith("[治理提示]")


def test_summary_sorts_by_repeats() -> None:
    ledger = FailureLedger()
    hot = signature_of_result(_result("read_file", "Error: no such file: /tmp/a.md"))
    cold = signature_of_result(_result("web_fetch", "Error: connection refused"))
    assert hot is not None and cold is not None
    for _ in range(3):
        ledger.record(hot, "x")
    ledger.record(cold, "x")
    top = ledger.summary()[0]
    assert top.signature == hot
    assert top.count == 3


# ---------------------------------------------------------------------------
# 停止原因
# ---------------------------------------------------------------------------


def test_completed_run_renders_nothing() -> None:
    assert StopLedger().render() == ""


def test_max_iterations_is_visible_to_the_user() -> None:
    ledger = StopLedger()
    ledger.set_reason(StopReason.MAX_ITERATIONS)
    text = ledger.render()
    assert "轮次上限" in text
    assert "尚未完成" in text


def test_first_non_normal_reason_wins() -> None:
    """真实终止原因只记第一个：后续覆盖会把"轮次耗尽"洗成"取消"。"""
    ledger = StopLedger()
    ledger.set_reason(StopReason.MAX_ITERATIONS)
    ledger.set_reason(StopReason.COMPLETED)
    assert ledger.reason is StopReason.MAX_ITERATIONS


def test_every_reason_has_a_readable_note() -> None:
    for reason in StopReason:
        if reason is StopReason.COMPLETED:
            continue
        assert StopLedger(reason=reason).render().strip(), reason


def test_notes_are_deduped() -> None:
    ledger = StopLedger()
    ledger.set_reason(StopReason.LOOP_GUARD)
    ledger.add_note("已拦下重复调用")
    ledger.add_note("已拦下重复调用")
    assert ledger.render().count("已拦下重复调用") == 1


def test_stop_ledger_is_per_agent_and_stable() -> None:
    class _Agent:
        pass

    agent = _Agent()
    first = get_stop_ledger(agent)
    first.set_reason(StopReason.ACTION_GATE)
    assert get_stop_ledger(agent) is first
    assert "授权" in first.render()
