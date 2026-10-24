# -*- coding: utf-8 -*-
"""resources: add ``version`` (同一文件的交付版本号).

方案 §12.4 L1 要求产出卡带「版本徽标 v1..vN」：同一份文件在一通会话里被反复
交付时，用户要能看出「这是第几版」。此前台账只有 ``updated_at``，能回答"最后
什么时候动过"，回答不了"动过几次、现在是第几版"。

规则（写死在 ``register`` 里，避免各处自行判断）：
 - 首次登记 → version = 1
 - 再次登记且**大小变了**（内容变了）→ version + 1
 - 再次登记但大小没变（同一份内容重复引用）→ version 不变

Revision ID: 0017
Revises: 0016
Create Date: 2026-10-22
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0017"
down_revision: Union[str, None] = "0016"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _existing_columns(table: str) -> set:
    insp = sa.inspect(op.get_bind())
    return {c["name"] for c in insp.get_columns(table)}


def upgrade() -> None:
    if "version" not in _existing_columns("resources"):
        op.add_column(
            "resources",
            sa.Column(
                "version",
                sa.Integer(),
                nullable=False,
                server_default=sa.text("1"),
            ),
        )


def downgrade() -> None:
    op.drop_column("resources", "version")
