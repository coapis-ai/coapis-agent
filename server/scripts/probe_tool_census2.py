#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""工具调用普查（只读）：自适应 schema 落地后的真实使用分布。"""
import json
import re
from collections import Counter

from _probe_db import connect_ro

DB = "/apps/ai/coapis-dev/system/coapis.db"
con = connect_ro(DB)
tabs = [r[0] for r in con.execute("SELECT name FROM sqlite_master WHERE type='table'")]
print("表:", tabs[:14])

cand = [t for t in tabs if re.search("message|dialog|history|turn", t, re.I)]
print("候选表:", cand)
for t in cand:
    cols = [r[1] for r in con.execute("PRAGMA table_info(%s)" % t)]
    n = con.execute("SELECT COUNT(*) FROM %s" % t).fetchone()[0]
    print("  %s: %d 行, 列=%s" % (t, n, cols[:10]))

names = Counter()
rows = 0
for t in cand:
    if "content" not in [r[1] for r in con.execute("PRAGMA table_info(%s)" % t)]:
        continue
    for (b,) in con.execute("SELECT content FROM %s" % t).fetchall():
        rows += 1
        try:
            arr = json.loads(b.decode("utf-8") if isinstance(b, bytes) else b)
        except Exception:
            continue
        if not isinstance(arr, list):
            continue
        for blk in arr:
            if isinstance(blk, dict) and blk.get("type") == "tool_use":
                names[blk.get("name", "?")] += 1

tot = sum(names.values())
print("\n扫描行=%d, 工具调用总数=%d" % (rows, tot))
plan = [k for k in names if re.search(r"plan|todo|task|paginat|chunk|shard|section", k, re.I)]
skill = [k for k in names if re.search(r"skill", k, re.I)]
print("计划/分片类: " + (", ".join("%s=%d" % (k, names[k]) for k in plan) if plan else "0（从未使用）"))
print("技能类: " + (", ".join("%s=%d" % (k, names[k]) for k in skill) if skill else "0"))
print("Top15: " + ", ".join("%s=%d" % (k, n) for k, n in names.most_common(15)))
con.close()
