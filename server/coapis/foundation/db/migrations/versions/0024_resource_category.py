# -*- coding: utf-8 -*-
"""resources: add ``category``（v20 · W1 资源类别统一尺子）.

kind 五档回答"资源从哪来"，回答不了"用户手里这是个什么东西"。本列落
``resource_category.resolve_category`` 的结果：doc/sheet/slide/pdf/image/
media/archive/code/web/chat_record/db_record/kb_entry/mcp_tool/other。

存量行**现场换算回填**（调用注册表本尊，不抄规则——抄一份规则就是第二把
尺子，v20 §1.5 的教训）。server_default 用 'other' 兜底：新行全部由
register 显式写入换算值，default 只在绕过 ledger 的裸插入时生效。

Revision ID: 0024_resource_category
Revises: 0023_memory_session_id
Create Date: 2026-11-09
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0024_resource_category"
down_revision: Union[str, None] = "0023_memory_session_id"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _existing_columns(table: str) -> set:
    insp = sa.inspect(op.get_bind())
    return {c["name"] for c in insp.get_columns(table)}


def upgrade() -> None:
    if "category" not in _existing_columns("resources"):
        op.add_column(
            "resources",
            sa.Column(
                "category",
                sa.Text(),
                nullable=False,
                server_default=sa.text("'other'"),
            ),
        )
    # 存量行回填：直接用注册表本尊换算（单一尺子）。导入失败（极端：
    # 迁移在纯 alembic 环境跑）就跳过回填——列已就位，ledger 的读侧
    # 有"缺值现算"兜底，不会给出错数字。
    try:
        from coapis.foundation.resource_category import resolve_category
    except Exception:  # pragma: no cover
        return
    bind = op.get_bind()
    rows = bind.execute(
        sa.text("SELECT id, kind, path FROM resources")
    ).fetchall()
    for row in rows:
        cat = resolve_category(str(row[1] or ""), str(row[2] or ""))
        bind.execute(
            sa.text("UPDATE resources SET category = :c WHERE id = :i"),
            {"c": cat, "i": row[0]},
        )


def downgrade() -> None:
    if "category" in _existing_columns("resources"):
        op.drop_column("resources", "category")
