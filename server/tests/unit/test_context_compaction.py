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
    def _build(ratio=0.8, chars=4.7, keep=15, model_id=""):
        from coapis.agents.react_agent import CoApisAgent

        running = RunningConfig(max_input_length=100_000)
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
        assert config.trigger_threshold == int(100_000 * 0.8 * 4.7)
        assert config.keep_recent == 15

    def test_divisor_change_does_not_move_the_trigger(self):
        """The old code multiplied by ``token_count_estimate_divisor`` (4),
        which put the trigger at ~156% of the window.  The calibrated field
        must be the one that decides."""
        assert self._build(chars=2.0).trigger_threshold == 160_000
        assert self._build(chars=4.7).trigger_threshold == 376_000

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


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-q"]))
