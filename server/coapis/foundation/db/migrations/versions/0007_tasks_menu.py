# -*- coding: utf-8 -*-
"""Insert the 'tasks' main-menu tag (v2.2.2 task center shell page).

Adds a top-level navigation item ``tasks-menu`` (name=任务, icon=RocketOutlined,
sort_order=9 — between 会话中心(8) and 工作台(10)). Idempotent: skips when the
row already exists.

Revision ID: 0007
Revises: 0006
Create Date: 2026-10-03
"""

import json
from datetime import datetime, timezone
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = "0007"
down_revision: Union[str, None] = "0006"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

TASKS_TAG_ID = "tasks-menu"


def _now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def upgrade() -> None:
    conn = op.get_bind()
    row = conn.execute(sa.text("SELECT 1 FROM tags WHERE id = :id"), {"id": TASKS_TAG_ID}).first()
    if row is None:
        now = _now_iso()
        meta = json.dumps(
            {"path": "/tasks", "permission": "", "isActive": True},
            ensure_ascii=False,
        )
        conn.execute(
            sa.text(
                "INSERT INTO tags "
                "(id, name, icon, type, parent_id, description, keywords, "
                "related_skills, sort_order, show_in_menu, enabled, category, "
                "metadata, created_at, updated_at) "
                "VALUES (:id, :name, :icon, 'menu', NULL, :desc, '[]', '[]', "
                ":sort, 1, 1, '', :meta, :now, :now)"
            ),
            {
                "id": TASKS_TAG_ID,
                "name": "任务",
                "icon": "RocketOutlined",
                "desc": "任务中心：长任务执行概览",
                "sort": 9,
                "meta": meta,
                "now": now,
            },
        )


def downgrade() -> None:
    conn = op.get_bind()
    conn.execute(sa.text("DELETE FROM tags WHERE id = :id"), {"id": TASKS_TAG_ID})
