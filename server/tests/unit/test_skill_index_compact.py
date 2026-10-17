"""S1: compact skill index (manager-only) contract tests.

Run from the repo root:
    .venv-test/bin/python -m pytest server/tests/unit/test_skill_index_compact.py
"""
from __future__ import annotations

from types import SimpleNamespace

from agentscope.tool import Toolkit

from coapis.agents.react_agent import CoApisAgent


def _agent(n_skills: int, *, compact=None, language: str = "zh"):
    """Minimal stand-in carrying only what ``_build_skill_index`` reads."""
    toolkit = Toolkit()
    for i in range(n_skills):
        toolkit.skills[f"skill-{i:02d}"] = {
            "name": f"skill-{i:02d}",
            "description": "d" * 400,  # upstream would dump all of this
            "dir": f"/apps/ai/coapis/workspaces/admin/skills/skill-{i:02d}",
        }
    running = SimpleNamespace()
    if compact is not None:
        running.skill_index_compact = compact
    return SimpleNamespace(
        toolkit=toolkit,
        _language=language,
        _agent_config=SimpleNamespace(running=running),
    )


def test_compact_index_is_dramatically_smaller():
    agent = _agent(36)
    compact = CoApisAgent._build_skill_index(agent)
    upstream = agent.toolkit.get_agent_skill_prompt() or ""
    assert compact, "compact index must not be empty"
    assert len(compact) < len(upstream) * 0.3, (
        f"compact {len(compact)} chars vs upstream {len(upstream)} chars"
    )


def test_compact_index_keeps_every_skill_name():
    agent = _agent(36)
    compact = CoApisAgent._build_skill_index(agent)
    for i in range(36):
        assert f"`skill-{i:02d}`" in compact, "visibility is the whole point"


def test_compact_index_points_at_the_skill_manager():
    agent = _agent(3)
    compact = CoApisAgent._build_skill_index(agent)
    assert "skill_manager" in compact
    assert "info" in compact


def test_compact_index_drops_descriptions_and_dirs():
    agent = _agent(5)
    compact = CoApisAgent._build_skill_index(agent)
    assert "d" * 400 not in compact
    assert "/apps/ai/coapis/workspaces" not in compact, (
        "absolute skill dirs are prompt weight the model never uses"
    )


def test_kill_switch_restores_upstream_index():
    agent = _agent(12, compact=False)
    compact = CoApisAgent._build_skill_index(agent)
    upstream = agent.toolkit.get_agent_skill_prompt() or ""
    assert compact == upstream


def test_no_skills_yields_empty_index():
    agent = _agent(0)
    assert CoApisAgent._build_skill_index(agent) == ""
    assert agent.toolkit.get_agent_skill_prompt() is None


def test_english_language_gets_english_index():
    agent = _agent(4, language="en")
    compact = CoApisAgent._build_skill_index(agent)
    assert "Available skills" in compact
    assert "技能正文" not in compact


def test_default_is_compact_when_config_omits_the_flag():
    # ``running`` without the attribute must default to compact (the flag is
    # additive; older configs keep working and get the saving).
    agent = _agent(20)
    compact = CoApisAgent._build_skill_index(agent)
    upstream = agent.toolkit.get_agent_skill_prompt() or ""
    assert len(compact) < len(upstream) * 0.3
