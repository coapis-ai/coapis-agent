"""沙箱掺水回归锁 —— 拒绝/放行必须按**结果**分，不按事件名分。

实锤根因（2026-11-15 核验 dev 审计链）：治理事件的兜底映射写的是

    if "sandbox" in event_type or "path" in event_type or "command" in event_type:
        return "sandbox_denied"

于是事件名里带 command/path/sandbox 的**放行**记录（沙箱检查通过、路径
校验通过）全部落进沙箱拒绝桶。dev 实测：1810 条放行里混着 213 条真拒绝，
看板上的"沙箱拦截率"是掺水数字 —— 这种数字会让人以为防线在工作，
实际是在给假的安全感。
"""

from __future__ import annotations

from coapis.governance.events import classify_audit_event


def _classify(event_type: str, result: str, tool: str | None = None):
    """返回归类桶名（``classify_audit_event`` 返回 dict，桶在 kind 里）。"""
    meta = {"tool": tool} if tool is not None else {}
    got = classify_audit_event(
        {
            "ts": 1.0,
            "channel": "console",
            "event_type": event_type,
            "result": result,
            # 契约字段名：分类函数读的是 metadata（不是 meta）。
            "metadata": meta,
        }
    )
    return got.get("kind") if isinstance(got, dict) else got


def test_sandbox_check_pass_is_not_a_denial():
    """沙箱检查通过 ≠ 沙箱拒绝（放行不得进拒绝桶）。"""
    for etype in ("sandbox_check", "path_check", "command_check"):
        got = _classify(etype, "allow", tool="Bash")
        assert got != "sandbox_denied", f"{etype} 放行被算成沙箱拒绝"


def test_named_denial_still_counts_as_sandbox_denied():
    """真拒绝照收：结果码说它是沙箱拒绝，才算。"""
    assert (
        _classify("tool_execution", "denied_by_policy(sandbox)", tool="Bash")
        == "sandbox_denied"
    )
    assert (
        _classify("sandbox", "denied:sandbox_violation", tool="Bash")
        == "sandbox_denied"
    )


def test_tool_denied_is_not_sandbox_denied():
    """策略拒绝（非沙箱）不得混进沙箱桶 —— 两类拒绝的修法不同。"""
    assert (
        _classify("tool_execution", "denied_by_policy(toy_approval)", tool="Bash")
        == "tool_denied"
    )


def test_allowed_events_land_in_tool_bucket_not_denial():
    """放行事件（有工具对象）归 tool 桶。"""
    assert _classify("command_check", "allow", tool="Bash") == "tool"
    assert _classify("path_check", "allowed", tool="read_file") == "tool"
