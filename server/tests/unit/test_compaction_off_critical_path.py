# -*- coding: utf-8 -*-
"""Compaction must not live on the user's turn.

Measured on dev 2026-10-18 (chat ``12f1111f``): a 285-row history split into
19 chunks of 14,233 chars, the chat stayed ``running`` for **18 min 40 s**
producing zero log lines, and the provider answered the oversized requests
with ``Context size has been exceeded`` -- a refusal with no number in it, so
the window the provider *fabricated* (102,400) kept defining every budget.

Three contracts, one per fix:

* **Refusal feedback (C)**: a numberless refusal is still information.  With
  our own measurement of the prompt that got refused, it caps the window, it
  ratchets down on repeats, and it expires -- a fact about the server as it
  was that minute must not define the budget forever.
* **Global deadline (A)**: per-call timeouts bound one request; the whole
  compaction needs one deadline shared by every chunk and the merge.  Past it,
  the chunks that answered are merged and the rest are dropped.
* **Off the critical path (D)**: the reasoning loop marks compaction due; the
  runner runs it after the reply is delivered, with a single global slot, one
  compaction per chat, and a persist that refuses to write stale memory.
"""

import asyncio
import time

import pytest
from agentscope.model._model_response import ChatResponse

from coapis.agents.context import window_source as ws
from coapis.agents.context.context_budget import (
    CompactionTimeoutError,
    ContextBudgetGuard,
)
from coapis.agents.react_agent import (
    CoApisAgent,
    compaction_budget_seconds,
    schedule_background_compaction,
)


@pytest.fixture(autouse=True)
def _clean_feedback():
    ws._FEEDBACK.clear()
    yield
    ws._FEEDBACK.clear()


# ── C: numberless refusals ────────────────────────────────────────────


def test_numberless_refusal_caps_window_from_our_measurement():
    """"Context size has been exceeded" must still lower the window."""
    entry = ws.record_window_feedback(
        "a3",
        "a31-jh25",
        "This model's maximum context length is not enough: Context size "
        "has been exceeded",
        measured_chars=90_000,
        chars_per_token=3.0,
    )
    assert entry is not None
    assert entry["inferred"] is True
    # 90,000 chars / 3.0 chars-per-token = 30,000 tokens, refused *at least*
    # at that size, so the cap sits below it.
    assert entry["window_tokens"] == 27_000
    assert ws.window_feedback("a3", "a31-jh25") is entry


def test_unrelated_error_records_nothing():
    """A 400 with no context wording and no number teaches us nothing."""
    assert (
        ws.record_window_feedback(
            "p",
            "m",
            "Internal server error while processing",
            measured_chars=90_000,
            chars_per_token=3.0,
        )
        is None
    )
    assert ws.window_feedback("p", "m") is None


def test_repeated_numberless_refusals_only_shrink():
    ws.record_window_feedback(
        "a3",
        "m",
        "Context size has been exceeded",
        measured_chars=90_000,
        chars_per_token=3.0,
    )
    first = ws.window_feedback("a3", "m")["window_tokens"]
    # The next refused prompt is *smaller* and still refused: the cap must
    # follow the evidence down, never up.
    ws.record_window_feedback(
        "a3",
        "m",
        "Context size has been exceeded",
        measured_chars=60_000,
        chars_per_token=3.0,
    )
    second = ws.window_feedback("a3", "m")["window_tokens"]
    assert second < first
    # 60,000 chars / 3.0 = 20,000 tokens refused, capped at 90% => 18,000,
    # which is already below the previous 27,000 cap.
    assert second == 18_000


def test_stated_window_is_not_marked_inferred():
    entry = ws.record_window_feedback(
        "p",
        "m",
        "This model's maximum context length is 32768 tokens. Please reduce "
        "the length of the prompt (34000).",
        measured_chars=70_000,
        chars_per_token=3.0,
    )
    assert entry["inferred"] is False
    assert entry["window_tokens"] == 32_768
    assert entry["observed_chars_per_token"] == round(70_000 / 34_000, 3)


def test_feedback_expires_and_is_dropped(monkeypatch):
    monkeypatch.setattr(ws, "_FEEDBACK_TTL_SECONDS", 0.0)
    ws.record_window_feedback(
        "a3",
        "m",
        "Context size has been exceeded",
        measured_chars=90_000,
        chars_per_token=3.0,
    )
    assert ws.window_feedback("a3", "m") is None
    # Expired means gone, not recomputed on every call.
    assert ("a3", "m") not in ws._FEEDBACK


def test_resolve_for_model_applies_the_cap():
    """The cap is consumed by the window resolution, not just recorded."""
    ws.record_window_feedback(
        "a3",
        "m",
        "Context size has been exceeded",
        measured_chars=90_000,
        chars_per_token=3.0,
    )

    class _Model:
        model_key = "a3/m"

    class _Run:
        max_input_length = 1_000_000

    info = ws.resolve_for_model(
        _Model(),
        _Run(),
        safety_factor=0.7,
        chars_per_token=3.0,
    )
    # The refusal outranks the provider's fabricated 1,000,000: the reported
    # window becomes the measured cap, and the budget is built from it.
    assert info.reported_tokens == 27_000
    assert info.effective_tokens == 18_900


# ── A: one deadline for the whole compaction ──────────────────────────


def _window(tokens=60_000, chars_per_token=1.1):
    return ws.WindowInfo(
        reported_tokens=tokens,
        effective_tokens=tokens,
        source="model_self_report",
        chars_per_token=chars_per_token,
    )


def _rows(n_history, row_chars=3_000, sys_chars=1_000, tail_chars=200):
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


class _SlowModel:
    """Answers, with a per-role delay; the merge call is identifiable."""

    def __init__(self, map_seconds=0.0, merge_seconds=0.0, structured=True):
        self.stream = False
        self.map_seconds = map_seconds
        self.merge_seconds = merge_seconds
        self.structured = structured
        self.map_calls = 0
        self.merge_calls = 0

    def _response(self, tag):
        meta = (
            {
                "task_overview": f"{tag} facts",
                "current_state": f"{tag} state",
                "solution": f"{tag} plan",
                "workline": f"{tag} workline",
                "file_system": f"{tag} files",
            }
            if self.structured
            else None
        )
        return ChatResponse(content=[{"type": "text", "text": f"{tag} text"}], metadata=meta)

    async def __call__(self, messages, tools=None, **kwargs):
        # The merge request is the one whose payload is the partial summaries
        # themselves; map requests carry history rows there.
        payload = str(messages[1].get("content")) if len(messages) > 1 else ""
        if payload.startswith("[部分") or "合并为" in payload:
            self.merge_calls += 1
            if self.merge_seconds:
                await asyncio.sleep(self.merge_seconds)
            return self._response("merge")
        self.map_calls += 1
        if self.map_seconds:
            await asyncio.sleep(self.map_seconds)
        return self._response(f"map{self.map_calls}")


def _guard(model, global_timeout, chunk_chars=4_000, concurrency=1):
    return ContextBudgetGuard(
        model,
        window=_window(),
        compaction_input_ratio=0.7,
        map_reduce=True,
        map_chunk_max_chars=chunk_chars,
        map_concurrency=concurrency,
        compaction_global_timeout=global_timeout,
    )


@pytest.mark.asyncio
async def test_global_deadline_stops_the_compaction_from_running_forever():
    """Chunks that cannot fit inside the remaining budget are skipped."""
    model = _SlowModel(map_seconds=6.0)
    # Concurrency 1: chunk 1 answers at 6s, chunk 2 at 12s, chunk 3 starts
    # with 8s left (below the 10s minimum) and is skipped.  12 chunks exist;
    # the compaction ends at ~12s instead of ~72s.
    guard = _guard(model, global_timeout=20)
    started = time.monotonic()
    res = await guard._compact_map_reduce(
        _rows(12),
        None,
        {"structured_model": object()},
    )
    elapsed = time.monotonic() - started
    assert res is not None  # a summary, not a stalled chat
    assert model.map_calls == 2
    assert elapsed < 20 + 5


@pytest.mark.asyncio
async def test_merge_runs_when_the_deadline_has_time_left():
    """The deadline skips work; it does not disable the merge by default."""
    model = _SlowModel(map_seconds=0.5)
    guard = _guard(model, global_timeout=60)
    res = await guard._compact_map_reduce(
        _rows(12),
        None,
        {"structured_model": object()},
    )
    assert res is not None
    assert model.merge_calls == 1
    assert "merge" in " ".join(str(v) for v in res.metadata.values())


@pytest.mark.asyncio
async def test_merge_skipped_concatenates_the_partials_that_answered():
    """Out of time for the merge is not a reason to drop the history."""
    model = _SlowModel(map_seconds=6.0)
    # Concurrency 1: chunk 1 answers at 6s, chunk 2 at 12s, chunk 3 starts with
    # 7s left (below the minimum) and is skipped.  The merge then has 7s left,
    # also below the minimum, so it is skipped and the partials are concatenated.
    guard = _guard(model, global_timeout=25)
    started = time.monotonic()
    res = await guard._compact_map_reduce(
        _rows(12),
        None,
        {"structured_model": object()},
    )
    elapsed = time.monotonic() - started
    assert res is not None
    assert model.merge_calls == 0
    joined = " ".join(str(v) for v in res.metadata.values())
    assert "map1" in joined and "map2" in joined
    assert elapsed < 25 + 5


@pytest.mark.asyncio
async def test_per_call_budget_shrinks_to_the_time_left():
    """The last chunk cannot spend a full per-call budget after the deadline."""
    model = _SlowModel(map_seconds=30.0)
    guard = _guard(model, global_timeout=15)
    guard.compaction_timeout = 90.0
    started = time.monotonic()
    await guard._compact_map_reduce(_rows(6), None, {"structured_model": object()})
    # The chunk timed out on the *remaining* budget, not on 90 s.
    assert time.monotonic() - started < 25


@pytest.mark.asyncio
async def test_await_response_timeout_argument_overrides_the_default():
    class _Never:
        stream = False

        async def __call__(self, messages, tools=None, **kwargs):
            await asyncio.sleep(30)

    guard = _guard(_Never(), global_timeout=180)
    guard.compaction_timeout = 90.0
    with pytest.raises(CompactionTimeoutError) as exc:
        await guard._await_response(
            [{"role": "user", "content": "x"}],
            None,
            {},
            timeout=0.5,
        )
    assert "0s" in str(exc.value) or "1s" in str(exc.value)


def test_global_timeout_never_resolves_to_zero():
    guard = _guard(object(), global_timeout=0)
    assert guard.compaction_global_timeout > 0
    guard = _guard(object(), global_timeout=None)
    assert guard.compaction_global_timeout == 180


# ── D: compaction off the user's turn ─────────────────────────────────


@pytest.mark.asyncio
async def test_loop_call_defers_and_only_marks_due(monkeypatch):
    """The reasoning loop must not pay for compaction."""
    calls = []

    async def _upstream(self):
        calls.append(self)

    from agentscope.agent import ReActAgent

    monkeypatch.setattr(
        ReActAgent,
        "_compress_memory_if_needed",
        _upstream,
    )

    class _Stub:
        _compaction_due = False

    stub = _Stub()
    await CoApisAgent._compress_memory_if_needed(stub)
    assert stub._compaction_due is True
    assert calls == []  # nothing ran on the user's turn


class _AgentStub:
    def __init__(self, due=True):
        self.name = "stub"
        self._compaction_due = due
        self._compaction_task = None


@pytest.mark.asyncio
async def test_background_run_compacts_persists_and_frees_the_slot(
    monkeypatch,
):
    from agentscope.agent import ReActAgent

    ran = []
    persisted = []

    async def _upstream(self):
        ran.append(time.monotonic())
        await asyncio.sleep(0.01)

    monkeypatch.setattr(ReActAgent, "_compress_memory_if_needed", _upstream)
    monkeypatch.setattr(
        "coapis.agents.react_agent.compaction_budget_seconds",
        lambda agent: 30.0,
    )

    async def _persist():
        persisted.append(True)

    agent = _AgentStub()
    task = schedule_background_compaction(agent, _persist)
    assert task is not None
    await task
    assert len(ran) == 1
    assert persisted == [True]
    assert agent._compaction_due is False
    import coapis.agents.react_agent as ra

    assert ra._COMPACTION_IN_FLIGHT == 0


@pytest.mark.asyncio
async def test_single_slot_defers_and_keeps_the_flag_for_next_turn(monkeypatch):
    import coapis.agents.react_agent as ra
    from agentscope.agent import ReActAgent

    async def _upstream(self):
        return None

    monkeypatch.setattr(ReActAgent, "_compress_memory_if_needed", _upstream)
    monkeypatch.setattr(ra, "_COMPACTION_IN_FLIGHT", 1)
    agent = _AgentStub()
    assert schedule_background_compaction(agent, None) is None
    # The compaction is not lost: the next turn runs it.
    assert agent._compaction_due is True


@pytest.mark.asyncio
async def test_one_compaction_per_agent_at_a_time(monkeypatch):
    from agentscope.agent import ReActAgent

    async def _upstream(self):
        await asyncio.sleep(0.05)

    monkeypatch.setattr(ReActAgent, "_compress_memory_if_needed", _upstream)
    agent = _AgentStub()
    task = schedule_background_compaction(agent, None)
    assert task is not None
    assert schedule_background_compaction(agent, None) is None
    await task


@pytest.mark.asyncio
async def test_timeout_keeps_compaction_due_for_the_next_turn(monkeypatch):
    import coapis.agents.react_agent as ra
    from agentscope.agent import ReActAgent

    async def _stall(self):
        await asyncio.sleep(5)

    monkeypatch.setattr(ReActAgent, "_compress_memory_if_needed", _stall)
    monkeypatch.setattr(
        ra,
        "compaction_budget_seconds",
        lambda agent: 0.2,
    )
    agent = _AgentStub()
    task = schedule_background_compaction(agent, None)
    await task
    assert agent._compaction_due is True
    assert ra._COMPACTION_IN_FLIGHT == 0


def test_budget_seconds_come_from_config_and_stay_above_the_gate_deadline():
    from types import SimpleNamespace

    cfg = SimpleNamespace(
        running=SimpleNamespace(
            light_context_config=SimpleNamespace(
                context_compact_config=SimpleNamespace(
                    compaction_global_timeout_seconds=180.0,
                ),
            ),
        ),
    )
    # The gate enforces its own deadline inside the compaction; this outer
    # ceiling is the last resort, so it sits above the gate's, not below.
    assert compaction_budget_seconds(cfg) == 210.0
    assert compaction_budget_seconds(object()) == 210.0


def test_factory_forwards_every_guard_parameter():
    """The factory must accept everything the guard accepts.

    The agent builds the gate only through ``build_budget_guard``.  A keyword
    the guard accepts and the factory does not is not a degraded feature -- it
    is a ``TypeError`` on the first chat of the process, and no unit test that
    constructs the guard directly can ever see it.  Measured on dev 2026-10-18:
    ``compaction_global_timeout`` made every request fail with MODEL_TIMEOUT
    before a single token was produced.
    """
    import inspect

    from coapis.agents.context.context_budget import (
        ContextBudgetGuard,
        build_budget_guard,
    )

    guard_kw = {
        name
        for name, param in inspect.signature(
            ContextBudgetGuard.__init__,
        ).parameters.items()
        if param.kind is inspect.Parameter.KEYWORD_ONLY and name != "window"
    }
    factory_kw = {
        name
        for name, param in inspect.signature(
            build_budget_guard,
        ).parameters.items()
        if param.kind is inspect.Parameter.KEYWORD_ONLY
    }
    assert guard_kw - factory_kw == set()

    # And forwarding is real, not just a matching signature.
    guard = build_budget_guard(
        _SlowModel(map_seconds=0.01),
        _window(tokens=60_000),
        compaction_timeout=31.0,
        compaction_global_timeout=131.0,
        map_chunk_max_chars=5_000,
        map_concurrency=2,
    )
    assert guard.compaction_timeout == 31.0
    assert guard.compaction_global_timeout == 131.0
    assert guard.map_chunk_max_chars == 5_000
    assert guard.map_concurrency == 2
