"""工具观测层（台账）尺子契约测试。

2026-11-26 起因：web_search 返回的是 dict（results/backend/query/message），
而 _extract_result_text 只认 text/output/content 三个键，其余一律返回 ""。
后果是台账把一次成功调用记成 output_len=0，且软失败探针永远读不到
"所有搜索后端均无结果" 这类话——工具没撒谎，观测层替它撒了。
这里锁住两件事：dict 结果必须留下可读文本；失败话术必须能被探针抓到。
"""

import sys
from pathlib import Path

SERVER_ROOT = Path(__file__).resolve().parents[1]
if str(SERVER_ROOT) not in sys.path:
    sys.path.insert(0, str(SERVER_ROOT))

from coapis.agents.react_agent import (  # noqa: E402
    _detect_soft_failure,
    _extract_result_text,
)


def test_dict_without_text_keys_still_yields_text():
    """web_search 的真实返回形状：没有 text/output/content。"""
    payload = {
        "results": [{"title": "A", "link": "https://a", "snippet": "s"}],
        "backend": "baidu",
        "query": "2026年11月26日 热点",
    }
    text = _extract_result_text(payload)
    assert text, "dict 结果被抽成空串，台账会记成 output_len=0"
    assert "baidu" in text
    assert "热点" in text


def test_dict_failure_message_is_visible_to_soft_probe():
    """失败话术必须能被软失败探针抓到（此前永远抓不到）。"""
    payload = {
        "results": [],
        "backend": None,
        "query": "x",
        "message": "所有搜索后端均无结果，请更换关键词或稍后再试",
    }
    text = _extract_result_text(payload)
    assert "所有搜索后端均无结果" in text
    # 探针吃的是拍平后的文本（与 react_agent 收口处的真实调用一致）
    assert _detect_soft_failure(text) == "no_search_backend"


def test_text_key_still_wins_over_json_dump():
    """有 text 键时保持原行为，不把整坨 JSON 塞进台账。"""
    assert _extract_result_text({"text": "hello"}) == "hello"
    assert _extract_result_text({"output": "world"}) == "world"


def test_non_serializable_dict_does_not_raise():
    class Nope:
        def __repr__(self):
            return "<Nope>"

    text = _extract_result_text({"weird": Nope(), "message": "boom"})
    assert isinstance(text, str) and text


def test_nested_blocks_list_still_flattened():
    blocks = [{"type": "text", "text": "第一段"}, {"type": "text", "text": "第二段"}]
    text = _extract_result_text({"content": blocks})
    assert "第一段" in text and "第二段" in text


# ---------------------------------------------------------------------------
# 台账取结果的源头：agentscope 的 _acting 对普通工具返回 None，
# 结果只落在 memory 的 ToolResultBlock 上（实测 4524 条 tool_call
# 里 92.9% output_len=0，就是因为只读了 result）。
# ---------------------------------------------------------------------------

class _FakeMsg:
    def __init__(self, content):
        self.content = content


class _FakeMemory:
    def __init__(self, msgs):
        self._msgs = msgs

    async def get_memory(self):
        return self._msgs


def _tool_result_block(tool_id: str, output):
    return _FakeMsg([
        {
            "type": "tool_result",
            "id": tool_id,
            "name": "web_search",
            "output": output,
        },
    ])


def test_ledger_reads_result_from_memory_block():
    import asyncio

    from coapis.agents.react_agent import _tool_result_text_from_memory

    mem = _FakeMemory([
        _FakeMsg([{"type": "text", "text": "assistant thinking"}]),
        _tool_result_block("call-42", [
            {"type": "text", "text": "搜索结果 1"},
            {"type": "text", "text": "搜索结果 2"},
        ]),
    ])
    text = asyncio.run(_tool_result_text_from_memory(mem, "call-42"))
    assert "搜索结果 1" in text and "搜索结果 2" in text


def test_ledger_ignores_other_turns_result():
    """按 tool_call_id 认领，不能把上一轮的结果当成本轮的。"""
    import asyncio

    from coapis.agents.react_agent import _tool_result_text_from_memory

    mem = _FakeMemory([_tool_result_block("call-old", [{"type": "text", "text": "旧结果"}])])
    assert asyncio.run(_tool_result_text_from_memory(mem, "call-new")) == ""


def test_ledger_survives_memory_failure():
    import asyncio

    from coapis.agents.react_agent import _tool_result_text_from_memory

    class _Boom:
        async def get_memory(self):
            raise RuntimeError("memory down")

    assert asyncio.run(_tool_result_text_from_memory(_Boom(), "x")) == ""


# ---------------------------------------------------------------------------
# 管理端工具分组：尺子必须与运行时注册表同源
# （实测旧尺子 5 组 / 23 名 vs 运行时 13 组 / 34 名 → 14 个工具被塞进
#   "other"，另有 data_ops / data_store / text_processor 三个幽灵名字）
# ---------------------------------------------------------------------------

def test_admin_tool_group_follows_runtime_ruler():
    from coapis.agents.tools.groups import TOOL_GROUP_MAP
    from coapis.app.routers.tools import _tool_group

    for name, group in TOOL_GROUP_MAP.items():
        assert _tool_group(name) == group, f"{name} 分组与运行时尺子不一致"

    # 运行时没有的工具不再冒充某个分组，统一落 basic
    for ghost in ("data_ops", "data_store", "text_processor"):
        assert _tool_group(ghost) == "basic"

    # 分组名必须全部来自运行时尺子，不再出现 "other"
    assert "other" not in {_tool_group(n) for n in TOOL_GROUP_MAP}


def test_availability_probe_flags_unconfigured_backends(monkeypatch):
    """没配 key 的 tavily 必须判 False——否则每次搜索都白起一个必败线程，
    还会把失败信息写成"已尝试: …,tavily"骗人。"""
    import coapis.agents.tools.web_search as ws

    monkeypatch.delenv("TAVILY_API_KEY", raising=False)
    monkeypatch.delenv("TAVILY_SEARCH_API_KEY", raising=False)
    assert ws._backend_available("tavily") is False
    assert ws._backend_available("browser") is True
    assert ws._backend_available("baidu") is True


def test_unavailable_backend_is_skipped_not_raced(monkeypatch):
    """不可用的后端不进竞速：它的实现函数一次都不该被调用。"""
    import asyncio

    import coapis.agents.tools.web_search as ws

    called = []

    async def _ok(query, max_results):
        called.append("good")
        return [{"title": "t", "content": "c", "url": "u"}]

    async def _dead(query, max_results):
        called.append("dead")
        return []

    monkeypatch.setattr(ws, "_BACKENDS", {"dead": _dead, "good": _ok})
    monkeypatch.setattr(ws, "_BACKEND_ORDER", ["dead", "good"])
    monkeypatch.setattr(ws, "_backend_available", lambda name: name != "dead")
    monkeypatch.setattr(ws, "_get_cached", lambda q, b: None)

    result = asyncio.run(
        ws.web_search("唯一哨兵词", max_results=3, backend="auto"),
    )
    assert "dead" not in called, "不可用后端仍被起线程竞速"
    assert result.get("backend") == "good"


def test_all_backends_unavailable_reports_skipped_not_empty_race(monkeypatch):
    """全不可用时要给出可操作的错误，而不是空竞速后报"全部后端失败"。"""
    import asyncio

    import coapis.agents.tools.web_search as ws

    async def _never(query, max_results):
        return []

    monkeypatch.setattr(ws, "_BACKENDS", {"tavily": _never})
    monkeypatch.setattr(ws, "_BACKEND_ORDER", ["tavily"])
    monkeypatch.setattr(ws, "_backend_available", lambda name: False)
    monkeypatch.setattr(ws, "_get_cached", lambda q, b: None)

    result = asyncio.run(ws.web_search("唯一哨兵词", backend="auto"))
    assert "tavily" in result.get("error", "")
    assert "失败" not in result.get("error", "")
