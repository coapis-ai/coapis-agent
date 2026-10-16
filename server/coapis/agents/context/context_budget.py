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

"""The gate in front of the model: fixed overhead counts against the window.

Why a wrapper and not a hook
----------------------------
Compaction (agentscope's ``_compress_memory_if_needed``) measures
``sys_prompt + history``.  It never sees the tool schemas, which are passed
separately to ``self.model(prompt, tools=...)`` — and in a Coapis session the
tool schemas are the single biggest fixed cost (30+ tools, tens of thousands
of characters, re-sent on every reasoning step).  A hook that only sees
memory cannot account for that, and hooks are registered per agent, so every
consumer outside the ReAct loop (AgentCore, the evolution engine, offline
evaluation) was unmeasured.

Wrapping the model covers every caller by construction: whoever calls the
model calls the gate.  The gate measures exactly what upstream counts
(``CharTokenCounter`` semantics: ``str(msg)`` per message plus ``str(tools)``)
and enforces the window resolved from the model's own report.

Three outcomes, and the third is loud
------------------------------------
- under the trigger: pass through.
- over the trigger, under the hard window: ask for compaction (the next
  reasoning step shrinks its tail) and pass through.
- over the hard window: archive the oldest messages to ``dialog/``, purge
  them from working memory **and trim the same rows out of the prompt being
  sent** — pruning memory alone only shrinks the *next* step, so the call
  that overflowed would still go out oversized.  If the fixed overhead alone
  is over the window, raise :class:`ContextOverflowError`.  A request that
  cannot fit is refused with a number attached — not sent to the provider to
  fail as an opaque 400.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any, Awaitable, Callable

from .window_source import WindowInfo

logger = logging.getLogger(__name__)


class ContextOverflowError(RuntimeError):
    """Raised when a prompt cannot fit the model's window after pruning."""


#: History that is never pruned, whatever the window says.  Two thousand
#: characters is roughly the last user turn plus one tool result — below it
#: the next reasoning step has nothing to reason about.
MIN_KEEP_CHARS = 2_000


def affordable_floor(
    budget_chars: int,
    fixed_chars: int,
    keep_chars_floor: int,
    min_keep_chars: int = MIN_KEEP_CHARS,
) -> int:
    """How deep the pruning loop is allowed to go before it refuses.

    The configured floor is derived from the window alone (``window × ratio ×
    0.5``), so an agent whose fixed overhead — system prompt + skills + tool
    schemas — is heavy gets a floor it cannot pay: ``fixed + floor > window``
    makes every single call overflow, and the floor then *blocks* the pruning
    that would have saved the call.  Measured on dev 2026-10-16: agent
    ``user:admin`` pays 49304 chars of fixed overhead against a 65536-char
    window with a 28835-char floor — 100% of its chats fail with
    ``MODEL_CONTEXT_LENGTH_EXCEEDED``.

    So the floor is a preference with a price.  When the window can pay it,
    it is the barrier.  When it cannot, the barrier drops to
    :data:`MIN_KEEP_CHARS` — the last exchange, which is the point below
    which the next reasoning step has nothing to reason about — and the call
    is pruned that deep rather than refused.  Losing the archived tail (it
    lands in ``dialog/*.jsonl``) beats failing every turn of the chat.
    """
    if budget_chars - fixed_chars >= keep_chars_floor:
        return keep_chars_floor
    return min_keep_chars


@dataclass(frozen=True)
class BudgetSnapshot:
    """One measurement of a prompt about to be sent."""

    history_chars: int
    fixed_chars: int
    tools_chars: int
    total_chars: int
    trigger_chars: int
    budget_chars: int

    @property
    def headroom_chars(self) -> int:
        return self.budget_chars - self.total_chars

    def as_dict(self) -> dict[str, Any]:
        return {
            "history_chars": self.history_chars,
            "fixed_chars": self.fixed_chars,
            "tools_chars": self.tools_chars,
            "total_chars": self.total_chars,
            "trigger_chars": self.trigger_chars,
            "budget_chars": self.budget_chars,
            "headroom_chars": self.headroom_chars,
        }


def measure_prompt(
    messages: Any,
    tools: Any,
    window: WindowInfo,
    compact_threshold_ratio: float,
) -> BudgetSnapshot:
    """Measure a prompt with the same arithmetic upstream uses.

    ``CharTokenCounter.count`` joins ``str(msg)`` for every formatted message
    and appends ``str(tools)``.  Anything that differs from that is a gate
    that disagrees with the provider about the size of the request.

    The system row is counted **once**, in ``fixed_chars``: it is overhead
    the model pays on every step and it is never pruned, so counting it in
    ``history_chars`` as well (as this function used to) inflated every
    measurement by the size of the system prompt and — because the floor is
    derived from ``budget - fixed`` — made the affordable history look
    bigger than it was.
    """
    rows = list(messages or [])
    tools_chars = len(str(tools)) if tools else 0
    # The formatter puts the system prompt first; it is fixed overhead the
    # model must pay on every step, same as the tool schemas.
    system_chars = 0
    if rows:
        first = rows[0]
        role = (
            first.get("role")
            if isinstance(first, dict)
            else getattr(first, "role", None)
        )
        if role == "system":
            system_chars = len(str(first))
    history_chars = sum(len(str(msg)) for msg in rows) - system_chars
    fixed_chars = system_chars + tools_chars
    total_chars = history_chars + fixed_chars
    budget_chars = window.effective_tokens
    trigger_chars = int(budget_chars * compact_threshold_ratio)
    return BudgetSnapshot(
        history_chars=history_chars,
        fixed_chars=fixed_chars,
        tools_chars=tools_chars,
        total_chars=total_chars,
        trigger_chars=trigger_chars,
        budget_chars=budget_chars,
    )


def trim_messages_to_budget(
    messages: list,
    window: WindowInfo,
    *,
    compact_threshold_ratio: float = 0.8,
    keep_chars_floor: int = 12_000,
    tools: Any = None,
) -> tuple[list, list, BudgetSnapshot]:
    """Drop the oldest messages until the prompt fits the window.

    The budget rule for callers that own a plain message list and have no
    ``AgentContext`` to purge through — the AgentCore path, which talks to
    the provider with a raw client and never goes through agentscope's
    compaction.  It uses the same window, the same trigger ratio and the
    same floor as the ReAct gate, so the two paths cannot disagree about
    what fits.

    Returns:
        ``(kept, dropped, snapshot)``.  ``kept`` is in original order.
        Raises ``ContextOverflowError`` when the floor blocks enough pruning
        that the request still cannot fit — the caller must surface that,
        not send an oversized request and take a provider 400.
    """
    rows = list(messages or [])
    snapshot = measure_prompt(
        rows,
        tools,
        window,
        compact_threshold_ratio,
    )
    if snapshot.total_chars <= snapshot.budget_chars:
        return rows, [], snapshot

    over = snapshot.total_chars - snapshot.budget_chars
    # Same clamp as the ReAct gate: the floor can never exceed what the
    # window spares after fixed overhead, or it blocks the pruning that
    # would have saved this call.
    floor = affordable_floor(
        snapshot.budget_chars,
        snapshot.fixed_chars,
        keep_chars_floor,
    )
    # System row is fixed overhead; pruning starts after it.
    start = 1 if rows and (rows[0].get("role") == "system") else 0
    droppable = rows[start:]
    remaining = sum(len(str(m)) for m in droppable)
    dropped: list = []
    reclaimed = 0
    for msg in droppable:
        if reclaimed >= over:
            break
        size = len(str(msg))
        if remaining - size < floor:
            break
        dropped.append(msg)
        reclaimed += size
        remaining -= size

    if not dropped:
        raise ContextOverflowError(
            f"Context overflow: {snapshot.total_chars} chars against a "
            f"{snapshot.budget_chars}-char window with nothing to prune "
            f"(fixed overhead {snapshot.fixed_chars} chars, history "
            f"{snapshot.history_chars} chars, floor {floor} chars).",
        )

    kept = rows[:start] + rows[start + len(dropped):]
    after = measure_prompt(kept, tools, window, compact_threshold_ratio)
    if after.total_chars > after.budget_chars:
        raise ContextOverflowError(
            f"Context overflow after pruning {len(dropped)} message(s) "
            f"({reclaimed} chars): {after.total_chars} chars still exceed "
            f"the {after.budget_chars}-char window; history is kept above "
            f"{floor} chars so the next step has the tail it reuses.",
        )
    logger.warning(
        "Context budget trimmed %d oldest message(s) (~%d chars); "
        "%d -> %d messages against a %d-char window.",
        len(dropped),
        reclaimed,
        len(rows),
        len(kept),
        after.budget_chars,
    )
    return kept, dropped, after


def fit_prompt_to_budget(
    messages: list,
    window: WindowInfo,
    *,
    compact_threshold_ratio: float = 0.8,
    source: str = "background",
) -> list:
    """Shrink a one-shot prompt to the budget the chat gate enforces.

    Background pipelines (evolution, eval) talk to the provider with a raw
    client and own a single oversized prompt rather than a conversation, so
    :func:`trim_messages_to_budget` has nothing to prune — dropping the one
    user message would make the call meaningless.  This reuses the **same**
    window, trigger ratio and measurement, and truncates the largest row in
    the middle (head and tail kept, cut marked) instead of raising: a
    skipped extraction is cheap, a provider 400 inside a background task is
    exactly what produced the 70 recorded rejections.

    Args:
        messages: OpenAI-style ``[{"role","content"}]`` rows.
        window: ``WindowInfo`` of the model that will receive them.
        compact_threshold_ratio: Same ratio the compaction trigger uses.
        source: Label for the log line.

    Returns:
        The message list, shortened when it would not fit.  Never raises.
    """
    rows = [dict(m) for m in (messages or [])]
    if not rows or window.effective_tokens <= 0:
        return messages

    snapshot = measure_prompt(rows, None, window, compact_threshold_ratio)
    if snapshot.total_chars <= snapshot.budget_chars:
        return rows

    budget = snapshot.budget_chars
    for _ in range(3):
        # Biggest content row is the prompt; the rest is fixed overhead.
        idx = max(
            range(len(rows)),
            key=lambda i: len(str(rows[i].get("content", ""))),
        )
        content = str(rows[idx].get("content", ""))
        overhead = snapshot.total_chars - len(content)
        room = budget - overhead - 64
        if room < 200:
            logger.warning(
                "Context budget for %s cannot fit the fixed overhead "
                "(%d chars against a %d-char window); skipping the call.",
                source,
                overhead,
                budget,
            )
            return []
        head = int(room * 0.6)
        tail = max(0, room - head)
        marker = "\n…[truncated by context budget]…\n"
        cut = content[:head] + marker + (content[-tail:] if tail else "")
        rows[idx]["content"] = cut
        snapshot = measure_prompt(rows, None, window, compact_threshold_ratio)
        if snapshot.total_chars <= snapshot.budget_chars:
            logger.warning(
                "Context budget for %s truncated the prompt %d -> %d chars "
                "(window budget %d chars).",
                source,
                len(content),
                len(cut),
                budget,
            )
            return rows
    return rows


def budget_background_prompt(
    messages: list,
    model: Any,
    *,
    running_config: Any = None,
    source: str = "background",
) -> list:
    """Resolve *model*'s window and fit a one-shot prompt into it.

    Convenience wrapper for the raw-client background paths so they cannot
    re-invent (or skip) the budget rule.  Returns the messages untouched
    when the window is unknown — a background task must not lose its work
    to a measurement failure.
    """
    try:
        from .window_source import resolve_for_model

        window = resolve_for_model(model, running_config)
        return fit_prompt_to_budget(
            messages,
            window,
            source=source,
        )
    except Exception as exc:  # measurement must never break the call
        logger.debug("Background prompt budget skipped: %s", exc)
        return list(messages or [])


class ContextBudgetGuard:
    """Model wrapper enforcing the resolved window at the call site.

    Args:
        inner: The real chat model.
        window: ``WindowInfo`` from ``window_source``.
        compact_threshold_ratio: Fraction of the window that starts
            compaction; above it, above 1.0, is the hard gate.
        keep_chars_floor: Characters of history that are never pruned —
            the tail whose exact wording matters.  Pruning stops here even
            if that leaves the request over budget, which turns into an
            explicit overflow error instead of a silent amnesia.
        memory_provider: Returns the agent's ``AgentContext`` (or None) so
            pruning can persist.  A callable, not an object, because the
            guard is built before memory is attached.
        agent_name: For logs.
    """

    def __init__(
        self,
        inner: Any,
        *,
        window: WindowInfo,
        compact_threshold_ratio: float = 0.8,
        keep_chars_floor: int = 12_000,
        memory_provider: Callable[[], Any] | None = None,
        agent_name: str = "",
        ledger: Any = None,
    ) -> None:
        self._inner = inner
        self.window = window
        self.compact_threshold_ratio = compact_threshold_ratio
        self.keep_chars_floor = keep_chars_floor
        self._memory_provider = memory_provider
        self.agent_name = agent_name
        self.ledger = ledger
        self.last_snapshot: BudgetSnapshot | None = None
        self.pruned_events = 0
        self.overflow_events = 0

    # ── transparency ────────────────────────────────────────────────
    def __getattr__(self, name: str) -> Any:  # pragma: no cover - trivial
        return getattr(self._inner, name)

    @property
    def stream(self) -> bool:
        return bool(getattr(self._inner, "stream", False))

    def _governance_cap(self) -> int | None:
        """Registered context-token budget, when a ledger has one."""
        if self.ledger is None:
            return None
        try:
            from ...governance.limits import LimitKind

            budget = self.ledger.budget_of(LimitKind.CONTEXT_TOKENS, 0)
            return budget if budget and budget > 0 else None
        except Exception:
            return None

    # ── measurement ─────────────────────────────────────────────────
    def measure(
        self,
        messages: Any,
        tools: Any = None,
    ) -> BudgetSnapshot:
        snapshot = measure_prompt(
            messages,
            tools,
            self.window,
            self.compact_threshold_ratio,
        )
        cap = self._governance_cap()
        if cap is not None and cap < snapshot.budget_chars:
            budget_chars = self.window.to_chars(cap)
            snapshot = BudgetSnapshot(
                history_chars=snapshot.history_chars,
                fixed_chars=snapshot.fixed_chars,
                tools_chars=snapshot.tools_chars,
                total_chars=snapshot.total_chars,
                trigger_chars=int(budget_chars * self.compact_threshold_ratio),
                budget_chars=budget_chars,
            )
        return snapshot

    def _memory(self) -> Any:
        return self._memory_provider() if self._memory_provider else None

    # ── enforcement ─────────────────────────────────────────────────
    def _trim_prompt(self, messages: Any, snapshot: BudgetSnapshot) -> int:
        """Drop the oldest history rows from the prompt being sent.

        Pruning memory shrinks the *next* step's prompt; the call that
        overflowed is already built and would still be sent oversized — the
        cure arriving one step too late, which is what made every admin chat
        on dev answer ``MODEL_CONTEXT_LENGTH_EXCEEDED``.  Trimming the same
        oldest rows from the prompt applies the cure to the call that
        triggered it.  The rows are the formatter's view of the memory that
        was just purged, so the two stay consistent.

        Mutates *messages* in place; ``__call__`` forwards the trimmed list.
        Returns the characters reclaimed.
        """
        if not isinstance(messages, list):
            return 0
        over = snapshot.total_chars - snapshot.budget_chars
        if over <= 0:
            return 0
        floor = affordable_floor(
            snapshot.budget_chars,
            snapshot.fixed_chars,
            self.keep_chars_floor,
        )
        # The system row is fixed overhead and stays at the head.
        start = 0
        if messages:
            first = messages[0]
            role = (
                first.get("role")
                if isinstance(first, dict)
                else getattr(first, "role", None)
            )
            if role == "system":
                start = 1
        remaining = sum(len(str(m)) for m in messages[start:])
        reclaimed = 0
        dropped = 0
        index = start
        while index < len(messages):
            if reclaimed >= over:
                break
            size = len(str(messages[index]))
            if remaining - size < floor:
                break
            messages.pop(index)
            remaining -= size
            reclaimed += size
            dropped += 1
        if dropped:
            logger.warning(
                "Context budget guard trimmed %d oldest prompt row(s) "
                "(~%d chars) for agent %s so this call fits a %d-char "
                "window (fixed overhead %d, floor applied %d).",
                dropped,
                reclaimed,
                self.agent_name,
                snapshot.budget_chars,
                snapshot.fixed_chars,
                floor,
            )
        return reclaimed

    async def _prune_to_budget(self, snapshot: BudgetSnapshot) -> int:
        """Archive the oldest history out of working memory.

        Reuses the compaction loop closer (``archive_compressed_and_purge``)
        so pruned messages land in ``dialog/*.jsonl`` on disk — pruning the
        live window never means deleting the transcript.
        """
        memory = self._memory()
        if memory is None:
            return 0
        mark_cls = _memory_mark()
        if mark_cls is None:
            return 0
        content = getattr(memory, "content", None)
        if not content:
            return 0

        over = snapshot.total_chars - snapshot.budget_chars
        if over <= 0:
            return 0

        # Oldest first, and never below the floor: the tail whose exact
        # wording (tool output, paths, numbers) the next step reuses stays.
        # The floor is clamped to what the window can spare once fixed
        # overhead is paid — a floor the agent cannot pay must not block the
        # pruning that would have saved this call.
        floor = affordable_floor(
            snapshot.budget_chars,
            snapshot.fixed_chars,
            self.keep_chars_floor,
        )
        remaining = sum(len(str(msg.content)) for msg, _ in content)
        candidates: list[Any] = []
        reclaimable = 0
        for msg, _marks in content:
            if reclaimable >= over:
                break
            size = len(str(msg.content))
            if remaining - size < floor:
                break
            candidates.append(msg)
            reclaimable += size
            remaining -= size
        if not candidates:
            return 0

        mark_cls = _memory_mark()
        if mark_cls is None:
            return 0
        try:
            await memory.update_messages_mark(
                new_mark=mark_cls.COMPRESSED,
                msg_ids=[msg.id for msg in candidates],
            )
        except Exception as exc:
            logger.warning("Context pruning could not mark messages: %s", exc)
            return 0
        try:
            archived = await memory.archive_compressed_and_purge()
        except Exception as exc:
            logger.warning("Context pruning could not purge memory: %s", exc)
            return 0
        self.pruned_events += 1
        logger.warning(
            "Context budget guard pruned %d message(s) (~%d chars) for "
            "agent %s to fit a %d-char window (fixed overhead %d, history "
            "floor applied %d of configured %d).",
            len(archived) or len(candidates),
            reclaimable,
            self.agent_name,
            snapshot.budget_chars,
            snapshot.fixed_chars,
            floor,
            self.keep_chars_floor,
        )
        return reclaimable

    async def enforce(
        self,
        messages: Any,
        tools: Any = None,
    ) -> BudgetSnapshot:
        """Check the prompt, prune if needed, refuse what cannot fit.

        Returns the post-pruning snapshot.  Raises ``ContextOverflowError``
        when the request still exceeds the window.
        """
        snapshot = self.measure(messages, tools)
        self.last_snapshot = snapshot

        if snapshot.total_chars <= snapshot.trigger_chars:
            return snapshot

        if snapshot.total_chars <= snapshot.budget_chars:
            logger.info(
                "Context over trigger (%d > %d chars) for agent %s; "
                "fixed overhead %d chars (tools %d). Compaction will size "
                "the tail on the next step.",
                snapshot.total_chars,
                snapshot.trigger_chars,
                self.agent_name,
                snapshot.fixed_chars,
                snapshot.tools_chars,
            )
            return snapshot

        reclaimed = await self._prune_to_budget(snapshot)
        reclaimed += self._trim_prompt(messages, snapshot)
        after = self.measure(messages, tools)
        self.last_snapshot = after
        if after.total_chars <= after.budget_chars:
            return after

        self.overflow_events += 1
        floor = affordable_floor(
            after.budget_chars,
            after.fixed_chars,
            self.keep_chars_floor,
        )
        if after.fixed_chars >= after.budget_chars:
            cause = (
                "the fixed overhead alone — system prompt, skills and tool "
                f"schemas, {after.fixed_chars} chars, of which "
                f"{after.tools_chars} are tool schemas — is at or over the "
                f"{after.budget_chars}-char window, so no history size can "
                "fit. Reduce the enabled tools, shorten the system prompt, "
                "or raise the model's context window."
            )
        else:
            cause = (
                f"history is kept above {floor} chars so the next reasoning "
                "step has the tail it reuses verbatim, and that is what "
                "does not fit. Shorten the conversation, reduce the "
                "enabled tools, or raise the model's context window."
            )
        message = (
            f"Context overflow for agent '{self.agent_name}': the prompt "
            f"measures {after.total_chars} chars against a "
            f"{after.budget_chars}-char window "
            f"(fixed overhead {after.fixed_chars} chars, of which "
            f"{after.tools_chars} are tool schemas; history "
            f"{after.history_chars} chars, pruning reclaimed "
            f"{reclaimed} chars). {cause}"
        )
        logger.error(message)
        raise ContextOverflowError(message)

    # ── the call ────────────────────────────────────────────────────
    async def __call__(
        self,
        messages: Any = None,
        tools: Any = None,
        **kwargs: Any,
    ) -> Any:
        # Compaction itself sends the whole uncompressed prefix to a model;
        # gating that would make the cure overflow.
        if "structured_model" in kwargs:
            return await self._inner(messages, tools=tools, **kwargs)
        snapshot: BudgetSnapshot | None = None
        if messages is not None:
            snapshot = await self.enforce(messages, tools)
        self._publish_to_governance(snapshot)
        return await self._inner(messages, tools=tools, **kwargs)

    def _publish_to_governance(self, snapshot: BudgetSnapshot | None) -> None:
        """Report the measured prompt to the governance ledger, if any.

        ``LimitKind.CONTEXT_TOKENS`` existed as a published budget with
        nobody consuming it.  This is the consumer: the number recorded is
        the measurement the gate actually made, and when a ledger registers
        a context budget the gate refuses above it.  No ledger, no opinion —
        the gate does not invent limits the configuration never set.
        """
        if snapshot is None or self.ledger is None:
            return
        try:
            from ...governance.limits import LimitKind

            self.ledger.record(
                LimitKind.CONTEXT_TOKENS,
                self.window.to_tokens(snapshot.total_chars),
            )
        except Exception as exc:  # governance must never break a call
            logger.debug("Governance context accounting skipped: %s", exc)


def _memory_mark() -> Any:
    try:
        from agentscope.agent._react_agent import _MemoryMark

        return _MemoryMark
    except Exception:
        return None


def build_budget_guard(
    model: Any,
    window: WindowInfo,
    *,
    compact_threshold_ratio: float = 0.8,
    keep_chars_floor: int = 12_000,
    memory_provider: Callable[[], Any] | None = None,
    agent_name: str = "",
    ledger: Any = None,
) -> Any:
    """Wrap *model* in the gate, or return it unchanged when unusable.

    A gate that cannot measure (no window) must not swallow calls, so the
    fallback is the untouched model — the same behaviour as compaction being
    disabled by configuration.
    """
    if model is None or isinstance(model, ContextBudgetGuard):
        return model
    if window.effective_tokens <= 0:
        return model
    return ContextBudgetGuard(
        model,
        window=window,
        compact_threshold_ratio=compact_threshold_ratio,
        keep_chars_floor=keep_chars_floor,
        memory_provider=memory_provider,
        agent_name=agent_name,
        ledger=ledger,
    )