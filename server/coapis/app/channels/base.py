# -*- coding: utf-8 -*-
"""
Base Channel: bound to AgentRequest/AgentResponse, unified by process.

Simplified version for CoApis - only keeps core functionality needed
for console channel. Original CoApis BaseChannel has 1324 lines with
DingTalk, WeChat, etc. support.
"""
from __future__ import annotations

import asyncio
import json
import logging
import time
import threading
from abc import ABC
from typing import (
    Optional,
    Dict,
    Any,
    List,
    Union,
    AsyncIterator,
    AsyncGenerator,
    Callable,
    TYPE_CHECKING,
)

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

# Optional callback to enqueue payload (set by manager)
EnqueueCallback = Optional[Callable[[Any], None]]

# Called when a user-originated reply was sent (channel, user_id, session_id)
OnReplySent = Optional[Callable[[str, str, str], None]]

logger = logging.getLogger(__name__)


if TYPE_CHECKING:
    from agentscope_runtime.engine.schemas.agent_schemas import (
        AgentRequest,
        AgentResponse,
        Event,
    )

# process: accepts AgentRequest, streams Event
# (including message events with status completed)
ProcessHandler = Callable[[Any], AsyncIterator["Event"]]

# Outgoing part = runtime content types (no Dict[str, Any])
OutgoingContentPart = Union[
    TextContent,
    ImageContent,
    VideoContent,
    AudioContent,
    FileContent,
    RefusalContent,
]


class BaseChannel(ABC):
    """Base for all channels. Queue lives in ChannelManager; channel defines
    how to consume via consume_one().
    """

    channel: str = "base"

    # If True, manager creates a queue and consumer loop for this channel.
    uses_manager_queue: bool = True

    # Stream types that can be streamed to the channel.  Subclasses may
    # override to enable real-time push (e.g. WeCom reply_stream).
    # Supported values: "reasoning", "message"
    _STREAMABLE_TYPES: tuple = ()

    def __init__(
        self,
        process: ProcessHandler,
        on_reply_sent: OnReplySent = None,
        show_tool_details: bool = True,
        filter_tool_messages: bool = False,
        filter_thinking: bool = False,
        streaming_enabled: bool = False,
        workspace_dir=None,
        **kwargs,
    ):
        self._process = process
        self._on_reply_sent = on_reply_sent
        # v0.8.2: workspace_dir stored in base class for all channels
        self.workspace_dir = workspace_dir

        # CommandRegistry: used by consume_one to route control commands
        # (e.g. /stop) directly to _process, while non-control commands
        # go through _consume_with_tracker for TaskTracker registration.
        from .command_registry import CommandRegistry
        self._command_registry = CommandRegistry()

        # Session rotation: per-user current session tracking.
        # Key = "channel:sender_id", Value = current session_id.
        # Used by resolve_session_id() to support /new session rotation
        # in channel layer (e.g. WeixinChannel, WeComChannel).
        self._user_sessions: Dict[str, str] = {}
        self._user_sessions_lock = threading.Lock()

        # v0.8.2: These channel-level filter params are deprecated.
        # Filtering is now handled centrally by workspace.py RenderStyle.
        # Kept for backward compat but logged as deprecated.
        import logging as _warn_log
        _warn_log.getLogger(__name__).debug(
            "DEPRECATED: filter_thinking=%s show_tool_details=%s "
            "filter_tool_messages=%s passed to %s — use agent.json "
            "channels.{channel} config instead.",
            filter_thinking, show_tool_details, filter_tool_messages,
            type(self).__name__,
        )
        self._show_tool_details = show_tool_details
        self._filter_tool_messages = filter_tool_messages
        self._filter_thinking = filter_thinking
        self.streaming_enabled = streaming_enabled

        # ── Renderer integration (aligned with QwenPaw) ──
        from .renderer import RenderStyle, MessageRenderer
        _channel_name = getattr(self, "channel", "base")
        _channel_cfg = kwargs.get("channel_cfg") or {}
        self._render_style = RenderStyle.from_channel(
            _channel_name,
            channel_config=_channel_cfg,
        )
        self._renderer = MessageRenderer(self._render_style)
        self._enqueue: EnqueueCallback = None
        self._workspace = None
        # Allowlist / denylist support (used by all channels)
        self._allow_from: List[str] = kwargs.get("allow_from") or []
        self._deny_message: str = kwargs.get("deny_message", "")
        self._dm_policy: str = kwargs.get("dm_policy", "open")
        self._group_policy: str = kwargs.get("group_policy", "open")

    def _check_allowlist(
        self, sender_id: str, is_group: bool
    ) -> tuple[bool, str]:
        """Check if sender is allowed. Returns (allowed, error_msg).

        Enhanced with AccessControlStore: when a workspace is attached,
        uses persistent per-channel ACL (whitelist/blacklist/pending).
        Falls back to simple allow_from/policy check otherwise.
        """
        # Try AccessControlStore first (persistent per-channel ACL)
        ws = getattr(self, "_workspace", None)
        if ws is not None:
            try:
                from ..access_control import get_access_control_store
                store = get_access_control_store(ws.workspace_dir)
                return store.check_access(
                    channel=self.channel,
                    user_id=sender_id,
                    is_group=is_group,
                    dm_policy=self._dm_policy,
                    group_policy=self._group_policy,
                    allow_from=self._allow_from or None,
                )
            except Exception:
                pass  # Fall through to simple check

        # Simple fallback (no workspace or store error)
        if self._allow_from and sender_id not in self._allow_from:
            return False, self._deny_message
        if is_group and self._group_policy == "closed":
            return False, self._deny_message
        if not is_group and self._dm_policy == "closed":
            return False, self._deny_message
        return True, ""

    def _is_native_payload(self, payload: Any) -> bool:
        """True if payload is a native dict that can be time-debounced."""
        return isinstance(payload, dict) and "content_parts" in payload

    # ------------------------------------------------------------------
    # Session rotation (v0.8.7)
    # ------------------------------------------------------------------

    @staticmethod
    def _session_user_key(channel: str, sender_id: str) -> str:
        """Build a unique key for the per-user session mapping."""
        return f"{channel}:{sender_id}"

    def _init_user_session(
        self,
        sender_id: str,
        channel_meta: Optional[Dict[str, Any]] = None,
    ) -> str:
        """Ensure a session_id exists for this user; return the current one.

        If no session has been recorded yet, creates the default
        ``{channel}:{sender_id}`` (or channel-group variant) and stores
        it.  Thread-safe.
        """
        key = self._session_user_key(self.channel, sender_id)
        with self._user_sessions_lock:
            if key not in self._user_sessions:
                self._user_sessions[key] = self._make_default_session_id(
                    sender_id, channel_meta,
                )
            return self._user_sessions[key]

    def get_user_session(self, sender_id: str) -> str:
        """Return the current session_id for *sender_id*, or empty string."""
        key = self._session_user_key(self.channel, sender_id)
        with self._user_sessions_lock:
            return self._user_sessions.get(key, "")

    def rotate_user_session(
        self,
        sender_id: str,
        channel_meta: Optional[Dict[str, Any]] = None,
    ) -> str:
        """Create a **new** session_id for *sender_id* and return it.

        The new session_id is ``{channel}:{sender_id}:{timestamp}``
        (or channel-group variant with timestamp).  Subsequent calls to
        :meth:`resolve_session_id` will return this new id until the
        next rotation.

        This method is called when the user sends ``/new`` in a channel
        chat so that:
        - The **old** session history is preserved on disk.
        - The **current** ``/new`` request is still processed under the
          old session (so the runner can summarize /clear the old memory).
        - **Future** messages use the fresh session_id.
        """
        key = self._session_user_key(self.channel, sender_id)
        new_id = self._make_rotated_session_id(sender_id, channel_meta)
        with self._user_sessions_lock:
            self._user_sessions[key] = new_id
        logger.info(
            "session rotated: %s → %s", key, new_id,
        )
        return new_id

    def _make_default_session_id(
        self,
        sender_id: str,
        channel_meta: Optional[Dict[str, Any]] = None,
    ) -> str:
        """Build the initial (non-rotated) session_id."""
        meta = channel_meta or {}
        group_id = (meta.get("weixin_group_id")
                    or meta.get("group_id")
                    or "").strip()
        if group_id:
            return f"{self.channel}:group:{group_id}"
        return f"{self.channel}:{sender_id}" if sender_id else f"{self.channel}:unknown"

    def _make_rotated_session_id(
        self,
        sender_id: str,
        channel_meta: Optional[Dict[str, Any]] = None,
    ) -> str:
        """Build a rotated session_id (includes timestamp)."""
        ts = int(time.time())
        meta = channel_meta or {}
        group_id = (meta.get("weixin_group_id")
                    or meta.get("group_id")
                    or "").strip()
        if group_id:
            return f"{self.channel}:group:{group_id}:{ts}"
        base = sender_id if sender_id else "unknown"
        return f"{self.channel}:{base}:{ts}"

    def is_new_session_command(self, text: str) -> bool:
        """Return True if *text* is a session-rotation command (e.g. /new)."""
        if not text:
            return False
        stripped = text.strip().lstrip("/")
        parts = stripped.split(" ", 1)
        cmd = parts[0].lower() if parts else ""
        return cmd in ("new", "clear")

    # ------------------------------------------------------------------
    # resolve_session_id (enhanced with rotation support)
    # ------------------------------------------------------------------

    def resolve_session_id(
        self,
        sender_id: str,
        channel_meta: Optional[Dict[str, Any]] = None,
    ) -> str:
        """Map sender and optional channel meta to session_id.

        If the user already has a tracked session (via
        :meth:`_init_user_session` or :meth:`rotate_user_session`),
        returns that.  Otherwise falls back to the default pattern.
        """
        key = self._session_user_key(self.channel, sender_id)
        with self._user_sessions_lock:
            existing = self._user_sessions.get(key)
        if existing:
            return existing
        return self._make_default_session_id(sender_id, channel_meta)

    def build_agent_request_from_user_content(
        self,
        channel_id: str,
        sender_id: str,
        session_id: str,
        content_parts: List[Any],
        channel_meta: Optional[Dict[str, Any]] = None,
    ) -> "AgentRequest":
        """Build AgentRequest from runtime content parts."""
        from agentscope_runtime.engine.schemas.agent_schemas import (
            AgentRequest,
            Message,
            Role,
        )

        if not content_parts:
            content_parts = [
                TextContent(type=ContentType.TEXT, text=" "),
            ]
        msg = Message(
            type=MessageType.MESSAGE,
            role=Role.USER,
            content=content_parts,
        )
        # Pass selected_files through message metadata for dynamic hint injection
        # Note: Msg class uses 'metadata' attribute, not 'meta'
        if channel_meta:
            if channel_meta.get("selected_files"):
                msg.metadata = msg.metadata or {}
                msg.metadata["selected_files"] = channel_meta["selected_files"]
                logger.info(f"[DEBUG] Set msg.metadata to {msg.metadata}")
            # ── Scene ID: 场景智能体注入 ──
            if channel_meta.get("scene_id"):
                msg.metadata = msg.metadata or {}
                msg.metadata["scene_id"] = channel_meta["scene_id"]
                logger.info(f"[Scene] Set msg.metadata.scene_id to {channel_meta['scene_id']}")
        
        req = AgentRequest(
            session_id=session_id,
            user_id=sender_id,
            input=[msg],
            channel=channel_id,
        )
        # Pass chat_id through to request so query_handler can resolve
        # the correct chat in background tasks (contextvars don't propagate).
        if channel_meta and channel_meta.get("chat_id"):
            req.chat_id = channel_meta["chat_id"]
        return req

    def build_agent_request_from_native(
        self,
        native_payload: Any,
    ) -> "AgentRequest":
        """Convert channel-native message payload to AgentRequest."""
        raise NotImplementedError(
            f"{self.__class__.__name__} must implement "
            "build_agent_request_from_native(native_payload)",
        )

    def _payload_to_request(self, payload: Any) -> "AgentRequest":
        """Convert queue payload to AgentRequest."""
        if payload is None:
            raise ValueError("payload is None")
        if hasattr(payload, "session_id") and hasattr(payload, "input"):
            return payload
        return self.build_agent_request_from_native(payload)

    def get_to_handle_from_request(self, request: "AgentRequest") -> str:
        """Resolve send target (to_handle) from AgentRequest."""
        return getattr(request, "user_id", "") or ""

    async def _stream_with_tracker(
        self,
        payload: Any,
    ) -> AsyncGenerator[str, None]:
        """Stream events via TaskTracker, yielding SSE strings.

        When ``streaming_enabled``, streaming hooks are invoked for
        reasoning / message events alongside the normal path.
        
        """
        request = self._payload_to_request(payload)

        if isinstance(payload, dict):
            send_meta = dict(payload.get("meta") or {})
        else:
            send_meta = getattr(request, "channel_meta", None) or {}

        to_handle = self.get_to_handle_from_request(request)

        await self._before_consume_process(request)

        last_response = None
        process_iterator = None
        msg_id_to_stream_type: Dict[str, str] = {}
        streaming_buffers: Dict[str, str] = {}
        try:
            process_iterator = self._process(request)
            async for event in process_iterator:
                # Serialize for SSE yield
                if hasattr(event, "model_dump_json"):
                    data = event.model_dump_json()
                elif hasattr(event, "json"):
                    data = event.json()
                else:
                    data = json.dumps({"text": str(event)})
                yield f"data: {data}\n\n"

                obj = getattr(event, "object", None)
                status = getattr(event, "status", None)

                # --- streaming path ---
                handled_by_streaming = False
                if self.streaming_enabled:
                    handled_by_streaming = (
                        await self._dispatch_streaming_event(
                            request, to_handle, event, send_meta,
                            msg_id_to_stream_type, streaming_buffers,
                        )
                    )

                # --- non-streaming / fallback path ---
                # Only call on_event_content if streaming did NOT handle it.
                # (matches direct _process path logic in consume_one)
                if obj == "content" and not handled_by_streaming:
                    if await self.on_event_content(
                        request, to_handle, event, send_meta,
                    ):
                        continue
                if obj == "message" and status == RunStatus.Completed:
                    await self.on_event_message_completed(
                        request, to_handle, event, send_meta,
                    )
                elif obj == "response":
                    last_response = event
                    await self.on_event_response(request, event)

        except asyncio.CancelledError:
            logger.info(
                f"channel task cancelled: "
                f"session={getattr(request, 'session_id', '')[:30]}",
            )
            if process_iterator is not None:
                await process_iterator.aclose()
            raise

        except Exception as e:
            logger.exception(
                f"channel _stream_with_tracker failed: {e}, "
                f"session={getattr(request, 'session_id', 'N/A')[:30]}",
            )
            raise

    # ------------------------------------------------------------------
    # Streaming hooks — override in subclasses
    # ------------------------------------------------------------------

    async def _before_consume_process(self, request: "AgentRequest") -> None:
        """Hook called once before running _process. Override for
        pre-processing (e.g. send 'thinking' indicator)."""

    def _resolve_stream_type(self, event: Any) -> str:
        """Map event.type to a stream_type string.

        Returns ``"reasoning"`` or ``"message"`` for streamable text,
        or the raw type string (e.g. ``"plugin_call"``) otherwise.
        """
        msg_type = getattr(event, "type", None)
        if msg_type is None:
            return "message"
        type_str = (
            msg_type.value if hasattr(msg_type, "value") else str(msg_type)
        )
        return type_str

    async def _dispatch_streaming_event(
        self,
        request: "AgentRequest",
        to_handle: str,
        event: Any,
        send_meta: Dict[str, Any],
        msg_id_to_stream_type: Dict[str, str],
        streaming_buffers: Dict[str, str],
    ) -> bool:
        """Dispatch streaming hooks for reasoning / message events.

        Returns *True* if the event was consumed by the streaming
        path (so the caller should skip ``on_event_message_completed``).
        Non-streamable types (e.g. ``plugin_call``) return *False*,
        falling through to the normal non-streaming path.
        """
        obj = getattr(event, "object", None)
        status = getattr(event, "status", None)

        if obj == "message" and status == RunStatus.InProgress:
            return await self._on_stream_msg_start(
                request, to_handle, event, send_meta,
                msg_id_to_stream_type, streaming_buffers,
            )
        if obj == "content" and status == RunStatus.InProgress:
            return await self._on_stream_content_delta(
                request, to_handle, event, send_meta,
                msg_id_to_stream_type, streaming_buffers,
            )
        if obj == "message" and status == RunStatus.Completed:
            return await self._on_stream_msg_end(
                request, to_handle, event, send_meta,
                msg_id_to_stream_type, streaming_buffers,
            )
        return False

    async def _on_stream_msg_start(
        self,
        request: "AgentRequest",
        to_handle: str,
        event: Any,
        send_meta: Dict[str, Any],
        msg_id_to_stream_type: Dict[str, str],
        streaming_buffers: Dict[str, str],
    ) -> bool:
        stream_type = self._resolve_stream_type(event)
        if stream_type not in self._STREAMABLE_TYPES:
            return False
        msg_id = getattr(event, "id", None)
        if msg_id:
            msg_id_to_stream_type[msg_id] = stream_type
        logger.info(
            "_on_stream_msg_start stream_type=%s _filter_thinking=%s channel=%s",
            stream_type, self._filter_thinking, self.channel,
        )
        if stream_type == "reasoning" and self._filter_thinking:
            logger.info("_on_stream_msg_start: FILTERED reasoning (filter_thinking=True)")
            return True
        streaming_buffers[stream_type] = ""
        await self.on_streaming_start(
            request, to_handle, event, send_meta,
            stream_type, accumulated_text="",
        )
        return True

    async def _on_stream_content_delta(
        self,
        request: "AgentRequest",
        to_handle: str,
        event: Any,
        send_meta: Dict[str, Any],
        msg_id_to_stream_type: Dict[str, str],
        streaming_buffers: Dict[str, str],
    ) -> bool:
        if not getattr(event, "delta", False):
            return False
        content_msg_id = getattr(event, "msg_id", None) or ""
        stream_type = msg_id_to_stream_type.get(content_msg_id, "")
        if not stream_type or stream_type not in self._STREAMABLE_TYPES:
            return False
        if stream_type not in streaming_buffers:
            return False
        if stream_type == "reasoning" and self._filter_thinking:
            return True
        delta_text = getattr(event, "text", "") or ""
        streaming_buffers[stream_type] = (
            streaming_buffers.get(stream_type, "") + delta_text
        )
        await self.on_streaming_delta(
            request, to_handle, event, send_meta,
            stream_type,
            accumulated_text=streaming_buffers[stream_type],
        )
        return True

    async def _on_stream_msg_end(
        self,
        request: "AgentRequest",
        to_handle: str,
        event: Any,
        send_meta: Dict[str, Any],
        msg_id_to_stream_type: Dict[str, str],
        streaming_buffers: Dict[str, str],
    ) -> bool:
        stream_type = self._resolve_stream_type(event)
        msg_id = getattr(event, "id", None)
        if msg_id:
            msg_id_to_stream_type.pop(msg_id, None)
        if stream_type not in self._STREAMABLE_TYPES:
            return False
        if stream_type in streaming_buffers:
            if stream_type == "reasoning" and self._filter_thinking:
                streaming_buffers.pop(stream_type, None)
                return True
            accumulated = streaming_buffers.pop(stream_type, "")
            await self.on_streaming_end(
                request, to_handle, event, send_meta,
                stream_type, accumulated_text=accumulated,
            )
        return True

    async def on_streaming_start(
        self,
        request: "AgentRequest",
        to_handle: str,
        event: Any,
        send_meta: Dict[str, Any],
        stream_type: str,
        accumulated_text: str = "",
    ) -> None:
        """Called when a new streaming segment begins.
        stream_type is 'reasoning' or 'message'."""

    async def on_streaming_delta(
        self,
        request: "AgentRequest",
        to_handle: str,
        event: Any,
        send_meta: Dict[str, Any],
        stream_type: str,
        accumulated_text: str = "",
    ) -> None:
        """Called for each incremental text chunk.
        accumulated_text contains all text so far."""

    async def on_streaming_end(
        self,
        request: "AgentRequest",
        to_handle: str,
        event: Any,
        send_meta: Dict[str, Any],
        stream_type: str,
        accumulated_text: str = "",
    ) -> None:
        """Called when a streaming segment completes.
        accumulated_text is the final full text."""

    # ── Event hooks ──────────────────────────────
    # Subclasses override these to react to specific events from
    # _process().  Default implementations are no-ops so existing
    # channels keep working unchanged.

    async def on_event_content(
        self,
        request: "AgentRequest",
        to_handle: str,
        event: Any,
        send_meta: Dict[str, Any],
    ) -> bool:
        """Hook: content event (tool output / data content).

        Return True if the event was fully handled (skip default path).
        Return False to let the caller continue with default handling.
        """
        return False

    async def on_event_message_completed(
        self,
        request: "AgentRequest",
        to_handle: str,
        event: Any,
        send_meta: Dict[str, Any],
    ) -> None:
        """Hook: message completed event.

        Uses renderer to format message content (tool calls, thinking
        blocks, etc.) and sends via send_content_parts.
        """
        try:
            msg = getattr(event, "message", None) or event
            parts = self._message_to_content_parts(msg)
            if parts:
                await self.send_content_parts(to_handle, parts, send_meta)
        except Exception:
            logger.debug(
                "on_event_message_completed default handler failed",
                exc_info=True,
            )

    async def on_event_response(
        self,
        request: "AgentRequest",
        event: Any,
    ) -> None:
        """Hook: response event (agent response metadata)."""
        pass

    def _extract_final_text(self, event: Any) -> str:
        """Extract final text content from a message completed event."""
        msg = getattr(event, "message", None)
        if msg is None:
            msg = event
        content_list = getattr(msg, "content", None) or []
        parts = []
        for c in content_list:
            if hasattr(c, "text"):
                parts.append(getattr(c, "text", ""))
            elif isinstance(c, dict):
                parts.append(c.get("text", ""))
        return "\n".join(p for p in parts if p)

    def _message_to_content_parts(
        self,
        message: Any,
    ) -> List[OutgoingContentPart]:
        """Convert a Message into sendable parts via renderer.

        Delegates to self._renderer for channel-specific formatting
        (tool calls, thinking blocks, etc.).
        """
        return self._renderer.message_to_parts(message)

    def _resolve_send_fn(self) -> Any:
        """Resolve the best available send function for this channel."""
        for name in ("send_text", "send", "send_message"):
            fn = getattr(self, name, None)
            if fn:
                return fn
        return None

    async def send_content_parts(
        self,
        to_handle: str,
        parts: List[OutgoingContentPart],
        meta: Optional[Dict[str, Any]] = None,
    ) -> None:
        """Send a list of content parts.

        Default: merge text/refusal into one text message, send via
        the channel's send function.  Subclasses (e.g. WeCom) override
        for channel-specific multi-part sending.
        """
        text_parts: List[str] = []
        for p in parts:
            t = getattr(p, "type", None)
            if t == ContentType.TEXT and getattr(p, "text", None):
                text_parts.append(p.text or "")
            elif t == ContentType.REFUSAL and getattr(p, "refusal", None):
                text_parts.append(p.refusal or "")
        body = "\n".join(text_parts).strip()
        if body:
            send_fn = self._resolve_send_fn()
            if send_fn:
                await send_fn(to_handle, body, meta)

    def _format_stream_tool_output_body(self, event: Any) -> Optional[str]:
        """Format tool output for display.

        Returns formatted string or None if event is not a tool output.
        """
        try:
            from ..channels.renderer import RenderStyle
            obj = getattr(event, "object", None)
            if obj != "content":
                return None
            msg_type = getattr(event, "type", None)
            type_str = (
                msg_type.value if hasattr(msg_type, "value")
                else str(msg_type) if msg_type else ""
            )
            if type_str not in ("tool_use", "tool_output", "tool_result"):
                return None
            content_text = ""
            for c in (event.content or []):
                if hasattr(c, "text"):
                    content_text = getattr(c, "text", "")
                elif isinstance(c, dict):
                    content_text = c.get("text", "")
                break
            tool_name = ""
            if hasattr(event, "metadata") and isinstance(event.metadata, dict):
                tool_name = event.metadata.get("tool_name", "")
            if not content_text:
                return None
            prefix = f"🔧 {tool_name}" if tool_name else "🔧 Tool"
            truncated = content_text[:1000]
            if len(content_text) > 1000:
                truncated += "…"
            return f"{prefix}\n```\n{truncated}\n```"
        except Exception:
            return None

    # ── Query extraction for command routing ───────────────────────

    def _extract_query_from_payload(self, payload: Any) -> str:
        """Extract query text from payload for command detection.

        Args:
            payload: Native dict or AgentRequest

        Returns:
            Query text string (empty if not found)
        """
        if isinstance(payload, dict):
            parts = payload.get("content_parts") or []
            for part in parts:
                if isinstance(part, dict) and part.get("type") == "text":
                    return part.get("text") or ""
                if hasattr(part, "type") and part.type == "text":
                    return getattr(part, "text", "") or ""
            return ""
        if hasattr(payload, "input"):
            inp = payload.input or []
            if inp and hasattr(inp[0], "content"):
                content = inp[0].content or []
                for part in content:
                    if isinstance(part, dict):
                        if part.get("type") == "text":
                            return part.get("text") or ""
                    elif hasattr(part, "type") and part.type == "text":
                        return getattr(part, "text", "") or ""
        return ""

    # ── Tracker-aware consume ──────────────────────────────────────

    async def _consume_with_tracker(
        self,
        request: "AgentRequest",
        payload: Any,
    ) -> None:
        """Consume with TaskTracker registration for /stop support.

        Registers the task in TaskTracker so /stop can cancel it.
        Session busy state is tracked via _processing_sessions.
        """
        session_id = getattr(request, "session_id", "") or ""

        chat = await self._workspace.chat_manager.get_or_create_chat(
            session_id,
            getattr(request, "user_id", "") or "",
            getattr(request, "channel", self.channel),
        )

        queue, is_new = await self._workspace.task_tracker.attach_or_start(
            chat.id,
            payload,
            self._stream_with_tracker,
        )

        if is_new:
            try:
                async for _ in self._workspace.task_tracker.stream_from_queue(
                    queue,
                    chat.id,
                ):
                    pass
            except asyncio.CancelledError:
                logger.info(f"Task cancelled: chat_id={chat.id}")
                raise

    async def _stream_with_tracker_for_task(
        self,
        request: "AgentRequest",
        to_handle: str,
        send_meta: Dict[str, Any],
    ) -> None:
        """Internal stream method called by TaskTracker."""
        msg_id_to_stream_type: Dict[str, str] = {}
        streaming_buffers: Dict[str, str] = {}

        try:
            async for event in self._process(request):
                obj = getattr(event, "object", None)
                status = getattr(event, "status", None)

                handled_by_streaming = False
                if self.streaming_enabled:
                    handled_by_streaming = await self._dispatch_streaming_event(
                        request, to_handle, event, send_meta,
                        msg_id_to_stream_type, streaming_buffers,
                    )

                if obj == "content" and not handled_by_streaming:
                    if await self.on_event_content(
                        request, to_handle, event, send_meta,
                    ):
                        continue
                # Always fire on_event_message_completed for card rendering etc.
                # Streaming handles the text send; the hook handles side-effects.
                if obj == "message" and status == RunStatus.Completed:
                    if not handled_by_streaming:
                        await self.on_event_message_completed(
                            request, to_handle, event, send_meta,
                        )
                    else:
                        await self.on_event_message_completed(
                            request, to_handle, event, send_meta,
                        )
                elif obj == "response":
                    await self.on_event_response(request, event)
        except Exception:
            logger.exception("stream_with_tracker failed")

    async def consume_one(self, payload: Any) -> None:
        """Consume one payload from queue.

        Routes through CommandRegistry:
        - Non-control commands (e.g. /new, /clear, /compact) →
          _consume_with_tracker (TaskTracker registration for /stop)
        - Control commands (e.g. /stop, /approve) → direct _process
          (bypass TaskTracker so /stop can cancel the non-control task)
        """
        logger.info(
            "consume_one START channel=%s payload_type=%s",
            self.channel,
            type(payload).__name__,
        )

        # ── Command routing ────────────────────
        if self._workspace is not None and self._command_registry is not None:
            query_text = self._extract_query_from_payload(payload)
            if query_text:
                is_control = self._command_registry.is_control_command(
                    query_text,
                )
                logger.debug(
                    "consume_one: query=%s is_control=%s",
                    query_text[:50],
                    is_control,
                )
                if not is_control:
                    # Non-control: route through TaskTracker
                    request = self._payload_to_request(payload)
                    # _before_consume_process is called in _stream_with_tracker
                    await self._consume_with_tracker(request, payload)
                    return
                # Control commands fall through to direct _process

        # ── Direct _process (control commands or no workspace) ──────
        request = self._payload_to_request(payload)
        to_handle = self.get_to_handle_from_request(request)

        if isinstance(payload, dict):
            send_meta = dict(payload.get("meta") or {})
        else:
            send_meta = getattr(request, "channel_meta", None) or {}

        await self._before_consume_process(request)

        msg_id_to_stream_type: Dict[str, str] = {}
        streaming_buffers: Dict[str, str] = {}

        try:
            # self._process is the ProcessHandler (callable) passed to __init__
            logger.info(
                "consume_one calling _process for channel=%s",
                self.channel,
            )
            event_count = 0
            async for event in self._process(request):
                event_count += 1
                obj = getattr(event, "object", None)
                status = getattr(event, "status", None)

                # --- streaming path ---
                handled_by_streaming = False
                if self.streaming_enabled:
                    handled_by_streaming = await self._dispatch_streaming_event(
                        request, to_handle, event, send_meta,
                        msg_id_to_stream_type, streaming_buffers,
                    )

                # --- non-streaming fallback ---
                # content events (tool output) — try hook first
                if obj == "content" and not handled_by_streaming:
                    if await self.on_event_content(
                        request, to_handle, event, send_meta,
                    ):
                        continue
                # message completed — always fire hook for cards etc.
                if obj == "message" and status == RunStatus.Completed:
                    await self.on_event_message_completed(
                        request, to_handle, event, send_meta,
                    )
                elif obj == "response":
                    await self.on_event_response(request, event)

        except Exception:
            logger.exception("channel consume_one failed channel=%s", self.channel)
        else:
            logger.info(
                "consume_one DONE channel=%s event_count=%s",
                self.channel,
                event_count,
            )
