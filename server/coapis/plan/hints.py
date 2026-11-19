# -*- coding: utf-8 -*-
# -*- coding: utf-8 -*-
# Copyright 2026 蜜蜂 & CoApis Contributors
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU Affero General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU Affero General Public License for more details.
#
# You should have received a copy of the GNU Affero General Public License
# along with this program.  If not, see <https://www.gnu.org/licenses/>.

"""Custom plan-to-hint generator for CoApis.

Differences from AgentScope's DefaultPlanToHint:

1. Confirmation step — after creating a plan the agent must present it and
   wait for user approval before execution.
2. Scoped ``no_plan`` hint — only injected when the runner has set the
   plan tool gate (explicit ``/plan`` entry), so normal chat is unaffected.
3. Compact plan text — completed subtask outcomes are dropped from the hint
   so per-iteration context cost stays constant.
4. Properly handles abandoned subtasks in all hint branches.
"""
from __future__ import annotations

import logging
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from agentscope.plan import Plan

logger = logging.getLogger(__name__)

try:
    from agentscope.plan._plan_notebook import DefaultPlanToHint

    _HAS_DEFAULT_HINT = True
except ImportError:
    _HAS_DEFAULT_HINT = False

_DESC_LIMIT = 80
_PLAN_DESC_LIMIT = 200


def set_plan_gate(  # pylint: disable=protected-access
    plan_notebook,
    enabled: bool = True,
) -> None:
    """Activate or deactivate the plan tool gate on *plan_notebook*."""
    if plan_notebook is not None:
        plan_notebook._plan_tool_gate = enabled


def check_plan_tool_gate(  # pylint: disable=protected-access
    plan_notebook,
    tool_name: str,
):
    """Return an error string if *tool_name* must be blocked, else ``None``.

    When a ``/plan`` request is pending (gate set by the runner), only
    ``create_plan`` may run.  The gate is cleared once a plan exists.
    """
    if plan_notebook is None:
        return None
    if plan_notebook.current_plan is not None:
        if getattr(plan_notebook, "_plan_tool_gate", False):
            plan_notebook._plan_tool_gate = False
        return None
    if not getattr(plan_notebook, "_plan_tool_gate", False):
        return None
    if tool_name == "create_plan":
        return None
    return (
        f"Tool '{tool_name}' is not available right now. "
        "You MUST call 'create_plan' first to define the plan and its "
        "subtasks. Decompose the user's request into a logical pipeline: "
        "each subtask needs a clear name, description, and measurable "
        "expected_outcome. Write plan text in the same language as the "
        "user's request."
    )


def should_skip_auto_continue(  # pylint: disable=protected-access
    plan_notebook,
) -> bool:
    """True when auto-continue must be suppressed for the current turn.

    After ``create_plan`` or ``revise_current_plan`` the notebook sets
    ``_plan_just_mutated`` so the agent can present the plan and wait for
    confirmation without auto-continue injecting an extra reasoning pass.
    """
    if plan_notebook is None:
        return False

    val = bool(getattr(plan_notebook, "_plan_just_mutated", False))
    if val:
        plan_notebook._plan_just_mutated = False
        return True

    if (
        bool(getattr(plan_notebook, "_plan_recently_finished", False))
        and not bool(getattr(plan_notebook, "_plan_tool_gate", False))
        and getattr(plan_notebook, "current_plan", None) is None
    ):
        return True

    return False


def _clip(text: str, limit: int) -> str:
    text = (text or "").strip().replace("\n", " ")
    if len(text) > limit:
        return text[: limit - 3] + "..."
    return text


def _compact_plan_text(plan: "Plan") -> str:
    """Build a compact representation of *plan*.

    2026-11-19 (计划执行能力优化) — 这一版同时服务于"结果必须可见"：

    * ``todo`` 步骤带 ``Expected``，模型在开工前就知道"做完"的标准是什么；
    * ``done`` 步骤带 ``Outcome``（模型此前**从未**在计划里看到产出字段，
      自然不会去填它——这是"步骤显示完成、结果什么都没有"的上游根因）；
    * 产出缺失时明写 ``Outcome: (missing)``，把缺口暴露在模型眼前，
      而不是静默省略。
    """
    desc = _clip(plan.description, _PLAN_DESC_LIMIT)

    lines = [
        f"# {plan.name}",
        f"Description: {desc}",
        f"State: {plan.state}",
        "## Subtasks",
    ]
    for i, st in enumerate(plan.subtasks):
        if st.state in ("done", "abandoned"):
            lines.append(f"  {i}. [{st.state}] {st.name}")
            outcome = _clip(st.outcome, _DESC_LIMIT)
            if outcome:
                lines.append(f"     Outcome: {outcome}")
            else:
                lines.append("     Outcome: (missing - state the concrete result)")
        elif st.state == "in_progress":
            lines.append(f"  {i}. [in_progress] {st.name}")
            lines.append(f"     Desc: {_clip(st.description, _DESC_LIMIT)}")
            lines.append(f"     Expected: {_clip(st.expected_outcome, _DESC_LIMIT)}")
        else:
            lines.append(f"  {i}. [todo] {st.name}")
            lines.append(f"     Desc: {_clip(st.description, _DESC_LIMIT)}")
            expected = _clip(st.expected_outcome, _DESC_LIMIT)
            if expected:
                lines.append(f"     Expected: {expected}")
    return "\n".join(lines)


def _count_states(plan: "Plan"):
    """Return (n_todo, n_ip, n_done, n_abn, ip_idx)."""
    n_todo = n_ip = n_done = n_abn = 0
    ip_idx = None
    for idx, st in enumerate(plan.subtasks):
        if st.state == "todo":
            n_todo += 1
        elif st.state == "in_progress":
            n_ip += 1
            ip_idx = idx
        elif st.state == "done":
            n_done += 1
        elif st.state == "abandoned":
            n_abn += 1
    return n_todo, n_ip, n_done, n_abn, ip_idx


_LANG_BLOCK = (
    "Language consistency: write all plan-visible text (subtask names, "
    "descriptions, outcomes, summaries) in the same language as the user's "
    "recent messages.\n\n"
)

if _HAS_DEFAULT_HINT:

    class SimplePlanToHint(DefaultPlanToHint):
        """Simplified plan hint generator with confirmation flow."""

        at_the_beginning: str = (
            "The current plan:\n```\n{plan}\n```\n"
            + _LANG_BLOCK
            + "Check the user's LATEST message:\n"
            "- If it is a confirmation (go ahead, start, yes, ok, confirm, "
            "begin, execute, proceed — in any language), IMMEDIATELY call "
            "'update_subtask_state' with subtask_idx=0 and "
            "state='in_progress', then begin executing it.\n"
            "- If the user asks to modify or change the plan in any way, "
            "call 'finish_plan' with state='abandoned' first, then call "
            "'create_plan' to build a completely new plan incorporating the "
            "user's changes. Do NOT use 'revise_current_plan' here.\n"
            "- If the user cancels, call 'finish_plan' with "
            "state='abandoned'.\n"
            "\n"
            "Only if the plan was JUST created and the user has NOT seen it, "
            "present this plan and ask the user to confirm, edit, or cancel. "
            "Do NOT execute any subtask until the user confirms.\n"
        )

        when_a_subtask_in_progress: str = (
            "The current plan:\n```\n{plan}\n```\n"
            + _LANG_BLOCK
            + "Subtask {subtask_idx} ('{subtask_name}') is in_progress.\n"
            "Execute this subtask:\n"
            "1. Each turn: short text + at least one tool call.\n"
            "2. When objective is met, call 'finish_subtask'. Its outcome is "
            "the RESULT the user will read: state the concrete deliverable "
            "(file path, command output, measured number or conclusion) in "
            "the user's language, in one sentence. Never leave it empty and "
            "never write a placeholder such as 'done' or 'completed'.\n"
            "3. If stuck after a few tries, call 'finish_subtask' with a "
            "partial outcome that says what was achieved and what is still "
            "missing.\n"
            "CRITICAL: Do NOT reply with text only — the ReAct loop stops "
            "without a tool call.\n"
        )

        when_no_subtask_in_progress: str = (
            "The current plan:\n```\n{plan}\n```\n"
            + _LANG_BLOCK
            + "The first {index} subtask(s) are finished and no subtask is "
            "currently in_progress.\n"
            "Call 'update_subtask_state' to mark the next todo subtask as "
            "'in_progress' and continue with tools for that subtask.\n"
            "CRITICAL: Include a tool call — text-only replies end the run.\n"
        )

        at_the_end: str = (
            "The current plan:\n```\n{plan}\n```\n"
            + _LANG_BLOCK
            + "All subtasks are complete. Call 'finish_plan' with "
            "state='done' and an outcome summary that reports, in the user's "
            "language: what was delivered (files, links, numbers) and which "
            "step, if any, ended without a recorded result.\n"
            "CRITICAL: Include a 'finish_plan' tool call.\n"
        )

        auto_no_plan: str = (
            "This turn was classified as a multi-step task, but no plan "
            "exists yet.\n"
            + _LANG_BLOCK
            + "Call 'create_plan' first: decompose the request into ordered "
            "subtasks, each with a name, a description and a measurable "
            "expected_outcome. Then start the first subtask right away; no "
            "user confirmation is required.\n"
        )


        no_plan: str | None = (
            "There is no active plan yet.\n"
            + _LANG_BLOCK
            + "Call 'create_plan' to decompose the user's request into a "
            "structured plan with subtasks. Each subtask needs: name, "
            "description, expected_outcome. Order by dependency.\n"
            "After 'create_plan' succeeds, present the plan and wait for "
            "user confirmation.\n"
        )

        at_the_beginning_after_mutation: str = (
            "The current plan:\n```\n{plan}\n```\n"
            + _LANG_BLOCK
            + "This plan was JUST created or revised. Present the plan to "
            "the user and ask them to confirm, edit, or cancel.\n"
            "Do NOT call 'revise_current_plan' again — the user has not "
            "responded to the updated plan yet.\n"
            "Do NOT execute any subtask until the user confirms.\n"
        )

        recently_finished_guard: str | None = (
            "There is no active plan now.\n"
            + _LANG_BLOCK
            + "The previous plan was finished or cancelled. Do NOT continue "
            "old plan subtasks.\n"
            "Check the user's LATEST message:\n"
            "- If the user asked to modify, change, or redo the plan, call "
            "'create_plan' to build a new plan based on the user's changes.\n"
            "- Otherwise, answer the user's latest message directly without "
            "creating a plan.\n"
        )

        def _hint_no_plan(self, nb) -> str | None:
            """Select hint when there is no active plan."""
            if nb is not None and getattr(nb, "_plan_tool_gate", False):
                return self.no_plan
            if nb is not None and getattr(nb, "_plan_auto_hint", False):
                return self.auto_no_plan

            if nb is not None and getattr(
                nb,
                "_plan_recently_finished",
                False,
            ):
                return self.recently_finished_guard
            return None

        def _hint_with_plan(self, plan: "Plan", nb) -> str | None:
            """Select hint when a plan is active."""
            _, n_ip, n_done, n_abn, ip_idx = _count_states(plan)
            just_mutated = nb is not None and getattr(
                nb,
                "_plan_just_mutated",
                False,
            )

            if n_ip == 0 and n_done == 0 and n_abn == 0:
                tmpl = (
                    self.at_the_beginning_after_mutation
                    if just_mutated
                    else self.at_the_beginning
                )
                return tmpl.format(plan=plan.to_markdown())

            if n_ip > 0 and ip_idx is not None:
                return self.when_a_subtask_in_progress.format(
                    plan=_compact_plan_text(plan),
                    subtask_idx=ip_idx,
                    subtask_name=plan.subtasks[ip_idx].name,
                    subtask=plan.subtasks[ip_idx].to_markdown(detailed=True),
                )

            if n_done + n_abn == len(plan.subtasks):
                return self.at_the_end.format(plan=_compact_plan_text(plan))

            if n_ip == 0 and (n_done + n_abn) > 0:
                return self.when_no_subtask_in_progress.format(
                    plan=_compact_plan_text(plan),
                    index=n_done + n_abn,
                )

            return None

        def __call__(self, plan: "Plan | None") -> str | None:
            nb = getattr(self, "_bound_notebook", None)
            if nb is not None:
                nb = nb() if callable(nb) else nb

            hint = (
                self._hint_no_plan(nb)
                if plan is None
                else self._hint_with_plan(plan, nb)
            )

            if hint:
                return f"{self.hint_prefix}{hint}{self.hint_suffix}"
            return hint

        def bind_notebook(self, plan_notebook) -> None:
            """Store a weak reference to the notebook for gate checks."""
            import weakref

            if plan_notebook is None:
                self._bound_notebook = None
            else:
                self._bound_notebook = weakref.ref(plan_notebook)

else:
    SimplePlanToHint = None  # type: ignore[misc,assignment]
