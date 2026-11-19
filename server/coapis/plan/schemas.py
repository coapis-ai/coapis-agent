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

"""Pydantic response schemas for plan API endpoints."""
from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field


_MISSING_OUTCOME_WORDS = {
    "done",
    "completed",
    "finish",
    "finished",
    "ok",
    "success",
    "成功",
    "完成",
    "已完成",
    "好了",
    "搞定",
    "无",
    "-",
    "n/a",
    "na",
}


def outcome_pending(expected: str | None, outcome: str | None, state: str) -> bool:
    """True when a step ended without telling the user what came out of it.

    2026-11-19 (计划执行能力优化) — 「步骤显示完成、结果什么都没有」是用户能
    直接看见的问题：模型常把 ``finish_subtask`` 的 outcome 留空或写成
    ``done``。这类步骤不能算真正交付，UI 要标成「结果待补」而不是绿勾，
    模型侧也才能在计划文本里看到缺口（见 ``plan.hints``）。
    """
    if state not in ("done", "abandoned"):
        return False
    text = (outcome or "").strip()
    if not text:
        return True
    if text.lower() in _MISSING_OUTCOME_WORDS:
        return True
    # 只复述承诺、没有新信息的产出同样不算交付
    promised = (expected or "").strip()
    if promised and text == promised:
        return True
    return False


class SubTaskResponse(BaseModel):
    """A single subtask in the plan response."""

    name: str
    description: str
    expected_outcome: str
    outcome: str | None = None
    state: Literal["todo", "in_progress", "done", "abandoned"] = "todo"
    created_at: str | None = None
    finished_at: str | None = None
    #: 已完成但没记录可用结果 —— UI 显示「结果待补」而非绿勾。
    outcome_pending: bool = False


class PlanStateResponse(BaseModel):
    """Top-level plan state returned by ``GET /plan/current``."""

    id: str
    name: str
    description: str
    expected_outcome: str
    state: Literal["todo", "in_progress", "done", "abandoned"] = "todo"
    subtasks: list[SubTaskResponse] = Field(default_factory=list)
    created_at: str | None = None
    finished_at: str | None = None
    outcome: str | None = None
    #: True when the plan lifecycle has ended (the runtime cleared
    #: ``current_plan`` after ``finish_plan``) but the final snapshot is
    #: still being served so the UI can show a completed plan.
    finished: bool = False


class PlanConfigResponse(BaseModel):
    """Plan configuration returned/accepted by config endpoints."""

    enabled: bool = False


def plan_to_response(plan) -> PlanStateResponse:
    """Convert an AgentScope ``Plan`` object to a ``PlanStateResponse``."""
    subtasks = [
        SubTaskResponse(
            name=st.name,
            description=st.description,
            expected_outcome=st.expected_outcome,
            outcome=st.outcome,
            state=st.state,
            created_at=st.created_at,
            finished_at=st.finished_at,
            outcome_pending=outcome_pending(
                st.expected_outcome,
                st.outcome,
                st.state,
            ),
        )
        for st in plan.subtasks
    ]
    return PlanStateResponse(
        id=plan.id,
        name=plan.name,
        description=plan.description,
        expected_outcome=plan.expected_outcome,
        state=plan.state,
        subtasks=subtasks,
        created_at=plan.created_at,
        finished_at=plan.finished_at,
        outcome=plan.outcome,
    )
