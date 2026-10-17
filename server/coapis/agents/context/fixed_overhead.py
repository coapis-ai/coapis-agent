# -*- coding: utf-8 -*-
"""Fixed-overhead guard (B0 / D8, 2026-10-17).

Measured on dev: the fixed part of a request — system prompt plus tool
schemas — is **54,900 chars of a 58,000-char window (95%)** before a single
turn of history is counted.  The budget guard treated fixed overhead as a
number it reported: it logged, it shrank the compaction input, it never
touched the overhead itself.  A guard that only reports is how a 97% fixed
share stayed invisible for as long as it did.

This module turns the ratio into a constraint with an action.  When the
fixed part exceeds its share of the window, the cheapest levers get pulled
in a fixed order — tool groups first (they are the part the model can
re-equip by itself), then the deferred plan tools, then the skill index —
and the numbers are logged so the operator sees what was being paid for.

The caps are the 拍板 E1 values (35% fixed, 45% history): they are the
floor under which the session stops being a conversation, not a target to
optimise towards.
"""
from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger(__name__)

#: Levers in the order they get pulled.  Cheapest for the model first: a
#: deactivated group is one ``reset_equipped_tools`` call away from coming
#: back, a removed plan tool is re-registered the moment a plan exists, and
#: only the skill index is a real loss (the model stops knowing a skill
#: exists), so it goes last.
LEVER_GROUPS = "tool_groups"
LEVER_PLAN = "plan_tools"
LEVER_SKILLS = "skill_index"
LEVERS = (LEVER_GROUPS, LEVER_PLAN, LEVER_SKILLS)

#: Diagnostics registry: agent_id -> last report.  In-memory on purpose —
#: this is a live reading of what a session is paying for, not history.
_REPORTS: dict[str, "FixedOverheadReport"] = {}
_MAX_REPORTS = 64


@dataclass
class FixedOverheadReport:
    """One reading of what the fixed part of a request costs."""

    agent_id: str = ""
    window_chars: int = 0
    sys_prompt_chars: int = 0
    tools_schema_chars: int = 0
    group_costs: dict[str, int] = field(default_factory=dict)
    shed: list[str] = field(default_factory=list)
    max_ratio: float = 0.35
    min_history_share: float = 0.45

    @property
    def total_chars(self) -> int:
        return self.sys_prompt_chars + self.tools_schema_chars

    @property
    def ratio(self) -> float:
        if self.window_chars <= 0:
            return 0.0
        return self.total_chars / self.window_chars

    @property
    def history_share(self) -> float:
        """What is left for the conversation once the fixed part is paid."""
        if self.window_chars <= 0:
            return 0.0
        return max(0.0, 1.0 - self.ratio)

    def as_dict(self) -> dict[str, Any]:
        return {
            "agent_id": self.agent_id,
            "window_chars": self.window_chars,
            "sys_prompt_chars": self.sys_prompt_chars,
            "tools_schema_chars": self.tools_schema_chars,
            "total_chars": self.total_chars,
            "ratio": round(self.ratio, 4),
            "history_share": round(self.history_share, 4),
            "max_ratio": self.max_ratio,
            "min_history_share": self.min_history_share,
            "group_costs": dict(self.group_costs),
            "shed": list(self.shed),
        }


def measure_fixed_overhead(agent: Any, window_chars: int) -> FixedOverheadReport:
    """Measure the fixed part of the next request for *agent*."""
    report = FixedOverheadReport(
        agent_id=str(getattr(agent, "agent_id", "") or ""),
        window_chars=int(window_chars),
    )
    try:
        prompt = getattr(agent, "sys_prompt", "")
        if callable(prompt):
            prompt = prompt()
        report.sys_prompt_chars = len(prompt or "")
    except Exception:
        logger.debug("fixed-overhead: sys prompt unreadable", exc_info=True)
    try:
        schemas = agent.toolkit.get_json_schemas()
        report.tools_schema_chars = len(
            json.dumps(schemas, ensure_ascii=False, separators=(",", ":")),
        )
        report.group_costs = _group_costs(schemas)
    except Exception:
        logger.debug("fixed-overhead: tool schema unreadable", exc_info=True)
    return report


def _group_costs(schemas: list) -> dict[str, int]:
    """What each *active* tool group costs the model, in schema characters.

    The diagnostics endpoint has to answer "which group is worth unloading",
    and that is a per-group number, not the total: on dev the browser group
    alone was 8,603 of 29,260 schema chars.
    """
    try:
        from ..tools.groups import group_of
    except Exception:  # pragma: no cover - import cycle guard
        return {}
    costs: dict[str, int] = {}
    for schema in schemas:
        fn = schema.get("function", {}) if isinstance(schema, dict) else {}
        name = str(fn.get("name", "") or "")
        if not name:
            continue
        blob = json.dumps(schema, ensure_ascii=False, separators=(",", ":"))
        group = group_of(name)
        costs[group] = costs.get(group, 0) + len(blob)
    return dict(sorted(costs.items(), key=lambda kv: -kv[1]))


def _shed_groups(agent: Any) -> bool:
    """Deactivate every optional tool group.  The model can re-equip them."""
    toolkit = getattr(agent, "toolkit", None)
    if toolkit is None:
        return False
    try:
        from ..tools.groups import TOOL_GROUPS

        optional = [
            name
            for name, spec in TOOL_GROUPS.items()
            if not spec.get("always_active")
        ]
        active = [
            name
            for name in optional
            if getattr(toolkit.groups.get(name), "active", False)
        ]
        if not active:
            return False
        toolkit.update_tool_groups(active, active=False)
        return True
    except Exception:
        logger.debug("fixed-overhead: group shed failed", exc_info=True)
        return False


def _shed_plan_tools(agent: Any) -> bool:
    """Drop the deferred plan tools again (the hook re-adds them per plan)."""
    toolkit = getattr(agent, "toolkit", None)
    if toolkit is None:
        return False
    try:
        core = getattr(type(agent), "PLAN_CORE_TOOLS", frozenset())
        names = [
            s.get("function", {}).get("name", "")
            for s in toolkit.get_json_schemas()
        ]
        victims = [n for n in names if n and n not in core and _is_plan_tool(n)]
        if not victims:
            return False
        for name in victims:
            toolkit.remove_tool_function(name)
        # Re-arm the plan-change hook so they come back when a plan exists.
        planner = getattr(agent, "plan_notebook", None)
        if planner is not None and hasattr(agent, "_plan_lazy_tools"):
            agent._plan_lazy_tools = [
                fn
                for fn in planner.list_tools()
                if fn.__name__ in victims
            ]
            try:
                planner.register_plan_change_hook(
                    "coapis_lazy_plan_tools",
                    agent._on_plan_change_equip_tools,
                )
            except Exception:
                logger.debug("plan hook re-arm skipped", exc_info=True)
        return True
    except Exception:
        logger.debug("fixed-overhead: plan shed failed", exc_info=True)
        return False


def _is_plan_tool(name: str) -> bool:
    return name in {
        "create_plan",
        "revise_current_plan",
        "finish_subtask",
        "update_subtask_state",
        "view_subtasks",
        "view_historical_plans",
        "recover_historical_plan",
    }


def _shed_skill_index(agent: Any) -> bool:
    """Shrink the skill index to names (the body stays readable on disk)."""
    toolkit = getattr(agent, "toolkit", None)
    skills = getattr(toolkit, "skills", None) if toolkit else None
    if not isinstance(skills, dict) or not skills:
        return False
    shrunk = 0
    for entry in skills.values():
        desc = entry.get("description", "") or ""
        if len(desc) > 1:
            entry["description"] = ""
            shrunk += 1
    return shrunk > 0


_LEVERS = {
    LEVER_GROUPS: _shed_groups,
    LEVER_PLAN: _shed_plan_tools,
    LEVER_SKILLS: _shed_skill_index,
}


def enforce_fixed_overhead(
    agent: Any,
    window_chars: int,
    *,
    max_ratio: float = 0.35,
    min_history_share: float = 0.45,
) -> FixedOverheadReport:
    """Pull levers until the fixed part fits its share of the window.

    Returns the report for this turn (measured after any shedding).  Logs at
    INFO when a lever fires — the point of this guard is that the operator
    sees the bill, not that it silently gets paid.
    """
    report = measure_fixed_overhead(agent, window_chars)
    report.max_ratio = max_ratio
    report.min_history_share = min_history_share

    if report.window_chars <= 0:
        _remember(report)
        return report

    if report.ratio <= max_ratio:
        _remember(report)
        return report

    before = report.ratio
    shed: list[str] = []
    for lever in LEVERS:
        fired = _LEVERS[lever](agent)
        if not fired:
            continue
        shed.append(lever)
        # Re-measure: the whole point of the ladder is to stop as soon as
        # the bill fits, not to pull every lever because we started.
        report = measure_fixed_overhead(agent, window_chars)
        report.max_ratio = max_ratio
        report.min_history_share = min_history_share
        if report.ratio <= max_ratio:
            break
    report.shed = shed

    logger.info(
        "fixed-overhead: agent '%s' fixed %d/%d chars (%.1f%% > cap %.0f%%); "
        "shed %s -> now %d chars (%.1f%%), history share %.1f%%",
        report.agent_id,
        int(before * report.window_chars),
        report.window_chars,
        before * 100,
        max_ratio * 100,
        ", ".join(report.shed) if report.shed else "nothing (no lever left)",
        report.total_chars,
        report.ratio * 100,
        report.history_share * 100,
    )
    _remember(report)
    return report


def _remember(report: FixedOverheadReport) -> None:
    key = report.agent_id or "_"
    _REPORTS[key] = report
    if len(_REPORTS) > _MAX_REPORTS:
        for stale in list(_REPORTS)[: len(_REPORTS) - _MAX_REPORTS]:
            _REPORTS.pop(stale, None)


def latest_reports() -> dict[str, dict[str, Any]]:
    """Diagnostics view: last fixed-overhead reading per agent."""
    return {k: v.as_dict() for k, v in _REPORTS.items()}


__all__ = [
    "FixedOverheadReport",
    "enforce_fixed_overhead",
    "latest_reports",
    "measure_fixed_overhead",
]
