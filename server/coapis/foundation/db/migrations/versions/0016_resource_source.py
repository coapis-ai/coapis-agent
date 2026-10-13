# -*- coding: utf-8 -*-
"""resources: add ``source`` (台账行的来源).

``register(source=...)`` 这个参数一直存在，但表里没有对应列——传进去就被丢掉，
于是"这行台账是谁写的"无从回答：工具调用登记的、还是巡检补登记的历史存量。
补登记（backfill）上线后这个区分变成必须：审计时要能回答"这 200 行里哪些是
补出来的、哪些是真被会话引用过的"。

既有行统一回填为 ``hook`` 不对——它们其实来源不明，但 ``hook`` 是这张表上线
以来唯一的写入路径（除 reconcile 外），所以按 ``hook`` 落；新写入按实际来源。

Revision ID: 0016
Revises: 0015
Create Date: 2026-10-13
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0016"
down_revision: Union[str, None] = "0015"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _existing_columns(table: str) -> set:
    insp = sa.inspect(op.get_bind())
    return {c["name"] for c in insp.get_columns(table)}


def upgrade() -> None:
    if "source" not in _existing_columns("resources"):
        op.add_column(
            "resources",
            sa.Column(
                "source",
                sa.Text(),
                nullable=False,
                server_default=sa.text("'hook'"),
            ),
        )


def downgrade() -> None:
    op.drop_column("resources", "source")
