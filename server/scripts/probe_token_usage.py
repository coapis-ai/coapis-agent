#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""只读诊断：最近真实 LLM 调用的 prompt_tokens（token_usage 表）。"""
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _probe_db import connect_ro  # noqa: E402

DB = sys.argv[1] if len(sys.argv) > 1 else "/apps/ai/coapis-dev/system/coapis.db"

c = connect_ro(DB)
tables = [r[0] for r in c.execute("select name from sqlite_master where type='table'")]
print("token tables:", [t for t in tables if "token" in t])

for t in [t for t in tables if "token" in t]:
    cols = [d[1] for d in c.execute(f"pragma table_info({t})")]
    print("---", t, cols)
    n = c.execute(f"select count(*) from {t}").fetchone()[0]
    print("rows:", n)
    if "created_at" in cols:
        rows = list(c.execute(f"select * from {t} order by created_at desc limit 25"))
    else:
        rows = list(c.execute(f"select * from {t} limit 25"))
    for row in rows:
        d = dict(zip(cols, row))
        if "created_at" in d and isinstance(d["created_at"], (int, float)):
            d["ts"] = time.strftime("%m-%d %H:%M:%S", time.localtime(d["created_at"]))
        print({k: v for k, v in d.items() if k not in ("id", "cost_cents")})
