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
from typing import Any, Dict, List, Optional

from c2a_protocol import (
    PROTOCOL_VERSION,
    validate_c2a_message,
    C2AValidationError,
)
from c2a_protocol.models import BLOCK_TYPES, ACTION_INTENTS
from c2a_tools.mcp_parser import MCPC2AParser
from c2a_tools.converter import convert_tool_output_to_c2a

logger = logging.getLogger(__name__)


# Hints returned to the LLM on failed/skip. They tell the LLM exactly how to
# recover (show the data as Markdown text in its reply) and — crucially — that
# it must NEVER leak raw tool output (JSON / error codes / Python reprs) to
# end users.
_USER_HINT_FAILED = (
    "卡片渲染失败。请把数据整理成 Markdown 表格直接写进你的文字回复，"
    "并简短说明卡片未能渲染、已改为文字展示；"
    "绝对不要向用户展示本工具返回的任何原始内容（JSON、错误码、Python 结构）。"
)
_USER_HINT_SKIPPED = (
    "工具输出中没有可渲染成卡片的表格数据。请把数据直接写进你的文字回复；"
    "不要提及卡片渲染或本工具的返回。"
)


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
# Content normalisation (framework-agnostic).
#
# LLMs frequently emit *almost*-valid C2A payloads that the protocol validator
# accepts (it does not inspect block content) but the frontend renderer cannot
# read — e.g. a data_table whose ``columns``/``rows`` live at the payload root
# with an empty ``content: {}``, or a text_markdown whose content is a bare
# string instead of ``{"markdown": "..."}``. These used to render as a blank
# card while the LLM still claimed "N rows shown" — the exact failure this
# guards against. We normalise the known shapes up-front and *fail loudly* when
# a data_table has no recoverable table data (never return a "success" card
# with an empty table).
# ---------------------------------------------------------------------------
def _normalize_markdown_content(content: Any) -> Dict[str, Any]:
    """text_markdown content must be ``{"markdown": str}``; a bare string is
    normalised into that shape."""
    if isinstance(content, str):
        return {"markdown": content}
    if isinstance(content, dict):
        return content  # already an object; trust the given keys
    return {"markdown": ""}


def _build_table_content(block: Dict[str, Any], payload: Dict[str, Any]) -> Dict[str, Any]:
    """Build the canonical data_table content:
    ``{"data": {"headers": [...labels], "rows": [[...strings]]}}``
    (plus passthrough of ``id_field`` / ``row_values`` / ``row_actions``).

    Tolerates four LLM shapes, in priority order:
      1. ``content.data.headers/rows``            (canonical)
      2. ``content.headers/rows``                (missing the ``data`` wrapper)
      3. block-level ``columns``/``headers`` + ``rows``
      4. payload-root ``columns``/``headers`` + ``rows`` (LLM put the table at
         the root, block content empty)

    Raises ``ValueError`` if no non-empty headers+rows can be recovered — the
    caller converts that into a *failed* card rather than a blank success.
    """
    content = block.get("content")
    if not isinstance(content, dict):
        content = {}

    # Candidate (headers, rows, extra) tuples, first match wins.
    candidates: List[tuple] = []
    d = content.get("data")
    if isinstance(d, dict) and d.get("headers") and d.get("rows"):
        candidates.append((d["headers"], d["rows"],
                           {k: v for k, v in content.items() if k != "data"}))
    if content.get("headers") and content.get("rows"):
        candidates.append((content["headers"], content["rows"],
                           {k: v for k, v in content.items() if k not in ("headers", "rows")}))
    if block.get("rows") is not None:
        bh = block.get("columns") or block.get("headers")
        if bh:
            candidates.append((bh, block["rows"], {}))
    if payload.get("rows") is not None:
        ph = payload.get("columns") or payload.get("headers")
        if ph:
            candidates.append((ph, payload["rows"], {}))

    if not candidates:
        raise ValueError(
            "no table data found — put a non-empty content.data.headers + "
            "content.data.rows on the data_table block (or pass tool_output "
            "for auto-conversion)"
        )

    headers_raw, rows_raw, extra = candidates[0]

    # Display labels + column keys. columns may be [{"key","label"}] or [str].
    if headers_raw and isinstance(headers_raw[0], dict):
        keys = [str(h.get("key") or h.get("label") or f"col_{i}")
                for i, h in enumerate(headers_raw)]
        labels = [str(h.get("label") or h.get("key") or f"列{i + 1}")
                  for i, h in enumerate(headers_raw)]
    else:
        labels = [str(h) for h in headers_raw]
        keys = list(labels)  # for dict rows, the dict keys == the labels

    table_rows: List[List[str]] = []
    for r in rows_raw:
        if isinstance(r, list):
            table_rows.append([str(x) for x in r])
        elif isinstance(r, dict):
            table_rows.append([str(r.get(k, "")) for k in keys])
        else:
            table_rows.append([str(r)])

    out = dict(extra)
    out["data"] = {"headers": labels, "rows": table_rows}
    return out


def _salvage_block_type(block: Dict[str, Any], payload: Dict[str, Any]) -> Optional[str]:
    """Try to determine the intended valid block type from content shape.

    LLMs occasionally emit a block with a made-up type (e.g. ``action_link``)
    while the content clearly belongs to a known type.  This inspects the
    shape and maps it to the nearest valid ``BLOCK_TYPES`` entry.  Returns
    ``None`` if the block is unrecognizable.
    """
    content = block.get("content")

    # Table data?
    if isinstance(content, dict):
        d = content.get("data")
        if isinstance(d, dict) and d.get("headers") and d.get("rows"):
            return "data_table"
        if content.get("headers") and content.get("rows"):
            return "data_table"
    if block.get("rows") is not None and (block.get("columns") or block.get("headers")):
        return "data_table"
    if payload.get("rows") is not None and (payload.get("columns") or payload.get("headers")):
        return "data_table"

    # Text?
    if isinstance(content, str) and content.strip():
        return "text_markdown"
    if isinstance(content, dict) and content.get("markdown"):
        return "text_markdown"

    # List items?
    if isinstance(content, dict) and isinstance(content.get("items"), list) and content["items"]:
        return "data_list"

    return None


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
    # P0: LLM frequently passes c2a_payload as a JSON string (not a dict).
    # Try to parse it before anything else so we don't crash on .get().
    if isinstance(c2a_payload, str):
        try:
            c2a_payload = json.loads(c2a_payload)
        except (json.JSONDecodeError, TypeError):
            return {"status": "failed",
                    "errors": ["c2a_payload is a string but not valid JSON — "
                               "pass a dict or a valid JSON string"],
                    "user_hint": _USER_HINT_FAILED}

    # P0: a non-None payload must be a dict (string is parsed above; a raw
    # int/float/list would otherwise crash on .get() below — that crash is
    # exactly what leaked a raw traceback to end users).
    if c2a_payload is not None and not isinstance(c2a_payload, dict):
        return {"status": "failed",
                "errors": [f"c2a_payload must be a JSON object (dict), "
                           f"got {type(c2a_payload).__name__}"],
                "user_hint": _USER_HINT_FAILED}

    # Mode 1: explicit payload
    if c2a_payload:
        from c2a_protocol import (
            C2AMessage, ContextRef, Metadata, Block, BlockContent,
            Action, ActionSecurity, State,
        )
        try:
            blocks = []
            for i, b in enumerate(c2a_payload.get("blocks", [])):
                btype = b.get("type", "text_markdown")

                # P0: Salvage invalid block types instead of failing the
                # whole card.  LLMs occasionally emit made-up types like
                # "action_link"; if the content clearly belongs to a known
                # type, use that; otherwise skip the block.
                if btype not in BLOCK_TYPES:
                    salvaged = _salvage_block_type(b, c2a_payload)
                    if salvaged is None:
                        logger.warning(
                            "c2a_render_card: skipping unrecognizable "
                            "block_%d (type=%r)", i, b.get("type"),
                        )
                        continue
                    btype = salvaged

                if btype == "data_table":
                    # Normalise to content.data.headers/rows; raise (→ failed
                    # card, not a blank success) when the table is empty.
                    content = _build_table_content(b, c2a_payload)
                elif btype == "text_markdown":
                    content = _normalize_markdown_content(b.get("content"))
                else:
                    content = b.get("content", {})
                blocks.append(Block(
                    block_id=b.get("block_id", f"block_{i}"),
                    type=btype,
                    content=BlockContent(data=content),
                ))

            # P0: If all blocks were skipped/invalid, fail loudly (no
            # empty card pretending to succeed).
            if not blocks:
                return {"status": "failed",
                        "errors": ["no valid blocks found in c2a_payload"],
                        "user_hint": _USER_HINT_FAILED}

            actions = []
            for i, a in enumerate(c2a_payload.get("actions", [])):
                intent = a.get("intent", "api_call")
                # P0: Skip invalid action intents instead of failing the
                # whole card (LLM invented "view_detail" etc.).
                if intent not in ACTION_INTENTS:
                    logger.warning(
                        "c2a_render_card: skipping action_%d with "
                        "invalid intent=%r", i, intent,
                    )
                    continue
                sec = a.get("security", {}) or {}
                actions.append(Action(
                    action_id=a.get("action_id", f"action_{i}"),
                    label=a.get("label", "操作"),
                    style=a.get("style", "secondary"),
                    intent=intent,
                    payload=a.get("payload", {}) or {},
                    security=ActionSecurity(
                        requires_auth=sec.get("requires_auth", False),
                        required_permissions=sec.get("required_permissions", []),
                        confirmation_prompt=sec.get("confirmation_prompt"),
                    ),
                ))
            # ── Parse metadata (summary, buttons, etc.) from the payload ──
            meta_raw = c2a_payload.get("metadata", {}) or {}
            buttons = None
            if meta_raw.get("buttons"):
                from c2a_protocol.models import Button as _Button
                buttons = []
                for bi, braw in enumerate(meta_raw["buttons"]):
                    if isinstance(braw, dict):
                        url_t = braw.get("url_template", "")
                        if not url_t:
                            # Navigation-only: button without URL is dropped, not executed
                            logger.warning(
                                "c2a_render_card: skipping button_%d (no url_template)", bi
                            )
                            continue
                        buttons.append(_Button(
                            id=braw.get("id", f"btn_{bi}"),
                            label=braw.get("label", "操作"),
                            scope=braw.get("scope", "card"),
                            url_template=url_t,
                            style=braw.get("style", "secondary"),
                        ))
                if not buttons:
                    buttons = None

            msg = C2AMessage(
                protocol_version=c2a_payload.get("protocol_version", PROTOCOL_VERSION),
                message_id=c2a_payload.get("message_id", f"msg_{len(blocks)}"),
                context_ref=ContextRef(session_id=session_id),
                metadata=Metadata(
                    generated_by="c2a_render_card",
                    source_system=meta_raw.get("source_system"),
                    summary=meta_raw.get("summary"),
                    buttons=buttons,
                ),
                blocks=blocks,
                actions=actions,
                state=State(status="rendered"),
            )
            validate_c2a_message(msg)
            return {"status": "success", "c2a_message": msg.to_dict(),
                    "c2a_json": msg.to_json(indent=2), "errors": []}
        except (C2AValidationError, ValueError) as e:
            # ValueError comes from _build_table_content when a data_table
            # block has no recoverable rows — we must NOT report success for
            # an empty table (that is the "27 rows shown, user sees nothing" bug).
            logger.warning("c2a_render_card payload invalid/empty: %s", e)
            return {"status": "failed", "errors": [str(e)],
                    "user_hint": _USER_HINT_FAILED}

    # Mode 2: raw tool output → implicit conversion
    if tool_output is not None and isinstance(tool_output, str):
        # P0-class tolerance: the LLM sometimes forwards the raw tool
        # response as a JSON *string* instead of a dict.
        try:
            tool_output = json.loads(tool_output)
        except (json.JSONDecodeError, TypeError):
            return {"status": "failed",
                    "errors": ["tool_output is a string but not valid JSON — "
                               "pass the tool's dict output or a valid JSON string"],
                    "user_hint": _USER_HINT_FAILED}

    if tool_output:
        converted = convert_tool_output_to_c2a(tool_name, tool_output, session_id)
        if converted is None:
            return {"status": "skipped",
                    "errors": ["tool_output contains no data list to render as a C2A card"],
                    "user_hint": _USER_HINT_SKIPPED}
        return {"status": "success", "c2a_message": converted.to_dict(),
                "c2a_json": converted.to_json(indent=2), "errors": []}

    return {"status": "failed",
            "errors": ["provide c2a_payload or (tool_output + tool_name)"],
            "user_hint": _USER_HINT_FAILED}


# ---------------------------------------------------------------------------
# Framework-native tool registration (CoApis / AgentScope)
# ---------------------------------------------------------------------------
@_register(
    name="c2a_render_card",
    description=(
        "渲染并校验 C2A (Chat-to-Action) 交互卡片，供前端渲染数据表格、行级链接与操作按钮。"
        "当需要以交互式 UI（而非纯文本）呈现列表/表格/表单/操作时，优先用本工具。\n"
        "★ 有工具/MCP 原始数据时，务必只传 tool_output(+tool_name)，切勿自己拼 payload——"
        "工具会自动转成合法 data_table（含表头、行、行链接），最不易出错。\n"
        "★★ tool_output 必须原样传入该工具返回的完整 dict（MCP 工具返回形如 "
        "{\"result\": \"<JSON>\", \"is_error\": false, \"metadata\": {...}}——整段照传，"
        "包括 result 字符串和 metadata，不要只摘 result 里的业务数据、不要自己解析或改写；"
        "行级链接正是靠 metadata 里的 action_templates 生成的）。\n"
        "手动拼 c2a_payload 时的严格格式：\n"
        "• 合法 block type：text_markdown | data_table | data_list | form_definition | custom_component。\n"
        "• text_markdown：content 必须是对象 {\"markdown\": \"...\"}，不要传裸字符串。\n"
        "• data_table：content 必须是对象 {\"data\": {\"headers\": [\"列1\",\"列2\"], "
        "\"rows\": [[\"值1\",\"值2\"]]}}——headers 为字符串数组（列名），rows 为字符串二维数组"
        "（每行与 headers 一一对应）。表格数据必须非空，否则整卡判为 failed。\n"
        "• 合法 action intent：api_call | function_invoke | web_redirect | "
        "workflow_trigger | form_submit | custom_extension（不要用 view_detail 等自造值）。\n"
        "不要把 columns/rows 放在 payload 顶层——必须放进 data_table block 的 content.data 内。\n"
        "★ metadata 辅助决策字段（推荐提供）：\n"
        "• metadata.summary：一段简短的辅助决策文本（关键结论/风险提示/下一步建议），"
        "纯展示，不驱动渲染分支。\n"
        "• metadata.buttons：纯导航按钮列表，每项 {id, label, scope, url_template, style}。"
        "scope=\"card\" 渲染在卡片底部，scope=\"row\" 按行渲染（url_template 支持 {列名} 占位符）。"
        "AI 不执行业务操作——按钮只跳转外部系统页面，用户在那里完成审批/导出等操作。\n"
        "• metadata.source_system：数据来源系统标识（如 oa_system、erp）。\n"
        "★ 失败处理（强制）：若返回 status=\"failed\" 或 \"skipped\"，禁止向用户展示本工具返回的"
        "任何原始内容（JSON、错误码、Python 结构、字段名）。正确做法：把数据整理成 Markdown 表格"
        "直接写进你的文字回复，并简短说明卡片未能渲染、已改为文字展示。"
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
    **kwargs: Any,
) -> Dict[str, Any]:
    """解析并验证 C2A payload（或自动转换工具输出）为可渲染的 C2A 消息。

    两种输入模式（互斥，c2a_payload 优先）：
      * **推荐**：只传 ``tool_output`` + ``tool_name``（MCP/工具的原始返回）。
        工具自动检测数据列表并生成合法 data_table（表头 + 行 + 行链接），最不易出错。
      * 手动：传完整 ``c2a_payload``。此时 blocks 的 content 必须是 *对象*：
          - text_markdown → ``{"markdown": "..."}``
          - data_table    → ``{"data": {"headers": ["列1", ...], "rows": [["值", ...], ...]}}``
            （表格数据必须非空，否则返回 failed 而不是空白卡）
        合法 block type：text_markdown / data_table / data_list / form_definition /
        custom_component；合法 action intent：api_call / function_invoke / web_redirect /
        workflow_trigger / form_submit / custom_extension。

    Args:
        c2a_payload: 完整 C2A 消息负载，含 protocol_version / blocks / actions。
            blocks 为 [{type, content}]（content 为对象，见上），actions 为
            [{action_id, label, intent, payload}]。
        tool_output: MCP 或任意工具的原始返回（dict）。提供后自动检测数据列表并
            生成 data_table 卡片（含 row_link 行链接）；无数据列表时返回 skipped。
        tool_name: 与 tool_output 配套，用于生成 action id 与 endpoint。
        session_id: 会话标识，写入 context_ref。

    Returns:
        ``{"status": "success"|"failed"|"skipped", "c2a_message": {...},
        "c2a_json": "...", "errors": [...]}``
        ——空表格 / 格式非法返回 ``failed``（含具体原因），不会再假成功。
    """
    # Tolerate hallucinated / unknown kwargs (e.g. an LLM emitting a
    # non-existent ``card_id``). Log once so the hallucination is visible in
    # logs, but do NOT crash: the previous bare TypeError escaped the function
    # (raised before the body ran) and leaked a raw Python error to the user,
    # which aborts the whole card render. Ignore them and proceed.
    if kwargs:
        logger.warning(
            "c2a_render_card: ignoring unexpected arguments: %s",
            sorted(kwargs.keys()),
        )

    return render_card_payload(
        c2a_payload=c2a_payload,
        tool_output=tool_output,
        tool_name=tool_name,
        session_id=session_id,
    )
