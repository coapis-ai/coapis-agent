# -*- coding: utf-8 -*-
# Copyright 2026 蜜蜂 & CoApis Contributors
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU Affero General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU Affero General Public License for more details.
#
# You should have received a copy of the GNU Affero General Public License
# along with this program.  If not, see <https://www.gnu.org/licenses/>.

"""系统消息位置治理测试（治本 M1 / M2 / M4）。

现场铁证（dev 日志 2026-10-14 10:36:43 与 10:39:26，共 8 条）：
用户勾选 ``AI_Agent技术总结报告.docx`` 让模型分析，注入的文件提示以
``role="system"`` 落在历史中间，本地严格 Jinja 模板直接
``500 System message must be at the beginning``，且被当作瞬时故障重试 4 次。

本文件锁定三件事：
1. 请求侧唯一咽喉把散落的**文本型** system 合并进首位 system，**不动**工具载体；
2. ``rebuild_sys_prompt`` 不再覆盖 memory 里的注入消息；
3. 形状类错误不再重试。
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest
from agentscope.message import Msg

from coapis.agents.utils.message_request_normalizer import (
    _hoist_system_messages,
    _system_governance_enabled,
    normalize_messages_for_model_request,
)
from coapis.agents.utils.tool_message_utils import extract_tool_ids
from coapis.providers.retry_chat_model import _is_request_shape_error, _is_retryable


def _msg(role: str, content, name: str = "n") -> Msg:
    return Msg(name=name, role=role, content=content)


def _norm(msgs, **kw):
    kw.setdefault("supports_multimodal", False)
    return normalize_messages_for_model_request(msgs, **kw)


def _system_indexes(msgs) -> list[int]:
    """Indexes of system turns that carry *prose* (tool carriers excluded)."""
    out = []
    for i, msg in enumerate(msgs):
        if msg.role != "system":
            continue
        blocks = msg.content if isinstance(msg.content, list) else []
        if any(
            isinstance(b, dict) and b.get("type") in ("tool_use", "tool_result")
            for b in blocks
        ):
            continue
        out.append(i)
    return out


def _all_text(msgs) -> str:
    parts = []
    for msg in msgs:
        blocks = msg.content if isinstance(msg.content, list) else [msg.content]
        for block in blocks:
            if isinstance(block, dict):
                if block.get("type") == "text":
                    parts.append(block.get("text") or "")
            else:
                parts.append(str(block))
    return "\n".join(parts)


# ---------------------------------------------------------------------------
# M1 —— 文本型 system 合并进首位
# ---------------------------------------------------------------------------


def test_real_incident_shape_yields_single_leading_system() -> None:
    """dev 日志原形状：[system提示, user, assistant, system(文件提示), user]。"""
    out = _norm([
        _msg("system", "你是 CoApis 智能体"),
        _msg("user", "帮我看看"),
        _msg("assistant", "好的"),
        _msg("system", "[已勾选文件] AI_Agent技术总结报告.docx"),
        _msg("user", "请分析一下这个文件的内容"),
    ])
    assert _system_indexes(out) == [0]
    head = out[0].get_text_content() or ""
    assert "CoApis 智能体" in head
    assert "AI_Agent技术总结报告.docx" in head
    # 合并而非丢弃：一个字都不能少
    assert "请分析一下这个文件的内容" in _all_text(out)


def test_multiple_hints_merge_in_appearance_order() -> None:
    out = _norm([
        _msg("system", "基础提示"),
        _msg("user", "q1"),
        _msg("system", "文件提示"),
        _msg("assistant", "a1"),
        _msg("system", "知识库提示"),
        _msg("user", "q2"),
    ])
    assert _system_indexes(out) == [0]
    head = out[0].get_text_content() or ""
    assert head.index("基础提示") < head.index("文件提示") < head.index("知识库提示")
    assert len(out) == 4


def test_head_system_created_when_history_has_none() -> None:
    out = _norm([
        _msg("user", "q"),
        _msg("assistant", "a"),
        _msg("system", "计划闸门：请先给出计划"),
    ])
    assert _system_indexes(out) == [0]
    assert out[0].role == "system"
    assert "计划闸门" in out[0].get_text_content()


def test_no_system_message_is_not_invented() -> None:
    out = _norm([_msg("user", "q"), _msg("assistant", "a"), _msg("user", "q2")])
    assert all(m.role != "system" for m in out)


def test_tool_result_system_carrier_stays_in_place() -> None:
    """工具载体不得移动：OpenAI 家族渲染成 role=tool，Anthropic 路径转 user。"""
    msgs = [
        _msg("system", "基础提示"),
        _msg("user", "读文件"),
        _msg("assistant", [
            {"type": "tool_use", "id": "t1", "name": "read_file", "input": {}},
        ]),
        _msg("system", [
            {
                "type": "tool_result",
                "id": "t1",
                "name": "read_file",
                "output": [{"type": "text", "text": "内容"}],
            },
        ]),
        _msg("system", "文件提示：已勾选 x.docx"),
        _msg("user", "分析它"),
    ]
    out = _norm(msgs, strict_chain=True)
    assert _system_indexes(out) == [0]
    carriers = [
        m for m in out
        if m.role == "system" and extract_tool_ids(m)[1]
    ]
    assert len(carriers) == 1
    uses: set[str] = set()
    results: set[str] = set()
    for m in out:
        u, r = extract_tool_ids(m)
        uses |= u
        results |= r
    assert uses == {"t1"} and results == {"t1"}


def test_media_on_system_survives_as_user_turn() -> None:
    out = _norm(
        [
            _msg("system", "基础提示"),
            _msg("user", "q"),
            _msg("system", [
                {"type": "text", "text": "看图"},
                {"type": "image", "image_url": {"url": "file:///tmp/a.png"}},
            ]),
        ],
        supports_multimodal=True,
    )
    assert _system_indexes(out) == [0]
    assert "看图" in _all_text(out)
    media_turns = [
        m for m in out
        if m.role == "user"
        and isinstance(m.content, list)
        and any(b.get("type") == "image" for b in m.content if isinstance(b, dict))
    ]
    assert len(media_turns) == 1


def test_hoisting_is_idempotent() -> None:
    msgs = [
        _msg("system", "基础"),
        _msg("user", "q"),
        _msg("system", "提示A"),
        _msg("assistant", "a"),
        _msg("system", "提示B"),
    ]
    once = _norm(msgs)
    twice = _norm(once)
    assert [m.role for m in once] == [m.role for m in twice]
    assert _all_text(once) == _all_text(twice)


def test_source_messages_are_not_mutated() -> None:
    msgs = [
        _msg("system", "基础"),
        _msg("user", "q"),
        _msg("system", "提示"),
    ]
    before = [(m.role, m.content) for m in msgs]
    _norm(msgs)
    assert [(m.role, m.content) for m in msgs] == before


def test_stored_history_keeps_mid_list_system_untouched() -> None:
    """治理只作用于请求副本，存档形状不变（D1：不动存储层）。"""
    msgs = [
        _msg("system", "基础"),
        _msg("user", "q"),
        _msg("system", "知识库提示"),
    ]
    _norm(msgs)
    assert [m.role for m in msgs] == ["system", "user", "system"]


# ---------------------------------------------------------------------------
# 开关语义（D3：不受 COAPIS_MODEL_COMPAT_MODE 门控）
# ---------------------------------------------------------------------------


def test_governance_runs_in_shadow_mode(monkeypatch) -> None:
    """影子模式只治理内容改写；形状硬失败必须照治，否则等于继续崩。"""
    monkeypatch.setenv("COAPIS_MODEL_COMPAT_MODE", "shadow")
    out = _norm([
        _msg("system", "基础"),
        _msg("user", "q"),
        _msg("system", "文件提示"),
        _msg("user", "q2"),
    ])
    assert _system_indexes(out) == [0]


def test_governance_off_restores_raw_shape(monkeypatch) -> None:
    monkeypatch.setenv("COAPIS_SYSTEM_MSG_GOVERNANCE", "off")
    assert _system_governance_enabled() is False
    out = _norm([
        _msg("system", "基础"),
        _msg("user", "q"),
        _msg("system", "文件提示"),
        _msg("user", "q2"),
    ])
    assert _system_indexes(out) == [0, 2]


def test_governance_defaults_on(monkeypatch) -> None:
    monkeypatch.delenv("COAPIS_SYSTEM_MSG_GOVERNANCE", raising=False)
    assert _system_governance_enabled() is True


def test_hoist_helper_returns_same_object_when_nothing_to_do() -> None:
    msgs = [_msg("system", "基础"), _msg("user", "q")]
    assert _hoist_system_messages(msgs) is msgs


# ---------------------------------------------------------------------------
# 压缩调用同样中招（附带发现）
# ---------------------------------------------------------------------------


def test_compression_call_shape_is_legal() -> None:
    """``light_context_manager`` 构造 [system指令, *history, user]。"""
    history = [
        _msg("user", "q1"),
        _msg("assistant", [
            {"type": "tool_use", "id": "t9", "name": "web_search", "input": {}},
        ]),
        _msg("system", [
            {
                "type": "tool_result",
                "id": "t9",
                "name": "web_search",
                "output": [{"type": "text", "text": "结果"}],
            },
        ]),
        _msg("system", "知识库提示"),
        _msg("user", "q2"),
    ]
    out = _norm([
        _msg("system", "You compress conversation history."),
        *history,
        _msg("user", "请总结以上对话"),
    ])
    assert _system_indexes(out) == [0]
    assert "知识库提示" in out[0].get_text_content()


# ---------------------------------------------------------------------------
# M2 —— rebuild_sys_prompt 不再覆盖注入消息
# ---------------------------------------------------------------------------


def test_rebuild_sys_prompt_leaves_tool_carrier_alone() -> None:
    """41/100 dev 会话的第一条 system 是工具载体，旧实现会把它覆盖成系统提示。"""
    from coapis.agents.react_agent import CoApisAgent

    carrier = _msg("system", [
        {
            "type": "tool_result",
            "id": "call_939b",
            "name": "web_search",
            "output": [{"type": "text", "text": "真实工具结果"}],
        },
    ])
    stub = SimpleNamespace(
        _sys_prompt="旧提示",
        memory=SimpleNamespace(content=[(carrier, [])]),
        _build_sys_prompt=lambda: "新提示",
    )
    CoApisAgent.rebuild_sys_prompt(stub)

    assert stub._sys_prompt == "新提示"
    assert carrier.content[0]["type"] == "tool_result"
    assert carrier.content[0]["id"] == "call_939b"
    assert "真实工具结果" in str(carrier.content)


def test_rebuild_sys_prompt_leaves_prose_injection_alone() -> None:
    from coapis.agents.react_agent import CoApisAgent

    hint = _msg("system", "已勾选文件：报告.docx")
    stub = SimpleNamespace(
        _sys_prompt="旧提示",
        memory=SimpleNamespace(content=[(hint, [])]),
        _build_sys_prompt=lambda: "新提示",
    )
    CoApisAgent.rebuild_sys_prompt(stub)
    assert hint.content == "已勾选文件：报告.docx"


# ---------------------------------------------------------------------------
# M4 —— 形状错误不再重试
# ---------------------------------------------------------------------------


class _ApiError(Exception):
    def __init__(self, message: str, status_code: int) -> None:
        super().__init__(message)
        self.status_code = status_code


def test_shape_500_is_not_retryable() -> None:
    exc = _ApiError(
        "Error code: 500 - Jinja Exception: System message must be at the beginning.",
        500,
    )
    assert _is_request_shape_error(exc) is True
    assert _is_retryable(exc) is False


def test_anthropic_style_shape_400_is_not_retryable() -> None:
    exc = _ApiError("400 - The system role is reserved for the system prompt", 400)
    assert _is_retryable(exc) is False


def test_tool_use_id_shape_error_is_not_retryable() -> None:
    exc = _ApiError("400 - tool_use_id not found: call_939b", 400)
    assert _is_retryable(exc) is False


def test_plain_500_still_retries() -> None:
    assert _is_retryable(_ApiError("internal server error", 500)) is True


def test_rate_limit_still_retries() -> None:
    assert _is_retryable(_ApiError("too many requests", 429)) is True


def test_shape_patterns_are_case_insensitive() -> None:
    exc = _ApiError("SYSTEM MESSAGE MUST BE THE FIRST MESSAGE", 400)
    assert _is_request_shape_error(exc) is True


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(pytest.main([__file__, "-q"]))
