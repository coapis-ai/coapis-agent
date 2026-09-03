"""
C2A (Chat-to-Action) Interactive Message Protocol - Python Data Models

This module provides the data structures for the C2A protocol.

Protocol version: c2a-v1.0 (the single canonical version).
All producers (mcp_parser, tools, LLM) and consumers (validator, renderers)
speak this version — there is no v2/v3 fork.
"""

import json
import uuid
from datetime import datetime
from typing import Any, Dict, List, Optional
from dataclasses import dataclass, field, asdict

# Single canonical protocol version (see project README).
PROTOCOL_VERSION = "c2a-v1.0"

# Canonical block types (must match schemas/c2a-message-v1.jsonschema).
BLOCK_TYPES = (
    "text_markdown",
    "data_table",
    "data_list",
    "form_definition",
    "custom_component",
)

# Canonical action intents (must match schemas/c2a-message-v1.jsonschema).
ACTION_INTENTS = (
    "api_call",
    "function_invoke",
    "web_redirect",
    "workflow_trigger",
    "form_submit",
    "custom_extension",
)


@dataclass
class ContextRef:
    session_id: str
    task_id: Optional[str] = None
    scene_id: Optional[str] = None


@dataclass
class Button:
    """A pure *navigation* button — opens an external URL, never executes
    business logic in the AI.

    Boundary principle: the AI only *helps decide* (shows the card, the summary,
    and the buttons); the external system *performs* the action (approve / reject /
    export / view). So every button is just ``label + url + scope`` — there is no
    ``api_call`` / ``function_invoke`` behind it.

    - ``scope="card"``: rendered once under the card (e.g. 去审批 / 查看详情 / 导出).
    - ``scope="row"``:  rendered per table row; ``url_template`` may use ``{field}``
      placeholders resolved against the row data.

    A button is renderable only when ``url_template`` is non-empty; a button with
    no URL (e.g. a legacy ``api_endpoint``-only export) is dropped, not executed.
    """
    id: str
    label: str
    scope: str = "card"  # "card" | "row"
    url_template: str = ""  # required to render; {field} for row scope
    style: str = "secondary"  # primary | secondary | danger | success | warning | text


@dataclass
class Metadata:
    generated_by: str
    generated_at: str = field(default_factory=lambda: datetime.utcnow().isoformat() + "Z")
    ttl_seconds: Optional[int] = None
    source_system: Optional[str] = None
    attachments: Optional[List[Dict[str, Any]]] = None
    permissions_required: Optional[List[str]] = None
    # ── C2A boundary additions ──────────────────────────────────────────────
    # AI 辅助决策：关键结论 / 风险提示 / 下一步建议（纯展示文本，不驱动渲染分支）。
    summary: Optional[str] = None
    # 纯导航按钮（label + url + scope）。AI 不执行业务，只把用户带到外部系统。
    buttons: Optional[List["Button"]] = None


@dataclass
class BlockContent:
    """Generic content container — a plain dict, structure depends on block type.

    - text_markdown:  ``{"markdown": "..."}``
    - data_table:     ``{"data": {"headers": [...], "rows": [[...]]},
                        "id_field": "approval_id",
                        "row_values": [{"approval_id": "A001"}, ...],
                        "row_actions": {...}}``
    - data_list:      ``{"items": [{"key": ..., "title": ..., "subtitle": ...}]}``
    - form_definition: ``{"fields": [...], "submit_label": "..."}``
    """
    data: Dict[str, Any] = field(default_factory=dict)

    def get(self, key: str, default: Any = None) -> Any:
        """Safe accessor — ``block.content.get("markdown")`` style."""
        return (self.data or {}).get(key, default)

    def to_dict(self) -> Dict[str, Any]:
        """Serialize to the wire shape.

        The content is the dict *itself* (e.g. ``{"data": {...}, "row_actions": ...}``
        for a data_table block), NOT wrapped in an extra ``{"data": ...}`` layer.
        This is what the frontend renderer (``content.data.headers``,
        ``content.row_actions``) and the jsonschema (``dataTableContent``) expect.
        """
        return self.data if self.data is not None else {}


@dataclass
class Block:
    block_id: str = field(default_factory=lambda: f"block_{uuid.uuid4().hex[:8]}")
    type: str = "text_markdown"  # one of BLOCK_TYPES
    content: BlockContent = field(default_factory=BlockContent)

    def to_dict(self) -> Dict[str, Any]:
        """Serialize with ``content`` as the raw dict (no extra ``data`` wrap)."""
        return {
            "block_id": self.block_id,
            "type": self.type,
            "content": self.content.to_dict(),
        }


@dataclass
class ActionSecurity:
    requires_auth: bool = False
    required_permissions: List[str] = field(default_factory=list)
    confirmation_prompt: Optional[str] = None


@dataclass
class Action:
    action_id: str
    label: str
    icon: Optional[str] = None
    style: str = "secondary"  # primary, secondary, danger, success, warning, text
    disabled: bool = False
    intent: str = "api_call"  # one of ACTION_INTENTS
    payload: Dict[str, Any] = field(default_factory=dict)
    security: ActionSecurity = field(default_factory=ActionSecurity)


@dataclass
class Suggestion:
    """Quick-reply suggestion shown under the card (e.g. 导出列表 / 查看更多)."""
    suggestion_id: str
    label: str
    business_intent: str = ""
    context_data: Dict[str, Any] = field(default_factory=dict)


@dataclass
class State:
    status: str = "idle"  # idle, generating, rendered, interactive, executing, completed, failed
    error_code: Optional[str] = None
    error_message: Optional[str] = None


@dataclass
class C2AMessage:
    protocol_version: str = PROTOCOL_VERSION
    message_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    context_ref: ContextRef = field(default_factory=lambda: ContextRef(session_id="default_session"))
    metadata: Optional[Metadata] = None
    blocks: List[Block] = field(default_factory=list)
    actions: List[Action] = field(default_factory=list)
    state: State = field(default_factory=State)
    suggestions: List[Suggestion] = field(default_factory=list)
    extensions: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        """Convert the C2AMessage to a dictionary for JSON serialization."""
        d = {
            "protocol_version": self.protocol_version,
            "message_id": self.message_id,
            "context_ref": asdict(self.context_ref),
            "blocks": [b.to_dict() for b in self.blocks],
            "actions": [asdict(a) for a in self.actions],
            "state": asdict(self.state),
        }
        if self.metadata is not None:
            d["metadata"] = asdict(self.metadata)
        if self.suggestions:
            d["suggestions"] = [asdict(s) for s in self.suggestions]
        if self.extensions:
            d["extensions"] = self.extensions
        return d

    def to_json(self, indent: Optional[int] = None) -> str:
        """Convert the C2AMessage to a JSON string."""
        return json.dumps(self.to_dict(), indent=indent, ensure_ascii=False)
