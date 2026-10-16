"""C2A payload converters.

Converts between the raw LLM output (a JSON payload) and the typed
:class:`C2AMessage` model.  This is the bridge the integration layer uses
when the host LLM returns a C2A-rendered payload.
"""
from __future__ import annotations

from typing import Any, Dict, List

from .models import (
    C2AMessage,
    Block,
    BlockContent,
    State,
    Metadata,
)


def c2a_payload_from_llm(
    payload: Dict[str, Any],
    *,
    tool_name: str,
    tool_call_id: str,
) -> C2AMessage:
    """Build a :class:`C2AMessage` from a raw LLM C2A payload.

    Handles both the full C2A message shape (``blocks`` / ``state`` / …) and
    a minimal shape where the LLM returned a bare block list.  The
    ``tool_name`` / ``tool_call_id`` are stamped into the message id prefix so
    the host framework can match the card to the originating tool call.

    Raises ``ValueError`` for an empty / malformed payload.
    """
    if not payload or not isinstance(payload, dict):
        raise ValueError("C2A payload must be a non-empty object")

    raw_blocks = payload.get("blocks") or payload.get("content") or []
    if not raw_blocks:
        raise ValueError("C2A payload has no blocks")
    if isinstance(raw_blocks, dict):
        raw_blocks = [raw_blocks]

    blocks: List[Block] = []
    for b in raw_blocks:
        if not isinstance(b, dict) or not b.get("type"):
            continue
        content = b.get("content")
        if content is None:
            # LLM put block content flat at block level, e.g.
            # {"type": "text_markdown", "markdown": "..."} — gather it.
            content = {k: v for k, v in b.items() if k not in ("block_id", "type")}
        if not isinstance(content, dict):
            content = {"data": content}
        blocks.append(
            Block(
                block_id=b.get("block_id", ""),
                type=b["type"],
                content=BlockContent(data=content),
            )
        )
    if not blocks:
        raise ValueError("C2A payload produced no valid blocks")

    # State
    raw_state = payload.get("state") or {}
    state = State(
        status=raw_state.get("status", "completed"),
        error_code=raw_state.get("error_code"),
        error_message=raw_state.get("error_message"),
    )

    # Metadata
    raw_meta = payload.get("metadata") or {}
    metadata = Metadata(
        generated_by=raw_meta.get("generated_by", tool_name),
        ttl_seconds=raw_meta.get("ttl_seconds"),
        source_system=raw_meta.get("source_system"),
    )

    return C2AMessage(
        message_id=f"{tool_call_id}_{raw_meta.get('message_id', '')}".strip("_")
        or f"{tool_call_id}",
        metadata=metadata,
        blocks=blocks,
        actions=list(payload.get("actions", [])),
        state=state,
        suggestions=list(payload.get("suggestions", [])),
    )
