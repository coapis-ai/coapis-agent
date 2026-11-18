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
import os
import time
import uuid
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

from ...constant import TOOL_GUARD_APPROVAL_TIMEOUT_SECONDS
from ...security.tool_guard.approval import ApprovalDecision
from .intent_ledger import (
    intent_stats as _intent_stats,
    list_intent_rows as _list_intent_rows,
    list_timeout_rows as _list_timeout_rows,
    record_intent,
    sweep_orphaned_intents,
)

if TYPE_CHECKING:
    from ...security.tool_guard.models import ToolGuardResult

logger = logging.getLogger(__name__)

_GC_MAX_AGE_SECONDS = 3600.0
_GC_MAX_COMPLETED = 500
_GC_PENDING_MAX_AGE_SECONDS = 1800.0
_GC_MAX_PENDING = 200

# Actor sources accepted by :func:`_identity_check`.  ``internal`` is the
# approval system itself (expiry / GC), ``card_callback`` is the WeCom card
# callback whose binding was already validated by the channel layer, and
# ``agent`` is the waiting coroutine closing its own future.  Everything
# else — HTTP requests and control commands — must carry a real identity.
ACTOR_INTERNAL = "internal"
ACTOR_CARD_CALLBACK = "card_callback"
ACTOR_AGENT = "agent"
TRUSTED_ACTOR_SOURCES = frozenset({ACTOR_INTERNAL, ACTOR_CARD_CALLBACK, ACTOR_AGENT})

#: Single user-facing text for every identity rejection (D11 一刀a).
FORBIDDEN_MESSAGE = "无权操作此审批"


# ------------------------------------------------------------------
# Data model
# ------------------------------------------------------------------


@dataclass(frozen=True)
class ApprovalActor:
    """Who is operating on an approval.

    Carried explicitly at every call site — the system never infers an
    identity from ambient context variables.  ``source`` marks where the
    request came from: ``http``, ``control_command``, ``card_callback``,
    ``internal`` or ``agent``; only the first two require a full identity.
    """

    user_id: str = ""
    is_admin: bool = False
    channel: str = ""
    source: str = ""


def _self_approval_forbidden() -> bool:
    """属主本人能否批准自己发起的操作（默认 **放行**）。

    2026-11-18 拍板：CoApis 是「个人对自己的会话做自己的操作」，审批的
    目的不是「谁也不能自批」这种合规形态，而是「危险动作要有人确认」。
    属主本人点批准就是最强确认 —— 拦它只会把「顺畅」变成「反复打断」。

    治理诉求保留：部署侧显式 ``COAPIS_APPROVAL_SELF_APPROVAL=forbid``
    即打开强约束（属主自批被拒，台账记 ``refused:self_approval_forbidden``）。

    真正的跨用户边界不在这个旋钮里：非属主的普通用户、无身份的调用者，
    任何档位下都拒（见 ``_identity_check`` 的 ``missing_actor`` /
    ``missing_identity`` / ``not_owner``）。管理员代批始终放行并单独成桶
    （``decide_source=admin_override``）。
    """
    return (
        os.environ.get("COAPIS_APPROVAL_SELF_APPROVAL", "allow").strip().lower()
        == "forbid"
    )


def _identity_check(pending: Any, actor: Any) -> str | None:
    """Return ``None`` to allow, or a reason code to reject.

    Identity is enforced **inside** the resolve entry points, not in the
    routers: an internal caller that forgets to pass an actor is denied
    rather than silently trusted, which is what keeps a cross-user
    approval from being resolved by accident.
    """
    if actor is None:
        return "missing_actor"
    source = str(getattr(actor, "source", "") or "")
    if source in TRUSTED_ACTOR_SOURCES:
        return None
    owner = str(getattr(pending, "owner_user_id", "") or "")
    if not owner:
        # Legacy ledgers written before ownership existed.  Denying beats
        # guessing: the user re-issues the approval in their own session.
        return "unowned_record"
    actor_user = str(getattr(actor, "user_id", "") or "")
    if not actor_user:
        return "missing_identity"
    actor_channel = str(getattr(actor, "channel", "") or "")
    pending_channel = str(getattr(pending, "channel", "") or "")
    if actor_channel and pending_channel and actor_channel != pending_channel:
        return "channel_mismatch"
    if actor_user == owner:
        # D7 禁止自批（方案 §13 拍板 D7）：发起这次工具调用的属主不能
        # 自己批准自己的操作。灰度旋钮见 _self_approval_forbidden()。
        if _self_approval_forbidden():
            return "self_approval_forbidden"
        return None
    if bool(getattr(actor, "is_admin", False)):
        # Admin override is allowed but must leave a trace: 台账
        # decide_source="admin_override"（见 resolve_request 落账处），
        # 事后能回答"这张卡是谁替谁批的"。
        logger.info(
            "approval admin override: request_id=%s owner=%s actor=%s "
            "source=%s",
            pending.request_id,
            owner,
            actor_user,
            source,
        )
        return None
    return "not_owner"


#: Public alias — routers use it to answer 403 before calling resolve.
identity_check = _identity_check


#: 拒绝原因 → 台账码位（聚合尺子）。
#:
#: 台账按码分桶，不对人话句子做字符串匹配 —— 与判官原因码（judge_reasons）
#: 同一纪律。已知码透传，未知原因取首词兜底，保证"每行都有码"。
def _reason_code(reason: str) -> str:
    text = str(reason or "").strip()
    for known in ("missing_actor", "not_owner"):
        if text.startswith(known):
            return known
    return (text.split(" ", 1)[0].lower()[:32]) if text else "unknown"


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
    #: Ownership axis of the identity boundary (B2).  Written by
    #: :meth:`create_pending` from the requesting user; rows restored from a
    #: ledger written before ownership existed carry an empty owner, and the
    #: identity check refuses those instead of guessing.
    owner_user_id: str = ""


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
            # 台账：超时不是"消失"，是一次**默认拒绝**（B2 · 契约目标锁）。
            # 裁决字面量用 TIMED_OUT（台账尺子）；Future 侧仍回 TIMEOUT，
            # 因为那是 agent 等的信号，改名等于历史对不上。
            record_intent(
                pending,
                decision=ApprovalDecision.TIMED_OUT.value,
                outcome="auto:timeout",
                decide_source="internal",
                why=(
                    f"超时默认拒绝：age={now - pending.created_at:.0f}s > "
                    f"timeout={pending.timeout_seconds:.0f}s"
                ),
            )
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
                    # DB 侧清扫：内存 future 活不过重启，上一辈子的
                    # pending 行必须有人收场，否则读侧永远看见僵尸行
                    sweep_orphaned_intents()
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
            owner_user_id=user_id,
        )

        async with self._lock:
            self._pending[request_id] = pending
            self._gc_pending_locked()

        # 台账：入队即登记（decision 留空 = 仍在等）。B2 交付：审批意图从
        # 这一刻起可统计——此前队列是纯内存态，裁决取走即消失，盘上 0 行，
        # 「用户到底批过什么」在盘上没有任何证据。
        record_intent(pending)

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
        *,
        actor: ApprovalActor | None = None,
    ) -> PendingApproval | None:
        """Resolve pending approval by setting Future result.

        *actor* states **who** is acting (B2 identity boundary).  The check
        lives here rather than in the routers on purpose: a caller that
        forgets the actor is denied instead of silently trusted, and the
        agent-side, card-callback and expiry paths stay open by declaring
        ``source="internal"`` / ``"card_callback"`` / ``"agent"``.
        """
        async with self._lock:
            pending = self._pending.get(request_id)
            if pending is None:
                logger.warning(
                    "Approval request %s not found (already resolved?)",
                    request_id[:8],
                )
                return None

            reason = _identity_check(pending, actor)
            if reason is not None:
                # One unified user-facing outcome for every identity
                # rejection; the log carries the machine-readable reason.
                logger.warning(
                    "Approval %s refused: %s (source=%s actor=%s)",
                    request_id[:8],
                    reason,
                    getattr(actor, "source", ""),
                    getattr(actor, "user_id", ""),
                )
                # 台账：未遂选择照入账（B2 身份边界的账面证据）。
                # decision 记**用户点的动作**，outcome 记 refused:<原因> ——
                # 两列分记是刻意的：用户点了批准，台账不能写成他拒绝。
                # 对账时"跨用户审批未遂"按 outcome 前缀单列成桶。
                record_intent(
                    pending,
                    decision=decision.value,
                    outcome="refused:" + _reason_code(reason),
                    decided_by=str(getattr(actor, "user_id", "") or ""),
                    decide_source="refused",
                    why=reason,
                )
                return None

            self._pending.pop(request_id, None)
            pending.status = decision.value
            pending.resolved_at = time.time()

        # Set Future result outside lock
        if not pending.future.done():
            pending.future.set_result(decision)

        # 台账：用户的选择落成一行（B2 · 契约目标锁
        # ``test_user_choice_leaves_an_intent_ledger_row``）。验收口径要求
        # 事后能回答"选了哪种、为什么、谁选的、经哪条通道"。
        # 管理员代批单独成桶（decide_source=admin_override）——
        # "谁替谁批的"必须能从台账直接查，不靠翻日志。
        _actor_source = str(getattr(actor, "source", "") or "")
        _admin_override = (
            bool(getattr(actor, "is_admin", False))
            and str(getattr(actor, "user_id", "") or "")
            != str(getattr(pending, "owner_user_id", "") or "")
        )
        # 尺子修正：agent 侧的**自动收场**不是「用户裁决被采纳」。
        # 超时（tool_guard_mixin 等待循环）与用户 /stop（CancelledError）
        # 都经这里落账，此前一律写 outcome=applied + 枚举名，于是台账里
        # 出现过 decision=timeout / outcome=applied 这种自相矛盾的行，
        # 而 /stop 也被计进了「用户拒绝」。两件事都不该存在：
        #   · decision 是台账尺子词表（timed_out / system_cancelled），
        #     枚举名 timeout 越界；
        #   · outcome 前缀 auto = 系统自动收场，与 applied 严格分家。
        if decision == ApprovalDecision.TIMEOUT:
            _ledger_decision = "timed_out"
            _ledger_outcome = "auto:timeout"
            _decide_source = "internal"
        elif decision == ApprovalDecision.DENIED and _actor_source == "agent":
            _ledger_decision = "system_cancelled"
            _ledger_outcome = "auto:cancel"
            _decide_source = "internal"
        else:
            _ledger_decision = decision.value
            _ledger_outcome = "applied"
            _decide_source = (
                "admin_override"
                if _admin_override
                else (_actor_source or "internal")
            )
        record_intent(
            pending,
            decision=_ledger_decision,
            outcome=_ledger_outcome,
            decided_by=str(getattr(actor, "user_id", "") or ""),
            decide_source=_decide_source,
            why=str(getattr(actor, "reason", "") or ""),
        )

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
        *,
        actor: ApprovalActor | None = None,
    ) -> tuple[PendingApproval | None, str]:
        """Resolve *request_id* only if an agent is still waiting on it.

        Returns ``(pending, state)`` where ``state`` is one of:

        ``ok``        — record was live, decision delivered, tool will run.
        ``not_found`` — no such record (never existed / already GC'd).
        ``stale``     — record exists but its Future is closed: the waiting
                        agent gave up long ago. Approving it would only
                        produce a "✅ 已批准，正在执行" message that nothing
                        backs up — which is exactly symptom 3.
        ``forbidden`` — *actor* may not act on this record (B2 identity
                        boundary); nothing was changed.
        """
        async with self._lock:
            self._expire_stale_locked(time.time())
            pending = self._pending.get(request_id)
            if pending is None:
                return None, "not_found"
            if _identity_check(pending, actor) is not None:
                logger.warning(
                    "Approval %s refused: identity check failed "
                    "(source=%s actor=%s)",
                    request_id[:8],
                    getattr(actor, "source", ""),
                    getattr(actor, "user_id", ""),
                )
                return None, "forbidden"
            if pending.status != "pending" or pending.future.done():
                return pending, "stale"

        resolved = await self.resolve_request(request_id, decision, actor=actor)
        if resolved is None:
            return None, "not_found"
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

    # ------------------------------------------------------------------
    # 意图台账（B2 · 方案 v1 §4 验收 5）
    #
    # 队列回答"现在要不要批"，台账回答"批过什么、谁批的、怎么收的场"。
    # 读侧永不抛：台账坏了返回空列表，审批主链不受影响。
    # ------------------------------------------------------------------

    async def list_intent_rows(
        self,
        session_id: str = "",
        *,
        user_id: str = "",
        limit: int = 100,
    ) -> list[dict[str, Any]]:
        """已收场的审批意图（用户选择可统计、可追溯）。"""
        return _list_intent_rows(
            session_id, user_id=user_id, limit=limit
        )

    async def list_timeout_rows(
        self,
        session_id: str = "",
        *,
        user_id: str = "",
        limit: int = 100,
    ) -> list[dict[str, Any]]:
        """超时默认拒绝的审批（超时不是一笑了之，是一次裁决）。

        读侧先结账：过期卡留在内存里不算"已超时入账"，读的时候顺手把
        过期行落成裁决 —— 于是"超时了几张"这个数不依赖维护循环的节拍。
        """
        async with self._lock:
            self._expire_stale_locked(time.time())
        return _list_timeout_rows(
            session_id, user_id=user_id, limit=limit
        )

    async def intent_stats(self, *, since: float = 0.0) -> dict[str, Any]:
        """裁决分布计数（看板口径：已收场的行 + 按收场通道分桶）。"""
        return _intent_stats(since=since)

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
            await self.resolve_request(
                request_id,
                decision,
                actor=ApprovalActor(source=ACTOR_INTERNAL),
            )

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
        # ``now`` is read inside the loop below but was never defined, so
        # closing a chat that still had pending approvals raised NameError.
        now = time.time()
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
                # 台账：被取代也是收场，必须入账（否则"卡凭空消失"与
                # "用户批了"在台账里长得一样）。
                record_intent(
                    pending,
                    decision="system_cancelled",
                    outcome="auto:superseded",
                    decide_source="internal",
                    why=f"同一工具调用重放，旧卡作废（tool_call={tool_call_id}）",
                )
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

    async def cancel_by_chat(
        self,
        chat_id: str,
        actor: ApprovalActor | None,
        *,
        reason: str = "chat_closed",
    ) -> int:
        """Cancel every approval left over in **one chat** (B2-③).

        Three explicit dimensions: the *chat_id* passed by the caller (never
        read from a context variable), the record's channel, and the actor's
        identity.  Records owned by someone else are skipped — this is the
        end-of-tool-call sweep, not an admin tool.
        """
        if not chat_id:
            return 0
        cancelled = 0
        # ``now`` is read inside the loop below but was never defined, so
        # closing a chat that still had pending approvals raised NameError.
        now = time.time()
        async with self._lock:
            for request_id, pending in list(self._pending.items()):
                if str(pending.extra.get("chat_id", "")) != chat_id:
                    continue
                if _identity_check(pending, actor) is not None:
                    continue
                # 修缺陷（B2 实测发现，崩溃级）：这里原本调用
                # ``self._expire_stale_locked(pending, reason)`` 并把返回值
                # 当计数累加，而该方法签名是 ``(self, now)``、无返回值 ——
                # 只要 chat 有残留待批卡就会 TypeError。就地收场，语义与
                # _expire_stale_locked 一致（置超时、结算 Future、落台账）。
                pending.status = "timeout"
                pending.resolved_at = now
                if not pending.future.done():
                    pending.future.set_result(ApprovalDecision.TIMEOUT)
                record_intent(
                    pending,
                    decision=ApprovalDecision.TIMED_OUT.value,
                    outcome="auto:chat_closed",
                    decide_source="internal",
                    why=reason,
                )
                cancelled += 1
        if cancelled:
            logger.info(
                "Cancelled %d leftover approval(s) for chat %s",
                cancelled,
                chat_id,
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
        # ``now`` is read inside the loop below but was never defined, so
        # closing a chat that still had pending approvals raised NameError.
        now = time.time()
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
                # 台账：/stop 或断连导致的批量作废要入账（system_cancelled）。
                # 与用户主动拒批分开统计 —— 否则"取消会话"会被算成
                # "用户拒绝审批"，拒绝率被污染。
                record_intent(
                    pending,
                    decision="system_cancelled",
                    outcome="auto:stop_or_disconnect",
                    decide_source="internal",
                    why="用户停止任务/断连，待批准卡自动拒绝",
                )
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
            # 台账：GC 清的卡也是收场（超时默认拒绝），不记的话"卡凭空
            # 消失"与"用户批了/拒了"在台账里长得一样，超时率算不出来。
            record_intent(
                pending,
                decision=ApprovalDecision.TIMED_OUT.value,
                outcome="auto:timeout_gc",
                decide_source="internal",
                why=f"队列 GC 清理（卡龄超过 {_GC_PENDING_MAX_AGE_SECONDS:.0f}s）",
            )

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
            record_intent(
                pending,
                decision=ApprovalDecision.TIMED_OUT.value,
                outcome="auto:timeout_overflow",
                decide_source="internal",
                why=f"队列超过 {_GC_MAX_PENDING} 张上限，清最老的卡",
            )


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
