#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""故障深挖（只读）：异常栈归类 + 压缩不可拟合后果 + 计划/分片工具真实使用率。"""
import json
import re
import sqlite3
import sys
from collections import Counter

LOG = "/apps/ai/coapis-dev/coapis.log"
DB = "/apps/ai/coapis-dev/working/workspaces/default/history/history.db"
size = __import__("os").path.getsize(LOG)
start = max(0, size - 80 * 1024 * 1024)

print("=== 1) 异常栈归类（尾部80MB）===")
tb = Counter()
with open(LOG, "r", encoding="utf-8", errors="replace") as f:
    f.seek(start)
    lines = f.readlines()
for i, ln in enumerate(lines):
    if "Traceback (most recent call last)" in ln:
        exc = ""
        for j in range(i + 1, min(i + 25, len(lines))):
            m = re.match(r"^([A-Za-z_][A-Za-z0-9_.]*(?:Error|Exception))\s*:?\s*(.*)", lines[j].strip())
            if m:
                exc = m.group(1) + ": " + m.group(2)[:70]
                break
        caller = ""
        for j in range(i - 1, max(i - 8, -1), -1):
            m = re.search(r"\|\s*([\w/]+\.py):\d+", lines[j])
            if m:
                caller = m.group(1)
                break
            m2 = re.search(r"File \"[^\"]*?([\w/]+\.py)\", line", lines[j])
            if m2:
                caller = m2.group(1)
                break
        tb[(caller, exc[:80])] += 1
for (c, e), n in tb.most_common(10):
    print("  %3d  %s  %s" % (n, c, e))

print("\n=== 2) 压缩不可拟合事件与后果 ===")
with open(LOG, "r", encoding="utf-8", errors="replace") as f:
    f.seek(start)
    lines = f.readlines()
idx = [i for i, l in enumerate(lines) if "cannot fit the fixed overhead" in l]
for i in idx[-6:]:
    print("  " + lines[i].strip()[:230])
    for j in range(i + 1, min(i + 6, len(lines))):
        s = lines[j].strip()
        if re.search(r"hard refusal|budget|compact|ERROR|WARNING|refus", s, re.I):
            print("      ↳ " + s[:190])

print("\n=== 3) 计划/分片类工具真实使用率（全历史）===")
con = sqlite3.connect("file:%s?mode=ro" % DB, uri=True)
names = Counter()
for (b,) in con.execute("SELECT content FROM messages WHERE role='tool' ORDER BY seq").fetchall():
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
plan_keys = [k for k in names if re.search(r"plan|todo|task|paginat|chunk|shard|section|doc_", k, re.I)]
print("  工具调用总数=%d" % tot)
print("  计划/分片类: " + ", ".join("%s=%d" % (k, names[k]) for k in plan_keys) if plan_keys else "  计划/分片类: 0（从未使用）")
print("  Top10 工具: " + ", ".join("%s=%d" % (k, n) for k, n in names.most_common(10)))
con.close()
