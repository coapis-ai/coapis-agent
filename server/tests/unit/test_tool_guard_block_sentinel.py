"""拦截态下发契约 · 被拦下的工具不许在界面里显示成成功.

钉住小蜜蜂 2026-11-17 提的两条尾巴：
  尾巴1：动作被拦下（其实没执行），工具卡却显示绿色✅ —— 界面在撒谎；
  尾巴2：拦下之后用户看不到任何说明，只剩一个「深度思考」块。

工具结果一路到前端只剩一条 ``output`` 文本（``FunctionCallOutput`` 没有 error
位），所以"被拦下"这个事实只能随文本下发。本文件锁住这层契约：

  * 控制台/网页通道：输出首行带 ``[[coapis:tool-blocked]] kind=...`` 哨兵，
    kind 能区分「方案未确认」和「通用安全拦截」；
  * IM 通道（企微等）：输出保持干净，不许漏机器标记。
"""

from __future__ import annotations

import pytest

from coapis.agents.tool_guard_mixin import (
    GUARD_BLOCK_KIND_DENIED,
    GUARD_BLOCK_KIND_PLAN_PENDING,
    GUARD_BLOCK_SENTINEL,
    ToolGuardMixin,
    _guard_block_kind,
)
from coapis.security.tool_guard.models import (
    GuardFinding,
    GuardSeverity,
    GuardThreatCategory,
    ToolGuardResult,
)


def _finding(rule_id: str, guardian: str) -> GuardFinding:
    return GuardFinding(
        id="f-1",
        rule_id=rule_id,
        category=GuardThreatCategory.COMMAND_INJECTION,
        severity=GuardSeverity.HIGH,
        title="危险命令",
        description="该动作被安全规则拦下",
        tool_name="execute_shell_command",
        guardian=guardian,
    )


def _result(*findings: GuardFinding) -> ToolGuardResult:
    return ToolGuardResult(
        tool_name="execute_shell_command",
        params={"command": "rm -rf /tmp/plan-scope-probe"},
        findings=list(findings),
    )


class _StubMemory:
    def __init__(self) -> None:
        self.added: list = []

    async def add(self, msg) -> None:
        self.added.append(msg)


class _StubAgent(ToolGuardMixin):
    """最小可跑通 ``_acting_auto_denied`` 的桩：只记录下发内容。"""

    def __init__(self, channel: str) -> None:
        self._request_context = {
            "channel": channel,
            "session_id": "sess-1",
            "user_id": "u1",
        }
        self._guard_agent_name = "CoApis"
        self._tool_guard_lang = "zh"
        self._tool_guard_policy_denied_tools: list = []
        self.printed: list = []
        self.memory = _StubMemory()

    async def print(self, msg, last: bool = True) -> None:
        self.printed.append(msg)


def _blocked_text(agent: _StubAgent) -> str:
    assert agent.printed, "被拦下的工具结果必须下发到界面"
    block = agent.printed[0].content[0]
    output = block.get("output") or []
    if isinstance(output, str):
        return output
    return "\n".join(str(seg.get("text", "")) for seg in output)


# ---------------------------------------------------------------------------
# kind 归一
# ---------------------------------------------------------------------------


def test_plan_scope_finding_maps_to_plan_pending() -> None:
    gr = _result(_finding("PLAN_SCOPE_PENDING", "plan_scope"))
    assert _guard_block_kind(gr) == GUARD_BLOCK_KIND_PLAN_PENDING


def test_other_guardian_maps_to_generic_denied() -> None:
    gr = _result(_finding("RULE_X", "input_guard_engine"))
    assert _guard_block_kind(gr) == GUARD_BLOCK_KIND_DENIED


def test_kind_normalization_never_raises() -> None:
    assert _guard_block_kind(None) == GUARD_BLOCK_KIND_DENIED


# ---------------------------------------------------------------------------
# 下发契约
# ---------------------------------------------------------------------------


async def test_console_channel_carries_sentinel_with_reason() -> None:
    agent = _StubAgent("console")
    await agent._acting_auto_denied(
        tool_call={"id": "c1", "name": "execute_shell_command", "input": {}},
        tool_name="execute_shell_command",
        guard_result=_result(_finding("PLAN_SCOPE_PENDING", "plan_scope")),
    )
    text = _blocked_text(agent)
    first_line = text.splitlines()[0]
    assert first_line.startswith(GUARD_BLOCK_SENTINEL)
    assert f"kind={GUARD_BLOCK_KIND_PLAN_PENDING}" in first_line
    # 哨兵之后仍要有人话原因，供 IM/日志等不渲染卡片的消费方使用
    assert "拦截" in text or "拦" in text


async def test_im_channel_output_stays_clean() -> None:
    agent = _StubAgent("wecom")
    await agent._acting_auto_denied(
        tool_call={"id": "c1", "name": "execute_shell_command", "input": {}},
        tool_name="execute_shell_command",
        guard_result=_result(_finding("RULE_X", "input_guard_engine")),
    )
    text = _blocked_text(agent)
    assert GUARD_BLOCK_SENTINEL not in text
    assert "coapis:tool-blocked" not in text
