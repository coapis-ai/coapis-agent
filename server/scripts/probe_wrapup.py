#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""收尾三项：_get_executor 作用域 / 计划与分片工具真实使用率 / runner 异常归类（只读）。"""
import ast
import glob
import json
import os
import re
from collections import Counter

from _probe_db import connect_ro

SRC = "coapis/agents/tools/browser_control.py"
t = ast.parse(open(SRC, encoding="utf-8").read())
print("=== 1) _get_executor 作用域 ===")
for fn in ast.walk(t):
    if isinstance(fn, (ast.FunctionDef, ast.AsyncFunctionDef)):
        for s in ast.walk(fn):
            if isinstance(s, (ast.FunctionDef, ast.AsyncFunctionDef)) and s.name == "_get_executor" and s is not fn:
                print("   嵌套定义于 %s (def@%d) 内, 行 %d" % (fn.name, fn.lineno, s.lineno))
print("   _USE_SYNC_PLAYWRIGHT 赋值：")
for ln in open(SRC, encoding="utf-8"):
    if "_USE_SYNC_PLAYWRIGHT" in ln and "=" in ln and "if" not in ln[:8]:
        print("      " + ln.strip()[:150])

print("\n=== 2) 计划/分片类工具真实使用率 ===")
cands = glob.glob("/apps/ai/coapis-dev/**/history.db", recursive=True) + \
        glob.glob("/apps/ai/coapis-dev/working/**/*.db", recursive=True)
cands = sorted(set(cands), key=lambda p: -os.path.getsize(p))
print("   候选库: " + ", ".join("%s(%.1fMB)" % (c, os.path.getsize(c) / 1e6) for c in cands[:4]))
if cands:
    con = connect_ro(cands[0])
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
    plan = [k for k in names if re.search(r"plan|todo|task|paginat|chunk|shard|section", k, re.I)]
    print("   tool 消息行=%d, 工具调用总数=%d" % (rows, tot))
    print("   计划/分片类: " + (", ".join("%s=%d" % (k, names[k]) for k in plan) if plan else "0（从未使用）"))
    print("   Top12: " + ", ".join("%s=%d" % (k, n) for k, n in names.most_common(12)))
    con.close()

print("\n=== 3) runner.py 异常归类（尾部80MB）===")
LOG = "/apps/ai/coapis-dev/coapis.log"
size = os.path.getsize(LOG)
with open(LOG, "r", encoding="utf-8", errors="replace") as f:
    f.seek(max(0, size - 80 * 1024 * 1024))
    lines = f.readlines()
cnt = Counter()
for i, ln in enumerate(lines):
    if "Traceback (most recent call last)" in ln:
        exc = ""
        for j in range(i + 1, min(i + 30, len(lines))):
            m = re.match(r"^([A-Za-z_][\w.]*(?:Error|Exception))\s*:?\s*(.*)", lines[j].strip())
            if m:
                exc = "%s: %s" % (m.group(1), m.group(2)[:60])
                break
        ctx = ""
        for j in range(i - 1, max(i - 12, -1), -1):
            m = re.search(r"\|\s*(\S+\.py):\d+", lines[j])
            if m:
                ctx = m.group(1)
                break
        cnt[(ctx, exc)] += 1
for (c, e), n in cnt.most_common(8):
    print("   %3d  %s | %s" % (n, c, e))
