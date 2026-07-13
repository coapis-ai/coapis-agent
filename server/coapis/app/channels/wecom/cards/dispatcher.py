# -*- coding: utf-8 -*-
# pylint: disable=protected-access
"""WeCom interactive template-card dispatcher (routing-only).

Two lookup tables drive the dispatch:

* ``_by_message_type``   — outbound: ``metadata.message_type`` → ``render``.
* ``_by_task_id_prefix`` — inbound:  ``task_id`` prefix       → ``handle``.

Public entry-points (called by :class:`~..channel.WecomChannel`):
:meth:`try_send_card_for_event` and :meth:`handle_template_card_event_sync`.

Adding a new card kind: drop a module exposing ``NAME`` /
``MESSAGE_TYPE`` / ``TASK_ID_PREFIX`` plus ``render`` / ``handle``,
then register it in :meth:`_register_kinds`.
"""
from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from typing import (
    TYPE_CHECKING,
    Any,
    Awaitable,
    Callable,
    Dict,
    Optional,
)

from . import context

if TYPE_CHECKING:
    from ..channel import WecomChannel

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------
# Registry record
# ---------------------------------------------------------------------

# Outbound: given (channel, to_handle, event, send_meta, meta) build +
# send the card.  Returns True if the card was sent so the caller can
# skip the default text rendering.
RenderFn = Callable[
    ["WecomChannel", str, Any, Dict[str, Any], Dict[str, Any]],
    Awaitable[bool],
]

# Inbound: given (channel, raw WeCom callback frame), perform the card
# update and any side effects (queue injection, etc).
HandleFn = Callable[["WecomChannel", Any], Awaitable[None]]


@dataclass(frozen=True)
class CardKind:
    """Describes one kind of template card and its handlers."""

    name: str  # human-readable tag for logs
    message_type: str  # matches ``metadata.message_type`` (outbound)
    task_id_prefix: str  # matches ``task_id`` prefix (inbound)
    render: RenderFn
    handle: HandleFn


# ---------------------------------------------------------------------
# Dispatcher
# ---------------------------------------------------------------------


class WecomCardHandler:
    """Routing-only dispatcher for WeCom interactive template cards."""

    def __init__(self, channel: "WecomChannel") -> None:
        self._channel = channel
        self._by_message_type: Dict[str, CardKind] = {}
        self._by_task_id_prefix: Dict[str, CardKind] = {}
        self._register_kinds()

    # ------------------------------------------------------------------
    # Registration
    # ------------------------------------------------------------------

    def register(self, kind: CardKind) -> None:
        """Install a card kind into both lookup tables."""
        if kind.message_type in self._by_message_type:
            logger.warning(
                "wecom card: message_type %r already registered, overriding",
                kind.message_type,
            )
        if kind.task_id_prefix in self._by_task_id_prefix:
            logger.warning(
                "wecom card: task_id_prefix %r already registered, overriding",
                kind.task_id_prefix,
            )
        self._by_message_type[kind.message_type] = kind
        self._by_task_id_prefix[kind.task_id_prefix] = kind

    def _register_kinds(self) -> None:
        """Register all built-in card kinds."""
        from . import tool_guard

        self.register(
            CardKind(
                name=tool_guard.NAME,
                message_type=tool_guard.MESSAGE_TYPE,
                task_id_prefix=tool_guard.TASK_ID_PREFIX,
                render=tool_guard.render,
                handle=tool_guard.handle,
            )
        )

    # ------------------------------------------------------------------
    # Outbound: render a card for an event
    # ------------------------------------------------------------------

    async def try_send_card_for_event(
        self,
        to_handle: str,
        event: Any,
        send_meta: Dict[str, Any],
    ) -> bool:
        """Try to send a card for the given event.

        Returns True if a card was sent, False if no card kind matched.
        """
        meta = context.extract_meta(event)
        if not meta:
            return False

        message_type = meta.get("message_type", "")
        kind = self._by_message_type.get(message_type)
        if not kind:
            return False

        try:
            return await kind.render(
                self._channel,
                to_handle,
                event,
                send_meta,
                meta,
            )
        except Exception:
            logger.exception(
                "wecom card render failed for message_type=%r",
                message_type,
            )
            return False

    # ------------------------------------------------------------------
    # Inbound: handle a template card callback
    # ------------------------------------------------------------------

    async def handle_template_card_event_async(
        self,
        frame: Any,
    ) -> None:
        """Route an inbound template-card callback to the right handler.

        Extracts ``task_id`` from the frame, matches its prefix, and
        delegates to the registered ``CardKind.handle``.
        """
        task_id = self._extract_task_id(frame)
        if not task_id:
            logger.warning("wecom card callback: no task_id in frame")
            return

        for prefix, kind in self._by_task_id_prefix.items():
            if task_id.startswith(prefix):
                try:
                    await kind.handle(self._channel, frame)
                except Exception:
                    logger.exception(
                        "wecom card handle failed for kind=%r",
                        kind.name,
                    )
                return

        logger.warning(
            "wecom card callback: no handler for task_id=%r",
            task_id[:50],
        )

    def handle_template_card_event_sync(
        self,
        frame: Any,
    ) -> None:
        """Sync wrapper for :meth:`handle_template_card_event_async`.

        Used as the callback registered with the WeCom SDK.
        Schedules the async handler on the channel's event loop.
        """
        loop = getattr(self._channel, "_loop", None)
        if loop and loop.is_running():
            asyncio.run_coroutine_threadsafe(
                self.handle_template_card_event_async(frame),
                loop,
            )
        else:
            logger.warning(
                "wecom card callback: no event loop available, "
                "running synchronously",
            )
            asyncio.run(self.handle_template_card_event_async(frame))

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _extract_task_id(frame: Any) -> Optional[str]:
        """Extract ``task_id`` from a WeCom template-card callback frame.

        The SDK delivers the raw WebSocket frame whose structure is::

            { "body": { "event": { "template_card_event": { "task_id": ... } } } }

        We also tolerate flattened frames where ``task_id`` sits at the
        top level or directly under ``event``.
        """
        if hasattr(frame, "task_id"):
            return getattr(frame, "task_id", None)
        if isinstance(frame, dict):
            # 1. Flat: frame["task_id"]
            tid = frame.get("task_id")
            if tid:
                return tid
            # 2. SDK raw frame: body → event → template_card_event → task_id
            body = frame.get("body") or {}
            event = body.get("event") or {}
            card = event.get("template_card_event") or {}
            tid = card.get("task_id")
            if tid:
                return tid
            # 3. body → event → task_id
            tid = event.get("task_id")
            if tid:
                return tid
            # 4. frame → event → task_id
            event2 = frame.get("event") or {}
            if isinstance(event2, dict):
                tid = event2.get("task_id")
                if tid:
                    return tid
        return None
