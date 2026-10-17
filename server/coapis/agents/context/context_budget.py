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

import copy
import logging
from dataclasses import dataclass, replace
from typing import Any, Awaitable, Callable

from .window_source import WindowInfo

logger = logging.getLogger(__name__)


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
# Cost bound: a compaction is a background task, not a batch job.  When the
# prefix needs more chunks than this, chunks grow instead of the call count.
_COMPACT_MAX_CHUNKS = 12


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
            )
        except Exception:  # observation must never change the outcome
            logger.debug("window feedback failed", exc_info=True)

    # ── chunked compaction (map-reduce) ─────────────────────────────
    async def _await_response(self, messages: Any, tools: Any, kwargs: Any):
        """Call the real model, normalizing a stream to its final chunk."""
        res = await self._inner(messages, tools=tools, **kwargs)
        if getattr(self._inner, "stream", False) and hasattr(res, "__aiter__"):
            last = None
            async for chunk in res:
                last = chunk
            return last
        return res

    @staticmethod
    def _partial_text(response: Any) -> str:
        """Render one structured summary as text the merge step can read."""
        meta = getattr(response, "metadata", None)
        if not meta:
            return ""
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
        if chunk_budget < 4_000:
            # No room for a chunk that carries anything: the single fitted
            # request is the best this window can do.
            return None

        chunks = split_rows_for_compaction(history, chunk_budget)
        if len(chunks) <= 1:
            return None

        partials: list[str] = []
        total = len(chunks)
        for idx, chunk in enumerate(chunks):
            request = [mini_sys, *chunk, *tail]
            request = fit_prompt_to_budget(
                request,
                self.window,
                compact_threshold_ratio=self.compact_threshold_ratio,
                source=f"compaction-map:{self.agent_name}:{idx + 1}/{total}",
            )
            try:
                res = await self._await_response(request, tools, kwargs)
            except Exception as exc:
                logger.warning(
                    "Compaction map chunk %d/%d failed (%s); merging %d "
                    "partial summary(ies) without it.",
                    idx + 1,
                    total,
                    exc,
                    len(partials),
                )
                continue
            text = self._partial_text(res)
            if text:
                partials.append(f"[部分 {idx + 1}/{total}]\n{text}")
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
        merge_request = [
            mini_sys,
            {"role": "user", "content": merged_text},
            *tail,
        ]
        merge_request = fit_prompt_to_budget(
            merge_request,
            self.window,
            compact_threshold_ratio=self.compact_threshold_ratio,
            source=f"compaction-reduce:{self.agent_name}",
        )
        try:
            final = await self._await_response(merge_request, tools, kwargs)
        except Exception as exc:
            logger.warning(
                "Compaction reduce failed (%s); falling back to the single "
                "fitted request.",
                exc,
            )
            return None
        if not getattr(final, "metadata", None):
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
        compaction_input_ratio=compaction_input_ratio,
        keep_chars_floor=keep_chars_floor,
        memory_provider=memory_provider,
        agent_name=agent_name,
        ledger=ledger,
        map_reduce=map_reduce,
    )