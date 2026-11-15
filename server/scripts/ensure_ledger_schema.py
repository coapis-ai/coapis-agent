# -*- coding: utf-8 -*-
"""台账 schema 同步器：把"迁移文件"真落到库上（幂等，可重复跑）。

为什么需要它（2026-11-15 实测实锤）：仓库里**没有 alembic.ini / env.py**，
``foundation/db/migrations/versions/`` 下那串编号文件从来没有执行者 ——
dev 真库实测：``resources`` 表没有 ``turn_id``（迁移 0025 声称的列）、
``usage_events`` 表零列（迁移 0026）、``approval_intents`` 表不存在。
迁移线是纸面的，模型与库各说各话，于是"写侧传了参数、读侧查不到列"
这类断点一路无人发现。

本脚本按**模型定义**（唯一真相源）同步库：
* 表不存在 → 建表；
* 表存在但缺列 → ``ALTER TABLE ... ADD COLUMN``（带服务端默认值）；
* 已有列一律不动（不删、不改类型）—— 幂等，重复跑零副作用。

用法（容器内，连的是真实运行库）：
    python /app/scripts/ensure_ledger_schema.py
宿主调试：
    COAPIS_DATABASE_URL=sqlite:////path/to/coapis.db python scripts/ensure_ledger_schema.py
"""
from __future__ import annotations

import os
import sys

from sqlalchemy import create_engine, event, inspect, text
from sqlalchemy.schema import CreateColumn


def _engine():
    url = os.environ.get("COAPIS_DATABASE_URL", "").strip()
    if not url:
        from coapis.foundation.db.paths import get_database_url

        url = get_database_url()
    return create_engine(url)


def _literal_default(col) -> str:
    """新列的服务端默认值（非空红线：老行读出为默认值，不留 NULL）。"""
    if col.server_default is not None:
        arg = getattr(col.server_default, "arg", None)
        txt = arg.text if hasattr(arg, "text") else str(arg)
        return f"DEFAULT {txt}"
    if not col.nullable:
        # 非空且无声明默认：按类型给保守默认（文本 ''、数值 0）
        return "DEFAULT ''"
    return ""


def ensure(bind) -> dict[str, list[str]]:
    """按模型补建表/补列。返回 ``{表名: [新增列]}``（空 = 已同步）。"""
    from coapis.foundation.db.base import Base
    import coapis.foundation.db.models  # noqa: F401  (注册全部模型)

    ins = inspect(bind)
    existing_tables = set(ins.get_table_names())
    changed: dict[str, list[str]] = {}

    with bind.connect() as conn:
        for name, table in Base.metadata.tables.items():
            if name not in existing_tables:
                table.create(bind=conn)
                changed[name] = ["<new table>"]
                continue
            have = {c["name"] for c in ins.get_columns(name)}
            added = []
            for col in table.columns:
                if col.name in have:
                    continue
                frag = str(CreateColumn(col).compile(dialect=bind.dialect))
                # CreateColumn 输出 "<name> <type>"，补默认值后缀
                literal = _literal_default(col)
                sql = f"ALTER TABLE {name} ADD COLUMN {frag} {literal}".strip()
                conn.execute(text(sql))
                added.append(col.name)
            if added:
                changed[name] = added
        conn.commit()
    return changed


def main() -> int:
    eng = _engine()
    changed = ensure(eng)
    if not changed:
        print("schema 已同步：无新增表/列")
        return 0
    for table, cols in sorted(changed.items()):
        print(f"{table}: +{', '.join(cols)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
