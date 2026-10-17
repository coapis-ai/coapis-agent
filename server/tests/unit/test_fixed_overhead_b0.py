# -*- coding: utf-8 -*-
"""Tests for B0: deferred plan tools, slim catalog, slim skill index,
fixed-overhead constraint."""
from __future__ import annotations

import json
from types import SimpleNamespace
from pathlib import Path

import pytest
from agentscope.plan import PlanNotebook
from agentscope.tool import Toolkit

from coapis.agents.context.fixed_overhead import (
    LEVER_GROUPS,
    LEVER_PLAN,
    LEVER_SKILLS,
    enforce_fixed_overhead,
    latest_reports,
    measure_fixed_overhead,
)
from coapis.agents.react_agent import CoApisAgent
from coapis.agents.tools.groups import (
    GROUP_META_DESCRIPTION,
    TOOL_GROUPS,
)
from coapis.skills.manager import SKILL_INDEX_HINT_CHARS, skill_index_hint


class FakeAgent:
    """A stand-in with the three things the guard reads: prompt, toolkit,
    notebook.  The plan-registration methods are borrowed from CoApisAgent
    verbatim, so the test exercises the production code path."""

    PLAN_CORE_TOOLS = CoApisAgent.PLAN_CORE_TOOLS
    _register_plan_tools = CoApisAgent._register_plan_tools
    _on_plan_change_equip_tools = CoApisAgent._on_plan_change_equip_tools
    _equip_lazy_plan_tools = CoApisAgent._equip_lazy_plan_tools

    def __init__(self, *, sys_prompt_chars: int = 1000) -> None:
        self.agent_id = "b0-test"
        self._namesake_strategy = "rename"
        self.toolkit = Toolkit()
        self.plan_notebook = PlanNotebook()
        self.cur_iter = 0
        self.sys_prompt = "x" * sys_prompt_chars


def _fake_agent(*, sys_prompt_chars: int = 1000) -> FakeAgent:
    return FakeAgent(sys_prompt_chars=sys_prompt_chars)


def _schema_names(toolkit: Toolkit) -> set[str]:
    return {s["function"]["name"] for s in toolkit.get_json_schemas()}


class TestDeferredPlanTools:
    """B0-1: eight plan tools were paid on every turn; six of them only
    become meaningful once a plan exists."""

    def test_only_core_two_at_init(self):
        agent = _fake_agent()
        agent._register_plan_tools(agent.plan_notebook.list_tools())
        names = _schema_names(agent.toolkit)
        assert {"create_plan", "finish_plan"} <= names
        lazy = {
            "view_subtasks",
            "update_subtask_state",
            "finish_subtask",
            "revise_current_plan",
            "view_historical_plans",
            "recover_historical_plan",
        }
        assert not (names & lazy), f"lazy plan tools leaked into step 1: {names & lazy}"

    @pytest.mark.asyncio
    async def test_equipped_when_a_plan_exists(self):
        agent = _fake_agent()
        agent._register_plan_tools(agent.plan_notebook.list_tools())
        from agentscope.plan import SubTask

        await agent.plan_notebook.create_plan(
            name="B0 测试计划",
            description="验证延迟注册",
            expected_outcome="六个记账工具出现在 schema 里",
            subtasks=[
                SubTask(name="甲", description="做甲", expected_outcome="甲完成"),
            ],
        )
        names = _schema_names(agent.toolkit)
        assert {"revise_current_plan", "finish_subtask", "view_subtasks"} <= names

    def test_restored_plan_equips_at_init(self):
        agent = _fake_agent()
        from agentscope.plan import Plan, SubTask

        agent.plan_notebook.current_plan = Plan(
            name="恢复的计划",
            description="会话恢复时已有计划",
            expected_outcome="记账工具立即可用",
            subtasks=[SubTask(name="甲", description="a", expected_outcome="b")],
        )
        agent._register_plan_tools(agent.plan_notebook.list_tools())
        names = _schema_names(agent.toolkit)
        assert "revise_current_plan" in names

    def test_equip_is_idempotent(self):
        agent = _fake_agent()
        agent._register_plan_tools(agent.plan_notebook.list_tools())
        agent._equip_lazy_plan_tools("first")
        first = len(_schema_names(agent.toolkit))
        agent._equip_lazy_plan_tools("second")
        assert len(_schema_names(agent.toolkit)) == first


class TestSlimCatalog:
    """B0-3: the group catalog is paid on every turn."""

    def test_group_descriptions_are_short(self):
        long = {
            name: spec["description"]
            for name, spec in TOOL_GROUPS.items()
            if len(spec["description"]) > 60
        }
        assert not long, f"group descriptions over 60 chars: {long}"

    def test_meta_description_beats_upstream_docstring(self):
        upstream = len(Toolkit().reset_equipped_tools.__doc__ or "")
        assert 0 < len(GROUP_META_DESCRIPTION) < upstream
        assert "ABSOLUTE" in GROUP_META_DESCRIPTION


class TestSlimSkillIndex:
    """B0-4: the index line is paid on every turn; the body is read on
    demand."""

    def test_hint_prefers_index_hint(self):
        skill = {
            "name": "s",
            "description": "Use this skill when …" + "x" * 400,
            "index_hint": "短触发语",
        }
        assert skill_index_hint(skill) == "短触发语"

    def test_description_truncated_to_cap(self):
        skill = {"name": "s", "description": "y" * 400}
        hint = skill_index_hint(skill)
        assert len(hint) <= SKILL_INDEX_HINT_CHARS
        assert hint.endswith("…")

    def test_cap_skill_index_shortens_registered_skill(self, tmp_path: Path):
        skill_dir = tmp_path / "demo"
        skill_dir.mkdir()
        (skill_dir / "SKILL.md").write_text(
            "---\nname: demo\ndescription: "
            + "这是一段很长的技能描述，用于验证索引瘦身。" * 8
            + "\n---\nbody\n",
            encoding="utf-8",
        )
        toolkit = Toolkit()
        toolkit.register_agent_skill(str(skill_dir))
        before = len(toolkit.skills["demo"]["description"])
        CoApisAgent._cap_skill_index(toolkit, "demo")
        after = len(toolkit.skills["demo"]["description"])
        assert after < before
        assert after <= SKILL_INDEX_HINT_CHARS

    def test_index_hint_frontmatter_parsed(self):
        content = "---\nname: a\nindex_hint: 触发条件\n---\nbody\n"
        from coapis.skills.manager import SkillManager

        assert SkillManager._parse_index_hint(content) == "触发条件"
        assert SkillManager._parse_index_hint("no frontmatter") == ""


class TestFixedOverheadGuard:
    """B0/D8: the fixed share is a constraint with an action."""

    def test_under_cap_does_nothing(self):
        agent = _fake_agent(sys_prompt_chars=1000)
        agent._register_plan_tools(agent.plan_notebook.list_tools())
        report = enforce_fixed_overhead(agent, 10_000, max_ratio=0.40)
        assert report.shed == []
        assert report.total_chars == report.sys_prompt_chars + report.tools_schema_chars
        assert 0 < report.ratio < 0.40

    def test_measure_counts_prompt_and_schema(self):
        agent = _fake_agent(sys_prompt_chars=2000)
        agent._register_plan_tools(agent.plan_notebook.list_tools())
        report = measure_fixed_overhead(agent, 10_000)
        assert report.sys_prompt_chars == 2000
        assert report.tools_schema_chars > 1000

    def test_sheds_groups_first(self):
        agent = _fake_agent(sys_prompt_chars=1000)

        def _dummy_tool(text: str) -> str:
            """Dummy tool for the group-shed measurement."""
            return text

        for name, spec in TOOL_GROUPS.items():
            if spec.get("always_active"):
                continue
            agent.toolkit.create_tool_group(
                name,
                description=spec["description"],
                active=True,
            )
            # A deactivated group only leaves the schema when it carries
            # tools; without them the lever has nothing to take away.
            agent.toolkit.register_tool_function(
                _dummy_tool,
                group_name=name,
                func_name=f"dummy_{name}",
            )
        agent.toolkit.register_tool_function(
            agent.toolkit.reset_equipped_tools,
            func_description=GROUP_META_DESCRIPTION,
        )
        before = measure_fixed_overhead(agent, 10_000)
        report = enforce_fixed_overhead(agent, 10_000, max_ratio=0.10)
        assert report.shed[0] == LEVER_GROUPS
        assert report.total_chars < before.total_chars
        active = [
            n
            for n, spec in TOOL_GROUPS.items()
            if not spec.get("always_active")
            and getattr(agent.toolkit.groups.get(n), "active", False)
        ]
        assert active == []

    def test_ladder_reaches_plan_tools_and_skills(self):
        agent = _fake_agent(sys_prompt_chars=9_000)
        agent._register_plan_tools(agent.plan_notebook.list_tools())
        # A plan exists, so the bookkeeping tools are in the schema; the
        # guard may drop them and must re-arm the hook that brings them back.
        agent._equip_lazy_plan_tools("test: plan in place")
        agent.toolkit.skills["s1"] = {
            "name": "s1",
            "description": "x" * 500,
            "dir": "/tmp/s1",
        }
        report = enforce_fixed_overhead(agent, 10_000, max_ratio=0.50)
        assert LEVER_PLAN in report.shed
        assert LEVER_SKILLS in report.shed
        assert report.shed.index(LEVER_PLAN) < report.shed.index(LEVER_SKILLS)
        assert "revise_current_plan" not in _schema_names(agent.toolkit)
        assert agent.toolkit.skills["s1"]["description"] == ""
        # The deferred set is re-armed so a plan brings the tools back.
        assert agent._plan_lazy_tools

    def test_zero_ratio_disables_guard(self):
        agent = _fake_agent(sys_prompt_chars=9_000)
        report = enforce_fixed_overhead(agent, 10_000, max_ratio=0.0)
        assert report.shed == []

    def test_diagnostics_reports_latest_reading(self):
        agent = _fake_agent(sys_prompt_chars=1_000)
        enforce_fixed_overhead(agent, 10_000, max_ratio=0.40)
        reports = latest_reports()
        assert "b0-test" in reports
        row = reports["b0-test"]
        assert row["sys_prompt_chars"] == 1_000
        assert "ratio" in row and "history_share" in row and "shed" in row


class TestConfigContract:
    def test_fixed_overhead_fields_exist(self):
        from coapis.config.config import ContextCompactConfig

        cc = ContextCompactConfig()
        # 拍板 E1 (2026-10-17): 35% fixed / 45% history.
        assert cc.fixed_overhead_max_ratio == 0.35
        assert cc.min_history_share == 0.45
        assert 0 < cc.compaction_input_ratio < 1


class _FakeMemory:
    def __init__(self, messages: list) -> None:
        self._messages = messages

    async def get_memory(self, prepend_summary: bool = False, **_: object) -> list:
        return list(self._messages)


class _HookAgent:
    """Everything ``pre_reasoning`` touches, and nothing else.

    The hook is the only consumer of the fixed-overhead guard at runtime, and
    the two bugs this test locks out (``cc`` for the compact config,
    ``window.effective_chars``) were both invisible to the direct-call tests:
    they are attribute-name errors in the *wiring*, and a wiring error that
    raises inside ``pre_reasoning`` kills every reply in the deployment.
    """

    def __init__(self, *, sys_prompt_chars: int, toolkit: Toolkit) -> None:
        self.agent_id = "b0-hook"
        self.sys_prompt = "x" * sys_prompt_chars
        self.toolkit = toolkit
        self.cur_iter = 0
        self.model = object()
        self.memory = _FakeMemory(
            [SimpleNamespace(role="user", content="hi"),
             SimpleNamespace(role="assistant", content="ok")],
        )
        self.compression_config = SimpleNamespace(enable=True, keep_recent=12)
        self.context_guard = None


def _run_hook(monkeypatch, agent, *, effective_tokens: int = 65_536):
    from coapis.agents.context import light_context_manager as lcm
    from coapis.agents.context.window_source import WindowInfo
    from coapis.config.config import AgentsRunningConfig

    monkeypatch.setattr(
        lcm,
        "load_agent_config",
        lambda _agent_id: SimpleNamespace(running=AgentsRunningConfig()),
    )
    monkeypatch.setattr(
        lcm,
        "resolve_for_model",
        lambda *_a, **_k: WindowInfo(
            reported_tokens=None,
            effective_tokens=effective_tokens,
            source="config_fallback",
            chars_per_token=1.1,
        ),
    )
    manager = lcm.LightContextManager(working_dir="/tmp", agent_id="b0-hook")
    return manager, lcm


@pytest.mark.asyncio
async def test_pre_reasoning_runs_the_guard(monkeypatch):
    agent = _HookAgent(sys_prompt_chars=1_000, toolkit=Toolkit())
    manager, _ = _run_hook(monkeypatch, agent)
    assert await manager.pre_reasoning(agent, {}) is None
    reports = latest_reports()
    assert "b0-hook" in reports
    assert reports["b0-hook"]["window_chars"] == 72_089  # 65536 * 1.1


@pytest.mark.asyncio
async def test_pre_reasoning_sheds_when_over_cap(monkeypatch):
    # 40,000 fixed chars against a 72,089-char window = 55% > the 35% cap.
    agent = _HookAgent(sys_prompt_chars=40_000, toolkit=Toolkit())
    # A skill index is the lever this stand-in can fire: it is the last one
    # in the ladder, so the test also proves the ladder reaches it.
    agent.toolkit.skills = {
        "demo": {"name": "demo", "description": "d" * 200, "dir": "/tmp"},
    }
    manager, _ = _run_hook(monkeypatch, agent)
    await manager.pre_reasoning(agent, {})
    report = latest_reports()["b0-hook"]
    assert report["ratio"] > 0.35
    assert report["shed"] == [LEVER_SKILLS], f"levers fired: {report['shed']}"
    assert agent.toolkit.skills["demo"]["description"] == ""


@pytest.mark.asyncio
async def test_guard_failure_never_kills_the_turn(monkeypatch):
    """A broken guard must not propagate: pre_reasoning sits on the reply path."""
    agent = _HookAgent(sys_prompt_chars=1_000, toolkit=Toolkit())
    manager, lcm = _run_hook(monkeypatch, agent)
    monkeypatch.setattr(
        lcm,
        "enforce_fixed_overhead",
        lambda *_a, **_k: (_ for _ in ()).throw(RuntimeError("boom")),
    )
    assert await manager.pre_reasoning(agent, {}) is None
