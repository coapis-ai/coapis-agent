# -*- coding: utf-8 -*-
"""file_records 解析台账列（一期 A1）。

文档解析此前**跑完就蒸发**：成功/失败/超时/超阈值/降级方式只写日志，
台账无从知晓。后果是「解析状态」无法成为计划闸门（P1）与判据（P2）的
输入，智能体只能盲猜附件可用性。

本迁移给 ``file_records`` 加四列，把解析结果钉在文件台账上：

- ``parse_status``：ok / timeout / fail / degraded
- ``parse_chars``：解析出的字符数
- ``parse_method``：实际生效的方式，如 ``full/docx``、``index+head/pdf``
- ``parse_at``：解析完成时间（epoch 秒）

全部可空——历史行没有解析记录，读取侧按「未解析」处理，绝不回填假数据。

Revision ID: 0019
Revises: 0018
Create Date: 2026-10-29
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0019"
down_revision: Union[str, None] = "0018"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _columns(table: str) -> set:
    insp = sa.inspect(op.get_bind())
    if table not in insp.get_table_names():
        return set()
    return {c["name"] for c in insp.get_columns(table)}


def upgrade() -> None:
    have = _columns("file_records")
    if not have:
        return
    new = {
        "parse_status": sa.Column("parse_status", sa.Text(), nullable=True),
        "parse_chars": sa.Column("parse_chars", sa.Integer(), nullable=True),
        "parse_method": sa.Column("parse_method", sa.Text(), nullable=True),
        "parse_at": sa.Column("parse_at", sa.REAL(), nullable=True),
    }
    for name, col in new.items():
        if name not in have:
            op.add_column("file_records", col)


def downgrade() -> None:
    have = _columns("file_records")
    for name in ("parse_at", "parse_method", "parse_chars", "parse_status"):
        if name in have:
            op.drop_column("file_records", name)
