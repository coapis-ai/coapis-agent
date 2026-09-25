# -*- coding: utf-8 -*-
"""Add token columns to external_bindings (B 方案).

The external-system access token / refresh token / expiry previously lived
inside the ``extra_data`` JSON blob. They are promoted to first-class
columns so token refreshes become atomic column updates and auditing is
trivial:

* ``external_access_token``  — 当前有效的外部系统 token（列即权威）
* ``external_refresh_token`` — 刷新令牌（如有）
* ``token_expires_at``       — ISO-8601 过期时间（空串 = 未知）
* ``token_updated_at``       — ISO-8601 最近一次落库时间

Upgrade behaviour:

* fresh database  → 0001 already created the table from the updated
  metadata, so ``add_column`` is skipped (existence-checked);
* legacy database → columns are added (dialect-neutral, SQLite ≥3.35 and
  PostgreSQL both support plain ADD COLUMN with server defaults), then
  any token values sitting in ``extra_data`` are moved into the columns
  and removed from the blob (one-time, idempotent).

Revision ID: 0002
Revises: 0001
Create Date: 2026-09-24
"""

import json
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = "0002"
down_revision: Union[str, None] = "0001"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

# (column name, extra_data dict key)
_TOKEN_COLUMNS = (
    ("external_access_token", "token"),
    ("external_refresh_token", "refresh_token"),
    ("token_expires_at", "expires_at"),
    ("token_updated_at", "token_updated_at"),
)


def _existing_columns(bind) -> set:
    return {
        c["name"]
        for c in sa.inspect(bind).get_columns("external_bindings")
    }


def upgrade() -> None:
    bind = op.get_bind()
    cols = _existing_columns(bind)

    for col_name, _key in _TOKEN_COLUMNS:
        if col_name in cols:
            continue
        op.add_column(
            "external_bindings",
            sa.Column(
                col_name,
                sa.Text(),
                nullable=False,
                server_default=sa.text("''"),
            ),
        )

    # One-time backfill: move token values out of extra_data into the
    # new columns (only rows where the column is still empty, i.e.
    # legacy rows written before this migration).
    rows = bind.execute(
        sa.text(
            "SELECT id, extra_data, "
            "external_access_token, external_refresh_token, "
            "token_expires_at, token_updated_at "
            "FROM external_bindings"
        )
    ).fetchall()

    for row in rows:
        rid = row[0]
        try:
            extra = json.loads(row[1] or "{}")
        except (TypeError, ValueError):
            continue
        if not isinstance(extra, dict):
            continue

        changed = False
        new_extra = dict(extra)
        for col_idx, (col_name, key) in enumerate(_TOKEN_COLUMNS, start=2):
            cur = row[col_idx]
            legacy_val = extra.get(key)
            if (cur in (None, "")) and legacy_val not in (None, ""):
                bind.execute(
                    sa.text(
                        f"UPDATE external_bindings SET {col_name} = :val "
                        "WHERE id = :rid"
                    ),
                    {"val": str(legacy_val), "rid": rid},
                )
                new_extra.pop(key, None)
                changed = True

        if changed:
            bind.execute(
                sa.text(
                    "UPDATE external_bindings SET extra_data = :extra "
                    "WHERE id = :rid"
                ),
                {
                    "extra": json.dumps(new_extra, ensure_ascii=False),
                    "rid": rid,
                },
            )


def downgrade() -> None:
    bind = op.get_bind()
    cols = _existing_columns(bind)
    for col_name, _key in reversed(_TOKEN_COLUMNS):
        if col_name in cols:
            op.drop_column("external_bindings", col_name)
