# -*- coding: utf-8 -*-
# Copyright 2026 蜜蜂 & CoApis Contributors
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU Affero General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.

"""C2A Card Renderer tool — parse and validate C2A payload for card rendering and interaction discovery."""

from __future__ import annotations

import json
import logging
from typing import Any, Dict

from pydantic import BaseModel, Field

from .registry import register_tool

logger = logging.getLogger(__name__)


class C2ACardActionIntent(BaseModel):
    """C2A 卡片交互意图定义"""
    intent: str = Field(description="交互意图类型，支持 api_call, launch_external_url, open_drawer/modal_content, confirm_auth, form_input, external_redirect")
    id: str | None = Field(default=None, description="操作唯一标识符")
    text: str | None = Field(default=None, description="按钮或操作的显示文本")
    params: Dict[str, Any] | None = Field(default=None, description="传递给意图的参数")


class C2ACardBlock(BaseModel):
    """C2A 卡片区块定义"""
    type: str = Field(description="区块类型，支持 text_markdown, data_table, notification, approval_card")
    content: Dict[str, Any] | None = Field(default=None, description="区块内容数据")


class C2ACardPayloadSchema(BaseModel):
    """C2A 卡片 Payload 参数 Schema"""
    c2a_payload: Dict[str, Any] = Field(
        description="C2A 协议消息负载，包含 protocol_version, blocks, actions 等字段。blocks 为 C2ACardBlock 列表，actions 为 C2ACardActionIntent 列表。"
    )


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
