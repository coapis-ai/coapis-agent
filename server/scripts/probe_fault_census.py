#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""执行过程故障普查（只读）：扫日志尾部的错误/中断/拒绝类型与频次。"""
import re
import sys
from collections import Counter

LOG = sys.argv[1] if len(sys.argv) > 1 else "/apps/ai/coapis-dev/coapis.log"
MB = int(sys.argv[2]) if len(sys.argv) > 2 else 80

PATS = {
    "422 拒绝(超窗)": r"422|Unprocessable",
    "上下文超限": r"context_length|maximum context|too long|exceeds",
    "工具调用失败": r"Error calling tool|tool_call.*error|ToolResponse.*error",
    "模型调用失败": r"Error calling (model|llm)|ModelInvocation|Retry.*exhausted",
    "超时": r"timed out|TimeoutError|ReadTimeout",
    "压缩摘要失败": r"Failed to obtain.*compress|compression.*failed",
    "压缩不可拟合": r"cannot fit the fixed overhead|still \d+ over",
    "轨迹截断": r"truncat",
    "异常栈": r"Traceback \(most recent call last\)",
    "技能/工具缺失": r"not found|Unknown tool|no such tool|KeyError",
    "计划/分片": r"plan|paginat|chunk|shard",
}

size = __import__("os").path.getsize(LOG)
start = max(0, size - MB * 1024 * 1024)
cnt = Counter()
samples = {}
with open(LOG, "r", encoding="utf-8", errors="replace") as f:
    f.seek(start)
    for ln in f:
        for name, pat in PATS.items():
            if re.search(pat, ln, re.I):
                cnt[name] += 1
                if name not in samples:
                    samples[name] = ln.strip()[:220]
print("扫描尾部 %d MB (%.1f GB 文件)" % (MB, size / 1e9))
for name, n in cnt.most_common():
    print("%-14s %5d  例: %s" % (name, n, samples.get(name, "")[:170]))
