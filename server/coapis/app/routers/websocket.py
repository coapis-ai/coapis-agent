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

"""WebSocket router - Real-time streaming chat endpoints.

Provides WebSocket endpoints for streaming agent responses.
This enables real-time interaction without waiting for full responses.

Usage:
    ws = await websockets.connect("ws://localhost:8000/ws/chat/{agent_id}")
    await ws.send(json.dumps({"message": "Hello!", "chat_id": "default"}))
    async for chunk in ws:
        data = json.loads(chunk)
        if data["type"] == "chunk":
            print(data["content"], end="", flush=True)
        elif data["type"] == "done":
            print("\nDone!")
            break
"""

import asyncio
import json
import logging
import time
from typing import Dict, Any, Optional

from fastapi import APIRouter, HTTPException, WebSocket, WebSocketDisconnect, Query
from fastapi.requests import Request

logger = logging.getLogger(__name__)

router = APIRouter(tags=["websocket"])


@router.websocket("/ws/chat/{agent_id}")
async def websocket_chat(
    websocket: WebSocket,
    agent_id: str,
):
    """WebSocket endpoint for streaming chat.

    Protocol:
        Client → Server: {"message": "...", "chat_id": "default"}
        Server → Client: {"type": "chunk", "content": "..."}
        Server → Client: {"type": "done", "response": "..."}
        Server → Client: {"type": "error", "error": "..."}
    """
    await websocket.accept()
    manager = websocket.app.state.manager

    if not manager:
        await websocket.send_json({"type": "error", "error": "Agent manager not initialized"})
        await websocket.close()
        return

    workspace = manager.get_workspace(agent_id)
    if not workspace:
        await websocket.send_json({"type": "error", "error": "Agent not found"})
        await websocket.close()
        return

    logger.info(f"WebSocket chat connected: agent={agent_id}")
    await websocket.send_json({"type": "connected", "agent_id": agent_id})

    try:
        while True:
            # Receive message from client
            data = await websocket.receive_text()
            try:
                msg = json.loads(data)
            except json.JSONDecodeError:
                await websocket.send_json({"type": "error", "error": "Invalid JSON"})
                continue

            user_message = msg.get("message", "")
            chat_id = msg.get("chat_id", "default")

            if not user_message:
                await websocket.send_json({"type": "error", "error": "Missing 'message' field"})
                continue

            # ── Input Guard: 内容安全检测 ──
            from coapis.security.input_guard import get_input_guard_engine
            guard_result = get_input_guard_engine().check(user_message)
            if not guard_result.is_safe:
                logger.warning(
                    "Input guard blocked message from agent=%s: %s",
                    agent_id, [f.rule_id for f in guard_result.findings],
                )
                await websocket.send_json({
                    "type": "error",
                    "error": guard_result.block_message,
                })
                continue

            logger.info(f"WebSocket chat: agent={agent_id}, chat={chat_id}, msg={user_message[:50]}")

            # Get chat context
            context = await workspace._get_chat_context(chat_id)

            # Add user message to history
            context.add_message("user", user_message)

            # Stream response from agent
            full_response = ""
            try:
                async for chunk in workspace.core.stream_chat(user_message, context, show_tool_details=True):
                    full_response += chunk
                    await websocket.send_json({
                        "type": "chunk",
                        "content": chunk,
                        "timestamp": time.time(),
                    })

                # Add assistant response to history
                context.add_message("assistant", full_response)

                # Send done signal
                await websocket.send_json({
                    "type": "done",
                    "response": full_response,
                    "chat_id": chat_id,
                    "timestamp": time.time(),
                })

            except Exception as e:
                logger.error(f"WebSocket chat error: {e}")
                await websocket.send_json({
                    "type": "error",
                    "error": str(e),
                })

    except WebSocketDisconnect:
        logger.info(f"WebSocket chat disconnected: agent={agent_id}")
    except Exception as e:
        logger.error(f"WebSocket error: {e}")
        try:
            await websocket.send_json({"type": "error", "error": str(e)})
        except Exception:
            pass
