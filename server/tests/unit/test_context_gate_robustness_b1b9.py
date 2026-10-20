# -*- coding: utf-8 -*-
"""B1-B9: the context/tool/skill gate must never kill a user's turn.

Source: tech_docs/上下文工具技能压缩机制深度体检_20261019.md.  Every number in
the docstrings below is a measurement from prod/dev 2026-10-18/19, not a
hypothetical.
"""

import asyncio
import time
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

from coapis.agents.context.context_budget import (
    MIN_KEEP_CHARS,
    CompactionTimeoutError,
    ContextBudgetGuard,
    ContextOverflowError,
)
from coapis.agents.context.window_source import (
    MIN_USABLE_WINDOW_TOKENS,
    check_model_window,
    min_usable_window_tokens,
    window_usability,
)


def _window(tokens: int, cpt: float = 2.0):
    from coapis.agents.context.window_source import WindowInfo

    return WindowInfo(
        reported_tokens=tokens,
        effective_tokens=tokens,
        source="test",
        chars_per_token=cpt,
    )


def _sys(text: str) -> dict:
    return {"role": "system", "content": text}


def _row(role: str, text: str) -> dict:
    return {"role": role, "content": text}


# ── B1 L1: selection-time window gate ──────────────────────────────
class TestSelectionWindowGate:
    def test_threshold_is_the_measured_fixed_floor(self):
        assert min_usable_window_tokens() >= MIN_USABLE_WINDOW_TOKENS

    def test_small_window_is_refused_with_a_number_and_a_cure(self):
        verdict = window_usability(8192)
        assert verdict["usable"] is False
        assert "8192" in verdict["reason"]
        assert str(verdict["threshold"]) in verdict["reason"]
        # The user must be told what to do, not only that it failed.
        assert "context window" in verdict["reason"]

    def test_adequate_window_passes(self):
        assert window_usability(128000)["usable"] is True

    def test_unknown_window_is_not_a_refusal(self):
        """Failing to read metadata must not be used to reject a model."""
        verdict = window_usability(None)
        assert verdict["usable"] is True
        assert verdict["reason"] == "unknown"

    def test_check_model_window_uses_declared_metadata_only(self):
        provider = MagicMock()
        provider.max_input_tokens = 4096
        provider.model_info = {}
        provider.models = []
        provider.get_context_window = MagicMock(return_value=None)
        verdict = check_model_window("p1", "small-model", provider)
        assert verdict["usable"] is False
        assert verdict["effective_tokens"] == 4096

    def test_check_model_window_tolerates_a_dead_provider(self):
        assert check_model_window("p1", "m", None)["usable"] is True


# ── B1 L2/L3: degraded answers ─────────────────────────────────────
class TestDegradedAnswer:
    @pytest.mark.asyncio
    async def test_degrade_mode_is_recorded_and_visible(self):
        guard = ContextBudgetGuard(
            AsyncMock(),
            window=_window(600),
            compact_threshold_ratio=0.8,
            agent_name="small",
        )
        messages = [_sys("s" * 3000), _row("user", "hi")]
        snapshot = await guard.enforce(messages, "t" * 6000)
        assert guard.degrade_mode is not None
        assert len(guard.degrade_events) == 1
        assert guard.degrade_events[0]["agent"] == "small"
        assert snapshot.total_chars <= snapshot.budget_chars

    @pytest.mark.asyncio
    async def test_degrade_mode_resets_between_calls(self):
        guard = ContextBudgetGuard(
            AsyncMock(),
            window=_window(20000),
            compact_threshold_ratio=0.8,
            agent_name="ok",
        )
        messages = [_sys("s" * 100), _row("user", "hi")]
        await guard.enforce(messages, "t" * 100)
        assert guard.degrade_mode is None

    @pytest.mark.asyncio
    async def test_call_sheds_the_tool_catalogue_when_degraded(self):
        """The measurement said 'without tools'; the request must match it."""
        inner = AsyncMock()
        inner.return_value = MagicMock()
        guard = ContextBudgetGuard(
            inner,
            window=_window(600),
            compact_threshold_ratio=0.8,
            agent_name="small",
        )
        messages = [_sys("s" * 3000), _row("user", "hi")]

        async def _drive():
            # ``__call__`` is a coroutine function in both modes; under
            # ``stream=True`` it resolves to the async generator the caller
            # iterates, so the await comes first.
            result = await guard(messages, "t" * 6000)
            if guard.stream:
                result = await result.__anext__()
            return result

        await _drive()
        assert guard.degrade_mode is not None
        assert inner.await_args.kwargs["tools"] is None


# ── B2: compaction timeout is a degradation, not a death ───────────
class TestCompactionTimeout:
    @pytest.mark.asyncio
    async def test_map_reduce_timeout_falls_back_to_single_request(self):
        """A timed-out cure must not be the reason the turn dies."""
        guard = ContextBudgetGuard(
            AsyncMock(),
            window=_window(20000),
            agent_name="c",
        )
        messages = [_sys("s"), _row("user", "u")]

        async def _boom(*_a, **_kw):
            raise CompactionTimeoutError("boom")

        guard._compact_map_reduce = _boom
        guard.fit_prompt_to_budget = lambda msgs, kw: msgs
        guard._inner = AsyncMock()
        guard._inner.return_value = MagicMock()
        guard._no_tool_kwargs = lambda kw: kw

        await guard(messages, None, structured_model=object())
        guard._inner.assert_awaited()

    def test_runner_treats_compaction_timeout_as_overflow(self):
        """The remediation branch must recognise the timeout family."""
        import inspect
        import re

        from coapis.app.runner import runner as runner_mod

        src = inspect.getsource(runner_mod)
        assert "CompactionTimeoutError" in src
        assert re.search(
            r"isinstance\(\s*e,\s*\(\s*ContextOverflowError,\s*CompactionTimeoutError",
            src,
        ), "compaction timeout must join ContextOverflowError in remediation"


# ── B3: wall-clock bound ───────────────────────────────────────────
class TestGateWallClock:
    def test_clock_bounds_the_pass(self):
        guard = ContextBudgetGuard(
            AsyncMock(),
            window=_window(20000),
            agent_name="w",
        )
        guard.gate_wall_clock = 0.01
        guard.start_gate_clock()
        time.sleep(0.02)
        assert guard.gate_expired() is True

    def test_clock_is_generous_before_it_runs(self):
        guard = ContextBudgetGuard(
            AsyncMock(),
            window=_window(20000),
            agent_name="w",
        )
        assert guard.gate_time_left() > 0
        assert guard.gate_expired() is False

    def test_clock_is_configurable(self):
        guard = ContextBudgetGuard(
            AsyncMock(),
            window=_window(20000),
            agent_name="w",
        )
        assert guard.gate_wall_clock >= 15.0


# ── B4: keep-floor follows the history budget ─────────────────────
class TestKeepFloor:
    def test_floor_shrinks_when_fixed_overhead_eats_the_window(self):
        guard = ContextBudgetGuard(
            AsyncMock(),
            window=_window(11800),
            keep_chars_floor=40000,
            agent_name="f",
        )
        snapshot = guard.measure(
            [_sys("s" * 20000), _row("user", "hi")],
            "t" * 20000,
        )
        floor = guard.keep_floor(snapshot)
        history_budget = snapshot.budget_chars - snapshot.fixed_chars
        # The window cannot pay the configured floor at all, so the promise
        # shrinks to the hard minimum -- the last exchange.  The old floor
        # (40000 chars on an 11800-token window) made *every* call overflow.
        if history_budget <= 0:
            assert floor == MIN_KEEP_CHARS
        else:
            assert floor <= int(history_budget * guard.keep_floor_ratio)
        assert floor >= 2000

    def test_floor_never_below_the_hard_minimum(self):
        guard = ContextBudgetGuard(
            AsyncMock(),
            window=_window(100),
            keep_chars_floor=1,
            agent_name="f",
        )
        snapshot = guard.measure([_sys("s" * 5000)], "t" * 5000)
        assert guard.keep_floor(snapshot) >= 2000

    def test_floor_is_capped_by_the_configured_value(self):
        guard = ContextBudgetGuard(
            AsyncMock(),
            window=_window(400000),
            keep_chars_floor=5000,
            agent_name="f",
        )
        snapshot = guard.measure([_sys("s"), _row("user", "hi")], "t")
        assert guard.keep_floor(snapshot) == 5000

    def test_whole_rows_go_before_truncation(self):
        """Prefer archiving whole rows; truncating every row is not recoverable."""
        guard = ContextBudgetGuard(
            AsyncMock(),
            window=_window(6000),
            keep_chars_floor=30000,
            agent_name="t",
        )
        messages = [_sys("s" * 500)] + [
            _row("user", f"row{i} " + "u" * 1500) for i in range(20)
        ]
        snapshot = guard.measure(messages, "t" * 500)
        before = len(messages)
        guard._trim_prompt(messages, snapshot)
        # Rows were deleted whole; the survivors are not mutilated.
        assert len(messages) < before
        survivors = [m for m in messages if m.get("role") != "system"]
        assert all(len(str(m)) > 1400 for m in survivors), (
            "surviving rows must keep their text: the gate deletes whole rows "
            "into the summary queue before it truncates every row"
        )


# ── B5: compaction slots follow the queue ─────────────────────────
class TestCompactionSlots:
    def test_single_busy_session_keeps_one_slot(self):
        from coapis.agents.react_agent import (
            _LIVE_AGENTS,
            compaction_slots,
        )

        snapshot = list(_LIVE_AGENTS)
        try:
            _LIVE_AGENTS.clear()
            _LIVE_AGENTS.add(MagicMock(_compaction_due=True))
            assert compaction_slots() == 1
        finally:
            _LIVE_AGENTS.clear()
            for agent in snapshot:
                _LIVE_AGENTS.add(agent)

    def test_loaded_server_gets_more_slots(self):
        from coapis.agents.react_agent import (
            _COMPACTION_SLOTS_MAX,
            _LIVE_AGENTS,
            compaction_slots,
        )

        snapshot = list(_LIVE_AGENTS)
        # _LIVE_AGENTS is a WeakSet: the agents must stay referenced by this
        # test, or they vanish from the set before the count runs.
        fleet = [MagicMock(_compaction_due=True) for _ in range(16)]
        try:
            _LIVE_AGENTS.clear()
            for agent in fleet:
                _LIVE_AGENTS.add(agent)
            assert compaction_slots() == _COMPACTION_SLOTS_MAX
        finally:
            _LIVE_AGENTS.clear()
            for agent in snapshot:
                _LIVE_AGENTS.add(agent)

    def test_idle_server_keeps_the_original_guarantee(self):
        from coapis.agents.react_agent import (
            _LIVE_AGENTS,
            compaction_slots,
        )

        snapshot = list(_LIVE_AGENTS)
        try:
            _LIVE_AGENTS.clear()
            assert compaction_slots() == 1
        finally:
            _LIVE_AGENTS.clear()
            for agent in snapshot:
                _LIVE_AGENTS.add(agent)

    def test_agents_are_countable(self):
        """A live agent registers itself, so the slot count is not a guess."""
        import inspect

        from coapis.agents import react_agent as ra

        assert "_LIVE_AGENTS.add(self)" in inspect.getsource(ra.CoApisAgent)


# ── B8: skill trigger governance ───────────────────────────────────
class TestSkillTriggerGovernance:
    def test_index_prompt_is_defined_once(self):
        """B8: the class used to define get_index_prompt twice; one ran."""
        import inspect
        import re

        from coapis.skills import manager as mgr

        src = inspect.getsource(mgr.SkillManager)
        assert len(re.findall(r"def get_index_prompt\(", src)) == 1

    def test_trigger_sentence_is_detected(self):
        from coapis.skills.manager import has_trigger_sentence

        assert has_trigger_sentence(
            {"description": "Use this skill when the user asks for a PDF."},
        )
        assert has_trigger_sentence({"index_hint": "当用户要求生成周报时使用"})
        assert not has_trigger_sentence({"description": "Tools for PDF work."})
        assert not has_trigger_sentence({})

    def test_missing_trigger_skills_are_listed(self):
        from coapis.skills.manager import missing_trigger_skills

        silent = missing_trigger_skills(
            [
                {"name": "loud", "description": "Use when the user asks."},
                {"name": "ghost", "description": "A PDF toolkit."},
            ],
        )
        assert silent == ["ghost"]

    def test_discovery_warns_about_silent_skills(self, tmp_path, caplog):
        from coapis.skills.manager import SkillManager

        skill = tmp_path / "ghost"
        skill.mkdir()
        (skill / "SKILL.md").write_text(
            "---\nname: ghost\ndescription: A PDF toolkit.\n---\nbody\n",
            encoding="utf-8",
        )
        manager = SkillManager(Path(tmp_path))
        loop = asyncio.new_event_loop()
        try:
            with caplog.at_level("WARNING"):
                loop.run_until_complete(manager.discover())
        finally:
            loop.close()
        assert manager._skills["ghost"]["has_trigger"] is False
        assert any("no trigger sentence" in r.message for r in caplog.records)


# ── B9: no absolute path in the user's message ────────────────────
class TestErrorPathPrivacy:
    def _stream_query_source(self) -> str:
        """Source of the turn handler that writes the error dump.

        The dump lives in the runner's turn handler (``query_handler`` on the
        agent runner class), not in a module-level ``stream_query``, so the
        search walks module functions *and* class methods.
        """
        import inspect

        from coapis.app.runner import runner as runner_mod

        candidates = []
        for obj in vars(runner_mod).values():
            if inspect.isclass(obj):
                candidates.extend(
                    m for m in vars(obj).values() if callable(m)
                )
            elif callable(obj):
                candidates.append(obj)
        for fn in candidates:
            try:
                src = inspect.getsource(fn)
            except (TypeError, OSError):
                continue
            # The writer itself is imported into the module namespace; the
            # handler is the caller that composes the user-visible message.
            if "write_query_error_dump(" in src and "path_hint" in src:
                return src
        raise AssertionError("turn handler with the error dump not found")

    def test_dump_path_is_not_pasted_into_the_message(self):
        src = self._stream_query_source()
        assert "converted.message += suffix" not in src
        assert "converted.args[0]}{suffix}" not in src
        assert "add_note(" not in src

    def test_dump_path_stays_available_as_a_field(self):
        src = self._stream_query_source()
        assert 'setattr(converted, "debug_dump_path", debug_dump_path)' in src

    def test_dump_path_is_still_logged_server_side(self):
        src = self._stream_query_source()
        assert "logger.exception(" in src
        assert "path_hint" in src


# ── B7: the governance endpoint must be callable ──────────────────
class TestContextOverheadEndpoint:
    def test_handler_declares_the_request_parameter(self):
        """B7: @require_permission injects `request`; the handler lacked it."""
        import inspect

        from coapis.app.routers import agent_stats

        sig = inspect.signature(agent_stats.get_context_overhead)
        assert "request" in sig.parameters

    def test_decorator_still_wraps_the_handler(self):
        import inspect

        from coapis.app.routers import agent_stats

        src = inspect.getsource(agent_stats)
        at = src.index("/agent-stats/context-overhead")
        head = src[at : at + 400]
        assert "@require_permission" in head
        assert "async def get_context_overhead" in head
        # The decorator must sit directly above the handler, not above a
        # comment block that hides it.
        between = head.split("@require_permission")[1].split("async def")[0]
        assert "(" in between and ")" in between


def test_imports_stay_clean():
    import importlib

    for name in (
        "coapis.agents.context.context_budget",
        "coapis.agents.context.window_source",
        "coapis.agents.react_agent",
        "coapis.skills.manager",
        "coapis.app.runner.runner",
        "coapis.app.runner.session",
        "coapis.app.routers.providers",
        "coapis.app.routers.user_model_prefs",
        "coapis.app.routers.agent_stats",
    ):
        importlib.import_module(name)
