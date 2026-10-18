# -*- coding: utf-8 -*-
"""Compaction must answer, or say why it cannot.

Why this exists: on dev 2026-10-18 a chat entered ``running`` at 17:11:11 and
was still ``running`` 18 minutes 40 seconds later with **zero** log lines.
Nothing in the compaction path bounded how long one model call may take, and
nothing logged that compaction had started, so the failure was invisible:
no timeout, no progress, no reason.

The contract these tests pin:
- a model call that never answers raises ``CompactionTimeoutError`` within
  its budget, on both halves of the call (the request **and** a stream that
  stops producing chunks);
- a timed-out map chunk is skipped and the merge runs on the chunks that
  answered -- degradation, not a stalled chat;
- compaction logs that it started, per chunk, and the merge;
- the timeout is configurable and never resolves to zero/None.
"""

import asyncio
import logging
import time

import pytest
from agentscope.model._model_response import ChatResponse

from coapis.agents.context.context_budget import (
    CompactionTimeoutError,
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


def _rows(
    n_history: int,
    row_chars: int = 3_000,
    sys_chars: int = 22_000,
    tail_chars: int = 1_500,
) -> list[dict]:
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


class _StallingModel:
    """Answers instantly, except for the calls it is told to stall."""

    def __init__(
        self,
        stall_calls: tuple = (),
        stall_seconds: float = 30.0,
        stream: bool = False,
        structured: bool = True,
    ):
        self.stream = stream
        self.stall_calls = set(stall_calls)
        self.stall_seconds = stall_seconds
        self.structured = structured
        self.calls: list[list] = []

    def _response(self) -> ChatResponse:
        meta = (
            {
                "task_overview": f"chunk {len(self.calls)}",
                "key_facts": ["fact"],
                "next_steps": [],
                "empty_field": "",
            }
            if self.structured
            else None
        )
        return ChatResponse(
            content=[{"type": "text", "text": "摘要"}],
            metadata=meta,
        )

    async def __call__(self, messages, tools=None, **kwargs):
        self.calls.append(list(messages))
        if len(self.calls) in self.stall_calls:
            await asyncio.sleep(self.stall_seconds)
        resp = self._response()
        if self.stream:

            async def _gen():
                yield resp

            return _gen()
        return resp


class _StalledStreamModel:
    """Returns a stream that produces one chunk and then never again."""

    stream = True

    def __init__(self):
        self.calls: list[list] = []

    async def __call__(self, messages, tools=None, **kwargs):
        self.calls.append(list(messages))

        async def _gen():
            yield ChatResponse(
                content=[{"type": "text", "text": "半句"}],
                metadata=None,
            )
            await asyncio.sleep(600)

        return _gen()


def _guard(model, **kw) -> ContextBudgetGuard:
    return ContextBudgetGuard(
        model,
        window=_window(),
        compact_threshold_ratio=0.8,
        compaction_input_ratio=0.7,
        keep_chars_floor=2_000,
        agent_name="test:agent",
        **kw,
    )


class TestCallTimeout:
    def test_request_that_never_answers_times_out(self):
        model = _StallingModel(stall_calls={1}, stall_seconds=30)
        guard = _guard(model, compaction_timeout=0.3)
        with pytest.raises(CompactionTimeoutError):
            asyncio.run(guard._await_response(_rows(2), None, {}))

    def test_stream_that_stops_producing_chunks_times_out(self):
        """The half-measure this replaces: bounding only the call.

        Under streaming the call returns an async generator at once, so a
        stalled stream would keep the chat's critical path busy forever
        even with a timeout on the call itself.
        """
        guard = _guard(_StalledStreamModel(), compaction_timeout=0.5)
        started = time.monotonic()
        with pytest.raises(CompactionTimeoutError):
            asyncio.run(guard._await_response(_rows(2), None, {}))
        assert time.monotonic() - started < 5

    def test_healthy_call_is_untouched(self):
        model = _StallingModel()
        guard = _guard(model, compaction_timeout=5)
        res = asyncio.run(guard._await_response(_rows(2), None, {}))
        assert res is not None


class TestDegradation:
    def test_timed_out_map_chunk_is_skipped_not_fatal(self):
        """One silent chunk must not cost the user the whole turn."""
        model = _StallingModel(stall_calls={2}, stall_seconds=30)
        guard = _guard(model, compaction_timeout=0.4)
        res = asyncio.run(
            guard(_rows(40), tools=None, structured_model=object()),
        )
        assert res is not None and res.metadata
        # The stalled chunk was skipped, the rest still merged.
        assert len(model.calls) >= 3

    def test_every_chunk_stalling_falls_back_to_single_request(self):
        model = _StallingModel(stall_calls={1, 2, 3, 4, 5}, stall_seconds=30)
        guard = _guard(model, compaction_timeout=0.3)
        res = asyncio.run(
            guard(_rows(40), tools=None, structured_model=object()),
        )
        # map-reduce gave up; the caller's original single request answered.
        assert res is not None


class TestTimeoutResolution:
    def test_zero_and_none_resolve_to_the_env_default(self):
        default = ContextBudgetGuard._resolve_compaction_timeout(None)
        assert default > 0
        assert ContextBudgetGuard._resolve_compaction_timeout(0) == default
        assert ContextBudgetGuard._resolve_compaction_timeout("nope") == default

    def test_explicit_value_wins(self):
        assert ContextBudgetGuard._resolve_compaction_timeout(7) == 7.0

    def test_guard_exposes_the_resolved_budget(self):
        guard = _guard(_StallingModel())
        assert guard.compaction_timeout > 0


class TestObservability:
    def test_compaction_logs_start_chunks_and_merge(self, caplog):
        model = _StallingModel()
        guard = _guard(model, compaction_timeout=5)
        with caplog.at_level(logging.INFO, logger="coapis"):
            asyncio.run(guard(_rows(40), tools=None, structured_model=object()))
        text = "\n".join(r.getMessage() for r in caplog.records)
        assert "Compaction start" in text
        assert "Compaction map chunk 1/" in text
        assert "Compaction merged" in text

    def test_timeout_is_named_in_the_degradation_log(self, caplog):
        model = _StallingModel(stall_calls={2}, stall_seconds=30)
        guard = _guard(model, compaction_timeout=0.3)
        with caplog.at_level(logging.WARNING, logger="coapis"):
            asyncio.run(guard(_rows(40), tools=None, structured_model=object()))
        text = "\n".join(r.getMessage() for r in caplog.records)
        assert "Compaction map chunk" in text
        assert "failed after" in text


class TestChunkSizeAndConcurrency:
    """Chunks sized to the window are chunks the model cannot answer.

    Dev 2026-10-18: 85K-char chunks, ~90 s each, five in series -- a 305-row
    compaction cost the user a seven-minute turn.  The cap and the
    concurrency are the two knobs that make compaction cheap.
    """

    def test_map_requests_stay_under_the_char_cap(self):
        model = _StallingModel()
        guard = _guard(model, compaction_timeout=30, map_chunk_max_chars=8_000)
        asyncio.run(guard(_rows(60), tools=None, structured_model=object()))
        map_calls = model.calls[:-1]
        assert len(map_calls) > 2, "expected the cap to produce more chunks"
        sizes = sorted(
            sum(len(str(m)) for m in call) for call in map_calls
        )
        # The cap bounds the history carried; the mini system prompt, the
        # tail row and the JSON contract row ride on top of it.  The splitter
        # merges a runt tail chunk with its neighbour(s), so the final chunk
        # may be a multiple of the cap -- bounded, not widened without limit.
        over = [s for s in sizes if s > 8_000 + 4_000]
        assert len(over) <= 1, sizes
        assert not over or over[0] <= 3 * (8_000 + 4_000), sizes

    def test_chunks_go_in_flight_together(self):
        class _SlowModel(_StallingModel):
            async def __call__(self, messages, tools=None, **kwargs):
                self.calls.append(list(messages))
                await asyncio.sleep(0.4)
                return self._response()

        model = _SlowModel()
        guard = _guard(
            model,
            compaction_timeout=30,
            map_chunk_max_chars=6_000,
            map_concurrency=4,
        )
        started = time.monotonic()
        asyncio.run(guard(_rows(60), tools=None, structured_model=object()))
        elapsed = time.monotonic() - started
        chunks = len(model.calls) - 1
        assert chunks >= 4
        # Serial would be chunks x 0.4 s; concurrent must beat that clearly.
        assert elapsed < chunks * 0.4, (chunks, elapsed)

    def test_knobs_never_resolve_to_zero(self):
        assert ContextBudgetGuard._resolve_positive(0, "CONTEXT_COMPACTION_CHUNK_MAX_CHARS", 16_000) > 0
        assert ContextBudgetGuard._resolve_positive(None, "CONTEXT_COMPACTION_MAP_CONCURRENCY", 3) > 0
        assert ContextBudgetGuard._resolve_positive(5, "CONTEXT_COMPACTION_MAP_CONCURRENCY", 3) == 5


class TestProviderClientTimeout:
    def test_model_clients_get_an_explicit_timeout_and_no_sdk_retries(self):
        from coapis.providers.provider import Provider

        kwargs = Provider.client_timeout_kwargs()
        assert kwargs["max_retries"] == 0
        timeout = kwargs["timeout"]
        assert timeout.read is not None and 0 < timeout.read <= 900

    def test_timeout_follows_the_env_knob(self, monkeypatch):
        import importlib

        import coapis.constant as constant

        monkeypatch.setenv("COAPIS_LLM_REQUEST_TIMEOUT_SECONDS", "42")
        importlib.reload(constant)
        try:
            from coapis.providers.provider import Provider

            assert Provider.client_timeout_kwargs()["timeout"].read == 42.0
        finally:
            monkeypatch.delenv("COAPIS_LLM_REQUEST_TIMEOUT_SECONDS", raising=False)
            importlib.reload(constant)
