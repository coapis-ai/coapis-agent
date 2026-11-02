"""台账治理列：来源标记 / 零值语义 / 脏档位留痕（v14 §批次1 + §批次5）。

三个新列都服务"可对账"这一件事：

- ``origin``       行来源。''/unknown 是存量行的初值；写入侧按会话来源
                   标 ``web``（聊天会话）/ ``test``（e2e/合成会话）。
                   预检 KPI 只统计 ``web``——测试行不得掺入生产指标
                   （v14 §批次5：真判率掺了 52 条 e2e 合成行，虚高）。
- ``zero_reason``  成本零值的语义标记：``no_llm_cost``（设计上为 0）/
                   ``usage_missing``（该有记账而没有）/ ``write_failure``
                   （降级路径写的行）。无标记且 cost=0 的行 = 记账坏了。
- ``dirty_band``   岗位写了非档位词表值时，清洗进 complexity 前把原值
                   存在这里留痕——清洗不销毁证据。

纯加列，非空 + 服务端默认值，不动既有数据。
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "0021_ledger_governance"
down_revision: Union[str, None] = "0020_decision_columns"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_TABLE = "decision_events"
_NEW_COLUMNS = (
    ("origin", sa.Text(), "''", "行来源：web=聊天会话 test=测试/合成 '' =存量未知"),
    ("zero_reason", sa.Text(), "''", "零值语义：no_llm_cost/usage_missing/write_failure"),
    ("dirty_band", sa.Text(), "''", "被清洗的档位原值留痕"),
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
