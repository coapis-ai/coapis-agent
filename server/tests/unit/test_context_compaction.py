# -*- coding: utf-8 -*-
"""Single-compactor context architecture unit tests.

Covers the contract that the community edition relies on after the v3
rework (``tech_docs/社区版上下文优化实施方案_v3_20261014.md``):

- agentscope's ``ReActAgent._compress_memory_if_needed`` is the only
  compactor; coapis supplies the hygiene around it.
- ``AgentContext`` must keep the async memory contract upstream awaits.
- Compressed messages are archived to ``dialog/*.jsonl`` before they are
  purged from working memory — and never purged when the archive failed.
"""

import asyncio
import inspect
import json
from pathlib import Path

import pytest
from agentscope.agent._react_agent import _MemoryMark
from agentscope.memory import InMemoryMemory
from agentscope.message import Msg

from coapis.agents.context.agent_context import AgentContext
from coapis.agents.context.base_context_manager import BaseContextManager
from coapis.agents.context.light_context_manager import LightContextManager
from coapis.agents.utils.estimate_token_counter import EstimatedTokenCounter
from coapis.config.config import AgentsRunningConfig as RunningConfig


def _msg(text: str, role: str = "user") -> Msg:
    return Msg(name=role, content=text, role=role)


def _context(tmp_path: Path | None = None) -> AgentContext:
    return AgentContext(
        token_counter=None,
        dialog_path=str(tmp_path) if tmp_path else None,
    )


class TestAsyncSummaryContract:
    """Upstream does ``await memory.update_compressed_summary(...)``.

    A sync override turns that statement into ``await None`` and raises
    ``TypeError`` the first time compaction actually fires.
    """

    def test_agent_context_method_is_async(self):
        assert inspect.iscoroutinefunction(
            AgentContext.update_compressed_summary,
        )

    def test_matches_upstream_base_contract(self):
        assert inspect.iscoroutinefunction(
            InMemoryMemory.update_compressed_summary,
        )

    def test_await_updates_summary(self):
        async def run():
            ctx = _context()
            await ctx.update_compressed_summary("## summary")
            return ctx.get_compressed_summary()

        assert asyncio.run(run()) == "## summary"


class TestArchiveCompressedAndPurge:
    """COMPRESSED → dialog jsonl → drop from working memory."""

    def test_nothing_marked_is_a_noop(self, tmp_path):
        ctx = _context(tmp_path)
        ctx.content = [(_msg("a"), []), (_msg("b"), [])]
        assert asyncio.run(ctx.archive_compressed_and_purge()) == []
        assert len(ctx.content) == 2

    def test_archives_then_purges(self, tmp_path):
        ctx = _context(tmp_path)
        marked = [_msg("old-1"), _msg("old-2", "assistant")]
        ctx.content = [
            (marked[0], [_MemoryMark.COMPRESSED]),
            (marked[1], [_MemoryMark.COMPRESSED]),
            (_msg("kept"), []),
        ]

        archived = asyncio.run(ctx.archive_compressed_and_purge())

        assert [m.get_text_content() for m in archived] == ["old-1", "old-2"]
        assert len(ctx.content) == 1
        assert ctx.content[0][0].get_text_content() == "kept"

        files = list(Path(ctx._dialog_path).glob("*.jsonl"))
        assert files, "compressed messages must be archived on disk"
        lines = [
            json.loads(line)
            for f in files
            for line in f.read_text(encoding="utf-8").splitlines()
            if line.strip()
        ]
        assert {line["content"] for line in lines} >= {"old-1", "old-2"}

    def test_unmarked_messages_keep_their_marks(self, tmp_path):
        ctx = _context(tmp_path)
        ctx.content = [(_msg("keep-me"), ["note"])]
        asyncio.run(ctx.archive_compressed_and_purge())
        assert ctx.content[0][1] == ["note"]

    def test_without_dialog_path_keeps_messages(self, tmp_path):
        """No archive target → nothing is dropped; history beats hygiene."""
        ctx = _context(None)
        ctx.content = [(_msg("old"), [_MemoryMark.COMPRESSED])]
        assert asyncio.run(ctx.archive_compressed_and_purge()) == []
        assert len(ctx.content) == 1

    def test_archive_failure_keeps_messages(self, tmp_path, monkeypatch):
        ctx = _context(tmp_path)
        ctx.content = [(_msg("old"), [_MemoryMark.COMPRESSED])]

        async def boom(_messages):
            raise OSError("disk on fire")

        monkeypatch.setattr(ctx, "_append_messages_to_dialog", boom)
        assert asyncio.run(ctx.archive_compressed_and_purge()) == []
        assert len(ctx.content) == 1

    def test_partial_archive_keeps_messages(self, tmp_path, monkeypatch):
        ctx = _context(tmp_path)
        ctx.content = [
            (_msg("old-1"), [_MemoryMark.COMPRESSED]),
            (_msg("old-2"), [_MemoryMark.COMPRESSED]),
        ]

        async def partial(_messages):
            return 1  # wrote one of two

        monkeypatch.setattr(ctx, "_append_messages_to_dialog", partial)
        assert asyncio.run(ctx.archive_compressed_and_purge()) == []
        assert len(ctx.content) == 2


class TestCompressionConfig:
    """Threshold is calibrated in *formatted prompt* characters."""

    @staticmethod
    def _build(ratio=0.8, chars=4.7, keep=15, model_id="", safety=0.5):
        from coapis.agents.react_agent import CoApisAgent

        running = RunningConfig(max_input_length=100_000)
        running.context_window_safety_factor = safety
        ccc = running.light_context_config.context_compact_config
        ccc.compact_threshold_ratio = ratio
        ccc.formatted_chars_per_token = chars
        ccc.keep_recent_default = keep
        ccc.compaction_model_id = model_id
        return CoApisAgent._build_compression_config(None, running, object())

    def test_threshold_is_tokens_times_chars_per_token(self):
        config = self._build()
        assert config is not None
        assert config.enable
        # _running() calibrates 4.7 formatted chars/token:
        # 100000 * 0.5 safety factor = 50000 effective window,
        # * 0.8 ratio = 40000 tokens, * 4.7 chars/token = 188000 chars.
        assert config.trigger_threshold == int(50_000 * 0.8 * 4.7)
        assert config.keep_recent == 15

    def test_divisor_change_does_not_move_the_trigger(self):
        """The old code multiplied by ``token_count_estimate_divisor`` (4),
        which put the trigger at ~156% of the window.  The calibrated field
        must be the one that decides."""
        assert self._build(chars=2.0).trigger_threshold == 80_000
        assert self._build(chars=4.7).trigger_threshold == 188_000

    def test_safety_factor_shrinks_the_budgeted_window(self):
        """D1: the advertised window is not the usable one.

        Halving the safety factor must halve the trigger — the budget is
        derived from the *effective* window, never the advertised one.
        """
        assert self._build(safety=0.5).trigger_threshold == 188_000
        assert self._build(safety=1.0).trigger_threshold == 376_000
        assert self._build(safety=0.9).trigger_threshold == int(
            100_000 * 0.9 * 0.8 * 4.7
        )

    def test_disabled_returns_none(self):
        from coapis.agents.react_agent import CoApisAgent

        running = RunningConfig(max_input_length=100_000)
        running.light_context_config.context_compact_config.enabled = False
        assert CoApisAgent._build_compression_config(None, running, None) is None

    def test_bad_compaction_model_falls_back_to_session_model(self):
        """A broken ``compaction_model_id`` must not disable compaction."""
        config = self._build(model_id="no-such-provider:no-such-model")
        assert config is not None
        assert config.enable
        assert config.compression_model is None
        assert config.compression_formatter is None


class TestKeepRecentBudget:
    """The tail upstream keeps is sized by tokens, not by a constant."""

    @staticmethod
    def _keep(messages, budget_tokens=100, chars=4.0, lo=3, hi=20):
        class FakeMemory:
            async def get_memory(self, prepend_summary=True):
                return messages

        return asyncio.run(
            LightContextManager._compute_keep_recent(
                FakeMemory(),
                budget_tokens=budget_tokens,
                chars_per_token=chars,
                keep_recent_min=lo,
                keep_recent_max=hi,
            ),
        )

    def test_clamps_to_floor(self):
        """One huge message blows the budget immediately; the floor is what
        keeps a session from being squeezed to a single exchange."""
        assert self._keep([_msg("x" * 5000)] * 30, budget_tokens=1) == 3

    def test_clamps_to_ceiling(self):
        assert self._keep([_msg("x")] * 200, budget_tokens=10_000) == 20

    def test_budget_decides_in_between(self):
        messages = [_msg("x" * 40) for _ in range(20)]
        # budget = 100 tokens * 4 chars = 400 chars → 10 messages
        assert self._keep(messages, budget_tokens=100) == 10

    def test_empty_memory_gets_floor(self):
        assert self._keep([]) == 3


class TestPostReasoningHookContract:
    """``post_reasoning`` is part of the backend interface."""

    def test_base_hook_is_concrete_noop(self):
        assert not getattr(
            BaseContextManager.post_reasoning,
            "__isabstractmethod__",
            False,
        )
        assert asyncio.run(
            BaseContextManager.post_reasoning(None, None, {}, None),
        ) is None

    def test_light_backend_implements_it(self):
        assert hasattr(LightContextManager, "post_reasoning")
        assert inspect.iscoroutinefunction(
            LightContextManager.post_reasoning,
        )


class TestBackgroundPromptBudget:
    """D6: raw-client background calls reuse the gate's budget."""

    @staticmethod
    def _window(tokens=2000, chars=1.1):
        from coapis.agents.context.window_source import WindowInfo

        return WindowInfo(
            reported_tokens=tokens,
            effective_tokens=tokens,
            source="model_self_report",
            chars_per_token=chars,
        )

    def test_fitting_prompt_is_untouched(self):
        from coapis.agents.context.context_budget import fit_prompt_to_budget

        msgs = [
            {"role": "system", "content": "sys"},
            {"role": "user", "content": "short prompt"},
        ]
        assert fit_prompt_to_budget(msgs, self._window()) == msgs

    def test_oversized_prompt_is_truncated_not_sent(self):
        from coapis.agents.context.context_budget import fit_prompt_to_budget

        msgs = [
            {"role": "system", "content": "sys"},
            {"role": "user", "content": "x" * 20_000},
        ]
        window = self._window(tokens=2000)
        out = fit_prompt_to_budget(msgs, window)
        total = sum(len(str(m)) for m in out)
        # D1 (2026-10-17): the budget is the window expressed in formatted
        # characters — the unit the provider counts — not the token number.
        # Asserting ``total <= tokens`` here encoded the old unit, which is
        # exactly the disagreement that made compaction never fire.
        assert total <= window.to_chars(window.effective_tokens)
        body = out[1]["content"]
        assert "truncated by context budget" in body
        # Head and tail survive: the cut is in the middle.
        assert body.startswith("xxxx")
        assert body.endswith("xxxx")

    def test_fixed_overhead_too_big_skips_the_call(self):
        """Nothing left to cut means the task is refused, not crashed."""
        from coapis.agents.context.context_budget import fit_prompt_to_budget

        msgs = [
            {"role": "system", "content": "s" * 5000},
            {"role": "user", "content": "x" * 5000},
        ]
        # 6a-3 (2026-10-17): an unfixable request is sent as the best fit we
        # managed, never as an empty prompt — an empty prompt is a compaction
        # that silently never runs, which is the bug this batch exists to kill.
        out = fit_prompt_to_budget(msgs, self._window(tokens=100))
        assert out, "the fit must never return an empty prompt"
        assert sum(len(str(m)) for m in out) <= sum(
            len(str(m)) for m in msgs
        )

    def test_wrapper_never_breaks_a_call(self):
        from coapis.agents.context.context_budget import (
            budget_background_prompt,
        )

        msgs = [{"role": "user", "content": "hi"}]
        # Unmeasurable model (None) must return the prompt unchanged.
        assert budget_background_prompt(msgs, None, source="t") == msgs


class TestHistoryDisplayUsesGateCalibration:
    """D5: what the user reads is what the gate enforces."""

    @staticmethod
    def _window(tokens=1000, chars=1.1):
        from coapis.agents.context.window_source import WindowInfo

        return WindowInfo(
            reported_tokens=tokens,
            effective_tokens=tokens,
            source="model_self_report",
            chars_per_token=chars,
        )

    def test_window_path_measures_chars_with_the_calibration(self):
        ctx = AgentContext(token_counter=EstimatedTokenCounter())
        msgs = [_msg("x" * 1100) for _ in range(2)]
        asyncio.run(ctx.add(msgs[0]))
        asyncio.run(ctx.add(msgs[1]))
        stats = asyncio.run(
            ctx.estimate_tokens(1_000_000, window=self._window()),
        )
        assert stats["measured_chars"] == 2200
        assert stats["estimated_tokens"] == int(2200 / 1.1)
        # The advertised 1_000_000 is ignored: the effective window is truth.
        assert stats["max_input_length"] == 1000
        assert round(stats["context_usage_ratio"]) == 200

    def test_legacy_path_survives_without_a_window(self):
        ctx = AgentContext(token_counter=EstimatedTokenCounter())
        asyncio.run(ctx.add(_msg("hello")))
        stats = asyncio.run(ctx.estimate_tokens(1000))
        assert stats["max_input_length"] == 1000
        assert stats["estimated_tokens"] >= 1


def _window(tokens: int, chars_per_token: float = 1.1):
    from coapis.agents.context.window_source import WindowInfo

    return WindowInfo(
        reported_tokens=tokens,
        effective_tokens=tokens,
        source="model_self_report",
        chars_per_token=chars_per_token,
    )


def _heavy_tools(count: int, desc_chars: int) -> list[dict]:
    """A tool schema list of roughly ``count * (desc_chars + 60)`` chars."""
    return [
        {
            "type": "function",
            "function": {
                "name": f"tool_{i}",
                "description": "d" * desc_chars,
                "parameters": {"type": "object", "properties": {}},
            },
        }
        for i in range(count)
    ]


class TestAffordableFloor:
    """The history floor is a ceiling, not a target.

    Dev 2026-10-16: agent ``user:admin`` pays ~48K chars of fixed overhead
    (system prompt + skills + 45 tool schemas) against a 65536-char window
    with a configured 28835-char floor.  ``fixed + floor > window``, so every
    chat answered ``MODEL_CONTEXT_LENGTH_EXCEEDED`` — the floor blocked the
    very pruning that would have saved the call.
    """

    def test_configured_floor_wins_when_the_window_can_pay(self):
        from coapis.agents.context.context_budget import affordable_floor

        assert affordable_floor(65536, 10000, 28835) == 28835

    def test_floor_caps_to_what_the_window_spares(self):
        """An unaffordable floor drops to the hard minimum, not to zero."""
        from coapis.agents.context.context_budget import (
            MIN_KEEP_CHARS,
            affordable_floor,
        )

        # 48113 of fixed overhead leaves 17423 of a 65536 window: the
        # configured 28835 cannot be honoured, so the barrier is the last
        # exchange, not a number no call can pay.
        assert affordable_floor(65536, 48113, 28835) == MIN_KEEP_CHARS

    def test_never_below_the_hard_minimum(self):
        from coapis.agents.context.context_budget import (
            MIN_KEEP_CHARS,
            affordable_floor,
        )

        # A window with no room at all still keeps the last exchange rather
        # than sending an empty prompt; the overflow message reports it.
        assert affordable_floor(65536, 65000, 28835) == MIN_KEEP_CHARS
        assert affordable_floor(1000, 1000, 28835) == MIN_KEEP_CHARS

    def test_unpayable_floor_prunes_and_the_call_fits(self, tmp_path):
        """The admin scenario: heavy fixed overhead must prune, not refuse."""
        from coapis.agents.context.context_budget import ContextBudgetGuard

        window = _window(65536)
        ctx = AgentContext(token_counter=None, dialog_path=str(tmp_path))
        for _ in range(8):
            asyncio.run(ctx.add(_msg("h" * 3000, role="user")))
        guard = ContextBudgetGuard(
            None,
            window=window,
            keep_chars_floor=28835,
            memory_provider=lambda: ctx,
            agent_name="user:admin",
        )
        tools = _heavy_tools(45, 900)
        msgs = [{"role": "system", "content": "s" * 3111}] + [
            {"role": "user", "content": "h" * 3000} for _ in range(8)
        ]
        before = len(msgs)
        snapshot = asyncio.run(guard.enforce(msgs, tools))
        assert snapshot.total_chars <= snapshot.budget_chars
        assert guard.pruned_events == 1
        assert guard.overflow_events == 0
        # The system row stays at the head and the newest rows survive: the
        # cut is at the oldest end, in order.
        assert len(msgs) < before
        assert msgs[0]["role"] == "system"
        assert msgs[-1]["content"] == "h" * 3000

    def test_pruning_applies_to_the_call_that_triggered_it(self, tmp_path):
        """Purging memory alone shrinks the *next* prompt, not this one.

        The guard must trim the prompt it is about to send, otherwise the
        overflowing call goes out oversized and the user gets the provider's
        opaque context-length error.
        """
        from coapis.agents.context.context_budget import ContextBudgetGuard

        ctx = AgentContext(token_counter=None, dialog_path=str(tmp_path))
        for _ in range(6):
            asyncio.run(ctx.add(_msg("m" * 2000, role="user")))
        guard = ContextBudgetGuard(
            None,
            window=_window(30000),
            keep_chars_floor=4000,
            memory_provider=lambda: ctx,
            agent_name="trim",
        )
        tools = _heavy_tools(20, 900)
        msgs = [{"role": "system", "content": "s" * 500}] + [
            {"role": "user", "content": "u" * 4000} for _ in range(6)
        ]
        snapshot = asyncio.run(guard.enforce(msgs, tools))
        assert snapshot.total_chars <= snapshot.budget_chars
        # The list handed back to the caller is the trimmed one: what the
        # gate measured is what the model receives (history excludes the
        # system row, which lives in fixed overhead).
        assert msgs[0]["role"] == "system"
        assert (
            sum(len(str(m)) for m in msgs[1:]) == snapshot.history_chars
        )

    def test_fixed_overhead_alone_overflow_names_the_cause(self):
        """No history size fits: the message must name fixed overhead."""
        from coapis.agents.context.context_budget import (
            ContextBudgetGuard,
            ContextOverflowError,
        )

        guard = ContextBudgetGuard(
            None,
            window=_window(20000),
            keep_chars_floor=12000,
            memory_provider=lambda: None,
            agent_name="heavy",
        )
        tools = _heavy_tools(20, 1000)
        msgs = [{"role": "system", "content": "s" * 500}] + [
            {"role": "user", "content": "u" * 1000} for _ in range(5)
        ]
        with pytest.raises(ContextOverflowError) as excinfo:
            asyncio.run(guard.enforce(msgs, tools))
        text = str(excinfo.value)
        assert "fixed overhead alone" in text
        assert "tool schemas" in text
        assert guard.overflow_events == 1

    def test_trim_path_clamps_the_floor_too(self):
        """The AgentCore path shares the clamp, so the two cannot disagree."""
        from coapis.agents.context.context_budget import (
            trim_messages_to_budget,
        )

        window = _window(32000)
        tools = _heavy_tools(25, 900)
        msgs = [{"role": "system", "content": "s" * 1000}] + [
            {"role": "user", "content": "u" * 1500} for _ in range(10)
        ]
        kept, dropped, snapshot = trim_messages_to_budget(
            msgs,
            window,
            keep_chars_floor=12000,
            tools=tools,
        )
        assert dropped
        assert snapshot.total_chars <= snapshot.budget_chars
        assert kept[0]["role"] == "system"
        assert kept[-1]["content"] == "u" * 1500


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-q"]))
