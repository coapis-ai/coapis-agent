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


class SubTaskResponse(BaseModel):
    """A single subtask in the plan response."""

    name: str
    description: str
    expected_outcome: str
    outcome: str | None = None
    state: Literal["todo", "in_progress", "done", "abandoned"] = "todo"
    created_at: str | None = None
    finished_at: str | None = None


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
