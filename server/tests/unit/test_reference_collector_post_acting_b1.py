# -*- coding: utf-8 -*-
"""post_acting 采集取数的真实来源：memory 尾部的 tool_result 块。

盯三件事：

1. **agentscope 的 `_acting` 对普通工具返回 None**，钩子拿到的 output 恒为
   None —— 采集若只看 output，整条链路静默为空（首轮 E2E 实测就是这个坑）。
2. `_last_tool_result` 必须按调用 id 命中对应块，id 对不上时按 name 兜底，
   都没有时取最新的 tool_result，且不能把非 tool_result 的消息当结果。
3. `_iter_text_chunks` 要认 ToolResultBlock 的 ``output`` 字段（str 与块列表
   两种形态），否则网页/路径解析拿不到文本。
"""
from __future__ import annotations

import pytest

from coapis.agents.context import reference_collector as rc
from coapis.agents.context.light_context_manager import LightContextManager


class _FakeMemory:
    def __init__(self, messages):
        self._messages = messages

    async def get_memory(self, prepend_summary: bool = False):
        return list(self._messages)


class _FakeMsg:
    def __init__(self, blocks):
        self._blocks = blocks

    def get_content_blocks(self, block_type: str):
        return [b for b in self._blocks if b.get("type") == block_type]


class _FakeAgent:
    def __init__(self, messages):
        self.memory = _FakeMemory(messages)


def _result(call_id: str, name: str, output) -> dict:
    return {"type": "tool_result", "id": call_id, "name": name, "output": output}


@pytest.mark.asyncio
async def test_last_tool_result_matches_by_call_id():
    msgs = [
        _FakeMsg([_result("stale", "web_search", "旧结果")]),
        _FakeMsg([{"type": "text", "text": "思考中"}]),
        _FakeMsg([_result("call-42", "web_search", "https://example.com/a 韦伯")]),
    ]
    agent = _FakeAgent(msgs)
    lcm = LightContextManager.__new__(LightContextManager)
    block = await lcm._last_tool_result(
        agent, {"id": "call-42", "name": "web_search", "input": {}}
    )
    assert block is not None
    assert block["id"] == "call-42"


@pytest.mark.asyncio
async def test_last_tool_result_falls_back_to_name_then_newest():
    msgs = [
        _FakeMsg([_result("a", "read_file", "内容A")]),
        _FakeMsg([_result("b", "web_search", "内容B")]),
    ]
    agent = _FakeAgent(msgs)
    lcm = LightContextManager.__new__(LightContextManager)
    by_name = await lcm._last_tool_result(
        agent, {"id": "unknown", "name": "read_file", "input": {}}
    )
    assert by_name["id"] == "a"
    newest = await lcm._last_tool_result(
        agent, {"id": "unknown", "name": "no_such_tool", "input": {}}
    )
    assert newest["id"] == "b"


@pytest.mark.asyncio
async def test_last_tool_result_ignores_non_tool_result_messages():
    agent = _FakeAgent([_FakeMsg([{"type": "text", "text": "只有文本"}])])
    lcm = LightContextManager.__new__(LightContextManager)
    assert await lcm._last_tool_result(agent, {"id": "x", "name": "t"}) is None


def test_iter_text_chunks_reads_tool_result_output_field():
    as_str = rc._iter_text_chunks(_result("1", "web_search", "见 https://a.example/x"))
    assert any("a.example" in c for c in as_str)

    as_blocks = rc._iter_text_chunks(
        _result("2", "web_search", [{"type": "text", "text": '{"results":[{"url":"https://b.example/y","title":"乙"}]}'}])
    )
    assert any("b.example" in c for c in as_blocks)


def test_web_urls_parsed_from_tool_result_block_end_to_end(monkeypatch, tmp_path):
    """整条链路：ToolResultBlock → 采集 → 网页条目。"""
    rc.begin_turn(chat_id="chat-Z", username="alice")
    monkeypatch.setattr(rc, "_workspace_root", lambda u: tmp_path / u)
    added = rc.collect_from_tool_call(
        {"id": "c1", "name": "web_search", "input": {"query": "韦伯"}},
        _result(
            "c1",
            "web_search",
            '{"results":[{"url":"https://example.com/webb","title":"韦伯"}]}',
        ),
        username="alice",
    )
    assert any(i["kind"] == "web" for i in added)
    turn = rc.take_turn_resources()
    assert any(i["kind"] == "web" for i in turn)
