# -*- coding: utf-8 -*-
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

"""Approval service for sensitive tool execution.

The ``ApprovalService`` is the single central store for pending /
completed approval records.  Approval is granted exclusively via
the ``/daemon approve`` command in the chat interface.
"""
from __future__ import annotations

import asyncio
import logging
import time
import uuid
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

from ...constant import TOOL_GUARD_APPROVAL_TIMEOUT_SECONDS
from ...security.tool_guard.approval import ApprovalDecision

if TYPE_CHECKING:
    from ...security.tool_guard.models import ToolGuardResult

logger = logging.getLogger(__name__)

_GC_MAX_AGE_SECONDS = 3600.0
_GC_MAX_COMPLETED = 500
_GC_PENDING_MAX_AGE_SECONDS = 1800.0
_GC_MAX_PENDING = 200


# ------------------------------------------------------------------
# Data model
# ------------------------------------------------------------------


@dataclass
class PendingApproval:
    """In-memory record for one pending approval."""

    request_id: str
    session_id: str
    root_session_id: str  # Root session for cross-session approval routing
    user_id: str
    channel: str
    agent_id: str  # Which agent is requesting approval
    tool_name: str
    created_at: float
    future: asyncio.Future[ApprovalDecision]
    timeout_seconds: float = 300.0  # Approval timeout in seconds
    status: str = "pending"
    resolved_at: float | None = None
    result_summary: str = ""
    findings_count: int = 0
    severity: str = "medium"  # For frontend display
    extra: dict[str, Any] = field(default_factory=dict)


# ------------------------------------------------------------------
# Service
# ------------------------------------------------------------------


class ApprovalService:
    """Global singleton approval service.

    Manages all tool approval requests across sessions and agents.
    Approval is resolved via ``/approval`` control command.
    """

    def __init__(self) -> None:
        self._lock = asyncio.Lock()
        self._pending: dict[str, PendingApproval] = {}
        self._channel_manager: Any | None = None
        self._gc_task: asyncio.Task[None] | None = None

    def set_channel_manager(self, channel_manager: Any) -> None:
        """Store a reference to the channel manager for push notifications."""
        self._channel_manager = channel_manager

    # ------------------------------------------------------------------
    # Expiry helpers
    # ------------------------------------------------------------------

    def _expire_stale_locked(self, now: float) -> int:
        """Mark expired pending records as ``timeout`` and resolve futures.

        Caller must hold ``_lock``.  A record is expired once
        ``now - created_at > timeout_seconds``.  Resolving the future is
        essential: the waiting agent coroutine has usually already given up,
        and leaving the record ``pending`` makes every downstream reader
        (``/console/push-messages``, ``/approve``) hand out a *dead*
        approval — which is what produced the "card appears for 0 ms" and
        "approved but nothing ran" symptoms.

        Returns the number of records expired by this call.
        """
        expired = [
            k
            for k, v in self._pending.items()
            if v.status == "pending"
            and now - v.created_at > v.timeout_seconds
        ]
        for k in expired:
            pending = self._pending[k]
            if not pending.future.done():
                pending.future.set_result(ApprovalDecision.TIMEOUT)
            pending.status = "timeout"
            pending.resolved_at = now
            logger.info(
                "Approval %s auto-timed out (age=%.0fs, timeout=%.0fs, tool=%s)",
                k[:8],
                now - pending.created_at,
                pending.timeout_seconds,
                pending.tool_name,
            )
        return len(expired)

    def start_maintenance(self, interval_seconds: float = 60.0) -> None:
        """Start the periodic expiry/GC loop (idempotent).

        Expiry used to be evaluated only when a *new* approval was created
        (``_gc_pending_locked``) or when a reader happened to call
        ``list_pending_by_session``.  A session that produced one approval
        and then went quiet kept its dead record alive for the full
        ``_GC_PENDING_MAX_AGE_SECONDS`` (30 min), so the frontend kept
        being handed corpses.  This loop makes expiry time-based.
        """
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            logger.debug("Approval maintenance: no running loop, skip")
            return

        if self._gc_task is not None and not self._gc_task.done():
            return

        async def _loop() -> None:
            logger.info(
                "Approval maintenance loop started (interval=%.0fs)",
                interval_seconds,
            )
            while True:
                try:
                    await asyncio.sleep(interval_seconds)
                    async with self._lock:
                        expired = self._expire_stale_locked(time.time())
                        self._gc_pending_locked()
                    if expired:
                        logger.info(
                            "Approval maintenance: expired %d stale record(s)",
                            expired,
                        )
                except asyncio.CancelledError:
                    logger.debug("Approval maintenance loop cancelled")
                    raise
                except Exception:  # pragma: no cover - defensive
                    logger.warning("Approval maintenance tick failed", exc_info=True)

        self._gc_task = loop.create_task(_loop())

    def stop_maintenance(self) -> None:
        """Stop the periodic maintenance loop (used by tests/shutdown)."""
        if self._gc_task is not None and not self._gc_task.done():
            self._gc_task.cancel()
        self._gc_task = None

    # ------------------------------------------------------------------
    # Core approval lifecycle
    # ------------------------------------------------------------------

    async def create_pending(
        self,
        *,
        session_id: str,
        root_session_id: str,
        user_id: str,
        channel: str,
        agent_id: str,
        tool_name: str,
        result: "ToolGuardResult",
        timeout_seconds: float = TOOL_GUARD_APPROVAL_TIMEOUT_SECONDS,
        extra: dict[str, Any] | None = None,
    ) -> PendingApproval:
        """Create a pending approval record and return it."""
        from ...security.tool_guard.approval import format_findings_summary

        request_id = str(uuid.uuid4())
        loop = asyncio.get_running_loop()

        pending = PendingApproval(
            request_id=request_id,
            session_id=session_id,
            root_session_id=root_session_id,
            user_id=user_id,
            channel=channel,
            agent_id=agent_id,
            tool_name=tool_name,
            created_at=time.time(),
            future=loop.create_future(),
            timeout_seconds=timeout_seconds,
            result_summary=format_findings_summary(result),
            findings_count=result.findings_count,
            severity=result.max_severity.value,
            extra=dict(extra or {}),
        )

        async with self._lock:
            self._pending[request_id] = pending
            self._gc_pending_locked()

        logger.info(
            "Approval pending created: request_id=%s agent_id=%s tool=%s "
            "severity=%s session=%s root=%s",
            request_id[:8],
            agent_id,
            tool_name,
            pending.severity,
            session_id[:8],
            root_session_id[:8],
        )

        return pending

    async def resolve_request(
        self,
        request_id: str,
        decision: ApprovalDecision,
    ) -> PendingApproval | None:
        """Resolve pending approval by setting Future result."""
        async with self._lock:
            pending = self._pending.pop(request_id, None)
            if pending is None:
                logger.warning(
                    "Approval request %s not found (already resolved?)",
                    request_id[:8],
                )
                return None

            pending.status = decision.value
            pending.resolved_at = time.time()

        # Set Future result outside lock
        if not pending.future.done():
            pending.future.set_result(decision)

        logger.info(
            "Approval request %s resolved: decision=%s tool=%s",
            request_id[:8],
            decision.value,
            pending.tool_name,
        )

        return pending

    async def get_request(self, request_id: str) -> PendingApproval | None:
        """Get a pending request by id."""
        async with self._lock:
            return self._pending.get(request_id)

    async def resolve_live(
        self,
        request_id: str,
        decision: ApprovalDecision,
    ) -> tuple[PendingApproval | None, str]:
        """Resolve *request_id* only if an agent is still waiting on it.

        Returns ``(pending, state)`` where ``state`` is one of:

        ``ok``        — record was live, decision delivered, tool will run.
        ``not_found`` — no such record (never existed / already GC'd).
        ``stale``     — record exists but its Future is closed: the waiting
                        agent gave up long ago. Approving it would only
                        produce a "✅ 已批准，正在执行" message that nothing
                        backs up — which is exactly symptom 3.
        """
        async with self._lock:
            self._expire_stale_locked(time.time())
            pending = self._pending.get(request_id)
            if pending is None:
                return None, "not_found"
            if pending.status != "pending" or pending.future.done():
                return pending, "stale"

        resolved = await self.resolve_request(request_id, decision)
        return resolved, "ok"

    async def get_pending_by_session(
        self,
        session_id: str,
    ) -> PendingApproval | None:
        """Return the next *live* pending approval for *session_id* (FIFO).

        Pending approvals are consumed in creation order, so repeated
        ``/approve`` inputs walk the queue from oldest to newest.  Expired
        records are marked ``timeout`` and skipped — approving a dead record
        is what made ``/approve`` answer "✅ 工具已批准 … 正在执行" while no
        agent coroutine was waiting on the Future any more.
        """
        async with self._lock:
            self._expire_stale_locked(time.time())
            for pending in self._pending.values():
                if (
                    pending.session_id == session_id
                    and pending.status == "pending"
                ):
                    return pending
        return None

    async def get_all_pending_by_session(
        self,
        session_id: str | None,
    ) -> list[PendingApproval]:
        """Return *live* pending approvals, optionally filtered by session_id.

        When *session_id* is None, returns ALL live pending approvals across
        all sessions (used by ConsolePollService which polls globally).
        Expired records are marked ``timeout`` and excluded.
        """
        async with self._lock:
            self._expire_stale_locked(time.time())
            if session_id is None:
                return [
                    p for p in self._pending.values()
                    if p.status == "pending"
                ]
            return [
                p for p in self._pending.values()
                if p.session_id == session_id and p.status == "pending"
            ]

    async def list_pending_by_session(
        self,
        session_id: str,
        include_subagents: bool = True,  # pylint: disable=unused-argument
    ) -> list[PendingApproval]:
        """List all live pending approvals for a session (FIFO order).

        Args:
            session_id: Session ID to filter
            include_subagents: If False, exclude sub-agent approvals (future)

        Returns:
            List of pending approvals sorted by creation time.
            Expired approvals (past timeout) are marked ``timeout``, their
            Future resolved, and filtered out.
        """
        now = time.time()
        async with self._lock:
            self._expire_stale_locked(now)
            result = [
                p for p in self._pending.values()
                if p.session_id == session_id and p.status == "pending"
            ]
            return sorted(result, key=lambda p: p.created_at)

    async def get_pending_by_root_session(
        self,
        root_session_id: str,
    ) -> list[PendingApproval]:
        """Get all *live* pending approvals for root session and its children.

        Args:
            root_session_id: Root session ID

        Returns:
            List of pending approvals sorted by creation time (FIFO)
        """
        async with self._lock:
            self._expire_stale_locked(time.time())
            result = [
                p
                for p in self._pending.values()
                if p.root_session_id == root_session_id
                and p.status == "pending"
            ]
            return sorted(result, key=lambda p: p.created_at)

    async def get_all_pending_by_agent(
        self,
        agent_id: str,
    ) -> list[PendingApproval]:
        """Get all *live* pending approvals for an agent (across all sessions).

        Used by /approval list --all command.

        Args:
            agent_id: Agent ID

        Returns:
            List of pending approvals sorted by creation time (FIFO)
        """
        async with self._lock:
            self._expire_stale_locked(time.time())
            result = [
                p
                for p in self._pending.values()
                if p.agent_id == agent_id and p.status == "pending"
            ]
            return sorted(result, key=lambda p: p.created_at)

    async def get_pending_by_user(
        self,
        user_id: str,
    ) -> list[PendingApproval]:
        """Get all *live* pending approvals for a user.

        Used by /console/push-messages to ensure user-level isolation.
        Only returns approvals belonging to the specified user.

        Args:
            user_id: User ID (from authentication context)

        Returns:
            List of pending approvals sorted by creation time (FIFO)
        """
        async with self._lock:
            self._expire_stale_locked(time.time())
            result = [
                p
                for p in self._pending.values()
                if p.user_id == user_id and p.status == "pending"
            ]
            return sorted(result, key=lambda p: p.created_at)

    async def find_live_by_prefix(
        self,
        request_id_prefix: str,
        *,
        session_id: str | None = None,
        agent_id: str | None = None,
    ) -> tuple[PendingApproval | None, int]:
        """Resolve a request id prefix to one *live* approval.

        Lets ``/approve 1eb5d110`` target a specific approval.  Returns
        ``(pending, matches)``: ``matches`` is how many live records share
        the prefix, so the caller can complain about ambiguity instead of
        silently approving the wrong tool.
        """
        if not request_id_prefix:
            return None, 0
        async with self._lock:
            self._expire_stale_locked(time.time())
            hits = [
                p
                for p in self._pending.values()
                if p.status == "pending"
                and p.request_id.startswith(request_id_prefix)
                and (session_id is None or p.session_id == session_id)
                and (agent_id is None or p.agent_id == agent_id)
            ]
        hits.sort(key=lambda p: p.created_at)
        if len(hits) == 1:
            return hits[0], 1
        return None, len(hits)

    async def live_remaining_seconds(self, request_id: str) -> float | None:
        """Server-authoritative countdown for one approval, or None if gone.

        The frontend used to derive the countdown from ``Date.now()`` minus
        the server's ``created_at`` — two clocks that are not guaranteed to
        agree.  A browser running a few seconds ahead made cards expire the
        instant they mounted.
        """
        async with self._lock:
            pending = self._pending.get(request_id)
            if pending is None or pending.status != "pending":
                return None
            left = pending.timeout_seconds - (time.time() - pending.created_at)
            return max(0.0, left)


    async def wait_for_approval(
        self,
        request_id: str,
        timeout_seconds: float,
    ) -> ApprovalDecision:
        """Block and wait for approval decision with timeout.

        Args:
            request_id: Approval request ID
            timeout_seconds: Maximum wait time in seconds

        Returns:
            ApprovalDecision (APPROVED/DENIED/TIMEOUT)

        Raises:
            ValueError: If request_id not found
        """
        async with self._lock:
            pending = self._pending.get(request_id)

        if pending is None:
            raise ValueError(f"Approval request {request_id} not found")

        try:
            decision = await asyncio.wait_for(
                pending.future,
                timeout=timeout_seconds,
            )
        except asyncio.TimeoutError:
            decision = ApprovalDecision.TIMEOUT
            await self.resolve_request(request_id, decision)

        return decision

    async def cancel_stale_pending_for_tool_call(
        self,
        session_id: str,
        tool_call_id: str,
    ) -> int:
        """Cancel pending approvals whose stored tool_call id matches.

        When a tool call is replayed (e.g. after approval triggers
        sibling replay), the guard may create a *new* pending for the
        same logical tool call.  This method cancels the old pending
        first so orphaned records don't accumulate.

        Returns the number of records cancelled.
        """
        now = time.time()
        cancelled = 0
        async with self._lock:
            to_cancel = [
                k
                for k, p in self._pending.items()
                if p.session_id == session_id
                and p.status == "pending"
                and isinstance(p.extra.get("tool_call"), dict)
                and p.extra["tool_call"].get("id") == tool_call_id
            ]
            for k in to_cancel:
                pending = self._pending.pop(k)
                if not pending.future.done():
                    pending.future.set_result(ApprovalDecision.TIMEOUT)
                pending.status = "superseded"
                pending.resolved_at = now
                cancelled += 1
        if cancelled:
            logger.info(
                "Tool guard: cancelled %d stale pending approval(s) "
                "for tool_call %s (session %s)",
                cancelled,
                tool_call_id,
                session_id[:8],
            )
        return cancelled

    async def cancel_all_pending_by_root_session(
        self,
        root_session_id: str,
    ) -> int:
        """Cancel all pending approvals for root session and its children.

        Called when user stops/cancels a task (e.g., /stop command or
        SSE disconnect). Auto-denies all pending approvals to unblock
        waiting tasks.

        Args:
            root_session_id: Root session ID

        Returns:
            Number of approvals cancelled
        """
        now = time.time()
        cancelled = 0
        async with self._lock:
            to_cancel = [
                k
                for k, p in self._pending.items()
                if p.root_session_id == root_session_id
                and p.status == "pending"
            ]
            for k in to_cancel:
                pending = self._pending.pop(k)
                if not pending.future.done():
                    pending.future.set_result(ApprovalDecision.DENIED)
                pending.status = "cancelled"
                pending.resolved_at = now
                cancelled += 1
        if cancelled:
            logger.info(
                "Cancelled %d pending approval(s) for root session %s",
                cancelled,
                root_session_id[:8]
                if len(root_session_id) >= 8
                else root_session_id,
            )
        return cancelled

    # ------------------------------------------------------------------
    # Garbage collection
    # ------------------------------------------------------------------

    def _gc_pending_locked(self) -> None:
        """Evict stale pending records whose futures were never resolved.

        Caller must hold ``_lock``.
        """
        now = time.time()
        # Per-approval timeout first (the authoritative rule), then the
        # coarse age/size caps.
        self._expire_stale_locked(now)
        expired = [
            k
            for k, v in self._pending.items()
            if now - v.created_at > _GC_PENDING_MAX_AGE_SECONDS
        ]
        for k in expired:
            pending = self._pending.pop(k)
            if not pending.future.done():
                pending.future.set_result(ApprovalDecision.TIMEOUT)
            pending.status = "timeout"
            pending.resolved_at = now

        overflow = len(self._pending) - _GC_MAX_PENDING
        if overflow <= 0:
            return
        ordered = sorted(
            self._pending.items(),
            key=lambda item: item[1].created_at,
        )
        for key, pending in ordered[:overflow]:
            del self._pending[key]
            if not pending.future.done():
                pending.future.set_result(ApprovalDecision.TIMEOUT)
            pending.status = "timeout"
            pending.resolved_at = now


# ------------------------------------------------------------------
# Singleton
# ------------------------------------------------------------------

_approval_service: ApprovalService | None = None


def get_approval_service() -> ApprovalService:
    """Return the process-wide approval service singleton."""
    global _approval_service
    if _approval_service is None:
        _approval_service = ApprovalService()
    return _approval_service
