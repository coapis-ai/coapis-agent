# -*- coding: utf-8 -*-
"""C2A ↔ CoApis (AgentScope) integration — the "one-click injection" tool.

CoApis registers tools via ``coapis.agents.tools.registry.register_tool``.
Importing this module registers the framework-native ``c2a_render_card``
tool, which:

  * accepts a C2A payload (``blocks`` + ``actions``) produced by an LLM,
    and/or a raw MCP tool output (``tool_output`` + ``tool_name``);
  * validates it with the c2a_protocol validator (single source of truth);
  * returns the validated C2A message as JSON, ready for the frontend
    ``@coapis/c2a-renderer-react`` to render (data tables + row links).

The CoApis registry is imported defensively so this module can be imported
even when CoApis is not installed (e.g. running the c2a test suite alone).
"""

import json
import logging
from typing import Any, Dict, Optional

from c2a_protocol import (
    PROTOCOL_VERSION,
    validate_c2a_message,
    C2AValidationError,
)
from c2a_tools.mcp_parser import MCPC2AParser
from c2a_tools.converter import convert_tool_output_to_c2a

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Import the CoApis tool registry defensively.
# ---------------------------------------------------------------------------
try:
    from coapis.agents.tools.registry import register_tool as _register_tool

    _COAPIS_AVAILABLE = True
except Exception:  # pragma: no cover - CoApis not installed
    _register_tool = None
    _COAPIS_AVAILABLE = False


def _noop_register(*_args, **_kwargs):
    """Fallback decorator when CoApis is unavailable (keeps module importable)."""
    def decorator(fn):
        return fn
    if _args and callable(_args[0]) and not _kwargs:
        return _args[0]
    return decorator


_register = _register_tool if _COAPIS_AVAILABLE else _noop_register


# ---------------------------------------------------------------------------
# Core logic (framework-agnostic) — also importable for tests.
# ---------------------------------------------------------------------------
def render_card_payload(
    c2a_payload: Optional[Dict[str, Any]] = None,
    tool_output: Optional[Dict[str, Any]] = None,
    tool_name: str = "tool",
    session_id: str = "default_session",
) -> Dict[str, Any]:
    """Validate/convert to a C2A message and return a result dict.

    Two input modes (mutually exclusive, payload wins):
      1. ``c2a_payload`` — a full C2A message dict (``blocks`` + ``actions``).
      2. ``tool_output`` + ``tool_name`` — raw tool output, auto-converted.

    Returns a dict with ``status`` ('success' | 'failed') and, on success,
    ``c2a_message`` (the validated C2A message dict) and ``c2a_json``.
    """
    # Mode 1: explicit payload
    if c2a_payload:
        from c2a_protocol import (
            C2AMessage, ContextRef, Metadata, Block, BlockContent,
            Action, ActionSecurity, State,
        )
        try:
            blocks = [
                Block(
                    block_id=b.get("block_id", f"block_{i}"),
                    type=b.get("type", "text_markdown"),
                    content=BlockContent(data=b.get("content", {})),
                )
                for i, b in enumerate(c2a_payload.get("blocks", []))
            ]
            actions = []
            for i, a in enumerate(c2a_payload.get("actions", [])):
                sec = a.get("security", {}) or {}
                actions.append(Action(
                    action_id=a.get("action_id", f"action_{i}"),
                    label=a.get("label", "操作"),
                    style=a.get("style", "secondary"),
                    intent=a.get("intent", "api_call"),
                    payload=a.get("payload", {}) or {},
                    security=ActionSecurity(
                        requires_auth=sec.get("requires_auth", False),
                        required_permissions=sec.get("required_permissions", []),
                        confirmation_prompt=sec.get("confirmation_prompt"),
                    ),
                ))
            msg = C2AMessage(
                protocol_version=c2a_payload.get("protocol_version", PROTOCOL_VERSION),
                message_id=c2a_payload.get("message_id", f"msg_{len(blocks)}"),
                context_ref=ContextRef(session_id=session_id),
                metadata=Metadata(generated_by="c2a_render_card"),
                blocks=blocks,
                actions=actions,
                state=State(status="rendered"),
            )
            validate_c2a_message(msg)
            return {"status": "success", "c2a_message": msg.to_dict(),
                    "c2a_json": msg.to_json(indent=2), "errors": []}
        except C2AValidationError as e:
            logger.warning("c2a_render_card payload validation failed: %s", e)
            return {"status": "failed", "errors": [str(e)]}

    # Mode 2: raw tool output → implicit conversion
    if tool_output:
        converted = convert_tool_output_to_c2a(tool_name, tool_output, session_id)
        if converted is None:
            return {"status": "skipped",
                    "errors": ["tool_output contains no data list to render as a C2A card"]}
        return {"status": "success", "c2a_message": converted.to_dict(),
                "c2a_json": converted.to_json(indent=2), "errors": []}

    return {"status": "failed", "errors": ["provide c2a_payload or (tool_output + tool_name)"]}


# ---------------------------------------------------------------------------
# Framework-native tool registration (CoApis / AgentScope)
# ---------------------------------------------------------------------------
@_register(
    name="c2a_render_card",
    description=(
        "渲染并校验 C2A (Chat-to-Action) 交互卡片。传入 blocks+actions 的 C2A "
        "payload，或传入 MCP/工具返回的原始数据 (tool_output)，自动生成带数据表格、"
        "行级链接 (row_link) 与快捷操作 (导出/查看更多) 的 C2A 消息 JSON，供前端渲染。"
        "当需要以交互式 UI（而非纯文本）呈现列表、表格、表单或操作按钮时，优先使用本工具。"
    ),
    category="plugin",
    tags=["c2a", "card", "render", "validation"],
    dependencies=[
        {"name": "c2a-protocol", "manager": "pip", "required": True,
         "reason": "C2A 协议模型与校验器"},
        {"name": "c2a-tools", "manager": "pip", "required": True,
         "reason": "MCP→C2A 解析与转换"},
    ],
)
async def c2a_render_card(
    c2a_payload: Optional[Dict[str, Any]] = None,
    tool_output: Optional[Dict[str, Any]] = None,
    tool_name: str = "tool",
    session_id: str = "default_session",
) -> Dict[str, Any]:
    """解析并验证 C2A payload（或自动转换工具输出）为可渲染的 C2A 消息。

    Args:
        c2a_payload: 完整 C2A 消息负载，含 protocol_version / blocks / actions。
            blocks 为 [{type, content}]，actions 为 [{action_id, label, intent, payload}]。
        tool_output: MCP 或任意工具的原始返回（dict）。提供后自动检测数据列表并
            生成 data_table 卡片（含 row_link 行链接）。
        tool_name: 与 tool_output 配套，用于生成 action id 与 endpoint。
        session_id: 会话标识，写入 context_ref。

    Returns:
        ``{"status": "success"|"failed"|"skipped", "c2a_message": {...},
        "c2a_json": "...", "errors": [...]}``
    """
    return render_card_payload(
        c2a_payload=c2a_payload,
        tool_output=tool_output,
        tool_name=tool_name,
        session_id=session_id,
    )
