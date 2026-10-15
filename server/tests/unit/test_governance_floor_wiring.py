"""治理地板接线测试（片1）：工具结果超限自动截断。

覆盖 ``light_context_manager._governance_floor_truncate``——工具结果裁剪关闭时
的兜底路径，以及开启态下对「非 tool_result 超大文本块」的兜底。

对应实施方案：限制治理与文档长上下文_实施方案_20260729.md 片1
验收标准：工具结果超限自动截断；治理层缺失时不得中断对话。
"""

from __future__ import annotations

from types import SimpleNamespace

from agentscope.message import Msg

from coapis.agents.context.light_context_manager import (
    _governance_floor_truncate,
)
from coapis.governance import LimitKind, LimitLedger


def _limit(budget: int):
    ledger = LimitLedger.from_config(pruning_config=SimpleNamespace(
        pruning_recent_msg_max_bytes=budget,
        pruning_old_msg_max_bytes=budget,
    ))
    return ledger.limit(LimitKind.TOOL_RESULT_BYTES)


def _tool_result_msg(text: str) -> Msg:
    return Msg(
        name="assistant",
        role="assistant",
        content=[
            {
                "type": "tool_result",
                "id": "c1",
                "name": "execute_shell_command",
                "output": [{"type": "text", "text": text}],
            },
        ],
    )


def _plain_text_msg(text: str) -> Msg:
    return Msg(name="assistant", role="assistant", content=[{"type": "text", "text": text}])


def test_floor_truncates_oversized_tool_result() -> None:
    """裁剪关闭时的地板：超大工具结果必须被截断并留下可见说明。"""
    msg = _tool_result_msg("x" * 20_000)
    changed = _governance_floor_truncate([msg], _limit(3_000))
    assert changed == 1
    out = msg.content[0]["output"][0]["text"]
    assert len(out) < 20_000
    assert "治理层" in out  # 用户可见说明


def test_floor_leaves_small_tool_result_untouched() -> None:
    """预算内不得改动内容——地板不能变成无谓的改写。"""
    msg = _tool_result_msg("short result")
    before = msg.content[0]["output"][0]["text"]
    assert _governance_floor_truncate([msg], _limit(3_000)) == 0
    assert msg.content[0]["output"][0]["text"] == before


def test_floor_handles_string_output() -> None:
    """output 允许是裸字符串形态：必须截断并写回原字段，不得抛异常。"""
    msg = Msg(
        name="assistant",
        role="assistant",
        content=[{"type": "tool_result", "id": "c1", "name": "t", "output": "y" * 20_000}],
    )
    changed = _governance_floor_truncate([msg], _limit(3_000))
    assert changed == 1
    out = msg.content[0]["output"]
    assert isinstance(out, str) and len(out) < 20_000
    assert "治理层" in out


def test_floor_ignores_non_tool_result_blocks() -> None:
    """地板只管工具结果，不碰普通文本消息（那是压缩器的职责）。"""
    msg = _plain_text_msg("z" * 20_000)
    assert _governance_floor_truncate([msg], _limit(3_000)) == 0
    assert msg.content[0]["text"] == "z" * 20_000


def test_floor_survives_malformed_content() -> None:
    """内容结构异常（字符串 content、缺字段块）不得抛异常。"""
    msgs = [
        Msg(name="a", role="user", content="plain string"),
        Msg(name="a", role="assistant", content=[{"type": "tool_result"}]),
        Msg(name="a", role="assistant", content=[]),
    ]
    assert _governance_floor_truncate(msgs, _limit(1_000)) == 0


def test_floor_truncates_multiple_blocks_in_one_message() -> None:
    """一条消息里多个工具结果块都要处理。"""
    msg = Msg(
        name="assistant",
        role="assistant",
        content=[
            {
                "type": "tool_result",
                "id": f"c{i}",
                "name": "t",
                "output": [{"type": "text", "text": "w" * 20_000}],
            }
            for i in range(3)
        ],
    )
    assert _governance_floor_truncate([msg], _limit(2_000)) == 3
