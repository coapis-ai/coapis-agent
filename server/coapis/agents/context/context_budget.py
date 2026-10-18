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
  that overflowed would still go out oversized.  When the floor blocks the
  deletion (one oversized tool result is a single row, and the floor refuses
  to delete whole exchanges) the biggest rows are **truncated** head/tail in
  the sent view: the transcript in ``dialog/`` keeps the full text, the
  request keeps the information it can act on.  If the fixed overhead alone
  is over the window, raise :class:`ContextOverflowError`.  A request that
  cannot fit is refused with a number attached — not sent to the provider to
  fail as an opaque 400.
"""

from __future__ import annotations

import asyncio
import copy
import json
import logging
import time
from dataclasses import dataclass, replace
from typing import Any, Awaitable, Callable

from coapis.constant import (
    CONTEXT_PRUNED_SUMMARY_MAX_BATCHES,
    CONTEXT_PRUNED_SUMMARY_MAX_CHARS,
    EnvVarLoader,
)

from .window_source import WindowInfo

logger = logging.getLogger(__name__)


class CompactionTimeoutError(RuntimeError):
    """A compaction call the model did not answer within its budget.

    Raised as an ordinary failure so every existing degradation path applies
    unchanged: a map chunk that times out is skipped and the merge runs on
    the chunks that answered; a merge that times out falls back to the single
    fitted request.  Before this existed a stalled compaction request held
    the chat's critical path for the SDK's default 600 s and logged nothing.
    """


class ContextOverflowError(RuntimeError):
    """Raised when a prompt cannot fit the model's window after pruning."""


#: History that is never pruned, whatever the window says.  Two thousand
#: characters is roughly the last user turn plus one tool result — below it
#: the next reasoning step has nothing to reason about.
MIN_KEEP_CHARS = 2_000


def _is_system_row(row: Any) -> bool:
    """Is this prompt row the system prompt?"""
    if isinstance(row, dict):
        return row.get("role") == "system"
    return getattr(row, "role", None) == "system"


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


#: Absolute floor for a *single* row after truncation.  Below this the row
#: carries no information — a truncated tool result shorter than this is
#: noise the next step cannot act on.
MIN_ROW_CHARS = 400

# How many prune/trim rounds ``enforce`` may spend before it refuses.  Each
# round re-measures, so the target is always the size the prompt actually has
# after the previous round -- which is the point, since a prune changes it.
_ENFORCE_MAX_ROUNDS = 4

#: Rows shrink the prompt by less than their content each round (the
#: ``str(msg)`` wrapper adds role/name/quotes) and the truncation marker
#: costs characters of its own, so the loop re-measures instead of computing
#: the result exactly once.
_ROW_OVERHEAD_CHARS = 96

#: Rounds of "cut the biggest row" before the request is declared unfixable.
MAX_TRUNCATE_ROUNDS = 3

#: Floor per row when the row is *input to a summary request*.  A compaction
#: prompt is hundreds of rows against half the window; the chat floor
#: (:data:`MIN_ROW_CHARS`) leaves a 155k-char compaction request unfixable,
#: and a stub row that says "this exchange happened" still beats a summary
#: that never runs.
_COMPACT_MIN_ROW_CHARS = 200

#: The marker :func:`~coapis.governance.limits.truncate_head_tail` inserts.
_TRUNCATION_MARKER = "\n\n[…truncated by context budget…]\n\n"


def _cut_head_tail(text: str, room: int) -> str:
    """Head+tail cut whose result is **exactly** *room* characters.

    The governance helper keeps ``room`` characters of content *plus* its
    marker, so a prompt trimmed with it lands slightly over budget and the
    loop can never converge (the second pass computes the same length and
    stops).  The last round uses this exact cut so the request fits by
    construction.
    """
    if room <= len(_TRUNCATION_MARKER) + 2:
        return text[:room]
    keep = room - len(_TRUNCATION_MARKER)
    head = keep // 2
    tail = keep - head
    return text[:head] + _TRUNCATION_MARKER + (text[-tail:] if tail else "")


def _row_content(row: Any) -> str | None:
    """The text a prompt row carries, for dict rows and ``Msg`` rows alike."""
    if isinstance(row, dict):
        content = row.get("content")
    else:
        content = getattr(row, "content", None)
    return None if content is None else str(content)


def _replace_row_content(messages: list, index: int, new: str) -> bool:
    """Write truncated text into the **sent view** of a row, in place.

    The row is replaced by a copy, never mutated: dict rows handed to
    ``trim_messages_to_budget`` are the caller's own history rows, and
    ``Msg`` rows can be the very objects the agent's memory holds.  The
    contract of truncation is that the transcript keeps the full text — only
    the copy that goes into this one request is shorter.
    """
    row = messages[index]
    if isinstance(row, dict):
        if "content" not in row:
            return False
        clone = dict(row)
        clone["content"] = new
        messages[index] = clone
        return True
    if hasattr(row, "content"):
        try:
            clone = copy.copy(row)
            clone.content = new
            messages[index] = clone
            return True
        except Exception:
            return False
    return False


def truncate_rows_to_fit(
    messages: list,
    start: int,
    budget_chars: int,
    min_row_chars: int = MIN_ROW_CHARS,
) -> int:
    """Cut the biggest history rows until the prompt fits the window.

    The floor (:data:`MIN_KEEP_CHARS`) is a rule about *deleting whole
    exchanges*: the tail whose exact wording the next step reuses must
    survive.  It was never a rule about *lossy compression*, and the old code
    treated it as one: a single 88,000-char tool result is one row, so the
    delete loop refused to touch it, the loop exited with the prompt still
    over budget, and the call was refused with "shorten the conversation" —
    advice the user cannot act on, because the oversized thing is one reply
    they already got.

    Truncation is allowed to go deeper than the floor: the row stays in the
    prompt, head and tail preserved with a marker, so the model knows the
    exchange happened and roughly what it said.  Nothing is deleted, and
    :data:`MIN_ROW_CHARS` is the hard floor per row.

    Mutates *messages* in place (see :func:`_replace_row_content` for the
    memory-safety rule).  Returns the characters reclaimed.
    """
    if not isinstance(messages, list) or len(messages) <= start:
        return 0
    from ...governance.limits import truncate_head_tail

    # Callers hand in the window the rows may occupy (the window minus the
    # tool schemas, which ride in the same request and are not rows).  The
    # head rows -- the system prompt, which is never pruned -- occupy it too,
    # and they are not in the range this function cuts.  Subtracting them is
    # what makes the target the real allowance: measured on dev 2026-10-18,
    # agent user:admin, rows 137,009 chars against a target of 150,216 that
    # ignored the 18,057-char system row, so nothing was truncated and the
    # call was refused by 4,850 chars.
    head_chars = sum(len(str(m)) for m in messages[:start])
    budget_chars = max(0, budget_chars - head_chars)

    reclaimed = 0
    for round_index in range(MAX_TRUNCATE_ROUNDS):
        total = sum(len(str(m)) for m in messages)
        if total <= budget_chars:
            break
        candidates = [
            i
            for i in range(start, len(messages))
            if len(str(messages[i])) > min_row_chars
        ]
        if not candidates:
            break
        index = max(candidates, key=lambda i: len(str(messages[i])))
        content = _row_content(messages[index])
        if content is None:
            break
        size = len(str(messages[index]))
        room = budget_chars - (total - size) - _ROW_OVERHEAD_CHARS
        if room < min_row_chars or len(content) <= room:
            # The row's overhead is the wrapper, not its content: cutting
            # the content would not buy the space we need.
            break
        # The exact cut, every round.  The governance helper keeps ``room``
        # chars of content *plus* its marker, so each pass lands a little
        # over budget and the loop spends a second and third round getting
        # to the same place; and the marker is the only signal the model
        # gets that this row is not the whole story.
        shortened = _cut_head_tail(content, room)
        if len(shortened) >= len(content):
            break
        if not _replace_row_content(messages, index, shortened):
            break
        reclaimed += len(content) - len(shortened)
    return reclaimed


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
    # D1 (2026-10-17): the budget is measured in the unit upstream counts —
    # formatted characters, not tokens.  ``react_agent._build_compression_config``
    # computes ``char_threshold = window.to_chars(trigger_tokens)`` from the
    # same window and the same ratio; using the raw token number here made the
    # gate and the compactor disagree by a factor of ``chars_per_token``, which
    # is why the gate fired 125 times while compaction fired 0 times.
    budget_chars = window.to_chars(window.effective_tokens)
    trigger_chars = int(budget_chars * compact_threshold_ratio)
    return BudgetSnapshot(
        history_chars=history_chars,
        fixed_chars=fixed_chars,
        tools_chars=tools_chars,
        total_chars=total_chars,
        trigger_chars=trigger_chars,
        budget_chars=budget_chars,
    )


def fit_rows_to_window(
    messages: list,
    start: int,
    row_budget: int,
    floor: int,
    min_row_chars: int = MIN_ROW_CHARS,
) -> tuple[list, int]:
    """Make the prompt rows fit: delete whole exchanges, truncate rows.

    The two passes **feed each other**, which is why they alternate instead of
    each running once.  The floor stops deletion at an oversized row (one
    88,000-char tool result is a single row, and the floor refuses to delete
    the tail it belongs to); truncating that row is precisely what makes the
    rest of the tail deletable again.  Running deletion once and truncation
    once — the shape this function replaces — stops with the prompt over
    budget in exactly the case truncation exists to rescue: the dev incident
    of 2026-10-17 measured 89,297 chars against a 72,089-char window with a
    28,835-char floor, i.e. 17,208 chars of perfectly legal deletion left
    unreachable because the floor had been computed against the un-truncated
    giant row.

    Mutates *messages* in place.  Returns ``(dropped_rows, truncated_chars)``.
    """
    dropped: list = []
    truncated = 0
    if not isinstance(messages, list) or len(messages) <= start:
        return dropped, truncated
    logger.info(
        "context fit start: %d rows, %d chars, row_budget %d, floor %d, "
        "start %d",
        len(messages),
        sum(len(str(m)) for m in messages),
        row_budget,
        floor,
        start,
    )

    for _round_index in range(MAX_TRUNCATE_ROUNDS + 1):
        total = sum(len(str(m)) for m in messages)
        over = total - row_budget
        if over <= 0:
            break

        remaining = sum(len(str(m)) for m in messages[start:])
        index = start
        deleted = 0
        while index < len(messages):
            size = len(str(messages[index]))
            if remaining - size < floor:
                break
            dropped.append(messages.pop(index))
            remaining -= size
            over -= size
            deleted += 1
            if over <= 0:
                break

        cut = truncate_rows_to_fit(
            messages,
            start,
            row_budget,
            min_row_chars,
        )
        truncated += cut
        after_total = sum(len(str(m)) for m in messages)
        logger.info(
            "context fit round %d: total %d -> %d (row_budget %d, floor %d, "
            "deleted %d rows, cut %d chars, rows %d)",
            _round_index,
            total,
            after_total,
            row_budget,
            floor,
            deleted,
            cut,
            len(messages),
        )
        if over - cut <= 0:
            break
        if deleted == 0 and cut == 0:
            break
    return dropped, truncated


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
        # Nothing may be deleted, but a row may still be cut.  A single
        # oversized tool result is the case this exists for.  The rows get
        # the window minus the tool schemas: the schemas ride along in the
        # same request and are not rows.
        truncated = truncate_rows_to_fit(
            rows,
            start,
            snapshot.budget_chars - snapshot.tools_chars,
        )
        after = measure_prompt(rows, tools, window, compact_threshold_ratio)
        if after.total_chars <= after.budget_chars:
            logger.warning(
                "Context budget truncated prompt row(s) by %d chars; the "
                "request fits a %d-char window with nothing to delete.",
                truncated,
                after.budget_chars,
            )
            return rows, [], after
        raise ContextOverflowError(
            f"Context overflow: {snapshot.total_chars} chars against a "
            f"{snapshot.budget_chars}-char window with nothing to prune "
            f"(fixed overhead {snapshot.fixed_chars} chars, history "
            f"{snapshot.history_chars} chars, floor {floor} chars).",
        )

    kept = rows[:start] + rows[start + len(dropped):]
    after = measure_prompt(kept, tools, window, compact_threshold_ratio)
    if after.total_chars > after.budget_chars:
        # Deleting whole exchanges hit the floor; lossy truncation of the
        # remaining rows is allowed to go deeper than the floor.
        truncate_rows_to_fit(
            kept,
            start,
            after.budget_chars - after.tools_chars,
        )
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
    # The compaction request gets the *ratio* budget, not the whole window:
    # budget_chars is the window, trigger_chars is window × ratio.  Reading
    # budget_chars here made compaction_input_ratio a no-op (dev,
    # 2026-10-17: a 155,775-char compaction prompt against a 72,089-char
    # window, with the 0.5 ratio configured and never applied).
    budget = snapshot.trigger_chars
    if snapshot.total_chars <= budget:
        return rows

    before = snapshot.total_chars
    # A compaction request is the whole compressible prefix — hundreds of
    # rows, not one prompt.  Truncating the single largest row of a 155,775
    # char compaction prompt against a 36,044 char window reclaimed nothing
    # and the call was skipped, which is compaction never running at all
    # (dev, 2026-10-17).  So this uses the same two-pass fit as the chat
    # gate: drop the oldest exchanges, then truncate what is left.  The
    # floor is MIN_KEEP_CHARS, never the chat history floor: rows dropped
    # here are rows upstream archives as part of the compression, and a
    # summary of the newest part beats no summary.
    start = 1 if _is_system_row(rows[0]) else 0
    dropped, truncated = fit_rows_to_window(
        rows,
        start,
        budget,
        # A floor above the budget is a refusal, not a floor.
        min(MIN_KEEP_CHARS, budget),
        min_row_chars=_COMPACT_MIN_ROW_CHARS,
    )
    snapshot = measure_prompt(rows, None, window, compact_threshold_ratio)
    if snapshot.total_chars <= budget:
        logger.warning(
            "Context budget for %s fitted %d -> %d chars (window budget %d: "
            "%d row(s) dropped, %d chars truncated).",
            source,
            before,
            snapshot.total_chars,
            budget,
            len(dropped),
            truncated,
        )
        return rows
    # Unfixable within the ratio: the untouchable part of the request (the
    # system row plus the keep-recent floor) is over the budget, so the best
    # fit we managed is sent as-is.  It is strictly smaller than the original,
    # and the provider's answer to an oversized request is recoverable, while
    # a compaction that never runs is not.
    logger.warning(
        "Context budget for %s fitted to %d chars, still %d over the %d-char "
        "budget (%d row(s) dropped, %d chars truncated); sending the best "
        "fit.",
        source,
        snapshot.total_chars,
        max(0, snapshot.total_chars - budget),
        budget,
        len(dropped),
        truncated,
    )
    return rows if rows else messages


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


# ── chunked (map-reduce) compaction ─────────────────────────────────
# The compaction request is the whole uncompressed prefix.  Fitting it by
# dropping the oldest rows means those rows are archived as COMPRESSED
# without ever being summarized: the memory is gone and no summary holds it
# (dev 2026-10-17: 280 rows dropped per compaction, coverage 0.16).  The
# prefix does not fit in one request, so it is cut into chunks that each
# fit, every chunk is summarized, and the partial summaries are merged.
# Nothing is compressed that was not read.
_COMPACT_MINI_SYS = (
    "You compress conversation history into the structured summary the user "
    "message specifies. Summarize only what the messages contain; never "
    "continue the dialogue and never invent facts."
)
# Headroom for the JSON envelope and the measurement model's own overhead.
_COMPACT_CHUNK_FILL = 0.85
# Per-block cap when a pruned message is rendered for its summary.  Tool
# results are the bulk of a pruned history and the queue is bounded in chars;
# one 200K tool output must not be what the whole queue measures.
_RENDER_BLOCK_CAP_CHARS = 4_000
# Minimum seconds a map chunk (or the merge) needs left of the global deadline
# to be worth starting.  Launching a call with 2 seconds of budget guarantees it
# times out and burns the slot; below this the work is skipped and the merge
# runs on what already answered.
_MIN_CHUNK_WINDOW_SECONDS = 10.0
# Chunk-count bound.  It used to be the only cost brake, and it silently
# widened chunks to stay under it -- a 16K char cap with 12 chunks is a 16K
# cap only until the history needs 13 of them.  With the map calls running
# concurrently, the count is no longer the cost driver; the char cap is.
_COMPACT_MAX_CHUNKS = EnvVarLoader.get_int(
    "COAPIS_CONTEXT_COMPACTION_MAX_CHUNKS",
    24,
    min_value=2,
    max_value=200,
)
# Absolute ceiling on the chunk count, so a pathological history cannot make
# compaction unbounded.  Above it the tail chunk is widened (and truncated
# by the fitter), which is logged.
_COMPACT_CHUNK_CEILING = EnvVarLoader.get_int(
    "COAPIS_CONTEXT_COMPACTION_CHUNK_CEILING",
    40,
    min_value=4,
    max_value=400,
)
# NOTE: ``_COMPACT_MAX_CHUNKS`` is declared once, above, from the environment.
# It used to be declared a second time as a bare ``= 12`` below, which shadowed
# the configurable value and made COAPIS_CONTEXT_COMPACTION_MAX_CHUNKS a dead
# knob (the constant was read at import time, before the override never existed).


def _row_chars(row: Any) -> int:
    return len(str(row))


def _row_is_tool_pair(row: Any) -> bool:
    """True for an assistant row that issues tool calls (pair head)."""
    if not isinstance(row, dict):
        return False
    return bool(row.get("tool_calls"))


def build_compaction_units(rows: list) -> list[list]:
    """Group rows into units that must not be split.

    An assistant row issuing ``tool_calls`` and the ``tool`` rows answering
    those ids are one unit: a tool result summarized without the call that
    produced it is a summary of a fragment.

    Args:
        rows: Formatted prompt rows (OpenAI-style dicts), history only.

    Returns:
        List of units, each a list of rows, in original order.
    """
    units: list[list] = []
    i = 0
    n = len(rows)
    while i < n:
        row = rows[i]
        if _row_is_tool_pair(row):
            ids = {
                str(c.get("id"))
                for c in (row.get("tool_calls") or [])
                if isinstance(c, dict) and c.get("id")
            }
            unit = [row]
            j = i + 1
            while j < n:
                nxt = rows[j]
                if (
                    isinstance(nxt, dict)
                    and nxt.get("role") == "tool"
                    and str(nxt.get("tool_call_id")) in ids
                ):
                    unit.append(nxt)
                    j += 1
                else:
                    break
            units.append(unit)
            i = j
        else:
            units.append([row])
            i += 1
    return units


def split_rows_for_compaction(
    rows: list,
    chunk_budget: int,
    max_chunks: int = _COMPACT_MAX_CHUNKS,
) -> list[list]:
    """Cut history rows into chunks that each fit ``chunk_budget``.

    Args:
        rows: History rows (system row already removed).
        chunk_budget: Characters a single map call may carry.
        max_chunks: Cost bound.  When the rows need more chunks than this,
            the budget is widened so the count stays bounded (bigger chunks
            are truncated by the same fitter, which is strictly better than
            dropping whole chunks).

    Returns:
        List of row-lists, oldest first.  Empty when *rows* is empty.
    """
    units = build_compaction_units(rows)
    if not units:
        return []
    budget = max(2_000, int(chunk_budget * _COMPACT_CHUNK_FILL))
    chunks: list[list] = []
    current: list = []
    size = 0
    for unit in units:
        usize = sum(_row_chars(r) for r in unit)
        if current and size + usize > budget:
            chunks.append(current)
            current, size = [], 0
        current.extend(unit)
        size += usize
    if current:
        chunks.append(current)
    if len(chunks) <= max_chunks:
        return chunks
    # Too many chunks: merge the tail into the last allowed chunk.  The
    # merged chunk is over budget and gets truncated by fit_prompt_to_budget,
    # which keeps the newest rows — the same trade the single-request path
    # made for the whole prefix, now applied to one chunk instead of all.
    head, tail = chunks[: max_chunks - 1], chunks[max_chunks - 1:]
    merged: list = []
    for chunk in tail:
        merged.extend(chunk)
    return head + [merged]


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
        compaction_input_ratio: Budget fraction the **compaction request**
            is fitted into.  Compaction used to be exempt from the gate
            entirely ("the gate would make the cure overflow"), which let
            the summary request go out bigger than the request that was
            just refused.  It is now measured and fitted, never refused.
        agent_name: For logs.
    """

    # Bound on the queue of hard-pruned rows owed a summary (batches and
    # characters), both configurable -- see :meth:`_queue_pruned_for_summary`.
    _PRUNED_MAX_BATCHES = CONTEXT_PRUNED_SUMMARY_MAX_BATCHES
    _PRUNED_MAX_CHARS = CONTEXT_PRUNED_SUMMARY_MAX_CHARS

    def __init__(
        self,
        inner: Any,
        *,
        window: WindowInfo,
        compact_threshold_ratio: float = 0.8,
        compaction_input_ratio: float = 0.5,
        keep_chars_floor: int = 12_000,
        memory_provider: Callable[[], Any] | None = None,
        agent_name: str = "",
        ledger: Any = None,
        map_reduce: bool = True,
        compaction_timeout: float | None = None,
        map_chunk_max_chars: int | None = None,
        map_concurrency: int | None = None,
        compaction_global_timeout: float | None = None,
    ) -> None:
        self._inner = inner
        self.window = window
        self.compact_threshold_ratio = compact_threshold_ratio
        self.compaction_input_ratio = max(0.2, min(0.9, compaction_input_ratio))
        self.map_reduce = map_reduce
        self.keep_chars_floor = keep_chars_floor
        self._memory_provider = memory_provider
        self.agent_name = agent_name
        self.ledger = ledger
        self.compaction_timeout = self._resolve_compaction_timeout(
            compaction_timeout,
        )
        self.map_chunk_max_chars = self._resolve_positive(
            map_chunk_max_chars,
            "CONTEXT_COMPACTION_CHUNK_MAX_CHARS",
            16_000,
        )
        self.map_concurrency = self._resolve_positive(
            map_concurrency,
            "CONTEXT_COMPACTION_MAP_CONCURRENCY",
            3,
        )
        # Ceiling for one whole compaction (all map chunks + the merge), not
        # for one call.  Five chunks at the per-call ceiling still cost the
        # chat seven minutes, and a compaction that never finishes holds a
        # session open indefinitely.
        self.compaction_global_timeout = self._resolve_positive(
            compaction_global_timeout,
            "CONTEXT_COMPACTION_GLOBAL_TIMEOUT_SECONDS",
            180,
        )
        self.last_snapshot: BudgetSnapshot | None = None
        self.pruned_events = 0
        # What each hard prune dropped, queued for the summary it never got.
        # ``_prune_to_budget`` archives rows and removes them from working
        # memory in one motion; the deferred compaction then finds a history
        # under its trigger and does nothing (dev, 2026-10-18: compaction
        # "finished in 0.0s" right after prunes).  Archiving is not
        # summarising -- see :meth:`pop_pruned_for_summary`.
        self.pruned_pending: list[Any] = []
        self.pruned_pending_chars = 0
        self.overflow_events = 0

    @staticmethod
    def _resolve_compaction_timeout(value: float | None) -> float:
        """Per-compaction-call ceiling, env-configurable.

        Read lazily through the constant module so tests can monkeypatch the
        value and a deployment can raise it for a slow endpoint without
        touching code.  Any unusable value falls back to the default: a
        compaction path that cannot decide its own deadline is the bug this
        parameter exists to fix, so it must never be None or zero.
        """
        from coapis.constant import CONTEXT_COMPACTION_TIMEOUT_SECONDS

        if value is not None:
            try:
                parsed = float(value)
            except (TypeError, ValueError):
                parsed = 0.0
            if parsed > 0:
                return parsed
        try:
            default = float(CONTEXT_COMPACTION_TIMEOUT_SECONDS)
        except (TypeError, ValueError):
            default = 90.0
        return default if default > 0 else 90.0

    @staticmethod
    def _resolve_positive(value: Any, constant_name: str, fallback: int) -> int:
        """Resolve a positive integer knob from config, env, or the fallback.

        Same rule as the compaction timeout: a compaction parameter that
        resolves to zero or None silently disables the behaviour it exists to
        provide, so unusable values always land on the documented default.
        """
        import os

        for candidate in (value, os.getenv(f"COAPIS_{constant_name}")):
            try:
                parsed = int(candidate)  # type: ignore[arg-type]
            except (TypeError, ValueError):
                continue
            if parsed > 0:
                return parsed
        try:
            from coapis import constant as _c

            default = int(getattr(_c, constant_name, fallback))
        except Exception:  # pragma: no cover - import guard
            default = fallback
        return default if default > 0 else fallback

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
        truncated = 0
        if reclaimed < over:
            # The floor stopped the deletion.  Truncation is not bound by it:
            # an oversized single row (one 88k tool result) is exactly the
            # shape that used to make this raise "shorten the conversation".
            # The target is the window **minus the tool schemas**, which are
            # measured alongside the rows but are not rows themselves.
            truncated = truncate_rows_to_fit(
                messages,
                start,
                snapshot.budget_chars - snapshot.tools_chars,
            )
            reclaimed += truncated
        if dropped or truncated:
            logger.warning(
                "Context budget guard trimmed %d oldest prompt row(s) "
                "(~%d chars) and truncated row content by %d chars for "
                "agent %s so this call fits a %d-char window (fixed "
                "overhead %d, floor applied %d).",
                dropped,
                reclaimed - truncated,
                truncated,
                self.agent_name,
                snapshot.budget_chars,
                snapshot.fixed_chars,
                floor,
            )
        return reclaimed

    def _queue_pruned_for_summary(self, archived: list[Any]) -> None:
        """Remember what a hard prune dropped: it is owed a summary.

        Bounded on purpose.  The rows are not lost when the queue overflows
        -- every archived line is already in ``dialog/*.jsonl`` and marked
        compressed in the session state; the queue decides how much of that
        history gets folded into the working summary.  Keeping the newest
        batches is the useful bias: they are the ones the next request is
        about to lose.
        """
        if not archived:
            return
        self.pruned_pending.append(list(archived))
        self.pruned_pending_chars += sum(
            _row_chars(self._row_of(message)) for message in archived
        )
        while len(self.pruned_pending) > self._PRUNED_MAX_BATCHES:
            dropped = self.pruned_pending.pop(0)
            self.pruned_pending_chars -= sum(
                _row_chars(self._row_of(message))
                for message in dropped
            )
        while (
            self.pruned_pending_chars > self._PRUNED_MAX_CHARS
            and len(self.pruned_pending) > 1
        ):
            dropped = self.pruned_pending.pop(0)
            self.pruned_pending_chars -= sum(
                _row_chars(self._row_of(message))
                for message in dropped
            )
        logger.info(
            "context-budget: %d rows archived by hard pruning are queued for "
            "a summary (%d batches, %d chars)",
            len(archived),
            len(self.pruned_pending),
            self.pruned_pending_chars,
        )

    def pop_pruned_for_summary(self) -> list[Any]:
        """Take everything hard pruning has archived without summarising.

        Drains the queue, oldest batch first, so a summary built from the
        result reads in conversation order.  The caller (the deferred
        compaction round) folds it into the memory's running summary; when
        nothing is queued this returns an empty list and costs nothing.
        """
        if not self.pruned_pending:
            return []
        rows = [
            message
            for batch in self.pruned_pending
            for message in batch
        ]
        self.pruned_pending = []
        self.pruned_pending_chars = 0
        return rows

    def _row_of(self, message: Any) -> dict[str, Any]:
        """A message as a formatter row, for measuring and summarising."""
        content = getattr(message, "content", "")
        if content is None:
            content = ""
        return {
            "role": getattr(message, "role", "user") or "user",
            "content": content
            if isinstance(content, str)
            else self._render_blocks(content),
        }

    @staticmethod
    def _render_blocks(blocks: Any) -> str:
        """Every block of a message as text, the way the formatter sends them.

        :meth:`_blocks_text` keeps only ``text`` blocks, which is the right
        thing for a summary *response*; for history being summarised it is the
        tool calls and their results that carry the content.  Measured on dev
        2026-10-19: hard pruning dropped 177,912 chars and queued 8,079 for a
        summary, because every tool block was silently dropped from the rows
        the summary call sees -- the fold would have summarised 4% of what it
        archived.  Each block is capped so one huge tool output cannot eat the
        whole queue.
        """
        if isinstance(blocks, str):
            return blocks.strip()
        if not blocks:
            return ""
        out: list = []
        for block in blocks:
            if isinstance(block, dict):
                kind = block.get("type")
            else:
                kind = getattr(block, "type", None)
            get = (
                block.get
                if isinstance(block, dict)
                else lambda key, _b=block: getattr(_b, key, None)
            )
            if kind == "text":
                piece = str(get("text") or "")
            elif kind == "thinking":
                piece = f"思考：{get('thinking') or ''}"
            elif kind == "tool_use":
                args = get("input") or get("arguments") or ""
                try:
                    args = json.dumps(args, ensure_ascii=False)
                except Exception:
                    args = str(args)
                piece = f"调用工具 {get('name') or '?'}：{args}"
            elif kind == "tool_result":
                # agentscope's ToolResultBlock carries the payload under
                # ``output``; ``content`` is what a provider's wire format
                # calls the same thing.  Reading only one of the two is how
                # a 12,697-char tool result rendered as 5 chars on dev.
                inner = get("output")
                if inner in (None, "", [], {}):
                    inner = get("content")
                piece = (
                    ContextBudgetGuard._render_blocks(inner)
                    if isinstance(inner, (list, tuple))
                    else str(inner or "")
                )
                piece = f"工具结果 {get('name') or ''}：{piece}".strip()
            elif kind == "image":
                piece = "[图片]"
            elif kind == "audio":
                piece = "[语音]"
            elif kind == "video":
                piece = "[视频]"
            elif kind in ("file", "document"):
                piece = f"[{kind} {get('filename') or get('name') or ''}]"
            else:
                piece = str(block)
            piece = piece.strip()
            if not piece:
                continue
            if len(piece) > _RENDER_BLOCK_CAP_CHARS:
                piece = piece[:_RENDER_BLOCK_CAP_CHARS] + "…(截断)"
            out.append(piece)
        return "\n".join(out).strip()

    @staticmethod
    def _summary_ask_row() -> dict:
        """The instruction for a pruned-history summary call.

        Plain text, not the compaction's JSON contract: this summary is
        appended to the running summary as text, so there is no template to
        fill and no schema for a model to fail against.
        """
        return {
            "role": "user",
            "content": (
                "把上面的对话片段压缩成一份中文摘要，按时间顺序保留：事实与"
                "结论、涉及的文件路径与命令、数字与标识、未完成的事项。"
                "不要续写对话，不要编造，不要评论，只输出摘要正文。"
            ),
        }

    async def _summarize_rows(self, rows: list) -> str:
        """Summarize archived rows with the compaction's own map-reduce.

        Same machinery as :meth:`_compact_map_reduce` (budget-sized chunks,
        concurrent map calls, one shared deadline, merge at the end), because
        the failure modes are identical: a chunk that never answers, a
        deadline that expires mid-map, a model that answers in prose.  The
        difference is the output — plain text appended to the running summary,
        not a structured payload a template has to format.

        Returns the summary text, or ``""`` when the window has no room for a
        chunk worth sending.
        """
        rows = [r for r in rows if isinstance(r, dict)]
        if not rows:
            return ""

        mini_sys = {"role": "system", "content": _COMPACT_MINI_SYS}
        ask = self._summary_ask_row()
        budget_chars = self.window.to_chars(
            int(self.window.effective_tokens * self.compaction_input_ratio),
        )
        overhead = _row_chars(mini_sys) + _row_chars(ask) + 2_000
        chunk_budget = int(budget_chars * self.compact_threshold_ratio) - overhead
        chunk_budget = min(chunk_budget, self.map_chunk_max_chars)
        if chunk_budget < 4_000:
            logger.info(
                "Pruned-summary %s: no room for a chunk (%d chars/chunk after "
                "%d chars of fixed overhead in a %d-char compaction budget).",
                self.agent_name or "?",
                chunk_budget,
                overhead,
                budget_chars,
            )
            return ""

        history_chars = sum(_row_chars(r) for r in rows)
        needed_chunks = max(
            1,
            -(-history_chars // max(1, int(chunk_budget * _COMPACT_CHUNK_FILL))),
        )
        max_chunks = min(
            _COMPACT_CHUNK_CEILING,
            max(_COMPACT_MAX_CHUNKS, needed_chunks),
        )
        chunks = split_rows_for_compaction(
            rows,
            chunk_budget,
            max_chunks=max_chunks,
        )
        if not chunks:
            return ""

        started = time.monotonic()
        deadline_at = started + self.compaction_global_timeout
        total = len(chunks)
        logger.info(
            "Pruned-summary start %s: %d row(s) (%d chars) -> %d chunk(s) "
            "of %d chars, %.0fs deadline.",
            self.agent_name or "?",
            len(rows),
            history_chars,
            total,
            chunk_budget,
            self.compaction_global_timeout,
        )

        semaphore = asyncio.Semaphore(self.map_concurrency)

        async def _map_one(
            idx: int,
            chunk: list,
        ) -> tuple[str, int] | None:
            remaining = deadline_at - time.monotonic()
            if remaining <= _MIN_CHUNK_WINDOW_SECONDS:
                logger.warning(
                    "Pruned-summary chunk %d/%d skipped: deadline spent "
                    "(%.1fs elapsed).",
                    idx + 1,
                    total,
                    time.monotonic() - started,
                )
                return None
            request = fit_prompt_to_budget(
                [mini_sys, *chunk, ask],
                self.window,
                compact_threshold_ratio=self.compact_threshold_ratio,
                source=f"pruned-summary:{self.agent_name}:{idx + 1}/{total}",
            )
            chunk_chars = sum(_row_chars(r) for r in (request or chunk))
            async with semaphore:
                remaining = deadline_at - time.monotonic()
                if remaining <= _MIN_CHUNK_WINDOW_SECONDS:
                    return None
                chunk_started = time.monotonic()
                try:
                    res = await self._await_response(
                        request or chunk,
                        None,
                        {},
                        timeout=remaining,
                    )
                except Exception as exc:
                    logger.warning(
                        "Pruned-summary chunk %d/%d failed after %.1fs "
                        "(%d chars in): %s",
                        idx + 1,
                        total,
                        time.monotonic() - chunk_started,
                        chunk_chars,
                        exc,
                    )
                    return None
            text = self._partial_text(res)
            if not text:
                return None
            logger.info(
                "Pruned-summary chunk %d/%d: %.1fs, %d chars in -> %d chars "
                "of summary.",
                idx + 1,
                total,
                time.monotonic() - chunk_started,
                chunk_chars,
                len(text),
            )
            return (text, chunk_chars)

        results = await asyncio.gather(
            *(_map_one(idx, chunk) for idx, chunk in enumerate(chunks)),
        )
        texts = [item[0] for item in results if item]
        if not texts:
            return ""
        if len(texts) == 1:
            return texts[0]

        remaining = deadline_at - time.monotonic()
        if remaining <= _MIN_CHUNK_WINDOW_SECONDS:
            # No time for the merge.  Concatenating the partials that answered
            # keeps every row that was read; returning "" here would leave the
            # queue full and the history unsummarised for another round.
            logger.warning(
                "Pruned-summary reduce skipped: deadline spent after %d/%d "
                "chunk(s); the summary is the concatenation of the partials.",
                len(texts),
                total,
            )
            return "\n\n".join(texts)

        merge_request = [
            mini_sys,
            {
                "role": "user",
                "content": (
                    "以下是同一段对话按时间顺序分段生成的多份摘要。把它们合并"
                    "为一份完整摘要：去重、保留全部事实与未完成的待办、同一"
                    "事实取更新的那一份。\n\n" + "\n\n".join(texts)
                ),
            },
        ]
        merge_request = fit_prompt_to_budget(
            merge_request,
            self.window,
            compact_threshold_ratio=self.compact_threshold_ratio,
            source=f"pruned-summary-reduce:{self.agent_name}",
        )
        try:
            res = await self._await_response(
                merge_request,
                None,
                {},
                timeout=remaining,
            )
        except Exception as exc:
            logger.warning(
                "Pruned-summary reduce failed (%s); using the concatenation "
                "of the %d partial(s).",
                exc,
                len(texts),
            )
            return "\n\n".join(texts)
        merged = self._partial_text(res)
        logger.info(
            "Pruned-summary %s: %d chunk(s) merged into %d chars in %.1fs.",
            self.agent_name or "?",
            len(texts),
            len(merged or ""),
            time.monotonic() - started,
        )
        return merged or "\n\n".join(texts)

    async def summarize_pruned_history(self) -> int:
        """Fold what hard pruning dropped into the memory's running summary.

        Hard pruning archives rows and removes them from working memory in one
        motion, and the upstream compactor only reads rows **not** marked
        compressed — so pruned history never reaches a summary at all (dev,
        2026-10-18: prunes followed by a compaction that "finished in 0.0s").
        Archiving is persistence, not memory: the rows are on disk and the
        agent no longer knows them.  This is the half that makes them part of
        what it still knows.

        Returns the number of rows folded in.  The queue is drained only when a
        summary was actually produced, so a failed round keeps the rows for the
        next one.
        """
        if not self.pruned_pending:
            return 0
        memory = self._memory()
        if memory is None:
            logger.info(
                "Pruned-summary %s: no memory attached, %d queued row(s) stay "
                "queued.",
                self.agent_name or "?",
                self.pruned_pending_chars,
            )
            return 0

        row_count = sum(len(batch) for batch in self.pruned_pending)
        rows = [
            self._row_of(message)
            for batch in self.pruned_pending
            for message in batch
        ]
        history_chars = sum(_row_chars(row) for row in rows)
        try:
            text = await self._summarize_rows(rows)
        except Exception:
            logger.warning(
                "Pruned-summary for agent %s failed; the %d queued row(s) stay "
                "queued.",
                self.agent_name or "?",
                row_count,
                exc_info=True,
            )
            return 0
        if not text:
            logger.info(
                "Pruned-summary for agent %s produced nothing; %d row(s) stay "
                "queued.",
                self.agent_name or "?",
                row_count,
            )
            return 0

        try:
            previous = memory.get_compressed_summary() or ""
        except Exception:
            previous = ""
        block = f"### 硬修剪归档摘要\n{text}"
        merged = f"{previous}\n\n{block}" if previous else block
        try:
            await memory.update_compressed_summary(merged)
        except Exception:
            logger.warning(
                "Pruned-summary for agent %s could not be written to memory; "
                "%d row(s) stay queued.",
                self.agent_name or "?",
                row_count,
                exc_info=True,
            )
            return 0

        self.pruned_pending = []
        self.pruned_pending_chars = 0
        logger.info(
            "Pruned-summary for agent %s: %d row(s) (%d chars) folded into the "
            "running summary (%d chars of summary).",
            self.agent_name or "?",
            row_count,
            history_chars,
            len(text),
        )
        return row_count

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
        # The rows are on disk and out of working memory; nobody else will
        # ever read them (the upstream compactor skips rows marked compressed),
        # so the summary is owed here or never happens.
        self._queue_pruned_for_summary(archived)
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

        # One line per reasoning step (拍板 §3.5): the bill the fixed part of
        # the request is paid in, in the unit the gate and the compactor both
        # count.  Without this the only way to learn the ratio was to hit the
        # overflow and read the error text.
        logger.info(
            "Context budget %s: fixed=%d (sys=%d tools=%d) history=%d "
            "total=%d allowance=%d trigger=%d fixed_pct=%.1f%% "
            "window=%d src=%s cpt=%.2f",
            self.agent_name,
            snapshot.fixed_chars,
            snapshot.fixed_chars - snapshot.tools_chars,
            snapshot.tools_chars,
            snapshot.history_chars,
            snapshot.total_chars,
            snapshot.budget_chars,
            snapshot.trigger_chars,
            (
                100.0 * snapshot.fixed_chars / snapshot.budget_chars
                if snapshot.budget_chars
                else 0.0
            ),
            self.window.effective_tokens,
            self.window.source,
            self.window.chars_per_token,
        )

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

        # Pruning and trimming **change what there is to reclaim**: archiving
        # the head inserts the summary row the compactor leaves behind, and
        # trimming the prompt list deletes rows the memory prune has already
        # marked.  A single pass sized by the pre-prune snapshot therefore
        # stops at a target that no longer exists -- measured on dev
        # 2026-10-18, console chat of agent user:admin: 323,773 chars against
        # a 157,696-char window, 321,000 chars reclaimed, and the prompt came
        # out at 162,546, i.e. a refusal on a session that had just been
        # shrunk by 20%.  Re-measure and re-target each round; the loop is
        # bounded so a pathological memory cannot spin here.
        reclaimed = 0
        after = snapshot
        for round_no in range(1, _ENFORCE_MAX_ROUNDS + 1):
            reclaimed += await self._prune_to_budget(after)
            reclaimed += self._trim_prompt(messages, after)
            after = self.measure(messages, tools)
            self.last_snapshot = after
            if after.total_chars <= after.budget_chars:
                logger.info(
                    "Context budget guard fits agent %s in %d round(s): "
                    "%d -> %d chars against a %d-char window (%d chars "
                    "reclaimed).",
                    self.agent_name,
                    round_no,
                    snapshot.total_chars,
                    after.total_chars,
                    after.budget_chars,
                    reclaimed,
                )
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
    def observe_refusal(self, exc: BaseException) -> None:
        """Learn from a provider refusal that states the real window.

        ``prompt (114974 tokens) leaves no room to answer in the context
        (102400)`` — measured on dev, 2026-10-17 — is the provider
        self-reporting its window under load.  Recording it caps the next
        budget against the number the server actually enforces, and pairs our
        own char measurement with the provider's token count, which is the
        only way to know the real chars-per-token ratio.
        """
        try:
            from .window_source import (
                model_slot_of,
                record_window_feedback,
            )

            provider_id, model_name = model_slot_of(self._inner)
            snapshot = self.last_snapshot
            record_window_feedback(
                provider_id,
                model_name,
                str(exc),
                snapshot.total_chars if snapshot else None,
                self.window.chars_per_token,
            )
        except Exception:  # observation must never change the outcome
            logger.debug("window feedback failed", exc_info=True)

    # ── chunked compaction (map-reduce) ─────────────────────────────
    async def _await_response(
        self,
        messages: Any,
        tools: Any,
        kwargs: Any,
        timeout: float | None = None,
    ):
        """Call the real model, normalizing a stream to its final chunk.

        Both halves are bounded: the request that never gets answered **and**
        the stream that stops producing chunks.  Bounding only the call is the
        usual half-measure -- under streaming the call returns an async
        generator at once, so a stalled stream would keep sitting on the
        chat's critical path for as long as it liked.

        *timeout* overrides the per-call ceiling for one caller; the map-reduce
        path passes the time its global deadline has left, so the last chunks
        cannot spend a full per-call budget after the deadline has passed.
        """
        deadline = (
            self.compaction_timeout
            if timeout is None or timeout <= 0
            else min(self.compaction_timeout, timeout)
        )
        started = time.monotonic()
        try:
            res = await asyncio.wait_for(
                self._inner(messages, tools=tools, **kwargs),
                timeout=deadline,
            )
        except asyncio.TimeoutError as exc:
            raise CompactionTimeoutError(
                f"model did not answer within {deadline:.0f}s "
                f"(agent {self.agent_name or '?'})",
            ) from exc

        if not (
            getattr(self._inner, "stream", False)
            and hasattr(res, "__aiter__")
        ):
            return res

        last = None
        iterator = res.__aiter__()
        while True:
            remaining = deadline - (time.monotonic() - started)
            if remaining <= 0:
                await self._close_stream(res)
                raise CompactionTimeoutError(
                    f"stream stalled past its {deadline:.0f}s budget "
                    f"(agent {self.agent_name or '?'})",
                )
            try:
                chunk = await asyncio.wait_for(
                    iterator.__anext__(),
                    timeout=remaining,
                )
            except StopAsyncIteration:
                return last
            except asyncio.TimeoutError as exc:
                await self._close_stream(res)
                raise CompactionTimeoutError(
                    f"stream produced no chunk for {remaining:.0f}s "
                    f"(agent {self.agent_name or '?'})",
                ) from exc
            last = chunk

    @staticmethod
    async def _close_stream(stream: Any) -> None:
        """Close a abandoned stream; a dead stream must not add noise."""
        aclose = getattr(stream, "aclose", None)
        if aclose is None:
            return
        try:
            await aclose()
        except Exception:  # pragma: no cover - cleanup path
            logger.debug("stream close failed", exc_info=True)

    @staticmethod
    def _has_metadata(response: Any) -> bool:
        """``metadata`` check that survives dict-backed responses.

        ``ChatResponse.__getattr__`` raises ``KeyError`` (not ``AttributeError``)
        for an absent key, so the usual ``getattr(obj, "metadata", None)``
        idiom does not protect this call site.
        """
        try:
            return bool(getattr(response, "metadata", None))
        except Exception:
            return False

    @staticmethod
    def _json_contract_row(kwargs: Any) -> dict:
        """A user row spelling out the JSON contract for a summary call.

        The compaction requests ask for structured output through the
        provider's ``response_format``/``format`` field alone.  Measured on
        dev 2026-10-18 against the live OpenAI-compatible endpoint: the model
        answered with prose echoing the last dialogue row
        (``Invalid JSON ... input_value='第149轮 助手：已…'``), the provider's
        tool-call fallback then failed too, and the whole compaction degraded
        to the single fitted request that drops 508 of 841 rows.  Not every
        endpoint honours ``response_format``, so the contract has to be in
        the prompt where the model will actually read it.
        """
        schema = kwargs.get("structured_model") if isinstance(kwargs, dict) else None
        keys: list = []
        try:
            keys = list(schema.model_json_schema().get("properties", {}))
        except Exception:
            keys = []
        ask = (
            "Respond with ONLY a JSON object — no prose, no code fences, "
            "no commentary, and never continue the dialogue."
        )
        if keys:
            ask += " It must have exactly these keys: " + ", ".join(
                f'"{k}"' for k in keys
            ) + "."
        return {"role": "user", "content": ask}

    @staticmethod
    def _no_tool_kwargs(kwargs: Any) -> dict:
        """kwargs for a summarization call: tool-calling must be switched off.

        The map/reduce calls inherit the agent's own request kwargs, which
        carry the whole tool catalogue.  Ollama then answers with tool calls
        (``finish_reason=tool_calls``) instead of the JSON its ``format``
        field asked for, and every chunk summary fails — measured on dev:
        3 of 4 chunks died that way, so map-reduce silently degraded back to
        the single fitted request it was supposed to replace.
        """
        if not isinstance(kwargs, dict):
            return {}
        return {
            k: v
            for k, v in kwargs.items()
            if k not in ("tools", "tool_choice", "parallel_tool_calls")
        }

    @staticmethod
    def _partial_text(response: Any) -> str:
        """Render one chunk summary as text the merge step can read.

        Prefers the structured metadata; falls back to the plain text the
        model produced, because a prose summary is worth far more to the
        merge step than the empty string that used to discard the chunk.
        """
        # ``ChatResponse.__getattr__`` delegates to a dict and raises
        # ``KeyError`` for absent keys, so ``getattr(obj, name, default)``
        # does *not* swallow the miss — every access needs its own guard.
        # It also has no ``get_text_content`` (that lives on ``Msg``), so
        # the text has to come out of the content blocks by hand.
        try:
            meta = getattr(response, "metadata", None)
        except Exception:
            meta = None
        if not meta:
            try:
                blocks = getattr(response, "content", None)
            except Exception:
                blocks = None
            return ContextBudgetGuard._blocks_text(blocks)
        if isinstance(meta, dict):
            parts = []
            for key, value in meta.items():
                if value in (None, "", [], {}):
                    continue
                if isinstance(value, (list, tuple)):
                    value = "; ".join(str(v) for v in value)
                parts.append(f"### {key}\n{value}")
            return "\n".join(parts)
        return str(meta)

    @staticmethod
    def _blocks_text(blocks: Any) -> str:
        """Concatenate the text blocks of a model response."""
        if isinstance(blocks, str):
            return blocks.strip()
        if not blocks:
            return ""
        out: list = []
        for block in blocks:
            if isinstance(block, dict):
                if block.get("type") == "text" and block.get("text"):
                    out.append(str(block["text"]))
            elif getattr(block, "type", None) == "text":
                out.append(str(getattr(block, "text", "") or ""))
        return "\n".join(out).strip()

    async def _compact_map_reduce(
        self,
        messages: Any,
        tools: Any,
        kwargs: Any,
    ):
        """Summarize the whole prefix in budget-sized chunks, then merge.

        Returns the merged structured response, or ``None`` when chunking
        does not apply (the prefix already fits in one request, there is no
        history to chunk, or a map call failed) — the caller then falls back
        to the single fitted request it used before.

        The agent's own system prompt is replaced by a one-line compaction
        instruction: a summary request does not need the persona, the tool
        catalogue or the skill index, and that fixed overhead is exactly what
        left no room for the history (measured 22,200 chars of system prompt
        in a 36,044-char compaction budget).
        """
        rows = [dict(m) for m in (messages or []) if isinstance(m, dict)]
        if len(rows) < 3:
            return None
        head = 0
        while head < len(rows) and rows[head].get("role") == "system":
            head += 1
        tail: list = []
        stop = len(rows)
        if rows[-1].get("role") == "user":
            tail = [rows[-1]]
            stop = len(rows) - 1
        history = rows[head:stop]
        if not history:
            return None

        mini_sys = {"role": "system", "content": _COMPACT_MINI_SYS}
        budget_chars = self.window.to_chars(
            int(self.window.effective_tokens * self.compaction_input_ratio),
        )
        overhead = (
            _row_chars(mini_sys)
            + sum(_row_chars(r) for r in tail)
            + 2_000
        )
        chunk_budget = int(budget_chars * self.compact_threshold_ratio) - overhead
        # Fitting the window is not the same as answering in time.  Chunks
        # sized to the window measured 70-90K chars on dev 2026-10-18 and the
        # model needed ~90 s for each one, so a 305-row compaction cost the
        # user 7+ minutes of a single turn.  The cap is the knob that makes a
        # chunk answer in seconds; more, smaller chunks are cheaper overall.
        chunk_budget = min(chunk_budget, self.map_chunk_max_chars)
        if chunk_budget < 4_000:
            # No room for a chunk that carries anything: the single fitted
            # request is the best this window can do.
            return None

        history_chars = sum(_row_chars(r) for r in history)
        needed_chunks = max(
            2,
            -(-history_chars // max(1, int(chunk_budget * _COMPACT_CHUNK_FILL))),
        )
        max_chunks = min(
            _COMPACT_CHUNK_CEILING,
            max(_COMPACT_MAX_CHUNKS, needed_chunks),
        )
        if needed_chunks > max_chunks:
            logger.warning(
                "Compaction %s: %d chars need %d chunk(s) at %d chars/chunk "
                "but the ceiling is %d; the tail chunk gets widened and the "
                "fitter truncates it.",
                self.agent_name or "?",
                history_chars,
                needed_chunks,
                chunk_budget,
                max_chunks,
            )
        chunks = split_rows_for_compaction(
            history,
            chunk_budget,
            max_chunks=max_chunks,
        )
        if len(chunks) <= 1:
            return None

        # Compaction used to be invisible: it ran on a background task, and a
        # chat that died inside it left no trace at all (dev, 2026-10-18: 18
        # min 40 s of ``running``, zero log lines).  This is the line that
        # says the summariser started, in what shape, and the per-chunk lines
        # below say how each one went.
        started = time.monotonic()
        logger.info(
            "Compaction start %s: %d history rows -> %d chunk(s) "
            "(chunk budget %d chars, compaction window %d chars, "
            "ratio %.2f, map_reduce=%s)",
            self.agent_name or "?",
            len(history),
            len(chunks),
            chunk_budget,
            budget_chars,
            self.compact_threshold_ratio,
            self.map_reduce,
        )

        total = len(chunks)
        semaphore = asyncio.Semaphore(self.map_concurrency)
        collected: list[str] = []
        # One wall-clock ceiling for the whole compaction, shared by every
        # chunk and the merge.  Per-call timeouts bound a single request, and
        # five of them at the ceiling still cost the user seven minutes;
        # dev 2026-10-18 measured 19 chunks and 18 min 40 s of ``running``
        # with zero log lines.  Past the deadline the chunks that answered get
        # merged and the rest are dropped.
        deadline_at = started + self.compaction_global_timeout

        def _time_left() -> float:
            return deadline_at - time.monotonic()

        async def _map_one(idx: int, chunk: list) -> tuple[str, Any] | None:
            remaining = _time_left()
            if remaining <= _MIN_CHUNK_WINDOW_SECONDS:
                logger.warning(
                    "Compaction map chunk %d/%d skipped: the %.0fs compaction "
                    "deadline is spent (%.1fs elapsed).",
                    idx + 1,
                    total,
                    self.compaction_global_timeout,
                    time.monotonic() - started,
                )
                return None
            request = [mini_sys, *chunk, *tail, self._json_contract_row(kwargs)]
            request = fit_prompt_to_budget(
                request,
                self.window,
                compact_threshold_ratio=self.compact_threshold_ratio,
                source=f"compaction-map:{self.agent_name}:{idx + 1}/{total}",
            )
            chunk_chars = sum(_row_chars(r) for r in request)
            async with semaphore:
                # The semaphore is where the queueing happens, so the time the
                # chunk spent waiting is deducted here, not at entry.
                remaining = _time_left()
                if remaining <= _MIN_CHUNK_WINDOW_SECONDS:
                    logger.warning(
                        "Compaction map chunk %d/%d skipped: %.1fs left of the "
                        "%.0fs compaction deadline.",
                        idx + 1,
                        total,
                        remaining,
                        self.compaction_global_timeout,
                    )
                    return None
                chunk_started = time.monotonic()
                try:
                    res = await self._await_response(
                        request,
                        None,
                        self._no_tool_kwargs(kwargs),
                        timeout=remaining,
                    )
                except Exception as exc:
                    logger.warning(
                        "Compaction map chunk %d/%d failed after %.1fs "
                        "(%d chars in) (%s); merging %d partial summary(ies) "
                        "without it.",
                        idx + 1,
                        total,
                        time.monotonic() - chunk_started,
                        chunk_chars,
                        exc,
                        len(collected),
                    )
                    return None
                text = self._partial_text(res)
                logger.info(
                    "Compaction map chunk %d/%d: %.1fs, %d chars in -> %d "
                    "chars of summary (%.0fs of the deadline left).",
                    idx + 1,
                    total,
                    time.monotonic() - chunk_started,
                    chunk_chars,
                    len(text or ""),
                    _time_left(),
                )
                return (text, res) if text else None

        # Chunks are independent by construction, so they go in flight
        # together.  Serialized at ~90 s each, five of them cost the user a
        # seven-minute turn for work with no ordering requirement at all.
        results = await asyncio.gather(
            *(_map_one(idx, chunk) for idx, chunk in enumerate(chunks)),
        )
        partials: list[str] = []
        responses: list[Any] = []
        for idx, item in enumerate(results):
            if not item:
                continue
            text, res = item
            collected.append(text)
            partials.append(f"[部分 {idx + 1}/{total}]\n{text}")
            responses.append(res)
        if not partials:
            return None
        if len(partials) == 1:
            merged_text = partials[0]
        else:
            merged_text = (
                "以下是同一段对话按时间顺序分段生成的多份摘要。把它们合并为"
                "一份完整摘要：去重、保留全部事实与未完成的待办、同一事实"
                "取更新的那一份、保持结构化字段的语义。\n\n"
                + "\n\n".join(partials)
            )
        remaining = _time_left()
        if remaining <= _MIN_CHUNK_WINDOW_SECONDS and len(partials) > 1:
            # No time for the merge call.  Returning None here would send the
            # whole history out as one fitted request, which drops the oldest
            # rows unsummarized; concatenating the partials that *were* read
            # keeps every row's content in the summary.
            logger.warning(
                "Compaction reduce skipped: the %.0fs deadline is spent after "
                "%d/%d chunk(s); the summary is the concatenation of the "
                "partials that answered.",
                self.compaction_global_timeout,
                len(partials),
                total,
            )
            final = self._concat_partials(responses, collected)
            if final is None:
                return None
        else:
            merge_request = [
                mini_sys,
                {"role": "user", "content": merged_text},
                self._json_contract_row(kwargs),
                *tail,
            ]
            merge_request = fit_prompt_to_budget(
                merge_request,
                self.window,
                compact_threshold_ratio=self.compact_threshold_ratio,
                source=f"compaction-reduce:{self.agent_name}",
            )
            merge_started = time.monotonic()
            try:
                final = await self._await_response(
                    merge_request,
                    None,
                    self._no_tool_kwargs(kwargs),
                    timeout=max(_MIN_CHUNK_WINDOW_SECONDS, remaining),
                )
            except Exception as exc:
                logger.warning(
                    "Compaction reduce failed after %.1fs (%s); falling back to "
                    "the single fitted request.",
                    time.monotonic() - merge_started,
                    exc,
                )
                return None
            logger.info(
                "Compaction merged %d/%d chunk(s) in %.1fs (reduce %.1fs).",
                len(partials),
                total,
                time.monotonic() - started,
                time.monotonic() - merge_started,
            )
        if not self._has_metadata(final):
            # The merge step is the one call that *must* be structured: the
            # downstream template formats ``metadata`` keys.  Ask once more
            # with the schema spelled out in the prompt — a model that
            # answered in prose usually complies when told plainly.
            final = await self._reduce_json_retry(merge_request, kwargs)
        if not self._has_metadata(final):
            logger.warning(
                "Compaction reduce produced no structured summary; falling "
                "back to the single fitted request.",
            )
            return None
        logger.info(
            "Compaction map-reduce: %d row(s) in %d chunk(s) (budget %d "
            "chars/chunk) merged into one summary of %d char(s) — no row "
            "compressed without being read.",
            len(history),
            total,
            chunk_budget,
            len(self._partial_text(final)),
        )
        if self.stream:
            return self._single_chunk_stream(final)
        return final

    def _concat_partials(self, responses: list[Any], texts: list[str]) -> Any:
        """Merge partial summaries **without** a model call.

        The fallback when the compaction deadline is spent.  Returning ``None``
        there would hand the whole history to the single fitted request, which
        drops the oldest rows unsummarized -- the exact failure map-reduce
        exists to remove.  Concatenating the partials keeps the content of
        every row that was read; it is a rougher summary, not a lost one.

        Returns a response carrying the first structured summary, with the
        remaining partial texts appended to its longest text field, or ``None``
        when no chunk produced structured output.
        """
        base = next((r for r in responses if self._has_metadata(r)), None)
        if base is None:
            return None
        try:
            metadata = dict(base.metadata)
        except Exception:  # pragma: no cover - defensive
            return None
        keys = [k for k, v in metadata.items() if isinstance(v, str)]
        if not keys:
            return None
        key = max(keys, key=lambda k: len(metadata[k]))
        extra = "\n\n".join(texts[1:])
        if extra:
            metadata[key] = f"{metadata[key]}\n\n{extra}"
        try:
            from dataclasses import is_dataclass, replace

            if is_dataclass(base):
                return replace(base, metadata=metadata)
        except Exception:  # pragma: no cover - response shape we do not own
            logger.debug("partial-summary concat copy failed", exc_info=True)
        return None

    async def _reduce_json_retry(self, merge_request: Any, kwargs: Any) -> Any:
        """Ask the merge step once more, spelling the JSON contract out.

        Returns the retry response, or ``None`` when the retry itself
        failed; the caller re-checks ``metadata`` and falls back to the
        single fitted request either way, so this can only improve the
        outcome.
        """
        retry = [*merge_request, self._json_contract_row(kwargs)]
        fitted = fit_prompt_to_budget(
            retry,
            self.window,
            compact_threshold_ratio=self.compact_threshold_ratio,
            source=f"compaction-reduce-retry:{self.agent_name}",
        )
        try:
            return await self._await_response(
                fitted or retry,
                None,
                self._no_tool_kwargs(kwargs),
            )
        except Exception as exc:
            logger.warning("Compaction reduce retry failed (%s).", exc)
            return None

    async def _single_chunk_stream(self, response: Any):
        """Present one finished response as the stream the caller expects."""
        yield response

    async def __call__(
        self,
        messages: Any = None,
        tools: Any = None,
        **kwargs: Any,
    ) -> Any:
        # Compaction itself sends the whole uncompressed prefix to a model.
        # It is measured and fitted — never refused (refusing the cure would
        # guarantee the next step overflows too) — and never allowed to be
        # bigger than the request the gate just pruned.  Its budget is the
        # window scaled by ``compaction_input_ratio``, so the summary request
        # leaves room for the compression prompt appended to it.
        if "structured_model" in kwargs:
            if messages is not None:
                if self.map_reduce:
                    try:
                        reduced = await self._compact_map_reduce(
                            messages,
                            tools,
                            kwargs,
                        )
                    except Exception:  # never let the cure break the call
                        logger.debug(
                            "Chunked compaction skipped",
                            exc_info=True,
                        )
                        reduced = None
                    if reduced is not None:
                        return reduced
                fitted = fit_prompt_to_budget(
                    messages,
                    replace(
                        self.window,
                        effective_tokens=int(
                            self.window.effective_tokens
                            * self.compaction_input_ratio,
                        ),
                    ),
                    compact_threshold_ratio=self.compact_threshold_ratio,
                    source=f"compaction:{self.agent_name}",
                )
                # An empty fit means the fixed overhead alone cannot fit;
                # send the prompt as-is rather than losing the compaction.
                messages = fitted or messages
            return await self._inner(messages, tools=tools, **kwargs)
        snapshot: BudgetSnapshot | None = None
        if messages is not None:
            snapshot = await self.enforce(messages, tools)
        self._publish_to_governance(snapshot)
        try:
            return await self._inner(messages, tools=tools, **kwargs)
        except Exception as exc:
            # The provider's refusal is a window report; the gate is the only
            # place that has both the refusal text and our own measurement of
            # the prompt that caused it.
            self.observe_refusal(exc)
            raise

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
    compaction_input_ratio: float = 0.5,
    keep_chars_floor: int = 12_000,
    memory_provider: Callable[[], Any] | None = None,
    agent_name: str = "",
    ledger: Any = None,
    map_reduce: bool = True,
    compaction_timeout: float | None = None,
    map_chunk_max_chars: int | None = None,
    map_concurrency: int | None = None,
    compaction_global_timeout: float | None = None,
) -> Any:
    """Wrap *model* in the gate, or return it unchanged when unusable.

    A gate that cannot measure (no window) must not swallow calls, so the
    fallback is the untouched model — the same behaviour as compaction being
    disabled by configuration.

    Every keyword the guard accepts has to be forwarded here: the agent builds
    the gate through this function and nothing else, and a parameter accepted
    by ``ContextBudgetGuard`` but missing from this signature is a
    ``TypeError`` on the first chat of the process (measured on dev
    2026-10-18: ``compaction_global_timeout`` made every request fail with
    ``MODEL_TIMEOUT`` before a single token was produced).
    """
    if model is None or isinstance(model, ContextBudgetGuard):
        return model
    if window.effective_tokens <= 0:
        return model
    return ContextBudgetGuard(
        model,
        window=window,
        compact_threshold_ratio=compact_threshold_ratio,
        compaction_input_ratio=compaction_input_ratio,
        keep_chars_floor=keep_chars_floor,
        memory_provider=memory_provider,
        agent_name=agent_name,
        ledger=ledger,
        map_reduce=map_reduce,
        compaction_timeout=compaction_timeout,
        map_chunk_max_chars=map_chunk_max_chars,
        map_concurrency=map_concurrency,
        compaction_global_timeout=compaction_global_timeout,
    )