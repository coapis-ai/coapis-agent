# -*- coding: utf-8 -*-
"""Hard-pruned history must reach a summary (B, dev 2026-10-18).

The gate's hard prune archives the head of the history and removes it from
working memory in one motion.  The upstream compactor only reads rows **not**
marked compressed, so those rows are never summarised by anything: on dev the
sequence was a prune of ~160K chars followed by "Background compaction for
Friday finished in 0.0s" -- the compaction had nothing left to do because the
history it would have summarised had already been pruned out of its view.
Archiving is persistence, not memory.

Contract:
- a prune queues what it dropped, bounded by batches and characters;
- the deferred compaction folds the queue into the memory's running summary;
- a fold that produced nothing keeps the rows for the next round;
- upstream's summary replacement must not erase what earlier rounds already
  summarised.
"""

import asyncio

import pytest
from agentscope.agent._react_agent import _MemoryMark
from agentscope.message import Msg
from agentscope.model._model_response import ChatResponse

from coapis.agents.context.context_budget import (
    BudgetSnapshot,
    ContextBudgetGuard,
)
from coapis.agents.context.window_source import WindowInfo


def _window(tokens: int = 60_000, chars_per_token: float = 1.1) -> WindowInfo:
    return WindowInfo(
        reported_tokens=tokens,
        effective_tokens=tokens,
        source="model_self_report",
        chars_per_token=chars_per_token,
    )


def _msg(role: str, text: str) -> Msg:
    return Msg(name=role, content=text, role=role)


class _FakeMemory:
    """The slice of ``AgentContext`` the gate and the fold touch."""

    def __init__(self, rows: list) -> None:
        self.content = [(row, []) for row in rows]
        self.summary = ""
        self.updates = 0

    async def update_messages_mark(self, new_mark=None, msg_ids=None):
        for row, marks in self.content:
            if row.id in (msg_ids or []):
                marks.append(new_mark)

    async def archive_compressed_and_purge(self):
        archived = [
            row
            for row, marks in self.content
            if _MemoryMark.COMPRESSED in marks
        ]
        self.content = [
            (row, marks)
            for row, marks in self.content
            if _MemoryMark.COMPRESSED not in marks
        ]
        return archived

    def get_compressed_summary(self) -> str:
        return self.summary

    async def update_compressed_summary(self, summary: str) -> None:
        self.summary = summary
        self.updates += 1


class _FakeModel:
    """Answers every summarisation call; distinguishes map from merge."""

    def __init__(self, fail: bool = False, merge_text: str | None = None):
        self.stream = False
        self.fail = fail
        self.merge_text = merge_text
        self.calls: list[int] = []
        self.payloads: list[str] = []

    async def __call__(self, messages=None, tools=None, **kwargs):
        total = sum(len(str(m)) for m in messages or [])
        self.calls.append(total)
        self.payloads.append("".join(str(m) for m in messages or []))
        if self.fail:
            raise RuntimeError("provider is down")
        payload = str(messages[-1].get("content")) if messages else ""
        if "合并为一份完整摘要" in payload:
            return ChatResponse(
                content=[{"type": "text", "text": self.merge_text or "merged"}],
            )
        return ChatResponse(
            content=[{"type": "text", "text": f"summary-of-{total}"}],
        )


def _guard(model, memory, *, chunk_chars=4_000, tokens=60_000, timeout=60.0):
    return ContextBudgetGuard(
        model,
        window=_window(tokens=tokens),
        compaction_input_ratio=0.7,
        map_reduce=True,
        map_chunk_max_chars=chunk_chars,
        map_concurrency=1,
        compaction_global_timeout=timeout,
        memory_provider=lambda: memory,
        agent_name="tester",
    )


def _snap(total: int, budget: int) -> BudgetSnapshot:
    return BudgetSnapshot(
        history_chars=total,
        fixed_chars=1_000,
        tools_chars=0,
        total_chars=total,
        trigger_chars=int(budget * 0.8),
        budget_chars=budget,
    )


# ── the queue ────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_prune_queues_what_it_archived():
    """A hard prune must remember the rows it dropped from working memory."""
    rows = [_msg("user", "u" * 5_000) for _ in range(8)]
    memory = _FakeMemory(rows)
    guard = _guard(_FakeModel(), memory)
    before = len(memory.content)

    reclaimed = await guard._prune_to_budget(_snap(total=60_000, budget=20_000))

    assert reclaimed > 0
    assert len(memory.content) < before, "rows left working memory"
    assert guard.pruned_pending, "the archived rows are owed a summary"
    assert guard.pruned_pending_chars > 0
    queued = sum(len(batch) for batch in guard.pruned_pending)
    assert queued == before - len(memory.content)


@pytest.mark.asyncio
async def test_queue_is_bounded_by_batches_keeping_the_newest():
    guard = _guard(_FakeModel(), _FakeMemory([]))
    guard._PRUNED_MAX_BATCHES = 2
    for i in range(4):
        guard._queue_pruned_for_summary([_msg("user", f"batch-{i}")])
    batches = [batch[0].content for batch in guard.pruned_pending]
    assert len(batches) == 2
    assert batches == ["batch-2", "batch-3"], batches


@pytest.mark.asyncio
async def test_queue_is_bounded_by_chars_keeping_the_newest():
    guard = _guard(_FakeModel(), _FakeMemory([]))
    guard._PRUNED_MAX_CHARS = 1_000
    guard._PRUNED_MAX_BATCHES = 16
    guard._queue_pruned_for_summary([_msg("user", "o" * 900)])
    guard._queue_pruned_for_summary([_msg("user", "n" * 900)])
    assert guard.pruned_pending_chars <= 1_000
    assert guard.pruned_pending[0][0].content.startswith("n")


def test_pop_drains_oldest_first_and_empties_the_queue():
    guard = _guard(_FakeModel(), _FakeMemory([]))
    guard._queue_pruned_for_summary([_msg("user", "old")])
    guard._queue_pruned_for_summary([_msg("user", "new")])
    rows = guard.pop_pruned_for_summary()
    assert [row.content for row in rows] == ["old", "new"]
    assert guard.pruned_pending == []
    assert guard.pruned_pending_chars == 0
    assert guard.pop_pruned_for_summary() == []


# ── the fold ─────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_pruned_rows_are_folded_into_the_running_summary():
    memory = _FakeMemory([])
    model = _FakeModel(merge_text="merged summary")
    guard = _guard(model, memory)
    guard._queue_pruned_for_summary(
        [_msg("user", "u" * 3_000), _msg("assistant", "a" * 3_000)],
    )

    folded = await guard.summarize_pruned_history()

    assert folded == 2
    # 6K chars at a 4K chunk budget: two map calls, then the merge is what
    # lands in the summary.
    assert "merged summary" in memory.summary
    assert "硬修剪归档摘要" in memory.summary
    assert guard.pruned_pending == []


@pytest.mark.asyncio
async def test_fold_appends_to_the_existing_summary():
    memory = _FakeMemory([])
    memory.summary = "earlier rounds said this"
    guard = _guard(_FakeModel(), memory)
    guard._queue_pruned_for_summary([_msg("user", "x" * 2_000)])

    assert await guard.summarize_pruned_history() == 1
    assert memory.summary.startswith("earlier rounds said this")
    assert "summary-of-" in memory.summary


@pytest.mark.asyncio
async def test_failed_fold_keeps_the_rows_queued():
    memory = _FakeMemory([])
    guard = _guard(_FakeModel(fail=True), memory)
    guard._queue_pruned_for_summary([_msg("user", "x" * 2_000)])

    assert await guard.summarize_pruned_history() == 0
    assert len(guard.pruned_pending) == 1
    assert memory.summary == ""


@pytest.mark.asyncio
async def test_fold_without_memory_keeps_the_rows_queued():
    guard = _guard(_FakeModel(), None)
    guard._queue_pruned_for_summary([_msg("user", "x" * 2_000)])
    assert await guard.summarize_pruned_history() == 0
    assert len(guard.pruned_pending) == 1


@pytest.mark.asyncio
async def test_fold_with_no_window_room_produces_nothing():
    """A window too small for a chunk must not send a doomed request."""
    memory = _FakeMemory([])
    model = _FakeModel()
    guard = _guard(model, memory, chunk_chars=3_000, tokens=2_000)
    guard._queue_pruned_for_summary([_msg("user", "x" * 2_000)])

    assert await guard.summarize_pruned_history() == 0
    assert model.calls == [], "nothing was sent to the provider"
    assert len(guard.pruned_pending) == 1


@pytest.mark.asyncio
async def test_multi_chunk_fold_maps_every_chunk_then_merges():
    memory = _FakeMemory([])
    model = _FakeModel(merge_text="merged summary")
    guard = _guard(model, memory, chunk_chars=4_000)
    guard._queue_pruned_for_summary(
        [_msg("user", "u" * 6_000) for _ in range(6)],
    )

    assert await guard.summarize_pruned_history() == 6
    assert "merged summary" in memory.summary
    # 6 x 6K chars at a 4K chunk budget: more than one map call, and the
    # merge is the last request.
    assert len(model.calls) >= 3, model.calls


@pytest.mark.asyncio
async def test_nothing_queued_costs_nothing():
    memory = _FakeMemory([])
    model = _FakeModel()
    guard = _guard(model, memory)
    assert await guard.summarize_pruned_history() == 0
    assert model.calls == []
    assert memory.summary == ""


# ── the background round: preserve + fold ────────────────────────────


class _FakeAgent:
    def __init__(self, memory, guard):
        self.name = "Friday"
        self.memory = memory
        self.context_guard = guard
        self.compression_config = None  # upstream compaction no-ops
        self._compaction_due = True
        self._compaction_task = None


@pytest.mark.asyncio
async def test_fold_pruned_history_goes_through_the_guard():
    from coapis.agents.react_agent import fold_pruned_history

    memory = _FakeMemory([])
    guard = _guard(_FakeModel(), memory)
    guard._queue_pruned_for_summary([_msg("user", "x" * 2_000)])
    agent = _FakeAgent(memory, guard)

    assert await fold_pruned_history(agent) == 1
    assert "summary-of-" in memory.summary


@pytest.mark.asyncio
async def test_fold_survives_a_guard_without_the_method():
    from coapis.agents.react_agent import fold_pruned_history

    agent = _FakeAgent(_FakeMemory([]), object())
    assert await fold_pruned_history(agent) == 0


@pytest.mark.asyncio
async def test_background_round_preserves_the_earlier_summary():
    """Upstream replaces the summary; the round must not lose the old one."""
    from coapis.agents import react_agent as ra

    memory = _FakeMemory([])
    memory.summary = "what round one already knew"

    async def _fake_compress(_self):
        # Upstream's shape: a brand-new summary of the rows it just read.
        await memory.update_compressed_summary("what round two read")

    original = ra.ReActAgent._compress_memory_if_needed
    ra.ReActAgent._compress_memory_if_needed = _fake_compress
    try:
        await ra._run_background_compaction(_FakeAgent(memory, None), None)
    finally:
        ra.ReActAgent._compress_memory_if_needed = original

    assert "what round one already knew" in memory.summary
    assert "what round two read" in memory.summary


@pytest.mark.asyncio
async def test_background_round_folds_and_persists():
    from coapis.agents import react_agent as ra

    memory = _FakeMemory([])
    guard = _guard(_FakeModel(), memory)
    guard._queue_pruned_for_summary([_msg("user", "x" * 2_000)])
    agent = _FakeAgent(memory, guard)
    persisted = []
    in_flight = ra._COMPACTION_IN_FLIGHT

    async def _persist():
        persisted.append(memory.summary)

    await ra._run_background_compaction(agent, _persist)

    assert "summary-of-" in memory.summary
    assert persisted and "summary-of-" in persisted[0]
    # The round releases the slot it took; the counter is module-global, so
    # the assertion is about the delta, not the absolute value.
    assert ra._COMPACTION_IN_FLIGHT == in_flight


# ── what the fold actually sees ──────────────────────────────────────


def _tool_row() -> Msg:
    return Msg(
        name="assistant",
        content=[
            {"type": "text", "text": "我去读文件"},
            {
                "type": "tool_use",
                "id": "t1",
                "name": "read_file",
                "input": {"file_path": "/app/a.py"},
            },
            {
                # agentscope's own shape: the payload lives under ``output``.
                "type": "tool_result",
                "id": "t1",
                "name": "read_file",
                "output": [
                    {
                        "type": "text",
                        "text": "def compute():\n    return 42\n" * 60,
                    },
                ],
            },
            {
                # The provider wire shape, same payload under ``content``.
                "type": "tool_result",
                "id": "t2",
                "name": "grep_search",
                "content": "matched: line 7",
            },
        ],
        role="assistant",
    )


def test_queued_rows_carry_tool_blocks_not_only_text():
    """The fold must see what the prune measured.

    dev 2026-10-19: a prune dropped 177,912 chars and queued 8,079 for a
    summary, because rendering a row kept only ``text`` blocks -- tool calls
    and their results, which are the bulk of an agent's history, reached the
    summary as nothing.
    """
    guard = _guard(_FakeModel(), _FakeMemory([]))
    guard._queue_pruned_for_summary([_tool_row()])

    assert guard.pruned_pending_chars > 1_000, guard.pruned_pending_chars


@pytest.mark.asyncio
async def test_summary_call_is_fed_the_tool_calls_and_results():
    memory = _FakeMemory([])
    model = _FakeModel(merge_text="merged")
    guard = _guard(model, memory)
    guard._queue_pruned_for_summary([_tool_row()])

    assert await guard.summarize_pruned_history() == 1
    fed = "".join(model.payloads)
    assert "read_file" in fed, "the tool call reached the summary call"
    assert "def compute()" in fed, "the tool result reached the summary call"


def test_render_caps_one_huge_tool_result():
    """One 50K tool output must not be what the whole queue measures."""
    guard = _guard(_FakeModel(), _FakeMemory([]))
    row = guard._row_of(
        Msg(
            name="assistant",
            content=[
                {
                    "type": "tool_result",
                    "id": "t1",
                    "name": "read_file",
                    "output": "x" * 50_000,
                },
            ],
            role="assistant",
        ),
    )
    assert len(row["content"]) < 5_000
    assert row["content"].endswith("…(截断)")


def test_render_marks_media_blocks_instead_of_dropping_them():
    guard = _guard(_FakeModel(), _FakeMemory([]))
    row = guard._row_of(
        Msg(
            name="assistant",
            content=[
                {"type": "image", "source": {"url": "x"}},
                {"type": "thinking", "thinking": "先看看目录"},
            ],
            role="assistant",
        ),
    )
    assert "[图片]" in row["content"]
    assert "先看看目录" in row["content"]
