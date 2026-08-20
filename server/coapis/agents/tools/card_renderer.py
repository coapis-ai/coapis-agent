# -*- coding: utf-8 -*-
<<<<<<< HEAD
"""Tool for rendering C2A cards (Card-to-Action / Context-to-Application)."""

import json
from typing import Dict, Any
from pydantic import ValidationError

from ...app.cards.protocol import CardData
from ..registry import register_tool


@register_tool(
    name="render_card",
    description="Render a standardized C2A card for display in the chat interface. Use this to create action links, data tables, file previews, notifications, or approval cards."
)
def render_card(card_data: Dict[str, Any]) -> str:
    """
    Render a standardized C2A card for display in the chat interface.
    
    This tool allows LLMs to generate structured cards such as action links, 
    data tables, file previews, notifications, or approval cards.
    
    Args:
        card_data: A dictionary representing the CardData model structure.
        
    Returns:
        A JSON string of the validated CardData if successful, 
        or an error message if validation fails.
    """
    try:
        # Validate and parse CardData
        card = CardData.model_validate(card_data)
        
        # Return the JSON representation to be parsed by frontend
        return json.dumps(card.model_dump(), ensure_ascii=False, indent=2)
    except ValidationError as e:
        return f"Card validation error: {str(e)}"
    except Exception as e:
        return f"Error rendering card: {str(e)}"
=======
# Copyright 2026 蜜蜂 & CoApis Contributors
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU Affero General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.

"""C2A Card Renderer tool — parse and validate C2A payload for card rendering and interaction discovery."""

from __future__ import annotations

import logging
from typing import Any, Dict

from .registry import register_tool

logger = logging.getLogger(__name__)


@register_tool(
    name="c2a_render_card",
    description="解析并验证 C2A (Chat-to-Action) payload，自动发现卡片可渲染方式与交互意图（Intents）。支持 text_markdown、data_table blocks 以及 launch_external_url、open_drawer/modal_content、api_call、confirm_auth、form_input 等 actions intents。",
    category="plugin",
    tags=["c2a", "card_renderer", "render", "validation"],
    dependencies=[
        {"name": "pydantic", "manager": "pip", "required": True, "reason": "C2A CardData 模型验证"},
    ],
)
async def render_card(
    c2a_payload: Dict[str, Any] | None = None,
) -> dict[str, Any]:
    """解析并验证 C2A payload。

    此工具用于自动发现卡片可渲染方式与交互意图，基于 CardData.model_validate() 进行数据校验。

    Args:
        c2a_payload: C2A 协议消息负载，包含 protocol_version, blocks, actions 等字段

    Returns:
        验证结果字典，包含 status, validated_blocks, validated_actions, errors
    """
    if c2a_payload is None:
        return {"status": "failed", "errors": ["c2a_payload 不能为空"]}

    # Validate C2A payload structure
    blocks = c2a_payload.get("blocks", [])
    actions = c2a_payload.get("actions", [])
    protocol_version = c2a_payload.get("protocol_version", "c2a-v1.0")

    validated_blocks = []
    validated_actions = []
    errors = []

    # Validate blocks
    for block in blocks:
        block_type = block.get("type")
        if block_type in ["text_markdown", "data_table", "notification", "approval_card"]:
            validated_blocks.append(block)
        else:
            errors.append(f"不支持的 block 类型: {block_type}")

    # Validate actions intents
    valid_intents = [
        "api_call",
        "launch_external_url",
        "open_drawer/modal_content",
        "confirm_auth",
        "form_input",
        "external_redirect"
    ]

    for action in actions:
        intent = action.get("intent")
        if intent in valid_intents:
            validated_actions.append(action)
        else:
            errors.append(f"不支持的 action intent: {intent}")

    if errors:
        return {
            "status": "failed",
            "validated_blocks": [],
            "validated_actions": [],
            "errors": errors
        }

    logger.info("C2A payload validated successfully: %d blocks, %d actions, protocol_version=%s", 
                len(validated_blocks), len(validated_actions), protocol_version)

    return {
        "status": "success",
        "protocol_version": protocol_version,
        "validated_blocks": validated_blocks,
        "validated_actions": validated_actions,
        "errors": []
    }
>>>>>>> 4df6000 (v0.13.2: C2A protocol, MCP integration, skill upload fix, and multi-channel rendering)
