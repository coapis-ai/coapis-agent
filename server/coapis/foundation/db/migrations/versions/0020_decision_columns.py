"""判断台账补列：输入指纹 / 判断内容 / 轮次 / 用户评价。

v14 §4.3 要求台账能算命中率与复盘：
- ``input_hash``  输入指纹（sha1 前12位，**不存原文**，§4.5①）
- ``judgment``    判断内容（结论值，如 ``select:pdf`` / ``complex``）
- ``turn``        轮次号（单轮判官预算与"本轮判官花了多少"按轮聚合）
- ``rating``      用户评价 0/1/2/3（评价列，NULL 视作未评价）

新增列同样遵守**非空 + 服务端默认值**红线（台账列可为 ''/0，不得 NULL），
老行回填默认值即"未知"。

纯加列，不动既有数据。
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "0020_decision_columns"
down_revision: Union[str, None] = "0019"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_TABLE = "decision_events"
# (列名, 类型, 服务端默认值, 注释) —— 全部 NOT NULL，与台账既有红线一致
_NEW_COLUMNS = (
    ("input_hash", sa.Text(), "''", "输入指纹（sha1 前12位，不含原文）"),
    ("judgment", sa.Text(), "''", "判断内容（结论值）"),
    ("turn", sa.Integer(), "0", "轮次号"),
    ("rating", sa.Integer(), "3", "用户评价 0/1/2/3（3=没评价）"),
)


def _existing_columns() -> set[str]:
    import sqlalchemy

    bind = op.get_bind()
    insp = sqlalchemy.inspect(bind)
    if not insp.has_table(_TABLE):
        return set()
    return {c["name"] for c in insp.get_columns(_TABLE)}


def upgrade() -> None:
    have = _existing_columns()
    if not have:
        return
    for name, typ, default, comment in _NEW_COLUMNS:
        if name not in have:
            op.add_column(
                _TABLE,
                sa.Column(
                    name,
                    typ,
                    nullable=False,
                    server_default=default,
                    comment=comment,
                ),
            )


def downgrade() -> None:
    have = _existing_columns()
    for name, _typ, _comment in reversed(_NEW_COLUMNS):
        if name in have:
            with op.batch_alter_table(_TABLE) as batch_op:
                batch_op.drop_column(name)
