"""清洗 server_default 缺陷留下的字面量空串（v20 · F7）。

背景（实测 2026-11-15 dev v1.2.32）：
ORM 里写成 ``server_default=text("''")`` 的列，在 SQLite 下被渲染成
``DEFAULT ''''''``，也就是"默认值 = 两个单引号字符"。于是任何不显式传值的
写入，落库都是 ``''``（两字符）而不是空串。dev 实测污染：dirty_band 364/369
行、zero_reason 146 行、input_hash/judgment 各 14 行。凡按"非空即有值"过滤
的查询与前端统计都会被这些假值骗过 —— 本轮我自己就被 dirty_band "100% 非空"
骗过一次。

模型侧已改 ``server_default=""``（实测渲染成 ``DEFAULT ''``，插行落库长度 0），
本迁移清洗存量。
"""
from typing import Sequence
from typing import Union

import sqlalchemy as sa
from alembic import op

revision: str = "0029_clean_literal_empty"
down_revision: Union[str, None] = "0028_ledger_governance_columns"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

#: decision_events 里曾用 server_default=text("''") 的文本列（实测 17 处默认值，
#: 去重后落到这些列名；不存在的列跳过，兼容不同库的列集合）
_COLUMNS: Sequence[str] = (
    "source", "complexity", "action", "reason", "hit_layer", "model",
    "user_id", "chat_id", "input_hash", "judgment",
    "origin", "zero_reason", "dirty_band",
)


def _two_quotes(conn) -> str:
    """返回"两个单引号字符"的 SQL 表达式（SQLite 用 CHAR，Postgres 用 CHR）。"""
    if conn.dialect.name == "postgresql":
        return "CAST(CHR(39) AS TEXT) || CAST(CHR(39) AS TEXT)"
    return "CHAR(39) || CHAR(39)"


def _columns(conn) -> list:
    """库里真实存在的目标列（迁移必须在 SQLite/Postgres 两栈都跑得通）。

    Postgres 没有 PRAGMA，``exec_driver_sql("PRAGMA ...")`` 不是返回空行而是
    直接抛 ``SyntaxError``（实测 psycopg2.errors.SyntaxError: syntax error at
    or near "PRAGMA"），会把整个迁移和进程启动带崩；且事务一旦 aborted，同事务
    内后续语句全部失败。所以按方言分流，PG 侧根本不碰 PRAGMA。
    另外 PG 的 information_schema 结果只有一列，取值是 ``r[0]`` 而不是 ``r[1]``。
    """
    if conn.dialect.name == "postgresql":
        rows = conn.exec_driver_sql(
            "SELECT column_name FROM information_schema.columns "
            "WHERE table_name = 'decision_events'"
        ).fetchall()
        have = {str(r[0]) for r in rows}
    else:
        rows = conn.exec_driver_sql("PRAGMA table_info(decision_events)").fetchall()
        have = {str(r[1]) for r in rows}
    return [c for c in _COLUMNS if c in have]


def upgrade() -> None:
    conn = op.get_bind()
    if conn.dialect.name not in ("sqlite", "postgresql"):
        return
    lit = _two_quotes(conn)
    for col in _columns(conn):
        # 只清洗值恰为两个单引号字符的行；真实内容一律不动。
        conn.exec_driver_sql(
            f'UPDATE decision_events SET "{col}" = \'\' WHERE "{col}" = {lit}'
        )


def downgrade() -> None:
    # 有意保持为空：把空串还原成污染值只会重新制造同一个缺陷，且会破坏
    # 迁移前已有真值的行。
    pass
