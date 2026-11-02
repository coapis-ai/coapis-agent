"""台账卫生：把历史脏档位/静默零值显式化（v14 §批次1 + §验收 3）。

背景（v14 实查）：写入侧绕过了全部既有函数，29 个动词串、37 条零成本
（其中 15 行判官真判的 cost/tokens 全 0）、37 条无 chat_id 全进台账；
档位列里还有 `plan_gate`（岗位名当档位）、`select:low,medium`（下拉串）。
新写入侧（:mod:`coapis.decision.ledger_contract`）从源头挡住，这条迁移负责
**历史行**：

* 脏档位：原值搬进 ``dirty_band`` 留证，``complexity`` 清空——预检的档位
  合法率从此只统计真档位，历史脏值不再冒充样本（也不销毁证据）。
* 静默零值：``hit_layer='llm'`` 且 cost/tokens 全 0 的历史行，补写
  ``zero_reason='历史行：写入侧未带 usage'``——「禁止静默 0」对存量同样生效。

幂等：重复执行不覆盖已有 ``dirty_band``/``zero_reason``，不改动合法档位。
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0022_ledger_band_hygiene"
down_revision: Union[str, None] = "0021_ledger_governance"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

# 判岗词表（与 coapis.agents.plan_gate.LEVELS 同一把尺子）
_LEVELS = ("simple", "medium", "complex")
_PLACEHOLDERS = ("-", "无", "(空)")


def upgrade() -> None:
    bind = op.get_bind()
    tbl = sa.table(
        "decision_events",
        sa.column("complexity", sa.String),
        sa.column("dirty_band", sa.String),
    )
    # 1) 脏档位：原值进 dirty_band（只在 dirty_band 为空时搬，不覆盖证据）
    illegal = [
        tbl.c.complexity.isnot(None),
        tbl.c.complexity != "",
        tbl.c.complexity.notin_(_LEVELS),
    ]
    rows = bind.execute(
        sa.select(tbl.c.complexity, tbl.c.dirty_band).where(sa.and_(*illegal)),
    ).fetchall()
    for band, dirty in rows:
        sets = {"complexity": ""}
        if not (dirty or "").strip() and band.strip() not in _PLACEHOLDERS:
            sets["dirty_band"] = band
        bind.execute(
            tbl.update().where(tbl.c.complexity == band).values(**sets),
        )
    # 2) 静默零值：真判行补写零值原因（只在为空时写，幂等）
    bind.execute(
        sa.text(
            "UPDATE decision_events SET zero_reason = '历史行：写入侧未带 usage'"
            " WHERE hit_layer = 'llm' AND coalesce(cost, 0) <= 0"
            " AND coalesce(tokens, 0) <= 0"
            " AND coalesce(zero_reason, '') = ''",
        ),
    )


def downgrade() -> None:
    bind = op.get_bind()
    # 还原：把 dirty_band 搬回 complexity（只动被本迁移清空的那些行）
    bind.execute(
        sa.text(
            "UPDATE decision_events SET complexity = dirty_band"
            " WHERE coalesce(complexity, '') = '' AND coalesce(dirty_band, '') <> ''",
        ),
    )
    bind.execute(
        sa.text(
            "UPDATE decision_events SET zero_reason = ''"
            " WHERE zero_reason = '历史行：写入侧未带 usage'",
        ),
    )
