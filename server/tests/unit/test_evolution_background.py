# -*- coding: utf-8 -*-
"""Evolution extraction is background work (A, dev 2026-10-18).

The answer had already been delivered and persisted when the SSE stream stayed
open for ~200 more seconds.  The session-end hook was awaited inline on the
stream path: five strategies over every segment of the conversation, each an
LLM call with no timeout, and every one of them failing.  A stream that has
produced its last token must close.

Contract:
- ``schedule_session_end`` returns immediately; the round runs detached;
- one round per agent at a time, with a global cap on concurrent rounds;
- a round that hangs is cancelled at a deadline and releases its slot;
- failures stay inside the task;
- the extraction budget follows the model's real window, and every LLM call
  carries a timeout.
"""

import asyncio
import tempfile

import pytest

from coapis.agents.context.window_source import WindowInfo
from coapis.constant import EVOLUTION_EXTRACTION_SLOTS
from coapis.evolution import evolution_engine as ee
from coapis.evolution.evolution_engine import EvolutionEngine, TrajectoryEntry
from coapis.evolution.experience_extractor import (
    _EXTRACTION_MIN_SEGMENT_CHARS,
    ExperienceExtractor,
)


def _window(tokens: int = 10_000, chars_per_token: float = 3.0) -> WindowInfo:
    return WindowInfo(
        reported_tokens=tokens,
        effective_tokens=tokens,
        source="model_self_report",
        chars_per_token=chars_per_token,
    )


class _Engine(EvolutionEngine):
    """Engine whose extraction is a stub; records how often it ran."""

    def __init__(self, delay: float = 0.0, fail: bool = False, result=None):
        super().__init__(data_dir=tempfile.mkdtemp(prefix="evo-test-"))
        self._current_agent_id = "a1"
        self._current_user_id = "u1"
        self.calls = 0
        self.delay = delay
        self.fail = fail
        self.result = result if result is not None else []

    async def on_session_end(self):
        self.calls += 1
        if self.delay:
            await asyncio.sleep(self.delay)
        if self.fail:
            raise RuntimeError("extraction exploded")
        return self.result


async def _drain() -> None:
    """Let every scheduled round finish (the tasks are module-global)."""
    for _ in range(50):
        if not ee._EXTRACTION_TASKS:
            return
        await asyncio.sleep(0.02)


# ── scheduling ───────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_schedule_returns_before_the_round_finishes():
    engine = _Engine(delay=0.25)
    loop = asyncio.get_running_loop()
    started = loop.time()
    task = engine.schedule_session_end()
    elapsed = loop.time() - started
    assert task is not None
    assert elapsed < 0.05, f"scheduling blocked the caller {elapsed:.3f}s"
    assert not task.done(), "the round is still running"
    await asyncio.sleep(0.05)
    assert engine.calls == 1
    await _drain()


@pytest.mark.asyncio
async def test_one_round_per_agent_at_a_time():
    engine = _Engine(delay=0.1)
    first = engine.schedule_session_end()
    second = engine.schedule_session_end()
    third = engine.schedule_session_end()
    assert first is not None
    assert second is None and third is None, "one round per session, not per turn"
    await asyncio.sleep(0.05)
    assert engine.calls == 1
    await _drain()
    assert ee._EXTRACTION_IN_FLIGHT == 0


@pytest.mark.asyncio
async def test_global_slot_cap_is_respected():
    engines = [_Engine(delay=0.1) for _ in range(EVOLUTION_EXTRACTION_SLOTS + 2)]
    scheduled = [engine.schedule_session_end() for engine in engines]
    assert sum(1 for task in scheduled if task is not None) == (
        EVOLUTION_EXTRACTION_SLOTS
    )
    await asyncio.sleep(0.05)
    assert sum(engine.calls for engine in engines) == EVOLUTION_EXTRACTION_SLOTS
    await _drain()
    assert ee._EXTRACTION_IN_FLIGHT == 0


@pytest.mark.asyncio
async def test_round_deadline_cancels_a_hanging_extraction():
    original = ee.EVOLUTION_EXTRACT_ROUND_TIMEOUT_SECONDS
    ee.EVOLUTION_EXTRACT_ROUND_TIMEOUT_SECONDS = 0.2
    try:
        engine = _Engine(delay=30.0)
        task = engine.schedule_session_end()
        await asyncio.wait_for(task, timeout=5.0)
    finally:
        ee.EVOLUTION_EXTRACT_ROUND_TIMEOUT_SECONDS = original
    assert ee._EXTRACTION_IN_FLIGHT == 0, "the slot was released"
    assert engine._session_end_task is None or engine._session_end_task.done()


@pytest.mark.asyncio
async def test_failure_stays_inside_the_task():
    engine = _Engine(fail=True)
    task = engine.schedule_session_end()
    await asyncio.wait_for(task, timeout=5.0)  # must not raise
    assert ee._EXTRACTION_IN_FLIGHT == 0


@pytest.mark.asyncio
async def test_experience_flow_runs_after_the_round():
    """The reporting the runner used to do inline now runs inside the round."""

    class _Exp:
        content = "lesson"
        category = "lesson_learned"
        source_user = "u1"
        confidence = 0.8

    class _Cross:
        def __init__(self):
            self.reported = []

        async def report_experience(self, **kwargs):
            self.reported.append(kwargs)

    class _Flow:
        def __init__(self):
            self.flowed = []

        async def evaluate_and_flow(self, **kwargs):
            self.flowed.append(kwargs)

    engine = _Engine(result=[_Exp()])
    engine.cross_agent_evolution = _Cross()
    engine.knowledge_flow = _Flow()

    engine.schedule_session_end()
    await _drain()

    assert len(engine.cross_agent_evolution.reported) == 1
    reported = engine.cross_agent_evolution.reported[0]
    assert reported["content"] == "lesson"
    assert reported["source_user"] == "u1"
    assert reported["category"] == "lesson_learned"


@pytest.mark.asyncio
async def test_on_session_end_still_runs_inline_for_the_sync_path():
    """The awaited API is kept: a caller that wants the result can have it."""
    engine = _Engine(delay=0.0)
    assert await engine.on_session_end() == []
    assert engine.calls == 1


# ── the extraction budget ────────────────────────────────────────────


def _extractor(window) -> ExperienceExtractor:
    extractor = ExperienceExtractor(agent_core=type("C", (), {"model": "m"})())
    extractor._window = window
    extractor._window_resolved = True
    return extractor


def test_segment_limit_follows_the_model_window():
    extractor = _extractor(_window(tokens=10_000, chars_per_token=3.0))
    extractor.extract_chunk_chars = 200_000
    limit = extractor._segment_limit(template_chars=1_000)
    # 10_000 tokens * 0.5 = 5_000, minus the 2_000 token output reserve =
    # 3_000 tokens = 9_000 chars, minus the template and the envelope.
    assert limit == 9_000 - 1_000 - 400


def test_segment_limit_falls_back_to_the_configured_cap_without_a_window():
    """No window means no measurement to size by: the cap is the budget."""
    extractor = _extractor(None)
    extractor.extract_chunk_chars = 200_000
    assert extractor._segment_limit(1_000) == 200_000


def test_segment_limit_is_capped_by_the_configured_chunk():
    extractor = _extractor(_window(tokens=10_000_000, chars_per_token=4.0))
    extractor.extract_chunk_chars = 30_000
    assert extractor._segment_limit(0) == 30_000


def test_segment_limit_never_drops_below_the_floor():
    """A window smaller than the output reserve still gets a usable segment."""
    extractor = _extractor(_window(tokens=100, chars_per_token=3.0))
    extractor.extract_chunk_chars = 200_000
    assert extractor._segment_limit(1_000) == _EXTRACTION_MIN_SEGMENT_CHARS


def test_segments_never_exceed_the_limit():
    extractor = _extractor(_window(tokens=2_000, chars_per_token=3.0))
    extractor.extract_chunk_chars = 200_000
    limit = extractor._segment_limit(template_chars=500)
    conversation = "\n".join(f"line-{i}-" + "x" * 200 for i in range(60))
    segments = extractor._split_conversation(conversation, template_chars=500)
    assert len(segments) > 1
    assert all(len(seg) <= limit for seg in segments)
    assert "".join(segments).replace("\n", "") == conversation.replace("\n", "")


def test_oversized_single_line_is_sliced():
    extractor = _extractor(_window(tokens=1_000, chars_per_token=3.0))
    extractor.extract_chunk_chars = 200_000
    limit = extractor._segment_limit(template_chars=0)
    segments = extractor._split_conversation("y" * (limit * 2 + 50))
    assert len(segments) >= 2
    assert all(len(seg) <= limit for seg in segments)


def test_segments_are_capped_and_the_tail_drop_is_logged(caplog):
    """Segments are calls; a long trajectory must not mean 81 of them.

    dev 2026-10-19: a 2.5M-char trajectory became 81 parts per strategy, run
    back to back for minutes, holding the shared LLM slots against the chat.
    """
    extractor = _extractor(_window(tokens=2_000, chars_per_token=3.0))
    extractor.extract_chunk_chars = 200_000
    conversation = "\n".join(f"line-{i}-" + "x" * 200 for i in range(200))
    uncapped = extractor._split_conversation(conversation, 0)
    assert len(uncapped) > 10, len(uncapped)

    with caplog.at_level("WARNING"):
        capped = extractor._split_conversation(conversation, 0, max_segments=4)

    assert len(capped) == 4
    assert capped[0].startswith("line-0-"), "oldest first"
    assert "dropping" in caplog.text and "chars" in caplog.text


@pytest.mark.asyncio
async def test_extraction_round_stops_when_its_budget_is_spent():
    """Past the round's budget, remaining segments are skipped, not queued."""
    extractor = _extractor(_window(tokens=2_000, chars_per_token=3.0))
    extractor.extract_chunk_chars = 200_000
    extractor.extract_round_seconds = 0.0
    seen: list[int] = []

    async def _slow(prompt: str):
        seen.append(len(prompt))
        await asyncio.sleep(0.01)
        return '{"experiences": []}'

    extractor._call_llm = _slow
    trajectory = [
        TrajectoryEntry(
            user_message=f"问题 {i}",
            assistant_message="回答 " + "内容" * 100,
            tool_calls=[{"name": "read_file", "args": {"file_path": f"/f{i}"}}],
            tool_results=[{"name": "read_file", "output": "x" * 2_000}],
        )
        for i in range(200)
    ]
    out = await extractor._run_extraction(
        trajectory,
        "prompt: {}",
        "best_practice",
        "s1",
        "a1",
        "u1",
    )
    assert seen == [], "a spent budget launches nothing"
    assert out == []

    extractor.extract_round_seconds = 60.0
    await extractor._run_extraction(
        trajectory,
        "prompt: {}",
        "best_practice",
        "s1",
        "a1",
        "u1",
    )
    assert len(seen) == extractor.extract_max_segments, seen


# ── every call carries a timeout ─────────────────────────────────────


class _Core:
    """AgentCore stand-in whose endpoint never answers."""

    def __init__(self, delay: float):
        self.model = "ghost"
        self.base_url = "http://127.0.0.1:1"
        self.max_tokens = 2_000
        self.attempts = 0
        self._delay = delay

        outer = self

        class _Completions:
            async def create(_self, **kwargs):
                outer.attempts += 1
                await asyncio.sleep(delay)
                return type("R", (), {"choices": []})()

        class _Chat:
            completions = _Completions()

        class _Client:
            chat = _Chat()

        self.client = _Client()


@pytest.mark.asyncio
async def test_llm_call_is_cut_off_at_its_timeout():
    extractor = _extractor(None)
    extractor.agent_core = _Core(delay=30.0)
    extractor.llm_timeout_seconds = 0.2
    extractor.llm_retries = 0

    with pytest.raises(TimeoutError):
        await extractor._call_llm_once("analyze this")


@pytest.mark.asyncio
async def test_llm_call_retries_once_then_reports_the_failure():
    extractor = _extractor(None)
    extractor.agent_core = _Core(delay=30.0)
    extractor.llm_timeout_seconds = 0.1
    extractor.llm_retries = 2  # total attempts: one call plus one retry
    extractor.llm_backoff_seconds = 0.01

    with pytest.raises(TimeoutError):
        await extractor._call_llm("analyze this")
    assert extractor.agent_core.attempts == 2, "one call plus one retry"
