# -*- coding: utf-8 -*-
"""Chunked (map-reduce) compaction tests.

Why this exists: the compaction request carries the whole uncompressed
prefix, which never fits one request.  Fitting it by dropping the oldest
rows archived those rows as COMPRESSED **without any summary** — measured on
dev 2026-10-17: 280 rows dropped per compaction, coverage 0.16.  Memory was
deleted and nothing recorded it.

The contract these tests pin:
- every row handed to the compactor appears in some map request (nothing is
  compressed without being read);
- each map request fits the compaction budget it is given;
- the agent's fixed overhead (system prompt) is not paid per map call;
- the merged result is a single structured summary;
- chunking never breaks the call: on any failure the guard falls back to the
  single fitted request it used before.
"""

import asyncio

import pytest
from agentscope.model._model_response import ChatResponse

from coapis.agents.context.context_budget import (
    ContextBudgetGuard,
    build_budget_guard,
    build_compaction_units,
    split_rows_for_compaction,
)
from coapis.agents.context.window_source import WindowInfo


def _window(tokens: int = 60_000, chars_per_token: float = 1.1) -> WindowInfo:
    return WindowInfo(
        reported_tokens=tokens,
        effective_tokens=tokens,
        source="model_self_report",
        chars_per_token=chars_per_token,
    )


def _rows(
    n_history: int,
    row_chars: int = 3_000,
    sys_chars: int = 22_000,
    tail_chars: int = 1_500,
) -> list[dict]:
    """A formatted compaction prompt: system + history + compression prompt."""
    rows = [{"role": "system", "content": "S" * sys_chars}]
    rows += [
        {
            "role": "user" if i % 2 == 0 else "assistant",
            "content": f"row-{i}-" + "x" * (row_chars - 10),
        }
        for i in range(n_history)
    ]
    rows.append({"role": "user", "content": "T" * tail_chars})
    return rows


class _FakeModel:
    """Records every prompt it is sent and returns a structured summary."""

    def __init__(
        self,
        stream: bool = False,
        fail_map: bool = False,
        fail_from: int | None = None,
    ):
        self.stream = stream
        self.calls: list[list] = []
        self.fail_from = fail_from
        self.fail_map = fail_map

    async def __call__(self, messages, tools=None, **kwargs):
        self.calls.append(list(messages))
        if self.fail_from is not None and len(self.calls) >= self.fail_from:
            raise RuntimeError("provider refused")
        if self.fail_map and any(
            m.get("role") == "system" and len(str(m)) < 1_000
            for m in messages
        ):
            raise RuntimeError("chunk call refused")
        resp = ChatResponse(
            content=[{"type": "text", "text": "ok"}],
            metadata={
                "task_overview": f"chunk {len(self.calls)}",
                "key_facts": ["fact"],
                "next_steps": [],
                "empty_field": "",
            },
        )
        if self.stream:

            async def _gen():
                yield resp

            return _gen()
        return resp


def _guard(model: _FakeModel, **kw) -> ContextBudgetGuard:
    return ContextBudgetGuard(
        model,
        window=_window(),
        compact_threshold_ratio=0.8,
        compaction_input_ratio=0.7,
        keep_chars_floor=2_000,
        agent_name="test:agent",
        **kw,
    )


class TestCompactionUnits:
    def test_plain_rows_are_their_own_units(self):
        rows = [{"role": "user", "content": "a"}, {"role": "assistant", "content": "b"}]
        assert build_compaction_units(rows) == [[rows[0]], [rows[1]]]

    def test_tool_call_and_results_stay_in_one_unit(self):
        call = {
            "role": "assistant",
            "content": "calling",
            "tool_calls": [{"id": "t1", "name": "x"}, {"id": "t2", "name": "y"}],
        }
        rows = [
            call,
            {"role": "tool", "tool_call_id": "t1", "content": "r1"},
            {"role": "tool", "tool_call_id": "t2", "content": "r2"},
            {"role": "user", "content": "next"},
        ]
        units = build_compaction_units(rows)
        assert units[0] == rows[:3]
        assert units[1] == [rows[3]]

    def test_empty_input(self):
        assert build_compaction_units([]) == []


class TestCompactionChunks:
    def test_every_row_is_kept_once_in_order(self):
        rows = _rows(40)[:41]  # history only
        history = rows[1:-1]
        chunks = split_rows_for_compaction(history, 12_000)
        flat = [r for c in chunks for r in c]
        assert flat == history
        assert len(chunks) > 1

    def test_chunks_stay_within_budget(self):
        history = _rows(40)[1:-1]
        budget = 12_000
        chunks = split_rows_for_compaction(history, budget, max_chunks=99)
        for chunk in chunks:
            size = sum(len(str(r)) for r in chunk)
            # A single oversized unit is its own chunk; anything packed may
            # not exceed the budget it was packed with.
            assert size <= budget * 0.9 or len(chunk) == 1

    def test_chunk_count_is_bounded(self):
        history = _rows(400)[1:-1]
        chunks = split_rows_for_compaction(history, 8_000, max_chunks=12)
        assert len(chunks) <= 12
        assert [r for c in chunks for r in c] == history

    def test_empty_history(self):
        assert split_rows_for_compaction([], 10_000) == []


class TestMapReduceCompaction:
    def _run(self, coro):
        return asyncio.run(coro)

    def test_chunks_the_prefix_and_merges_one_summary(self):
        model = _FakeModel()
        guard = _guard(model)
        rows = _rows(40)
        res = self._run(
            guard(rows, tools=None, structured_model=object()),
        )
        assert res is not None and res.metadata
        # map calls + one reduce
        assert len(model.calls) > 2
        assert res.metadata["task_overview"].startswith("chunk")

    def test_no_row_is_compressed_without_being_read(self):
        model = _FakeModel()
        guard = _guard(model)
        rows = _rows(30)
        history = rows[1:-1]
        self._run(guard(rows, tools=None, structured_model=object()))
        seen = "\n".join(
            str(m) for call in model.calls[:-1] for m in call
        )
        missing = [
            r["content"][:20]
            for r in history
            if r["content"][:20] not in seen
        ]
        assert missing == [], f"{len(missing)} row(s) never summarized"

    def test_agent_system_prompt_is_not_paid_per_map_call(self):
        model = _FakeModel()
        guard = _guard(model)
        rows = _rows(30)
        self._run(guard(rows, tools=None, structured_model=object()))
        for call in model.calls:
            sys_rows = [m for m in call if m.get("role") == "system"]
            assert sys_rows
            assert all(len(str(m)) < 1_000 for m in sys_rows)

    def test_every_map_request_fits_the_compaction_budget(self):
        model = _FakeModel()
        guard = _guard(model)
        rows = _rows(40)
        self._run(guard(rows, tools=None, structured_model=object()))
        budget = int(
            _window().to_chars(int(60_000 * 0.7)) * 0.8,
        )
        for call in model.calls:
            total = sum(len(str(m)) for m in call)
            assert total <= budget, f"a map request of {total} > {budget}"

    def test_fits_in_one_request_is_a_single_call(self):
        model = _FakeModel()
        guard = _guard(model)
        rows = _rows(2, row_chars=200, sys_chars=500, tail_chars=200)
        self._run(guard(rows, tools=None, structured_model=object()))
        assert len(model.calls) == 1

    def test_disabled_uses_the_single_fitted_request(self):
        model = _FakeModel()
        guard = _guard(model, map_reduce=False)
        rows = _rows(40)
        self._run(guard(rows, tools=None, structured_model=object()))
        assert len(model.calls) == 1
        # The original system row is still there (nothing was chunked).
        assert any(
            m.get("role") == "system" and len(str(m)) > 10_000
            for m in model.calls[0]
        )

    def test_map_failure_falls_back_and_still_answers(self):
        model = _FakeModel(fail_map=True)
        guard = _guard(model)
        rows = _rows(40)
        res = self._run(guard(rows, tools=None, structured_model=object()))
        assert res is not None and res.metadata
        # The fallback single request carries the agent system prompt.
        assert any(
            m.get("role") == "system" and len(str(m)) > 10_000
            for m in model.calls[-1]
        )

    def test_streaming_caller_gets_an_async_iterator(self):
        model = _FakeModel(stream=True)
        guard = _guard(model)
        rows = _rows(30)

        async def run():
            res = await guard(rows, tools=None, structured_model=object())
            assert hasattr(res, "__aiter__")
            last = None
            async for chunk in res:
                last = chunk
            return last

        last = self._run(run())
        assert last is not None and last.metadata

    def test_structured_calls_are_not_chunked_without_structured_model(self):
        model = _FakeModel()
        guard = _guard(model)
        rows = _rows(40)
        self._run(guard(rows, tools=None))
        assert len(model.calls) == 1

    def test_partial_text_skips_empty_fields(self):
        resp = ChatResponse(
            content=[{"type": "text", "text": "x"}],
            metadata={"a": "keep", "b": "", "c": ["p", "q"]},
        )
        text = ContextBudgetGuard._partial_text(resp)
        assert "keep" in text and "p; q" in text
        assert "### b" not in text

    def test_guard_builder_passes_the_flag(self):
        model = _FakeModel()
        guard = build_budget_guard(
            model,
            _window(),
            map_reduce=False,
        )
        assert guard.map_reduce is False
        guard2 = build_budget_guard(model, _window())
        assert guard2.map_reduce is True

    def test_config_flag_exists_and_defaults_on(self):
        from coapis.config.config import ContextCompactConfig

        assert ContextCompactConfig().compaction_map_reduce is True
# the summary request by calling tools, and the structured ``format`` field
# was ignored.  _FakeModel above always returns valid metadata, which is
# exactly the assumption that hid the failure.  These tests drop it.

class _RecordingModel:
    """Records tools/kwargs per call; configurable structured/text answers."""

    def __init__(self, structured_calls: set[int] | None = None,
                 text: str = "散文摘要：用户要求 X，已完成 Y。"):
        self.stream = False
        self.calls: list[dict] = []
        self.structured_calls = structured_calls
        self.text = text

    async def __call__(self, messages, tools=None, **kwargs):
        self.calls.append({
            "messages": list(messages),
            "tools": tools,
            "kwargs": dict(kwargs),
        })
        idx = len(self.calls)
        want = (
            self.structured_calls is None or idx in self.structured_calls
        )
        meta = {
            "task_overview": f"merged {idx}",
            "current_state": "done",
            "important_discoveries": "d",
            "next_steps": "n",
            "context_to_preserve": "c",
        } if want else None
        return ChatResponse(
            content=[{"type": "text", "text": self.text}],
            metadata=meta,
        )


def _classify(model: _RecordingModel):
    """Split recorded calls into summarization calls vs. the real fallback.

    The single fitted request is the agent's own compaction call and carries
    the full 22K system row plus the tool catalogue — that is correct
    behaviour.  The map/reduce summarization requests are the ones that must
    be tool-free, and they are identifiable by their one-line system row.
    """
    summ, fallback = [], []
    for i, call in enumerate(model.calls, 1):
        sys_rows = [m for m in call["messages"] if str(m.get("role")) == "system"]
        big = any(len(str(m)) > 5_000 for m in sys_rows)
        (fallback if big else summ).append((i, call))
    return summ, fallback


class TestSummarizationCallsCarryNoTools:
    def test_map_and_reduce_requests_are_tool_free(self):
        model = _RecordingModel()
        guard = _guard(model)
        asyncio.run(guard(_rows(40), tools=[{"name": "execute_shell_command"}],
                          structured_model=object()))
        summ, fallback = _classify(model)
        assert summ, "expected map/reduce summarization calls"
        for i, call in summ:
            assert call["tools"] is None, f"summarization call {i} carries tools"
            for banned in ("tool_choice", "parallel_tool_calls"):
                assert banned not in call["kwargs"], (
                    f"summarization call {i} kwargs still has {banned}"
                )

    def test_only_the_real_request_may_carry_tools(self):
        model = _RecordingModel()
        guard = _guard(model)
        asyncio.run(guard(_rows(40), tools=[{"name": "execute_shell_command"}],
                          structured_model=object()))
        summ, fallback = _classify(model)
        for i, call in summ:
            assert call["tools"] is None, f"summarization call {i} carries tools"

    def test_structured_model_survives_the_strip(self):
        model = _RecordingModel()
        guard = _guard(model)
        asyncio.run(guard(_rows(40), tools=[{"name": "x"}],
                          structured_model=object()))
        summ, _ = _classify(model)
        assert summ
        assert all("structured_model" in c["kwargs"] for _, c in summ)

    def test_every_summarization_call_states_the_json_contract(self):
        # ``response_format`` is not honoured by every endpoint: measured on
        # dev, the live model answered the compaction request by echoing the
        # dialogue.  The contract has to be readable in the prompt itself.
        model = _RecordingModel()
        guard = _guard(model)
        asyncio.run(guard(_rows(40), tools=[{"name": "x"}],
                          structured_model=object()))
        summ, _ = _classify(model)
        assert summ
        for i, call in summ:
            assert any(
                "ONLY a JSON object" in str(m) for m in call["messages"]
            ), f"summarization call {i} relies on response_format alone"


class TestProseFallback:
    def test_prose_everywhere_never_raises(self):
        model = _RecordingModel(structured_calls=set())
        guard = _guard(model)
        out = asyncio.run(guard(_rows(40), tools=None,
                                structured_model=object()))
        # Nothing structured anywhere -> the guard must fall back to the
        # plain fitted request and return it, never raise.
        assert out is not None

    def test_partial_text_falls_back_to_text_content(self):
        resp = ChatResponse(
            content=[{"type": "text", "text": "纯文本摘要，没有结构化字段。"}],
            metadata=None,
        )
        text = ContextBudgetGuard._partial_text(resp)
        assert "纯文本摘要" in text

    def test_reduce_retries_once_when_metadata_missing(self):
        model = _RecordingModel(structured_calls=set())
        guard = _guard(model)
        asyncio.run(guard(_rows(40), tools=None, structured_model=object()))
        reduce_at = [
            i
            for i, call in enumerate(model.calls, 1)
            if any("分段生成的多份摘要" in str(m) for m in call["messages"])
        ]
        assert reduce_at, "reduce request not found"
        r = reduce_at[0]
        assert len(model.calls) > r, "reduce must be followed by a retry"
        retry = model.calls[r]  # 0-based: the call right after the reduce
        assert any("ONLY a JSON object" in str(m) for m in retry["messages"]), (
            "the retry must spell out the JSON contract"
        )
        assert retry["tools"] is None, "the retry must not carry tools"
        # reduce -> retry -> single fitted request (the degradation path),
        # so exactly two calls follow the reduce and no more.
        assert len(model.calls) == r + 2, (
            "exactly one retry then the fallback: "
            f"{len(model.calls)} calls, reduce at {r}"
        )

    def test_summarization_calls_never_carry_tools_when_prose(self):
        model = _RecordingModel(structured_calls=set())
        guard = _guard(model)
        asyncio.run(guard(_rows(40), tools=[{"name": "browser_use"}],
                          structured_model=object()))
        summ, fallback = _classify(model)
        assert summ
        for i, call in summ:
            assert call["tools"] is None, f"summarization call {i} carries tools"
