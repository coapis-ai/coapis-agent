# -*- coding: utf-8 -*-
"""Add created_at / duration_ms to agent_trajectories.

The router (``/admin/agent-eval/trajectories``) and the weekly miner
(``agent_eval/miner.py``) order/filter trajectories by creation time and
render their wall-clock duration, but the M0 table shipped without these
columns, causing 500s. Timestamps follow the data-layer convention:
Unix epoch floats (REAL).

Revision ID: 0005
Revises: 0004
Create Date: 2026-09-27
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = "0005"
down_revision: Union[str, None] = "0004"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Guard: on a fresh database, 0001 creates tables from the *current* ORM
    # models, which already carry these columns — blind add_column would
    # raise "duplicate column name". Only add what is actually missing.
    bind = op.get_bind()
    existing = {c["name"] for c in sa.inspect(bind).get_columns("agent_trajectories")}
    missing = [
        sa.Column("duration_ms", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.Float(), nullable=True),
    ]
    missing = [c for c in missing if c.name not in existing]
    if missing:
        with op.batch_alter_table("agent_trajectories") as batch:
            for col in missing:
                batch.add_column(col)


def downgrade() -> None:
    with op.batch_alter_table("agent_trajectories") as batch:
        batch.drop_column("created_at")
        batch.drop_column("duration_ms")
