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
    with op.batch_alter_table("agent_trajectories") as batch:
        batch.add_column(sa.Column("duration_ms", sa.Integer(), nullable=True))
        batch.add_column(sa.Column("created_at", sa.Float(), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("agent_trajectories") as batch:
        batch.drop_column("created_at")
        batch.drop_column("duration_ms")
