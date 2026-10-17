#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""会话存储体量与压缩落盘情况普查（只读）。"""
import glob
import json
import os

rows = []
bad = 0
for f in glob.glob("/apps/ai/coapis-dev/workspaces/*/sessions/*.json"):
    try:
        d = json.load(open(f))
    except Exception:
        bad += 1
        continue
    m = d.get("agent", {}).get("memory", {})
    c = m.get("content", [])
    if not c:
        continue
    chars = sum(len(json.dumps(x, ensure_ascii=False)) for x in c)
    marked = sum(1 for x in c if isinstance(x, list) and len(x) > 1 and x[1])
    summ = len(m.get("_compressed_summary", "") or "")
    rows.append((len(c), chars, marked, summ, f.split("/")[-3]))

rows.sort(key=lambda r: -r[1])
print("有消息的会话数:", len(rows), " 解析失败:", bad)
print("%-26s %6s %9s %6s %7s" % ("user", "rows", "chars", "marked", "summary"))
for r in rows[:12]:
    print("%-26s %6d %9d %6d %7d" % (r[4], r[0], r[1], r[2], r[3]))
if rows:
    tot = sum(r[1] for r in rows)
    print("合计历史体量 %.1f MB；平均 %.0f chars/会话；最大 %.0f chars"
          % (tot / 1e6, tot / len(rows), rows[0][1]))
    print("有摘要的会话: %d；有压缩标记的会话: %d"
          % (sum(1 for r in rows if r[3] > 0), sum(1 for r in rows if r[2] > 0)))
    print("超过压缩触发点(172K chars)的会话: %d" % sum(1 for r in rows if r[1] > 172032))
