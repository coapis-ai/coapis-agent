#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""工具调用普查（只读）：自适应 schema 下的真实使用分布 + 计划/分片类占比。"""
import glob
import json
import os
import re
import sqlite3
from collections import Counter

cands = sorted(set(glob.glob("/apps/ai/coapis-dev/**/*.db", recursive=True)),
               key=lambda p: -os.path.getsize(p))
for c in cands:
    try:
        con = sqlite3.connect("file:%s?mode=ro" % c, uri=True)
        tabs = [r[0] for r in con.execute("SELECT name FROM sqlite_master WHERE type='table'")]
    except Exception as e:
        print("%s -> %s" % (c, e))
        continue
    if "messages" not in tabs:
        con.close()
        continue
    print("库: %s (%.1f MB) 表=%s" % (c, os.path.getsize(c) / 1e6, tabs))
    names = Counter()
    rows = 0
    for (b,) in con.execute("SELECT content FROM messages WHERE role='tool' ORDER BY seq").fetchall():
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
    plan = [k for k in names if re.search(r"plan|todo|task|paginat|chunk|shard|section|skill", k, re.I)]
    print("  tool 行=%d 调用总数=%d" % (rows, tot))
    print("  计划/技能/分片类: " + (", ".join("%s=%d" % (k, names[k]) for k in plan) if plan else "0"))
    print("  Top12: " + ", ".join("%s=%d" % (k, n) for k, n in names.most_common(12)))
    con.close()
    break
