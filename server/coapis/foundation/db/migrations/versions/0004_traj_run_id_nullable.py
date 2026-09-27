# -*- coding: utf-8 -*-
"""Allow NULL run_id on agent_trajectories (online samples).

Benchmark trajectories link to an ``agent_runs`` row; online sampled
trajectories (written by ``agent_eval/telemetry_hook.py``) have no run and
must be storable with ``run_id = NULL`` so the weekly miner can query them
with ``WHERE run_id IS NULL``.

Revision ID: 0004
Revises: 0003
Create Date: 2026-09-27
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = "0004"
down_revision: Union[str, None] = "0003"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # batch mode: SQLite cannot ALTER COLUMN in place; PostgreSQL uses the
    # native ALTER TABLE ... ALTER COLUMN ... DROP NOT NULL path.
    with op.batch_alter_table("agent_trajectories") as batch:
        batch.alter_column("run_id", existing_type=sa.Integer(), nullable=True)


def downgrade() -> None:
    # Restore NOT NULL only if no NULL rows exist (they cannot be filled).
    bind = op.get_bind()
    cnt = bind.execute(sa.text(
        "SELECT COUNT(*) FROM agent_trajectories WHERE run_id IS NULL"
    )).scalar()
    if cnt == 0:
        with op.batch_alter_table("agent_trajectories") as batch:
            batch.alter_column("run_id", existing_type=sa.Integer(), nullable=False)
