# -*- coding: utf-8 -*-
"""WeCom Universal C2A Extension Card (Universal Chat-to-Agent extension card).

Provides a universal template card for rendering tool calls, agent actions,
or C2A-specific extensions. Adapted for CoApis runtime.

Refs: https://developer.work.weixin.qq.com/document/path/101032
      https://developer.work.weixin.qq.com/document/path/101027
"""
from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any, Dict

if TYPE_CHECKING:
    from ..channel import WecomChannel

logger = logging.getLogger(__name__)


# =====================================================================
# Module-level metadata (read by the dispatcher when registering)
# =====================================================================

NAME = "c2a_extension"

# Outbound metadata.message_type that triggers this card kind.
MESSAGE_TYPE = "c2a_extension_card"

# Unique prefix embedded in ``task_id`` so the dispatcher can route the
# inbound callback to this card kind.
TASK_ID_PREFIX = "c2a_ext_"


# =====================================================================
# Constants (internal)
# =====================================================================

_RESOLVED_CARD_URL = "https://coapis.agentscope.io"


# =====================================================================
# Outbound: render
# =====================================================================


async def render(
    channel: "WecomChannel",
    to_handle: str,
    event: Any,
    send_meta: Dict[str, Any],
    meta: Dict[str, Any],
) -> bool:
    """Render a universal C2A extension card for tool calls or agent actions."""
    request_id = str(meta.get("request_id") or meta.get("task_id", "unknown"))
    if not request_id:
        return False

    if not channel.enabled or not channel._client:
        return False

    frame = send_meta.get("wecom_frame")
    if not frame:
        logger.warning(
            "wecom c2a extension card: no frame for to_handle=%s",
            (to_handle or "")[:40],
        )
        return False

    # Build the universal C2A extension card (text_notice type)
    action_desc = str(meta.get("action_desc") or meta.get("tool_name") or "Processing C2A extension...")
    
    template_card = {
        "card_type": "text_notice",
        "task_id": f"{TASK_ID_PREFIX}{request_id}",
        "main_title": {
            "title": "🔄 C2A Extension Action",
            "desc": action_desc,
        },
        "card_action": {"type": 1, "url": _RESOLVED_CARD_URL},
    }

    try:
        await channel._client.reply_template_card(
            frame,
            template_card,
        )
        logger.info(
            "wecom c2a extension card sent: task_id=%s action_desc=%s",
            f"{TASK_ID_PREFIX}{request_id}"[:8],
            action_desc[:30],
        )
        return True
    except Exception:
        logger.exception(
            "wecom c2a extension card send failed: task_id=%s",
            f"{TASK_ID_PREFIX}{request_id}"[:8],
        )
        return False


# =====================================================================
# Inbound: handle
# =====================================================================


async def handle(
    channel: "WecomChannel",
    frame: Any,
) -> None:
    """Process a universal C2A extension callback."""
    body = frame.get("body") or {} if isinstance(frame, dict) else {}
    event_body = body.get("event") or {}
    
    task_id = "unknown"
    if hasattr(frame, 'task_id'):
        task_id = getattr(frame, 'task_id', 'unknown')
    elif isinstance(frame, dict):
        task_id = frame.get('task_id') or body.get('event', {}).get('template_card_event', {}).get('task_id')

    logger.info(
        "wecom c2a extension card event received: task_id=%s",
        str(task_id)[:20],
    )
    
    # Handle logic for C2A extension callbacks if needed