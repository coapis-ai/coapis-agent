# -*- coding: utf-8 -*-
"""Experience extractor budget tests.

Why: the extractor talks to the provider with a raw client, so the context
gate never saw its prompt.  A long session (tool results included) went out
whole and the provider answered ``500 - Context size has been exceeded``:
**849 extraction failures in one month** on dev, last seen 2026-10-17 14:42.
Evolution was silently running on the heuristic fallback, i.e. learning
nothing.

Contract:
- the conversation is cut into budget-sized segments, each request fits;
- every segment is extracted, so a long session is not worth less than the
  provider's window;
- transient refusals (429/500/timeout) are retried with backoff;
- a segment that still fails is skipped, the rest survive.
"""

import asyncio
import json
from types import SimpleNamespace

import pytest

from coapis.evolution.evolution_engine import TrajectoryEntry
from coapis.evolution.experience_extractor import ExperienceExtractor

HARD_WINDOW = 30_000  # chars the fake provider refuses above


def _core(provider):
    completions = SimpleNamespace(create=provider)
    chat = SimpleNamespace(completions=completions)
    client = SimpleNamespace(chat=chat)
    return SimpleNamespace(
        client=client,
        model="test-model",
        max_tokens=2000,
    )


def _resp(text: str):
    message = SimpleNamespace(content=text)
    return SimpleNamespace(choices=[SimpleNamespace(message=message)])


def _provider_ok(record: list, summary_tag: str):
    async def create(model=None, messages=None, max_tokens=None, **kw):
        total = sum(len(str(m)) for m in messages)
        record.append(total)
        if total > HARD_WINDOW:
            raise RuntimeError(
                "Error code: 500 - {'error': {'message': 'Context size has "
                "been exceeded.'}}",
            )
        payload = [
            {
                "title": f"{summary_tag}-{len(record)}",
                "content": "content",
                "confidence": 0.9,
            },
        ]
        return _resp(json.dumps(payload))

    return create


def _trajectory(n: int, chars: int) -> list:
    out = []
    for i in range(n):
        out.append(
            TrajectoryEntry(
                user_message=f"u{i} " + "u" * chars,
                assistant_message=f"a{i} " + "a" * chars,
                tool_calls=[{"name": "execute_shell_command"}],
            ),
        )
    return out


def _extractor(provider, **kw) -> ExperienceExtractor:
    return ExperienceExtractor(
        agent_core=_core(provider),
        llm_backoff_seconds=0.0,
        **kw,
    )


class TestConversationSplit:
    def test_short_conversation_is_one_segment(self):
        ex = _extractor(None)
        text = "a" * 1000
        assert ex._split_conversation(text) == [text]

    def test_segments_fit_and_cover_everything(self):
        ex = _extractor(None, extract_chunk_chars=8_000)
        text = "\n".join(f"line {i}: " + "x" * 300 for i in range(200))
        segments = ex._split_conversation(text)
        assert len(segments) > 1
        assert all(len(s) <= 8_000 for s in segments)
        assert "\n".join(segments) == text

    def test_single_oversized_line_is_sliced(self):
        ex = _extractor(None, extract_chunk_chars=5_000)
        text = "y" * 12_000
        segments = ex._split_conversation(text)
        assert all(len(s) <= 5_000 for s in segments)
        assert "".join(segments) == text

    def test_chunk_floor_is_enforced(self):
        ex = _extractor(None, extract_chunk_chars=10)
        assert ex.extract_chunk_chars == 4_000


class TestSegmentedExtraction:
    def test_long_session_is_extracted_in_segments(self):
        calls: list[int] = []
        ex = _extractor(_provider_ok(calls, "seg"), extract_chunk_chars=8_000)
        traj = _trajectory(40, 400)  # ~35K chars of conversation
        result = asyncio.run(
            ex._run_extraction(
                trajectory=traj,
                prompt_template="Extract lessons as JSON array.",
                exp_type="lesson",
                session_id="s1",
                agent_id="a1",
                user_id="u1",
            ),
        )
        assert len(calls) > 1, "the conversation should have been segmented"
        assert all(total <= HARD_WINDOW for total in calls), calls
        assert len(result) >= len(calls)

    def test_oversized_single_request_never_reaches_the_provider(self):
        # Without segmentation this is exactly the 849-failure shape.
        calls: list[int] = []
        ex = _extractor(_provider_ok(calls, "seg"), extract_chunk_chars=8_000)
        traj = _trajectory(120, 500)
        asyncio.run(
            ex._run_extraction(
                trajectory=traj,
                prompt_template="Extract lessons as JSON array.",
                exp_type="pattern",
                session_id="s2",
                agent_id="a1",
                user_id="u1",
            ),
        )
        assert calls and max(calls) <= HARD_WINDOW

    def test_transient_failure_is_retried(self):
        state = {"n": 0}

        async def create(model=None, messages=None, max_tokens=None, **kw):
            state["n"] += 1
            if state["n"] < 3:
                raise RuntimeError("Error code: 429 - rate limit")
            return _resp(json.dumps([{"title": "t", "content": "c", "confidence": 0.9}]))

        ex = _extractor(create, llm_retries=3)
        result = asyncio.run(
            ex._run_extraction(
                trajectory=_trajectory(2, 50),
                prompt_template="p",
                exp_type="preference",
                session_id="s3",
                agent_id="a1",
                user_id="u1",
            ),
        )
        assert state["n"] == 3
        assert len(result) == 1

    def test_persistent_failure_falls_back_to_heuristic(self):
        async def create(model=None, messages=None, max_tokens=None, **kw):
            raise RuntimeError("provider is down")

        ex = _extractor(create, llm_retries=2)
        result = asyncio.run(
            ex._run_extraction(
                trajectory=_trajectory(2, 50),
                prompt_template="p",
                exp_type="lesson",
                session_id="s4",
                agent_id="a1",
                user_id="u1",
            ),
        )
        assert isinstance(result, list)  # heuristic path, never raises

    def test_one_failed_segment_does_not_kill_the_rest(self):
        state = {"n": 0}

        async def create(model=None, messages=None, max_tokens=None, **kw):
            state["n"] += 1
            if state["n"] == 2:
                raise RuntimeError("Error code: 500 - Context size exceeded")
            return _resp(json.dumps([{"title": f"t{state['n']}", "content": "c", "confidence": 0.9}]))

        ex = _extractor(create, extract_chunk_chars=6_000, llm_retries=1)
        result = asyncio.run(
            ex._run_extraction(
                trajectory=_trajectory(40, 400),
                prompt_template="p",
                exp_type="skill_effectiveness",
                session_id="s5",
                agent_id="a1",
                user_id="u1",
            ),
        )
        assert state["n"] >= 3
        assert len(result) >= 2

    def test_retry_defaults_are_sane(self):
        ex = ExperienceExtractor(agent_core=_core(None))
        assert ex.llm_retries == 3
        assert ex.llm_backoff_seconds == 2.0
        assert ex.extract_chunk_chars == 24_000
