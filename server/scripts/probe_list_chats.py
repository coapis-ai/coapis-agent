#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""列出会话存储的 chat_id / 体量（只读），供 A/B 压缩成本实测选靶。"""
import glob
import json

rows = []
for f in glob.glob("/apps/ai/coapis-dev/workspaces/admin/sessions/*.json"):
    try:
        d = json.load(open(f))
    except Exception:
        continue
    m = d.get("agent", {}).get("memory", {})
    c = m.get("content", [])
    if not c:
        continue
    chars = sum(len(json.dumps(x, ensure_ascii=False)) for x in c)
    sid = f.split("/")[-1][len("admin_"):-5]
    rows.append((chars, len(c), sid))

rows.sort(reverse=True)
for chars, n, sid in rows[:8]:
    print("%9d chars %4d rows  %s" % (chars, n, sid))
