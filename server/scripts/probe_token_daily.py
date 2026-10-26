#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""只读诊断：最近每日 prompt_tokens / 调用次数 → 单次平均（真实 token 口径）。"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _probe_db import connect_ro  # noqa: E402

DB = "/apps/ai/coapis-dev/system/coapis.db"
c = connect_ro(DB)
rows = list(
    c.execute(
        "select date, provider_id, model_name, prompt_tokens, completion_tokens, call_count "
        "from token_usage_daily where date >= '2026-10-10' order by date desc",
    )
)
print(f"{'date':11} {'provider':14} {'model':22} {'prompt':>10} {'compl':>8} {'calls':>6} {'avg_pt':>8}")
for d, p, m, pt, ct, n in rows:
    avg = pt / n if n else 0
    print(f"{d:11} {p:14} {m:22} {pt:10,} {ct:8,} {n:6} {avg:8,.0f}")
