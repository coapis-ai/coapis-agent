"""B2 中断收口：取消的轮次不许留下悬空 tool_use。

锁定的行为（实施方案 §6 B2-A）：
  1. 有 tool_use 无 tool_result → close_dangling_tool_calls 返回闭合消息，
     每个悬空调用一条 tool_result，文案含"已中断"。
  2. 已在后续消息里给出结果的调用 **不得** 被二次闭合。
  3. 无悬空 → 返回空列表（正常轮次零改动）。
  4. 闭合消息带 metadata.interrupted=True 与 cancellation_reason。
"""

from __future__ import annotations

from agentscope.message import Msg

from coapis.agents.utils.tool_message_utils import (
    INTERRUPT_REASONS,
    close_dangling_tool_calls,
    find_dangling_tool_calls,
)


def _assistant_with_tool_use(call_ids: list[str]) -> Msg:
    return Msg(
        name="assistant",
        role="assistant",
        content=[
            {
                "type": "tool_use",
                "id": cid,
                "name": "Bash",
                "input": {"command": "echo hi"},
            }
            for cid in call_ids
        ],
    )


def _system_with_results(call_ids: list[str]) -> Msg:
    return Msg(
        name="system",
        role="system",
        content=[
            {
                "type": "tool_result",
                "id": cid,
                "name": "Bash",
                "output": [{"type": "text", "text": "ok"}],
            }
            for cid in call_ids
        ],
    )


def test_dangling_detection_finds_unanswered_calls():
    msgs = [_assistant_with_tool_use(["call_a", "call_b"])]
    dangling = find_dangling_tool_calls(msgs)
    assert {d["id"] for d in dangling} == {"call_a", "call_b"}


def test_closure_closes_every_dangling_call():
    msgs = [_assistant_with_tool_use(["call_a", "call_b"])]
    closures = close_dangling_tool_calls(msgs, reason="user_cancel")
    assert len(closures) == 1
    blocks = closures[0].content
    assert len(blocks) == 2
    assert {b["id"] for b in blocks} == {"call_a", "call_b"}
    for block in blocks:
        assert block["type"] == "tool_result"
        assert "已中断" in block["output"][0]["text"]
    meta = closures[0].metadata
    assert meta["interrupted"] is True
    assert meta["cancellation_reason"] == "user_cancel"


def test_closure_does_not_double_close_answered_calls():
    # call_a was answered in a later message; call_b is the one left hanging.
    msgs = [
        _assistant_with_tool_use(["call_a", "call_b"]),
        _system_with_results(["call_a"]),
    ]
    assert {d["id"] for d in find_dangling_tool_calls(msgs)} == {"call_b"}
    closures = close_dangling_tool_calls(msgs)
    ids = {b["id"] for m in closures for b in m.content}
    assert ids == {"call_b"}


def test_closure_is_empty_when_turn_is_complete():
    msgs = [
        _assistant_with_tool_use(["call_a"]),
        _system_with_results(["call_a"]),
    ]
    assert close_dangling_tool_calls(msgs) == []


def test_reason_vocabulary_is_stable():
    # 前端按这三个字面量出文案，改名等于历史对不上。
    assert set(INTERRUPT_REASONS) == {"user_cancel", "timeout", "budget"}


def test_closure_survives_non_list_content():
    # Plain-string messages must not crash the sweep.
    msgs = [Msg(name="user", role="user", content="hello")]
    assert close_dangling_tool_calls(msgs) == []
