"""片2 模型兼容治理测试：空消息清洗 + 角色交替合并 + 工具链校验。

背景：选择 Word 等文件让模型分析时，部分模型直接报错或无反应。根因不是文件本身，
而是送进请求的消息结构不合规——连续同角色、空 content、无配对的 tool_result，
严格端点（Anthropic / Gemini / 严格 OpenAI 兼容）会直接拒绝。

本模块此前已实现这些清洗函数但**无人调用**（空心）。本测试锁定"已接线"这一事实，
防止再次退化为空心实现。
"""

from __future__ import annotations

import pytest
from agentscope.message import Msg

from coapis.agents.utils.message_request_normalizer import (
    normalize_messages_for_model_request,
)
from coapis.agents.utils.tool_message_utils import extract_tool_ids


@pytest.fixture(autouse=True)
def _apply_mode(monkeypatch):
    """默认开关是 shadow（只观测）；本文件主体用例验证改写生效。"""
    monkeypatch.setenv("COAPIS_MODEL_COMPAT_MODE", "apply")


def _msg(role: str, content, name: str = "n") -> Msg:
    return Msg(name=name, role=role, content=content)


def _norm(msgs, **kw):
    kw.setdefault("supports_multimodal", False)
    return normalize_messages_for_model_request(msgs, **kw)


# ---------------------------------------------------------------------------
# 空消息清洗
# ---------------------------------------------------------------------------


def test_drops_assistant_message_with_empty_text() -> None:
    """空 content 的 assistant 消息必须被丢弃——严格端点必然拒绝。"""
    out = _norm([
        _msg("user", "问题"),
        _msg("assistant", ""),
        _msg("user", "追问"),
    ])
    # 空轮丢弃后剩两条相邻 user 轮，严格档必须合并为一条
    assert len(out) == 1
    assert out[0].role == "user"
    text = out[0].get_text_content() or ""
    assert "问题" in text and "追问" in text
    assert all(m.get_text_content() for m in out)


def test_drops_assistant_message_with_empty_blocks() -> None:
    out = _norm([
        _msg("user", "q"),
        _msg("assistant", [{"type": "text", "text": ""}]),
    ])
    assert len(out) == 1


def test_keeps_assistant_message_with_tool_use_only() -> None:
    """只有工具调用、没有文本的 assistant 消息是合法的，不得丢弃。"""
    msgs = [
        _msg("user", "q"),
        _msg("assistant", [
            {"type": "tool_use", "id": "t1", "name": "read_file", "input": {}},
        ]),
    ]
    out = _norm(msgs, strict_chain=True)
    # 该轮必须保留（旧清洗会整条删除），并补出配对的 tool_result
    assert any(m.role == "assistant" and extract_tool_ids(m)[0] for m in out)
    assert len(out) >= 2


def test_drops_empty_user_message() -> None:
    out = _norm([_msg("user", ""), _msg("user", "有内容")])
    assert len(out) == 1


def test_all_empty_input_returns_empty_not_error() -> None:
    """全空输入返回空列表，不得抛异常。"""
    assert _norm([_msg("user", ""), _msg("assistant", "")]) == []


# ---------------------------------------------------------------------------
# 角色交替合并
# ---------------------------------------------------------------------------


def test_merges_adjacent_assistant_text_messages() -> None:
    """连续两条 assistant 文本必须合并为一条（严格端点要求角色交替）。"""
    out = _norm([
        _msg("user", "q"),
        _msg("assistant", "第一段"),
        _msg("assistant", "第二段"),
    ])
    assistants = [m for m in out if m.role == "assistant"]
    assert len(assistants) == 1
    text = assistants[0].get_text_content()
    assert "第一段" in text and "第二段" in text


def test_merges_adjacent_user_messages() -> None:
    out = _norm([
        _msg("user", "第一条", name="u1"),
        _msg("user", "第二条", name="u2"),
    ])
    users = [m for m in out if m.role == "user"]
    assert len(users) == 1
    assert "第一条" in users[0].get_text_content()
    assert "第二条" in users[0].get_text_content()


def test_alternating_roles_preserved() -> None:
    """正常交替的消息不得被合并掉。"""
    out = _norm([
        _msg("user", "a"),
        _msg("assistant", "b"),
        _msg("user", "c"),
        _msg("assistant", "d"),
    ])
    assert [m.role for m in out] == ["user", "assistant", "user", "assistant"]


# ---------------------------------------------------------------------------
# 工具链校验（严格档）
# ---------------------------------------------------------------------------


def _tool_use_msg(call_id: str) -> Msg:
    return _msg("assistant", [
        {"type": "tool_use", "id": call_id, "name": "read_file", "input": {"file_path": "a.md"}},
    ])


def _tool_result_msg(call_id: str, text: str = "结果") -> Msg:
    return _msg("system", [
        {
            "type": "tool_result",
            "id": call_id,
            "name": "read_file",
            "output": [{"type": "text", "text": text}],
        },
    ])


def test_paired_tool_chain_survives() -> None:
    """配对完整的工具链必须原样保留——这是正常路径，不能被清洗误伤。"""
    out = _norm([_msg("user", "q"), _tool_use_msg("t1"), _tool_result_msg("t1")],
                strict_chain=True)
    assert len(out) == 3


def test_orphan_tool_result_dropped_in_strict_mode() -> None:
    """无配对的 tool_result 在严格档必须丢弃（严格端点直接报错）。"""
    out = _norm([_msg("user", "q"), _tool_result_msg("ghost")], strict_chain=True)
    assert not any(
        b.get("type") == "tool_result"
        for m in out
        for b in (m.content if isinstance(m.content, list) else [])
    )


def test_tool_use_without_result_gets_synthetic_result() -> None:
    """有 tool_use 无 tool_result 时必须补合成结果，不得留下断链。"""
    out = _norm([_msg("user", "q"), _tool_use_msg("t9")], strict_chain=True)
    results = [
        b
        for m in out
        for b in (m.content if isinstance(m.content, list) else [])
        if b.get("type") == "tool_result"
    ]
    assert any(b.get("id") == "t9" for b in results)


def test_strict_chain_auto_enabled_for_anthropic_family() -> None:
    """目标家族为 anthropic 时自动启用严格档，无需调用方显式传参。"""
    out = _norm([_msg("user", "q"), _tool_result_msg("ghost")], target_family="anthropic")
    assert not any(
        b.get("type") == "tool_result"
        for m in out
        for b in (m.content if isinstance(m.content, list) else [])
    )


def test_strict_chain_auto_enabled_for_gemini_family() -> None:
    out = _norm([_msg("user", "q"), _tool_result_msg("ghost")], target_family="gemini")
    assert not any(
        b.get("type") == "tool_result"
        for m in out
        for b in (m.content if isinstance(m.content, list) else [])
    )


def test_openai_family_also_drops_orphan_tool_result() -> None:
    """无配对的 tool_result 对宽松端点同样非法。"""
    out = _norm([_msg("user", "q"), _tool_result_msg("t1")], target_family="openai")
    # 无配对的 tool_result 对任何端点都非法，宽松档同样必须丢弃
    assert not any(
        b.get("type") == "tool_result"
        for m in out
        for b in (m.content if isinstance(m.content, list) else [])
    )


# ---------------------------------------------------------------------------
# 幂等与不改动原对象
# ---------------------------------------------------------------------------


def test_normalization_is_idempotent() -> None:
    """清洗一遍后再清洗不得继续丢消息——否则说明清洗在制造新的不合规。"""
    once = _norm([
        _msg("user", "a"),
        _msg("assistant", "b"),
        _msg("assistant", "c"),
        _tool_use_msg("t1"),
        _tool_result_msg("t1"),
    ], strict_chain=True)
    twice = _norm(once, strict_chain=True)
    assert len(twice) == len(once)


def test_source_messages_not_mutated() -> None:
    """清洗必须作用于副本，不得就地改坏会话记忆。"""
    src = [_msg("user", "q"), _msg("assistant", "")]
    _norm(src)
    assert len(src) == 2
    assert src[1].get_text_content() == ""

# ---------------------------------------------------------------------------
# 影子观测开关（拍板项：模型兼容先影子观测一周）
# ---------------------------------------------------------------------------


def test_shadow_mode_leaves_request_untouched(monkeypatch) -> None:
    """影子模式只记录、不改写：发给模型的内容保持原样。"""
    monkeypatch.setenv("COAPIS_MODEL_COMPAT_MODE", "shadow")
    msgs = [_msg("user", "q"), _msg("assistant", ""), _msg("assistant", "b")]
    out = normalize_messages_for_model_request(
        msgs,
        supports_multimodal=True,
        target_family="anthropic",
    )
    assert len(out) == 3


def test_apply_mode_rewrites(monkeypatch) -> None:
    monkeypatch.setenv("COAPIS_MODEL_COMPAT_MODE", "apply")
    msgs = [_msg("user", "q"), _msg("assistant", ""), _msg("assistant", "b")]
    out = normalize_messages_for_model_request(
        msgs,
        supports_multimodal=True,
        target_family="anthropic",
    )
    assert len(out) == 2


def test_off_mode_skips_pass(monkeypatch) -> None:
    monkeypatch.setenv("COAPIS_MODEL_COMPAT_MODE", "off")
    msgs = [_msg("user", ""), _msg("assistant", "")]
    out = normalize_messages_for_model_request(
        msgs,
        supports_multimodal=True,
        target_family="anthropic",
    )
    assert len(out) == 2


def test_unknown_mode_falls_back_to_shadow(monkeypatch) -> None:
    monkeypatch.setenv("COAPIS_MODEL_COMPAT_MODE", "wat")
    from coapis.agents.utils.message_request_normalizer import _compat_mode

    assert _compat_mode() == "shadow"
