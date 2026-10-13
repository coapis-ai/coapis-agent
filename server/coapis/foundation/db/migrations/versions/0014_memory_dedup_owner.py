# -*- coding: utf-8 -*-
"""memories: recompute dedup_key with the owner included.

Root cause being fixed: ``dedup_key`` was
``sha256(scope|category|title|normalized_content)`` with **no owner**
component, while the UNIQUE constraint on ``dedup_key`` is global. Two
consequences:

* identical rows from different owners collide on INSERT (IntegrityError)
  — this is what crashed the nightly dream whenever two agents produced the
  same outcome on the same day;
* ``add()`` looks up dedup_key globally, so a second writer's memory
  collapses into the first writer's row and is attributed to the wrong owner.

This migration recomputes every key with the owner component
(``user_id`` for scope=user, ``agent_id`` for scope=agent, ``workspace_id``
for scope=workspace, falling back to user_id when the scope's own identity is
empty). Recomputing can create new collisions between rows that were distinct
only by owner-less keys; those are merged into the earliest row (importance
takes the max) and the duplicates are deleted.

Revision ID: 0014
Revises: 0013
Create Date: 2026-10-12
"""
from __future__ import annotations

import hashlib
import re
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0014"
down_revision: Union[str, None] = "0013"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _normalize(text) -> str:
    if not text:
        return ""
    return re.sub(r"\s+", " ", str(text).strip()).lower()


def _owner(scope: str, user_id: str, agent_id, workspace_id) -> str:
    if scope == "agent":
        return agent_id or user_id or ""
    if scope == "workspace":
        return workspace_id or user_id or ""
    return user_id or ""


def _key(owner: str, scope: str, category: str, title, content) -> str:
    raw = "|".join([owner, scope, category, _normalize(title), _normalize(content)])
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def upgrade() -> None:
    bind = op.get_bind()
    rows = bind.execute(sa.text(
        "select id, scope, user_id, agent_id, workspace_id, category, "
        "title, content, importance from memories order by id"
    )).fetchall()

    keeper: dict[str, int] = {}  # new key -> surviving row id
    for (rid, scope, user_id, agent_id, workspace_id, category,
          title, content, importance) in rows:
        key = _key(_owner(scope, user_id, agent_id, workspace_id),
                   scope, category, title, content)
        if key in keeper:
            # Merge into the earliest row: importance takes the max, then the
            # duplicate goes away so the new UNIQUE constraint holds.
            keep = keeper[key]
            bind.execute(sa.text(
                "update memories set importance = :imp where id = :kid"
            ), {"imp": max(float(importance or 0.5), 0.5), "kid": keep})
            bind.execute(sa.text(
                "delete from memories where id = :rid"
            ), {"rid": rid})
        else:
            keeper[key] = rid
            bind.execute(sa.text(
                "update memories set dedup_key = :key where id = :rid"
            ), {"key": key, "rid": rid})


def downgrade() -> None:
    # Keys revert to the owner-less formula; merged duplicates cannot be
    # restored, so downgrade is key-only.
    bind = op.get_bind()
    rows = bind.execute(sa.text(
        "select id, scope, category, title, content from memories order by id"
    )).fetchall()
    for (rid, scope, category, title, content) in rows:
        raw = "|".join([scope, category, _normalize(title), _normalize(content)])
        bind.execute(sa.text(
            "update memories set dedup_key = :key where id = :rid"
        ), {"key": hashlib.sha256(raw.encode("utf-8")).hexdigest(), "rid": rid})
