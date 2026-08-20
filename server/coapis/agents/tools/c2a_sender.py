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

"""C2A (Chat-to-Action) message sender tool — send C2A interactive messages via service interface."""

from __future__ import annotations

import json
import logging
import uuid
from typing import Any, Dict

from .registry import register_tool

logger = logging.getLogger(__name__)


@register_tool(
    name="c2a_send_c2a_message",
    description="发送 C2A (Chat-to-Action) 交互式消息到指定渠道。支持卡片、表格、表单等交互元素。默认使用 console 渠道，或根据智能体配置的 Channel 进行发送。",
    category="plugin",
    tags=["c2a", "message", "channel", "card"],
    dependencies=[
        {"name": "httpx", "manager": "pip", "required": True, "reason": "C2A 服务接口调用"},
    ],
)
async def send_c2a_message(
    target_channel: str = "console",
    c2a_payload: Dict[str, Any] | None = None,
) -> dict[str, Any]:
    """发送 C2A (Chat-to-Action) 交互式消息。

    此工具封装了 C2A 服务接口，供 Agent 调用以发送带有交互元素（卡片、表格、表单、按钮）的消息。

    Args:
        target_channel: 目标渠道 (如 console, wecom, dingtalk, feishu)。默认为 'console'。
        c2a_payload: C2A 协议消息负载，包含 protocol_version, message_id, blocks, actions 等字段

    Returns:
        发送结果字典，包含 status, message_id, timestamp
    """
    if not target_channel:
        return {"error": "target_channel 是必填项"}

    if c2a_payload is None:
        c2a_payload = {}

    # Generate message ID if not provided
    if "message_id" not in c2a_payload:
        c2a_payload["message_id"] = f"msg_c2a_{uuid.uuid4().hex[:12]}"

    if "protocol_version" not in c2a_payload:
        c2a_payload["protocol_version"] = "c2a-v1.0"

    try:
        # Try to get channel manager from multi-agent manager (same pattern as proactive_trigger.py)
        try:
            from ....app.agent_context import get_current_agent_id
            from ....app.multi_agent_manager import MultiAgentManager
            
            active_agent_id = get_current_agent_id()
            logger.info(f"[c2a_sender] active_agent_id={active_agent_id}")
            
            multi_agent_manager = MultiAgentManager()
            workspace = await multi_agent_manager.get_agent(active_agent_id)
            channel_manager = workspace.channel_manager
            
            logger.info(f"[c2a_sender] channel_manager={channel_manager is not None}")
            
            if channel_manager:
                # Build standardized C2A message structure
                standardized_c2a_message = {
                    "id": c2a_payload.get("message_id"),
                    "role": "system",
                    "content": [
                        {
                            "type": "c2a_protocol",
                            "data": c2a_payload
                        }
                    ],
                    "meta": {
                        "message_id": c2a_payload.get("message_id")
                    }
                }
                
                # Send via channel manager
                await channel_manager.send_c2a(
                    channel=target_channel,
                    user_id="console",
                    session_id=f"{target_channel}:console",
                    c2a_payload=standardized_c2a_message,
                    meta={"message_id": c2a_payload.get("message_id")}
                )
                
                logger.info(f"[c2a_sender] Sent via channel_manager: channel={target_channel} message_id={c2a_payload.get('message_id')}")
                
                import time
                return {
                    "status": "success",
                    "message_id": c2a_payload.get("message_id"),
                    "timestamp": int(time.time()),
                    "channel": target_channel,
                    "method": "channel_manager"
                }
        except Exception as e:
            logger.warning(f"[c2a_sender] Failed to send via channel_manager: {e}", exc_info=True)
        
        # Fallback: simulate C2A service interface call
        logger.info(f"[c2a_sender] Sent via tool (simulated): channel={target_channel} message_id={c2a_payload.get('message_id')}")

        import time
        return {
            "status": "success",
            "message_id": c2a_payload.get("message_id"),
            "timestamp": int(time.time()),
            "channel": target_channel,
            "method": "simulated",
            "note": "Message structure built but not actually sent to channel. Channel manager not available."
        }

    except Exception as e:
        logger.error(f"[c2a_sender] C2A message send failed via tool: {e}", exc_info=True)
        return {"error": str(e), "status": "failed"}
