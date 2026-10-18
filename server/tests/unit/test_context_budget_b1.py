# -*- coding: utf-8 -*-
"""B1 (片6a) — the gate must be able to save the call it refuses.

Covers the four fixes of the 2026-10-17 construction plan:

- 6a-1: the gate's budget is measured in the unit upstream counts
  (formatted characters), so gate and compactor agree.
- 6a-2: a single oversized row is truncated in the sent view instead of
  making the call unrescuable ("floor blocks deletion" ≠ "floor blocks
  lossy compression").
- 6a-3: the compaction request is measured and fitted, never exempt.
- 6a-4: ``keep_recent`` is lowered when the session is over trigger but has
  no compressible groups (upstream skips compression entirely there).
"""

import copy
from pathlib import Path

import pytest
from agentscope.memory import InMemoryMemory
from agentscope.message import Msg

from coapis.agents.context.context_budget import (
    ContextBudgetGuard,
    ContextOverflowError,
    MIN_ROW_CHARS,
    build_budget_guard,
    fit_prompt_to_budget,
    measure_prompt,
    truncate_rows_to_fit,
)
from coapis.agents.context.light_context_manager import (
    compressible_prefix_count,
    count_message_groups,
)
from coapis.agents.context.window_source import WindowInfo
from coapis.config.config import AgentsRunningConfig as RunningConfig


def _window(tokens: int = 1000, cpt: float = 1.1) -> WindowInfo:
    return WindowInfo(
        reported_tokens=tokens,
        effective_tokens=tokens,
        source="model_self_report",
        chars_per_token=cpt,
    )


def _sys(text: str = "system prompt") -> dict:
    return {"role": "system", "content": text}


def _row(role: str, text: str) -> dict:
    return {"role": role, "content": text}


class _FakeModel:
    """Records what the gate actually forwarded."""

    def __init__(self) -> None:
        self.calls: list[dict] = []

    async def __call__(self, messages=None, tools=None, **kwargs):
        self.calls.append({"messages": messages, "tools": tools, **kwargs})
        return "ok"

    @property
    def stream(self) -> bool:
        return False


# ─────────────────────────────────────────────────────────────────────────────
# 6a-1 — one unit for the budget
# ─────────────────────────────────────────────────────────────────────────────


class TestBudgetUnit:
    def test_budget_is_characters_not_tokens(self):
        window = _window(tokens=1000, cpt=3.0)
        snap = measure_prompt([_row("user", "x" * 10)], None, window, 0.8)
        assert snap.budget_chars == 3000
        assert snap.trigger_chars == 2400

    def test_gate_and_compactor_agree_on_the_trigger(self):
        """The compaction trigger and the gate's trigger are the same number.

        ``react_agent._build_compression_config`` computes
        ``to_chars(int(effective * ratio))``; the gate computes
        ``int(to_chars(effective) * ratio)``.  Integer rounding is the only
        allowed difference — a factor of ``chars_per_token`` is what made
        compaction fire 0 times while the gate fired 125.
        """
        running = RunningConfig()
        ccc = running.light_context_config.context_compact_config
        window = _window(
            tokens=102400,
            cpt=ccc.formatted_chars_per_token,
        )
        compactor_trigger = window.to_chars(
            int(window.effective_tokens * ccc.compact_threshold_ratio),
        )
        gate_trigger = measure_prompt(
            [_row("user", "hi")],
            None,
            window,
            ccc.compact_threshold_ratio,
        ).trigger_chars
        assert abs(compactor_trigger - gate_trigger) <= 1

    def test_headroom_uses_the_same_unit(self):
        window = _window(tokens=2000, cpt=2.0)
        snap = measure_prompt([_row("user", "y" * 500)], None, window, 0.8)
        assert snap.budget_chars == 4000
        assert snap.headroom_chars == 4000 - snap.total_chars


# ─────────────────────────────────────────────────────────────────────────────
# 6a-2 — a giant row is rescuable
# ─────────────────────────────────────────────────────────────────────────────


class TestGiantRowTruncation:
    def test_truncation_fits_a_prompt_the_floor_cannot_prune(self):
        window = _window(tokens=1000, cpt=1.1)
        rows = [_sys(), _row("tool", "x" * 88_000)]
        before = measure_prompt(rows, None, window, 0.8)
        assert before.total_chars > before.budget_chars
        reclaimed = truncate_rows_to_fit(rows, 1, before.budget_chars)
        after = measure_prompt(rows, None, window, 0.8)
        assert reclaimed > 80_000
        assert after.total_chars <= after.budget_chars

    def test_truncated_row_stays_in_the_prompt(self):
        """Truncation is not deletion: the exchange is still represented."""
        window = _window(tokens=1000, cpt=1.1)
        rows = [_sys(), _row("tool", "x" * 88_000)]
        truncate_rows_to_fit(rows, 1, measure_prompt(rows, None, window, 0.8).budget_chars)
        assert len(rows) == 2
        assert "truncated" in rows[1]["content"]

    def test_source_rows_are_never_mutated(self):
        """The transcript keeps the full text; only the sent copy shrinks."""
        window = _window(tokens=1000, cpt=1.1)
        big = _row("tool", "x" * 88_000)
        snapshot_of_source = copy.deepcopy(big)
        rows = [_sys(), big]
        truncate_rows_to_fit(
            rows,
            1,
            measure_prompt(rows, None, window, 0.8).budget_chars,
        )
        assert rows[1]["content"] != snapshot_of_source["content"]
        assert big["content"] == snapshot_of_source["content"]

    def test_rows_below_the_floor_are_left_alone(self):
        window = _window(tokens=1000, cpt=1.1)
        rows = [_sys(), _row("user", "x" * 200), _row("user", "y" * 200)]
        # A budget the rows cannot fit — the point is that no row is big
        # enough (MIN_ROW_CHARS) to be a truncation candidate.
        budget = measure_prompt(rows, None, window, 0.8).budget_chars - 300
        assert truncate_rows_to_fit(rows, 1, budget) == 0
        assert len(rows) == 3

    def test_floor_blocks_deletion_only(self):
        """``trim_messages_to_budget`` truncates before it raises."""
        from coapis.agents.context.context_budget import trim_messages_to_budget

        window = _window(tokens=1000, cpt=1.1)
        rows = [_sys(), _row("tool", "x" * 88_000)]
        kept, dropped, snap = trim_messages_to_budget(
            rows,
            window,
            compact_threshold_ratio=0.8,
            keep_chars_floor=60_000,
        )
        assert dropped == []
        assert snap.total_chars <= snap.budget_chars
        assert len(kept) == 2

    @pytest.mark.asyncio
    async def test_guard_enforce_prunes_then_truncates(self):
        window = _window(tokens=2000, cpt=1.1)
        guard = ContextBudgetGuard(
            _FakeModel(),
            window=window,
            compact_threshold_ratio=0.8,
            keep_chars_floor=9_000,
            agent_name="test",
        )
        messages = [_sys()] + [_row("user", "m" * 1_000) for _ in range(4)]
        messages.append(_row("tool", "x" * 40_000))
        after = await guard.enforce(messages, None)
        assert after.total_chars <= after.budget_chars
        assert guard.overflow_events == 0

    @pytest.mark.asyncio
    async def test_fixed_overhead_alone_still_raises(self):
        """Truncation covers history, not an unaffordable fixed overhead."""
        window = _window(tokens=500, cpt=1.1)
        guard = ContextBudgetGuard(
            _FakeModel(),
            window=window,
            compact_threshold_ratio=0.8,
            agent_name="test",
        )
        messages = [_sys("s" * 4_000), _row("user", "hi")]
        with pytest.raises(ContextOverflowError):
            await guard.enforce(messages, "t" * 4_000)


# ─────────────────────────────────────────────────────────────────────────────
# 6a-3 — the compaction request is measured
# ─────────────────────────────────────────────────────────────────────────────


class TestCompactionInputFit:
    @pytest.mark.asyncio
    async def test_structured_model_call_is_fitted(self):
        window = _window(tokens=1000, cpt=1.1)
        fake = _FakeModel()
        guard = ContextBudgetGuard(
            fake,
            window=window,
            compact_threshold_ratio=0.8,
            compaction_input_ratio=0.5,
            agent_name="test",
        )
        messages = [_sys(), _row("tool", "x" * 60_000)]
        await guard(messages, None, structured_model=object())
        sent = fake.calls[0]["messages"]
        sent_chars = sum(len(str(m)) for m in sent)
        assert sent_chars <= int(window.to_chars(window.effective_tokens) * 0.5)
        assert len(sent) == len(messages)

    @pytest.mark.asyncio
    async def test_compaction_is_never_refused(self):
        """A summary request that cannot fit is sent as-is, not raised."""
        window = _window(tokens=500, cpt=1.1)
        fake = _FakeModel()
        guard = ContextBudgetGuard(
            fake,
            window=window,
            compaction_input_ratio=0.5,
            agent_name="test",
        )
        messages = [_sys("s" * 9_000), _row("tool", "x" * 9_000)]
        await guard(messages, None, structured_model=object())
        assert len(fake.calls) == 1
        assert fake.calls[0]["messages"]

    @pytest.mark.asyncio
    async def test_normal_calls_are_still_gated(self):
        window = _window(tokens=1000, cpt=1.1)
        fake = _FakeModel()
        guard = ContextBudgetGuard(
            fake,
            window=window,
            compaction_input_ratio=0.5,
            agent_name="test",
        )
        messages = [_sys(), _row("tool", "x" * 60_000)]
        await guard(messages, None)
        sent = fake.calls[0]["messages"]
        assert sum(len(str(m)) for m in sent) <= window.to_chars(
            window.effective_tokens,
        )

    def test_multi_row_compaction_prompt_is_fitted(self):
        """The dev shape: a compaction prompt of hundreds of rows.

        Truncating the single largest row of a 155,775-char compaction
        prompt against a 36,044-char window reclaimed nothing, the call was
        skipped, and compaction never ran (dev 2026-10-17).  The fit has to
        delete whole exchanges, not just shave one row.
        """
        window = _window(tokens=65_536)
        ratio = 0.5
        budget = int(window.to_chars(window.effective_tokens) * ratio)
        rows = [_sys()] + [
            _row("tool", "x" * 500) for _ in range(300)
        ]
        before = sum(len(str(m)) for m in rows)
        out = fit_prompt_to_budget(
            rows,
            window,
            compact_threshold_ratio=ratio,
            source="compaction:test",
        )
        after = sum(len(str(m)) for m in out)
        assert before > 4 * budget, before
        assert out, "the fit must never return an empty prompt"
        assert after <= budget, f"{after} chars against a {budget}-char window"

    def test_ratio_is_clamped(self):
        window = _window()
        guard = ContextBudgetGuard(
            _FakeModel(),
            window=window,
            compaction_input_ratio=99,
        )
        assert guard.compaction_input_ratio == 0.9
        guard2 = ContextBudgetGuard(
            _FakeModel(),
            window=window,
            compaction_input_ratio=0,
        )
        assert guard2.compaction_input_ratio == 0.2

    def test_config_field_exists(self):
        running = RunningConfig()
        ccc = running.light_context_config.context_compact_config
        assert ccc.compaction_input_ratio == 0.7
        # The compaction request must be able to carry the fixed overhead it
        # is charged for, with headroom.  Measured on dev 2026-10-18 from the
        # live gate line ("Context budget user:admin: fixed=25429
        # (sys=17949 tools=7480)"): the manager-ized tool catalogue and the
        # compacted skill index cut the fixed overhead from the 89,863 chars
        # measured on 2026-10-17 to 25,429.  The floor below is that
        # measurement with headroom; the compaction budget must clear it.
        measured_fixed_overhead = 25_429
        window = WindowInfo(
            reported_tokens=102400,
            effective_tokens=71680,
            source="model_self_report",
            chars_per_token=ccc.formatted_chars_per_token,
        )
        budget = int(window.to_chars(window.effective_tokens) * 0.8 * 0.7)
        assert budget > measured_fixed_overhead * 2, (budget, measured_fixed_overhead)


# ─────────────────────────────────────────────────────────────────────────────
# 6a-4 — keep_recent must leave something to compress
# ─────────────────────────────────────────────────────────────────────────────


class TestGroupCounting:
    def test_plain_messages_are_one_group_each(self):
        msgs = [Msg("user", "a", "user") for _ in range(5)]
        assert count_message_groups(msgs) == 5

    def test_tool_use_result_pair_is_one_group(self):
        use = Msg(
            "assistant",
            [
                {
                    "type": "tool_use",
                    "id": "call_1",
                    "name": "read_file",
                    "input": {},
                },
            ],
            "assistant",
        )
        result = Msg(
            "system",
            [
                {
                    "type": "tool_result",
                    "id": "call_1",
                    "name": "read_file",
                    "content": "x" * 88_000,
                },
            ],
            "system",
        )
        msgs = [Msg("user", "q", "user"), use, result]
        assert count_message_groups(msgs) == 2

    def test_unpaired_tool_use_still_closes_a_group(self):
        """Upstream only *accumulates* tool_result ids, never tool_use ids.

        A tool_use whose result is missing does not hold the counter open:
        it closes a group like any plain message.  The replica must
        reproduce that, not an idealised pairing.
        """
        use = Msg(
            "assistant",
            [{"type": "tool_use", "id": "call_9", "name": "x", "input": {}}],
            "assistant",
        )
        assert count_message_groups([Msg("user", "q", "user"), use]) == 2

    def test_trailing_lone_result_leaves_no_closed_group(self):
        """Scanned newest-first, an unmatched tool_result holds the tail open."""
        result = Msg(
            "system",
            [
                {
                    "type": "tool_result",
                    "id": "call_7",
                    "name": "x",
                    "content": "y",
                },
            ],
            "system",
        )
        assert count_message_groups([Msg("user", "q", "user"), result]) == 0

    def test_empty_list(self):
        assert count_message_groups([]) == 0


class TestCompressiblePrefix:
    """The prefix upstream compresses is the whole decision."""

    def test_prefix_is_the_messages_before_the_kept_groups(self):
        msgs = [Msg("user", f"m{i}", "user") for i in range(5)]
        assert compressible_prefix_count(msgs, 3) == 2

    def test_groups_equal_keep_recent_compresses_nothing(self):
        """The cliff: the break lands on index 0, so the prefix is empty."""
        msgs = [Msg("user", f"m{i}", "user") for i in range(3)]
        assert compressible_prefix_count(msgs, 3) == 0

    def test_fewer_groups_than_keep_recent_compresses_everything(self):
        msgs = [Msg("user", f"m{i}", "user") for i in range(3)]
        assert compressible_prefix_count(msgs, 12) == 3

    def test_keep_recent_one_keeps_only_the_last_group(self):
        msgs = [Msg("user", f"m{i}", "user") for i in range(5)]
        assert compressible_prefix_count(msgs, 1) == 4


class TestCompressibilityFloor:
    @staticmethod
    def _agent(total: int, trigger: int):
        class _Snap:
            total_chars = total
            trigger_chars = trigger

        class _Guard:
            last_snapshot = _Snap()

        class _Agent:
            context_guard = _Guard()

        return _Agent()

    @staticmethod
    def _ccc():
        return RunningConfig().light_context_config.context_compact_config

    @pytest.mark.asyncio
    async def test_keep_recent_drops_on_the_cliff(self):
        from coapis.agents.context.light_context_manager import (
            LightContextManager,
        )

        memory = InMemoryMemory()
        for i in range(3):
            await memory.add(Msg("user", f"m{i}", "user"))
        agent = self._agent(total=90_000, trigger=20_000)
        keep = await LightContextManager._compressibility_floor(
            agent,
            memory,
            3,
            self._ccc(),
        )
        assert keep == 2

    @pytest.mark.asyncio
    async def test_untouched_under_the_trigger(self):
        from coapis.agents.context.light_context_manager import (
            LightContextManager,
        )

        memory = InMemoryMemory()
        for i in range(3):
            await memory.add(Msg("user", f"m{i}", "user"))
        agent = self._agent(total=1_000, trigger=20_000)
        keep = await LightContextManager._compressibility_floor(
            agent,
            memory,
            3,
            self._ccc(),
        )
        assert keep == 3

    @pytest.mark.asyncio
    async def test_untouched_when_the_prefix_is_already_compressible(self):
        from coapis.agents.context.light_context_manager import (
            LightContextManager,
        )

        memory = InMemoryMemory()
        for i in range(3):
            await memory.add(Msg("user", f"m{i}", "user"))
        agent = self._agent(total=90_000, trigger=20_000)
        keep = await LightContextManager._compressibility_floor(
            agent,
            memory,
            12,
            self._ccc(),
        )
        assert keep == 12

    @pytest.mark.asyncio
    async def test_untouched_with_nothing_to_compress(self):
        from coapis.agents.context.light_context_manager import (
            LightContextManager,
        )

        memory = InMemoryMemory()
        await memory.add(Msg("user", "m", "user"))
        agent = self._agent(total=90_000, trigger=20_000)
        keep = await LightContextManager._compressibility_floor(
            agent,
            memory,
            1,
            self._ccc(),
        )
        assert keep == 1

    @pytest.mark.asyncio
    async def test_no_snapshot_is_untouched(self):
        from coapis.agents.context.light_context_manager import (
            LightContextManager,
        )

        class _Agent:
            context_guard = None

        memory = InMemoryMemory()
        await memory.add(Msg("user", "m", "user"))
        keep = await LightContextManager._compressibility_floor(
            _Agent(),
            memory,
            12,
            self._ccc(),
        )
        assert keep == 12


# ─────────────────────────────────────────────────────────────────────────────
# Wiring
# ─────────────────────────────────────────────────────────────────────────────


class TestWiring:
    def test_guard_builder_passes_the_ratio(self):
        window = _window()
        guard = build_budget_guard(
            _FakeModel(),
            window,
            compaction_input_ratio=0.42,
        )
        assert guard.compaction_input_ratio == 0.42

    def test_min_row_floor_is_exported(self):
        assert MIN_ROW_CHARS == 400

    def test_react_agent_wires_the_config(self):
        source = (
            Path(__file__).resolve().parents[2]
            / "coapis"
            / "agents"
            / "react_agent.py"
        ).read_text(encoding="utf-8")
        assert "compaction_input_ratio=_ccc.compaction_input_ratio" in source
