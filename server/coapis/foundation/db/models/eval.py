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

"""Agent evaluation models (capability-evaluation M0).

Tables:
* ``agent_tasks``      – benchmark task definitions (seeded from YAML dataset)
* ``agent_runs``       – one row per task execution, with scoring result
* ``agent_trajectories`` – per-run trace (steps, tool calls, tokens, raw trace)

Conventions matched to the rest of the data layer:
* integer PK autoincrement, ``nullable=False`` (T3 lesson)
* timestamps are Unix epoch floats (REAL) like ``token_usage.created_at``
* cost stored as cents (REAL) like ``token_usage.cost_cents``
* JSON blobs as Text with ``ensure_ascii=False`` dumps
"""

from __future__ import annotations

from typing import Optional

from sqlalchemy import Boolean, Float, Index, Integer, Text
from sqlalchemy.orm import Mapped, mapped_column

from ..base import BaseRow


class AgentTask(BaseRow):
    """A benchmark task definition."""

    __tablename__ = "agent_tasks"

    id: Mapped[int] = mapped_column(
        Integer, primary_key=True, autoincrement=True, nullable=False
    )
    task_uid: Mapped[str] = mapped_column(Text, nullable=False)
    title: Mapped[str] = mapped_column(Text, nullable=False)
    category: Mapped[str] = mapped_column(Text, nullable=False)
    difficulty: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    # JSON: {"user_turns": [...], "expected_tools": [...], "checks": {...}}
    spec: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[Optional[float]] = mapped_column(Float)

    __table_args__ = (
        Index("ix_agent_tasks_task_uid", "task_uid", unique=True),
        Index("ix_agent_tasks_category", "category"),
    )


class AgentRun(BaseRow):
    """One execution of a task by an agent."""

    __tablename__ = "agent_runs"

    id: Mapped[int] = mapped_column(
        Integer, primary_key=True, autoincrement=True, nullable=False
    )
    task_uid: Mapped[str] = mapped_column(Text, nullable=False)
    agent_id: Mapped[str] = mapped_column(Text, nullable=False)
    started_at: Mapped[Optional[float]] = mapped_column(Float)
    finished_at: Mapped[Optional[float]] = mapped_column(Float)
    duration_ms: Mapped[Optional[int]] = mapped_column(Integer)
    success: Mapped[Optional[bool]] = mapped_column(Boolean)
    score: Mapped[Optional[float]] = mapped_column(Float)
    verdict: Mapped[Optional[str]] = mapped_column(Text)  # pass/fail/partial
    # JSON: per-checker breakdown + judge rationale
    metrics: Mapped[Optional[str]] = mapped_column(Text)
    trajectory_id: Mapped[Optional[int]] = mapped_column(Integer)
    notes: Mapped[Optional[str]] = mapped_column(Text)

    __table_args__ = (
        Index("ix_agent_runs_task_uid", "task_uid"),
        Index("ix_agent_runs_agent_started", "agent_id", "started_at"),
    )


class AgentTrajectory(BaseRow):
    """Trace captured during one run."""

    __tablename__ = "agent_trajectories"

    id: Mapped[int] = mapped_column(
        Integer, primary_key=True, autoincrement=True, nullable=False
    )
    # NULL = online sampled trajectory (no benchmark run); the weekly miner
    # queries these with ``run_id IS NULL``.
    run_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    steps: Mapped[Optional[int]] = mapped_column(Integer)
    tool_calls: Mapped[Optional[int]] = mapped_column(Integer)
    llm_calls: Mapped[Optional[int]] = mapped_column(Integer)
    input_tokens: Mapped[Optional[int]] = mapped_column(Integer, default=0)
    output_tokens: Mapped[Optional[int]] = mapped_column(Integer, default=0)
    cost_cents: Mapped[Optional[float]] = mapped_column(Float, default=0.0)
    # JSON: ordered [{step, role, tool?, args_digest, ok}]
    trace: Mapped[Optional[str]] = mapped_column(Text)
    final_answer: Mapped[Optional[str]] = mapped_column(Text)
    duration_ms: Mapped[Optional[int]] = mapped_column(Integer)
    created_at: Mapped[Optional[float]] = mapped_column(Float)

    __table_args__ = (Index("ix_agent_trajectories_run_id", "run_id"),)
