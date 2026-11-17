"""历史回放必须带上工具结果，否则被安全闸拦下的动作在历史里显示绿色✅。

根因（2026-11-17 实测）：AgentScope 把工具结果存成 ``role="system"`` 的消息，
而 ``agentscope_msg_to_message`` 原先无条件跳过所有 system 消息——历史 API 里
``plugin_call`` 只剩 ``{call_id, name, arguments}``、``output`` 恒为 null，
前端卡片只能回落到默认 completed 状态（绿勾），被拦下的动作也在撒谎。
"""

from agentscope.message import Msg

from coapis.app.runner.utils import agentscope_msg_to_message

SENTINEL = "[[coapis:" + "tool-blocked]]"

CALL_ID = "call_block_1"


def _tool_use_block():
    return {
        "type": "tool_use",
        "id": CALL_ID,
        "name": "execute_shell_command",
        "input": {"command": "rm -rf /tmp/x"},
    }


def _tool_result_msg(text):
    return Msg(
        name="system",
        role="system",
        content=[
            {
                "type": "tool" + "_result",
                "id": CALL_ID,
                "name": "execute_shell_command",
                "output": [{"type": "text", "text": text}],
            }
        ],
    )


def _contents(messages):
    grouped = []
    for m in messages:
        grouped.append((m.type, [c.model_dump() for c in m.content]))
    return grouped


def _payload(dumped):
    """output 落库形态是块数组的 JSON 串，取出其中文本。"""
    import json

    raw = dumped["data"]["output"]
    try:
        parsed = json.loads(raw)
    except (ValueError, TypeError):
        return raw
    if isinstance(parsed, list):
        return "\n".join(
            b.get("text", "") for b in parsed if isinstance(b, dict)
        )
    return raw


def test_history_keeps_tool_result_system_message():
    """开闸后：system 消息里的工具结果必须转成 plugin_call_output 并带 output，
    且 call_id 与 plugin_call 对齐，前端 mergeToolMessages 才并得回同一张卡。"""
    messages = [
        Msg(name="assistant", role="assistant", content=[_tool_use_block()]),
        _tool_result_msg("命令执行成功"),
    ]
    grouped = _contents(
        agentscope_msg_to_message(messages, include_tool_results=True),
    )
    types = [t for t, _ in grouped]
    assert "plugin_call" in types, f"工具调用未进历史：{types}"
    assert "plugin_call_output" in types, f"工具结果未进历史：{types}"

    call = next(c for t, cs in grouped if t == "plugin_call" for c in cs)
    output = next(c for t, cs in grouped if t == "plugin_call_output" for c in cs)
    assert call["data"]["call_id"] == output["data"]["call_id"]
    assert "命令执行成功" in _payload(output)


def test_history_preserves_guard_blocked_sentinel_verbatim():
    """被拦下的工具结果，哨兵原文必须逐字进历史——前端靠它把卡片标成红色⛔，
    否则历史回放里「拦截」仍然显示绿色成功。"""
    text = SENTINEL + " kind=guard_denied\n⛔ **工具已拦截**\n\n  工具: execute_shell_command"
    messages = agentscope_msg_to_message(
        [_tool_result_msg(text)],
        include_tool_results=True,
    )
    grouped = _contents(messages)
    payload = _payload(next(c for _, cs in grouped for c in cs))
    assert SENTINEL in payload, f"哨兵丢失，前端无法识别拦截：{payload!r}"
    assert "guard_denied" in payload


def test_default_off_hides_internal_system_messages():
    """默认关闭：不带工具结果的内部 system 消息（进度小结等）仍旧不进历史，
    proactive_trigger 等调用方行为零变化。"""
    messages = [
        Msg(
            name="system",
            role="system",
            content=[{"type": "text", "text": "内部进度小结"}],
        ),
        _tool_result_msg("命令执行成功"),
    ]
    grouped = _contents(agentscope_msg_to_message(messages))
    types = [t for t, _ in grouped]
    assert "plugin_call_output" not in types
    assert "内部进度小结" not in str(grouped)


def test_flag_on_does_not_leak_plain_system_text():
    """开闸只放行「带工具结果」的 system 消息，普通 system 文本不得借道混入。"""
    messages = [
        Msg(
            name="system",
            role="system",
            content=[{"type": "text", "text": "进度小结不应出现"}],
        ),
    ]
    grouped = _contents(
        agentscope_msg_to_message(messages, include_tool_results=True),
    )
    assert grouped == [], f"纯 system 文本被放进历史：{grouped}"
