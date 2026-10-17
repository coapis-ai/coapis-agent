#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""取 browser_control NameError 的完整栈（只读日志尾部）。"""
import re

LOG = "/apps/ai/coapis-dev/coapis.log"
size = __import__("os").path.getsize(LOG)
start = max(0, size - 80 * 1024 * 1024)
with open(LOG, "r", encoding="utf-8", errors="replace") as f:
    f.seek(start)
    lines = f.readlines()

hits = 0
for i, ln in enumerate(lines):
    if "NameError: name 'path' is not defined" in ln:
        hits += 1
        if hits > 2:
            break
        print("=" * 78)
        lo = max(0, i - 22)
        for j in range(lo, i + 1):
            s = lines[j].rstrip()
            if s.strip():
                print("   " + s[:190])
