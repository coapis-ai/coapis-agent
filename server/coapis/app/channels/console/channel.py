# -*- coding: utf-8 -*-
"""Console Channel for CoApis.

Simplified from CoApis's ConsoleChannel (604 lines).
Stripped terminal printing, media extraction, and debounce logic.
Keeps the core stream_one SSE event streaming pipeline.
"""
from __future__ import annotations

import asyncio
import json
import logging
from typing import Any, AsyncGenerator, Dict, List, Optional, Union

from agentscope_runtime.engine.schemas.agent_schemas import (
    RunStatus,
    ContentType,
    TextContent,
    ImageContent,
    VideoContent,
    AudioContent,
    FileContent,
    RefusalContent,
    MessageType,
)

from ..base import (
    BaseChannel,
    OnReplySent,
    OutgoingContentPart,
    ProcessHandler,
)
from ...console_push_store import append as push_store_append

logger = logging.getLogger(__name__)


class ConsoleChannel(BaseChannel):
    """Console Channel for CoApis Web UI.

    Handles SSE event streaming for the web console.
    Input: AgentRequest (from console.py route)
    Output: SSE-formatted event strings matching @agentscope-ai/chat expectations.
    """

    channel = "console"

    def __init__(
        self,
        process: ProcessHandler,
        on_reply_sent: OnReplySent = None,
        show_tool_details: bool = True,
        filter_tool_messages: bool = False,
        filter_thinking: bool = False,
    ):
        """Initialize ConsoleChannel.

        Args:
            process: Handler that accepts AgentRequest and streams Event.
            on_reply_sent: Callback when reply is sent.
            show_tool_details: Whether to show tool execution details.
            filter_tool_messages: Whether to filter out tool messages.
            filter_thinking: Whether to filter thinking/reasoning blocks.
        """
        super().__init__(
            process=process,
            on_reply_sent=on_reply_sent,
            show_tool_details=show_tool_details,
            filter_tool_messages=filter_tool_messages,
            filter_thinking=filter_thinking,
        )

    def build_agent_request_from_native(
        self,
        native_payload: Any,
    ) -> Any:
        """Build AgentRequest from console native payload (dict with
        channel_id, sender_id, content_parts, meta).
        """
        payload = native_payload if isinstance(native_payload, dict) else {}
        channel_id = payload.get("channel_id") or self.channel
        sender_id = payload.get("sender_id") or ""
        content_parts = payload.get("content_parts") or []
        meta = payload.get("meta") or {}
        session_id = self.resolve_session_id(sender_id, meta)

        return self.build_agent_request_from_user_content(
            channel_id=channel_id,
            sender_id=sender_id,
            session_id=session_id,
            content_parts=content_parts,
            channel_meta=meta,
        )

    async def stream_one(
        self,
        payload: Any,
    ) -> AsyncGenerator[str, None]:
        """Process one payload and yield SSE-formatted events.

        This is the core streaming method that the console.py route calls.
        It delegates to self._process (the ProcessHandler), intercepts events,
        applies filters, and yields SSE-formatted strings.

        Args:
            payload: Either an AgentRequest or a native dict payload.

        Yields:
            SSE-formatted event strings like "data: {...}\\n\\n"
        """
        # ── Resolve payload to AgentRequest ──
        if isinstance(payload, dict) and "content_parts" in payload:
            request = self.build_agent_request_from_native(payload)
            session_id = getattr(request, "session_id", "") or ""
            # Extract chat_id from meta for frontend filtering
            meta = payload.get("meta", {})
            chat_id = meta.get("chat_id", "") or meta.get("session_id", "")
        else:
            request = payload
            session_id = getattr(request, "session_id", "") or ""
            chat_id = session_id  # Fallback

        last_response = None
        event_count = 0

        try:
            # self._process is the ProcessHandler callable passed to __init__
            async for event in self._process(request):
                event_count += 1
                obj = getattr(event, "object", None)
                status = getattr(event, "status", None)
                ev_type = getattr(event, "type", None)

                logger.debug(
                    "console event #%s: object=%s status=%s type=%s",
                    event_count,
                    obj,
                    status,
                    ev_type,
                )

                # NOTE: channel-level filtering removed (v0.8.2).
                # All filtering is now handled centrally by workspace.py's
                # RenderStyle + MessageRenderer. The old _filter_thinking /
                # _filter_tool_messages params are kept for backward compat
                # but are no longer applied here.

                # ── Handle response completion: extract media messages ──
                if obj == "response" and status == RunStatus.Completed:
                    event_output = getattr(event, "output", None)
                    if event_output is not None:
                        output_list = list(event_output)
                        event.output = []
                        for message in output_list:
                            event.output.append(message)
                            # Skip media extraction for web UI (handled by frontend)

                # ── Serialize and yield event ──
                data = _serialize_event(event)
                
                # Add chat_id to metadata for frontend session isolation
                # Frontend uses chat_id (UUID) to filter SSE events from different chats
                if chat_id:
                    try:
                        event_dict = json.loads(data)
                        if "metadata" not in event_dict:
                            event_dict["metadata"] = {}
                        event_dict["metadata"]["chat_id"] = chat_id
                        data = json.dumps(event_dict, ensure_ascii=False)
                    except (json.JSONDecodeError, TypeError):
                        pass  # Keep original data if parsing fails
                
                yield f"data: {data}\n\n"

                # ── Handle message completion ──
                if obj == "message" and status == RunStatus.Completed:
                    # For web UI, no need to extract media or print
                    pass

                if obj == "response":
                    last_response = event

        except asyncio.CancelledError:
            logger.info(
                "console stream cancelled: session=%s",
                session_id[:30] if session_id else "N/A",
            )
            raise

        except Exception as e:
            logger.exception(
                "console stream_one failed: session=%s",
                session_id[:30] if session_id else "N/A",
            )
            # Yield error event
            error_event = {
                "object": "response",
                "status": "failed",
                "error": str(e),
            }
            yield f"data: {json.dumps(error_event)}\n\n"

        # ── Post-stream callbacks ──
        to_handle = getattr(request, "user_id", "") or ""
        if self._on_reply_sent:
            self._on_reply_sent(
                self.channel,
                to_handle,
                session_id or f"{self.channel}:{to_handle}",
            )

        logger.info(
            "console stream done: event_count=%s has_response=%s",
            event_count,
            last_response is not None,
        )

    async def send(
        self,
        to_handle: str,
        text: str,
        meta: Optional[Dict[str, Any]] = None,
    ) -> None:
        """Send a text message proactively to the console.

        Used by CronExecutor (task_type='text') and other proactive
        notification paths. Stores the message in console_push_store
        so the frontend can retrieve it via /api/console/push.

        Args:
            to_handle: Target handle (session_id or channel:user_id).
            text: The message body to send.
            meta: Optional metadata (currently unused).
        """
        if not text:
            return

        # Extract session_id from to_handle
        # to_handle format: "console:user_id" or "console:user_id:timestamp"
        session_id = to_handle or "console:unknown"

        logger.info(
            "ConsoleChannel.send: session_id=%s len=%s",
            session_id[:60],
            len(text),
        )

        try:
            await push_store_append(session_id, text)
            logger.info(
                "ConsoleChannel.send: message stored for session=%s",
                session_id[:60],
            )
        except Exception as e:
            logger.error(
                "ConsoleChannel.send failed: session_id=%s error=%s",
                session_id[:60],
                repr(e),
            )

    async def consume_one(self, payload: Any) -> None:
        """Process one payload; drain stream_one (no terminal output)."""
        async for _ in self.stream_one(payload):
            pass


def _serialize_event(event: Any) -> str:
    """Serialize an event to JSON string.

    Tries model_dump_json() first (Pydantic v2), then .json(),
    then falls back to string representation.
    """
    if hasattr(event, "model_dump_json"):
        return event.model_dump_json()
    elif hasattr(event, "json"):
        return event.json()
    else:
        return json.dumps({"text": str(event)})
