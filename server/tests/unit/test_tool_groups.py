"""ToolManager (tool groups) tests.

Covers the mechanism the ToolManager relies on plus the two regressions it
must not introduce:
  - the group table must cover the live tool registry (an ungrouped tool lands
    in the always-active core group and silently inflates every step);
  - ``reset_equipped_tools`` has absolute semantics (groups absent from a call
    are deactivated) — pre-activation is step-1 only;
  - Mission Mode must hand migrated tools back to their original groups.

Run: pytest tests/test_tool_groups.py -q
"""

import json
import os
import sys
import warnings

warnings.filterwarnings("ignore")

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "server"))

import pytest  # noqa: E402
from agentscope.tool import Toolkit  # noqa: E402

from coapis.agents.tools.groups import (  # noqa: E402
    TOOL_GROUPS,
    TOOL_GROUP_MAP,
    active_groups_for_query,
    build_tool_group_map,
    group_of,
    is_always_active,
    validate_against_registry,
)
from coapis.agents.tools.registry import get_registered_tools  # noqa: E402

MAX_DESCRIPTION_CHARS = 170


def _build_toolkit(groups_enabled=True, with_meta=True):
    """Build a toolkit the way ``_create_toolkit`` does."""
    reg = get_registered_tools()
    toolkit = Toolkit()
    if groups_enabled:
        for group_name, spec in TOOL_GROUPS.items():
            if spec.get("always_active"):
                continue  # ``basic`` is built in; upstream refuses to create it
            toolkit.create_tool_group(
                group_name,
                description=spec["description"],
                active=False,
            )
    for name, registration in reg.items():
        toolkit.register_tool_function(
            registration.func,
            group_name=group_of(name) if groups_enabled else "basic",
            namesake_strategy="skip",
        )
    if with_meta and groups_enabled:
        toolkit.register_tool_function(
            toolkit.reset_equipped_tools,
            namesake_strategy="skip",
        )
    return toolkit


def _schema_chars(toolkit):
    return len(json.dumps(toolkit.get_json_schemas(), ensure_ascii=False))


def _tool_names(toolkit):
    return {s["function"]["name"] for s in toolkit.get_json_schemas()}


# ── table integrity ──────────────────────────────────────────────────────


def test_group_table_covers_registry():
    reg = set(get_registered_tools())
    drift = validate_against_registry(reg)
    assert not drift["missing"], (
        "registered tools without a group would land in the always-active "
        f"core group: {drift['missing']}"
    )
    assert not drift["extra"], f"stale group rows: {drift['extra']}"


def test_group_map_is_derived_from_groups():
    assert TOOL_GROUP_MAP == build_tool_group_map()
    assert group_of("no_such_tool") == "basic"


def test_group_descriptions_are_short():
    """The catalog is generated from group descriptions, so length is cost."""
    for group_name, spec in TOOL_GROUPS.items():
        desc = spec["description"]
        assert desc and desc.strip(), f"{group_name} has an empty description"
        assert len(desc) <= MAX_DESCRIPTION_CHARS, (
            f"{group_name} description is {len(desc)} chars "
            f"(> {MAX_DESCRIPTION_CHARS}); the catalog is paid for on every step"
        )


def test_only_basic_is_always_active():
    always = [g for g in TOOL_GROUPS if is_always_active(g)]
    assert always == ["basic"], f"always-active groups: {always}"
    assert all(not spec["keywords"] for g, spec in TOOL_GROUPS.items()
               if spec["always_active"]), "always-active groups need no keywords"


def test_every_group_has_keywords():
    for group_name, spec in TOOL_GROUPS.items():
        if spec["always_active"]:
            continue
        assert spec["keywords"], f"{group_name} can never be pre-activated"


# ── mechanism ────────────────────────────────────────────────────────────


def test_grouped_tools_hidden_until_activated():
    toolkit = _build_toolkit()
    assert "browser_use" not in _tool_names(toolkit)
    toolkit.update_tool_groups(["browser"], active=True)
    assert "browser_use" in _tool_names(toolkit)


def test_core_tools_always_visible():
    toolkit = _build_toolkit()
    names = _tool_names(toolkit)
    for tool in ("read_file", "write_file", "edit_file", "grep_search"):
        assert tool in names, f"{tool} must stay in the core group"


def test_reset_equipped_tools_is_absolute():
    """Groups absent from the call are deactivated — pre-activation is step 1 only."""
    toolkit = _build_toolkit()
    toolkit.update_tool_groups(["web", "shell"], active=True)
    assert {"web_search", "execute_shell_command"} <= _tool_names(toolkit)

    toolkit.reset_equipped_tools(web=True)
    names = _tool_names(toolkit)
    assert "web_search" in names
    assert "execute_shell_command" not in names, (
        "reset_equipped_tools must deactivate groups it does not mention"
    )


def test_meta_tool_catalog_lists_groups():
    toolkit = _build_toolkit()
    meta = next(
        s for s in toolkit.get_json_schemas()
        if s["function"]["name"] == "reset_equipped_tools"
    )
    props = meta["function"]["parameters"]["properties"]
    for group_name, spec in TOOL_GROUPS.items():
        if spec["always_active"]:
            assert group_name not in props, "always-active groups must not be in the catalog"
            continue
        assert group_name in props, f"{group_name} missing from the catalog"
        assert props[group_name]["description"] == spec["description"]


def test_grouping_shrinks_step_one_schema():
    """The whole point: step 1 must be dramatically cheaper than the full set."""
    full = _build_toolkit(groups_enabled=False, with_meta=False)
    grouped = _build_toolkit()
    full_chars, grouped_chars = _schema_chars(full), _schema_chars(grouped)
    assert grouped_chars < full_chars * 0.5, (
        f"grouped {grouped_chars} chars vs full {full_chars} chars — "
        "expected step 1 to drop by more than half"
    )


def test_kill_switch_restores_full_schema():
    off = _build_toolkit(groups_enabled=False, with_meta=True)
    assert "browser_use" in _tool_names(off)
    # With grouping off there is nothing to equip, so no meta tool is exposed.
    assert "reset_equipped_tools" not in _tool_names(off)
    assert set(off.groups) <= {"basic"}


# ── pre-activation ───────────────────────────────────────────────────────


@pytest.mark.parametrize(
    "query,expected",
    [
        ("帮我搜索一下最新的新闻", ["web"]),
        ("部署到生产环境并重启容器", ["shell"]),
        ("打开浏览器测试登录页面", ["browser"]),
        ("读取这个 pdf 文档", ["docs"]),
        ("把这段流程沉淀成技能", ["skills"]),
        ("今天天气怎么样", []),
        ("", []),
    ],
)
def test_preactivation_matches_keywords(query, expected):
    hits = active_groups_for_query(query)
    for group_name in expected:
        assert group_name in hits, f"{query!r} should pre-activate {group_name}"
    if query == "今天天气怎么样" or query == "":
        assert hits == []


def test_preactivation_never_returns_always_active_groups():
    for query in ("执行命令", "搜索", "浏览器", "文档", "技能"):
        assert "basic" not in active_groups_for_query(query)


# ── mission mode interaction ─────────────────────────────────────────────


def test_mission_returns_tools_to_original_groups():
    from coapis.agents.mission.mission_runner import (
        IMPLEMENTATION_TOOLS,
        MISSION_IMPL_GROUP,
        migrate_tools_to_group,
        restore_tools,
    )

    toolkit = _build_toolkit()
    agent = type("A", (), {"toolkit": toolkit})()
    agent._mission_tool_ownership = {}

    original = {
        name: toolkit.tools[name].group
        for name in IMPLEMENTATION_TOOLS
        if name in toolkit.tools
    }
    assert original, "implementation tools must be registered for this test"

    migrate_tools_to_group(agent)
    for name in original:
        assert toolkit.tools[name].group == MISSION_IMPL_GROUP

    toolkit.update_tool_groups([MISSION_IMPL_GROUP], active=False)
    for name in original:
        assert name not in _tool_names(toolkit), f"{name} must be hidden in Phase 2"

    restore_tools(agent)
    for name, group_name in original.items():
        assert toolkit.tools[name].group == group_name, (
            f"{name} stranded in {toolkit.tools[name].group} instead of {group_name}"
        )
    assert agent._mission_tool_ownership == {}

    # After restore, the model can reach the tools through their own groups.
    toolkit.reset_equipped_tools(browser=True, shell=True)
    assert "execute_shell_command" in _tool_names(toolkit)
    assert "browser_use" in _tool_names(toolkit)


def test_mission_migrate_is_idempotent():
    from coapis.agents.mission.mission_runner import (
        IMPLEMENTATION_TOOLS,
        MISSION_IMPL_GROUP,
        migrate_tools_to_group,
    )

    toolkit = _build_toolkit()
    agent = type("A", (), {"toolkit": toolkit})()
    migrate_tools_to_group(agent)
    migrate_tools_to_group(agent)
    assert MISSION_IMPL_GROUP in toolkit.groups
    for name in IMPLEMENTATION_TOOLS:
        if name in toolkit.tools:
            assert toolkit.tools[name].group == MISSION_IMPL_GROUP


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-q"]))
