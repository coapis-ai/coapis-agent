# -*- coding: utf-8 -*-
"""ChannelManager for CoApis.

Simplified from CoApis's ChannelManager (844 lines).
Stripped DingTalk, Feishu, WeChat, command registry, unified queue, etc.
Keeps core: create channels, get_channel(), enqueue, consumer loop.
"""
from __future__ import annotations

import asyncio
import logging
from pathlib import Path
from typing import Any, Dict, List, Optional, TYPE_CHECKING

from .base import BaseChannel, ProcessHandler

logger = logging.getLogger(__name__)

# Default max size per channel queue
_CHANNEL_QUEUE_MAXSIZE = 1000


class ChannelManager:
    """Owns queues and consumer loops for CoApis channels.

    Supports dynamic channel creation from config via ``from_config``.
    """

    def __init__(self, channels: List[BaseChannel]):
        self.channels = channels
        self._lock = asyncio.Lock()
        self._loop: Optional[asyncio.AbstractEventLoop] = None

        # Per-channel queues and consumer tasks
        self._queues: Dict[str, asyncio.Queue] = {}
        self._consumer_tasks: Dict[str, asyncio.Task] = {}

        # Build queues for channels that use manager queue
        for ch in channels:
            if ch.uses_manager_queue:
                queue = asyncio.Queue(maxsize=_CHANNEL_QUEUE_MAXSIZE)
                self._queues[ch.channel] = queue
                ch._enqueue = queue.put_nowait

    # ------------------------------------------------------------------
    # Factory
    # ------------------------------------------------------------------

    @classmethod
    def from_config(
        cls,
        process: ProcessHandler,
        config: Any,
        on_last_dispatch=None,
        workspace_dir: Optional[Path] = None,
    ) -> "ChannelManager":
        """Create ChannelManager from config with all enabled channels.

        Uses the channel registry to discover available channel types,
        then creates instances for each channel enabled in config.

        Args:
            process: ProcessHandler callback for message processing
            config: Config object with ``channels`` dict
            on_last_dispatch: Callback for last dispatch tracking
            workspace_dir: Optional workspace directory path

        Returns:
            ChannelManager with all enabled channels created
        """
        from .registry import get_channel_registry

        registry = get_channel_registry()
        channels_section = getattr(config, "channels", {}) or {}

        created: List[BaseChannel] = []

        # Always create ConsoleChannel
        console_cls = registry.get("console")
        if console_cls:
            try:
                console = console_cls(
                    process=process,
                    show_tool_details=True,
                    filter_tool_messages=False,
                    filter_thinking=False,
                )
                created.append(console)
                logger.info("ConsoleChannel created")
            except Exception as e:
                logger.warning("Failed to create ConsoleChannel: %s", e)

        # Create other channels from config
        for channel_key, channel_cfg in channels_section.items():
            if channel_key == "console":
                continue  # Already handled above

            if not isinstance(channel_cfg, dict):
                continue

            if not channel_cfg.get("enabled", False):
                continue

            channel_cls = registry.get(channel_key)
            if not channel_cls:
                logger.warning(
                    "Channel type '%s' not found in registry, skipping",
                    channel_key,
                )
                continue

            # Check if channel has from_config classmethod
            if not hasattr(channel_cls, "from_config"):
                logger.warning(
                    "Channel '%s' has no from_config method, skipping",
                    channel_key,
                )
                continue

            try:
                # Build a simple config-like object from the dict
                channel_config = type("ChannelConfig", (), channel_cfg)()
                ch = channel_cls.from_config(
                    process=process,
                    config=channel_config,
                    on_reply_sent=on_last_dispatch,
                    show_tool_details=channel_cfg.get("show_tool_details", True),
                    filter_tool_messages=channel_cfg.get("filter_tool_messages", False),
                    filter_thinking=channel_cfg.get("filter_thinking", False),
                    workspace_dir=workspace_dir,
                )
                created.append(ch)
                logger.info(
                    "Channel '%s' created from config (enabled=%s)",
                    channel_key,
                    channel_cfg.get("enabled"),
                )
            except Exception as e:
                logger.error(
                    "Failed to create channel '%s': %s",
                    channel_key,
                    e,
                    exc_info=True,
                )

        logger.info(
            "ChannelManager.from_config: created %d channels: %s",
            len(created),
            [ch.channel for ch in created],
        )
        return cls(created)

    def get_channel(self, channel_id: str) -> Optional[BaseChannel]:
        """Get channel by ID."""
        for ch in self.channels:
            if ch.channel == channel_id:
                return ch
        return None

    def enqueue(self, channel_id: str, payload: Any) -> None:
        """Enqueue a payload for the given channel (thread-safe)."""
        queue = self._queues.get(channel_id)
        if queue is None:
            logger.warning(
                "enqueue to unknown channel: %s", channel_id,
            )
            return
        try:
            queue.put_nowait(payload)
        except asyncio.QueueFull:
            logger.warning(
                "channel queue full, dropping payload: %s", channel_id,
            )

    async def start(self) -> None:
        """Start all channels and their consumer loops."""
        self._loop = asyncio.get_running_loop()

        # Start each channel (e.g., wecom WebSocket connection)
        for ch in self.channels:
            if hasattr(ch, "start") and callable(ch.start):
                try:
                    result = ch.start()
                    if asyncio.iscoroutine(result):
                        await result
                    logger.info("Channel '%s' start() called", ch.channel)
                except Exception as e:
                    logger.warning(
                        "Channel '%s' start() failed: %s", ch.channel, e,
                    )

        # Start consumer loops for channels that use manager queue
        for ch in self.channels:
            if ch.uses_manager_queue:
                task = asyncio.create_task(
                    self._consumer_loop(ch),
                    name=f"channel-consumer-{ch.channel}",
                )
                self._consumer_tasks[ch.channel] = task
        logger.info(
            "ChannelManager started: %d consumer loops, %d channels",
            len(self._consumer_tasks),
            len(self.channels),
        )

    # Alias for ServiceManager compatibility
    async def start_all(self) -> None:
        """Alias for start() — ServiceManager calls this via start_method."""
        await self.start()

    async def stop(self) -> None:
        """Stop all consumer loops gracefully."""
        for channel_id, task in self._consumer_tasks.items():
            task.cancel()
        if self._consumer_tasks:
            results = await asyncio.gather(
                *self._consumer_tasks.values(),
                return_exceptions=True,
            )
            for r in results:
                if isinstance(r, asyncio.CancelledError):
                    continue
                if isinstance(r, Exception):
                    logger.warning("consumer loop error: %s", r)
        self._consumer_tasks.clear()
        logger.info("ChannelManager stopped")

    # Alias for ServiceManager compatibility
    async def stop_all(self) -> None:
        """Alias for stop() — ServiceManager calls this via stop_method."""
        await self.stop()

    def set_workspace(self, workspace: Any) -> None:
        """Inject workspace reference into all channels."""
        for ch in self.channels:
            if hasattr(ch, "_workspace"):
                ch._workspace = workspace
            elif hasattr(ch, "workspace"):
                ch.workspace = workspace

    async def _consumer_loop(self, ch: BaseChannel) -> None:
        """Consume payloads from a channel's queue.

        Critical-priority commands (e.g. /stop, priority level 0) are
        dispatched as concurrent tasks so they can cancel the currently
        running normal task instead of waiting in the serial queue.
        """
        queue = self._queues.get(ch.channel)
        if queue is None:
            return
        logger.info("consumer loop started for channel: %s", ch.channel)
        # Track spawned critical tasks for cleanup
        _critical_tasks: set[asyncio.Task] = set()
        try:
            while True:
                try:
                    payload = await asyncio.wait_for(
                        queue.get(),
                        timeout=1.0,
                    )
                except asyncio.TimeoutError:
                    continue
                except asyncio.CancelledError:
                    break

                # ── Priority detection: critical commands run concurrently ──
                is_critical = False
                try:
                    registry = getattr(ch, "_command_registry", None)
                    if registry is not None:
                        query = ch._extract_query_from_payload(payload)
                        if query and registry.get_priority_level(query) == 0:
                            is_critical = True
                except Exception:
                    pass  # Never let priority check break the loop

                if is_critical:
                    logger.info(
                        "critical command detected, spawning concurrent "
                        "task for %s",
                        ch.channel,
                    )
                    task = asyncio.create_task(
                        ch.consume_one(payload),
                        name=f"critical-{ch.channel}",
                    )
                    _critical_tasks.add(task)
                    task.add_done_callback(_critical_tasks.discard)
                else:
                    logger.info(
                        "consumer loop dispatching to %s, payload_type=%s",
                        ch.channel,
                        type(payload).__name__,
                    )
                    await ch.consume_one(payload)
                    logger.info(
                        "consumer loop finished consume_one for %s",
                        ch.channel,
                    )
                queue.task_done()
        except asyncio.CancelledError:
            logger.info("consumer loop cancelled: %s", ch.channel)
            for t in _critical_tasks:
                t.cancel()
        except Exception:
            logger.exception(
                "consumer loop crashed: %s", ch.channel,
            )

    async def send_text(
        self,
        channel: str,
        user_id: str,
        session_id: str,
        text: str,
        meta: Optional[Dict[str, Any]] = None,
    ) -> None:
        """Send a text message proactively via the specified channel.

        Used by CronExecutor (task_type='text') and other proactive
        notification paths.  Delegates to the channel's ``send()``
        method which each concrete channel implements.

        Routing logic (same as each channel's ``to_handle_from_target``):
        1. Use the channel instance's ``to_handle_from_target`` if
           available — this produces the correct channel-prefixed
           handle (e.g. ``wecom:group:<chatid>``,
           ``dingtalk:sw:<session_id>``).
        2. Fallback to ``session_id`` directly.
        3. Final fallback to ``<channel>:<user_id>``.

        Args:
            channel: Channel ID (e.g. 'wecom', 'console').
            user_id: Target user identifier.
            session_id: Target session — should carry the channel
                prefix (e.g. ``wecom:group:xxx``) for proper routing.
            text: The message body to send.
            meta: Optional metadata forwarded to the channel.
        """
        ch = self.get_channel(channel)
        if ch is None:
            logger.warning(
                "send_text: channel '%s' not found", channel,
            )
            return
        if not hasattr(ch, "send") or not callable(ch.send):
            logger.warning(
                "send_text: channel '%s' has no send() method",
                channel,
            )
            return
        # Build to_handle using channel's own routing logic (preferred),
        # falling back to session_id, then to channel:user_id.
        if hasattr(ch, "to_handle_from_target"):
            to_handle = ch.to_handle_from_target(
                user_id=user_id,
                session_id=session_id or "",
            )
        else:
            to_handle = session_id or f"{channel}:{user_id}"
        try:
            logger.info(
                "send_text: channel=%s to_handle=%s len=%s",
                channel, (to_handle or "")[:60], len(text or ""),
            )
            await ch.send(to_handle=to_handle, text=text, meta=meta)
        except Exception:
            logger.exception(
                "send_text failed: channel=%s to_handle=%s",
                channel, (to_handle or "")[:60],
            )
