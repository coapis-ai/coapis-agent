# -*- coding: utf-8 -*-
"""Agent capability evaluation tables (M0).

Creates ``agent_tasks`` / ``agent_runs`` / ``agent_trajectories``.

Idempotent: each table creation is guarded by an existence check so the
migration is safe on both fresh databases (where ``create_all`` from the
updated metadata may already have created them) and upgraded ones.

Revision ID: 0003
Revises: 0002
Create Date: 2026-09-26
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = "0003"
down_revision: Union[str, None] = "0002"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _existing_tables(bind) -> set:
    insp = sa.inspect(bind)
    return set(insp.get_table_names())


def upgrade() -> None:
    bind = op.get_bind()
    have = _existing_tables(bind)

    if "agent_tasks" not in have:
        op.create_table(
            "agent_tasks",
            sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
            sa.Column("task_uid", sa.Text(), nullable=False),
            sa.Column("title", sa.Text(), nullable=False),
            sa.Column("category", sa.Text(), nullable=False),
            sa.Column("difficulty", sa.Integer(), nullable=False, server_default="1"),
            sa.Column("spec", sa.Text(), nullable=False),
            sa.Column("created_at", sa.Float()),
            sa.UniqueConstraint("task_uid", name="ix_agent_tasks_task_uid"),
        )
        op.create_index("ix_agent_tasks_task_uid_uq", "agent_tasks", ["task_uid"], unique=True)
        op.create_index("ix_agent_tasks_category", "agent_tasks", ["category"])

    if "agent_runs" not in have:
        op.create_table(
            "agent_runs",
            sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
            sa.Column("task_uid", sa.Text(), nullable=False),
            sa.Column("agent_id", sa.Text(), nullable=False),
            sa.Column("started_at", sa.Float()),
            sa.Column("finished_at", sa.Float()),
            sa.Column("duration_ms", sa.Integer()),
            sa.Column("success", sa.Boolean()),
            sa.Column("score", sa.Float()),
            sa.Column("verdict", sa.Text()),
            sa.Column("metrics", sa.Text()),
            sa.Column("trajectory_id", sa.Integer()),
            sa.Column("notes", sa.Text()),
        )
        op.create_index("ix_agent_runs_task_uid", "agent_runs", ["task_uid"])
        op.create_index("ix_agent_runs_agent_started", "agent_runs", ["agent_id", "started_at"])

    if "agent_trajectories" not in have:
        op.create_table(
            "agent_trajectories",
            sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
            sa.Column("run_id", sa.Integer(), nullable=False),
            sa.Column("steps", sa.Integer()),
            sa.Column("tool_calls", sa.Integer()),
            sa.Column("llm_calls", sa.Integer()),
            sa.Column("input_tokens", sa.Integer(), server_default="0"),
            sa.Column("output_tokens", sa.Integer(), server_default="0"),
            sa.Column("cost_cents", sa.Float(), server_default="0"),
            sa.Column("trace", sa.Text()),
            sa.Column("final_answer", sa.Text()),
        )
        op.create_index("ix_agent_trajectories_run_id", "agent_trajectories", ["run_id"])


def downgrade() -> None:
    bind = op.get_bind()
    have = _existing_tables(bind)
    for idx, tbl in (
        ("ix_agent_trajectories_run_id", "agent_trajectories"),
        ("ix_agent_runs_agent_started", "agent_runs"),
        ("ix_agent_runs_task_uid", "agent_runs"),
        ("ix_agent_tasks_category", "agent_tasks"),
        ("ix_agent_tasks_task_uid_uq", "agent_tasks"),
    ):
        if tbl in have:
            op.drop_index(idx, table_name=tbl)
    for tbl in ("agent_trajectories", "agent_runs", "agent_tasks"):
        if tbl in have:
            op.drop_table(tbl)
