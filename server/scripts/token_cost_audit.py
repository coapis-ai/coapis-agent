#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""token 成本结构分析（只读）：主步 vs 压缩调用 vs 固定开销。

读取 coapis.log 尾部若干 MB，统计：
  - 主推理步：fixed/history/total 字符数
  - 压缩调用：fitted before->after 字符数（= 压缩那次 LLM 调用的输入规模）
  - 压缩触发次数 / 主步次数（每次请求都会触发压缩吗？）
  - 历史里工具结果的体量分布（从 purge 行与 budget 行的 history 增量推断）
"""
import re
import sys
from collections import Counter, defaultdict

LOG = sys.argv[1] if len(sys.argv) > 1 else "/apps/ai/coapis-dev/coapis.log"
MB = int(sys.argv[2]) if len(sys.argv) > 2 else 200

BUDGET = re.compile(
    r"Context budget (?P<agent>\S+): fixed=(?P<fixed>\d+) \(sys=(?P<sys>\d+) tools=(?P<tools>\d+)\)"
    r" history=(?P<history>\d+) total=(?P<total>\d+) allowance=(?P<allow>\d+) trigger=(?P<trig>\d+)"
)
FIT = re.compile(
    r"Context budget for compaction:(?P<agent>\S+) fitted (?P<before>\d+) -> (?P<after>\d+) chars"
    r" \(window budget (?P<budget>\d+): (?P<dropped>\d+) row"
)
UNFIT = re.compile(r"Context budget for compaction:(?P<agent>\S+) fitted to (?P<after>\d+) chars, still")
PURGE = re.compile(r"purged (?P<n>\d+) messages|messages_purged|archived (?P<a>\d+)")
COMPACTED = re.compile(r"Context compacted|compact.*summary|rolling summary")
LLMCALL = re.compile(r"LLM (call|request)|Calling model|chat completion", re.I)


def main():
    # 读尾部 MB
    import os
    size = os.path.getsize(LOG)
    start = max(0, size - MB * 1024 * 1024)
    steps = []
    fits = []
    purges = 0
    compacted = 0
    with open(LOG, "r", encoding="utf-8", errors="replace") as f:
        f.seek(start)
        for ln in f:
            m = BUDGET.search(ln)
            if m:
                steps.append({"agent": m.group("agent"),
                              **{k: int(v) for k, v in m.groupdict().items() if k != "agent"}})
                continue
            m = FIT.search(ln)
            if m:
                fits.append({"agent": m.group("agent"),
                             "before": int(m.group("before")),
                             "after": int(m.group("after")),
                             "dropped": int(m.group("dropped"))})
                continue
            if UNFIT.search(ln):
                fits.append({"before": 0, "after": int(UNFIT.search(ln).group("after")), "dropped": -1})
                continue
            if COMPACTED.search(ln):
                compacted += 1
            if PURGE.search(ln):
                purges += 1
    print("窗口: 尾部 %d MB (文件 %.1f GB)" % (MB, size / 1e9))
    print("主推理步: %d 次" % len(steps))
    if steps:
        tot = sum(s["total"] for s in steps)
        fixed = sum(s["fixed"] for s in steps)
        hist = sum(s["history"] for s in steps)
        print("  主步字符合计: %.1fM  (fixed %.1fM = %.1f%%, history %.1fM = %.1f%%)"
              % (tot / 1e6, fixed / 1e6, 100 * fixed / tot, hist / 1e6, 100 * hist / tot))
        print("  平均每次主步: fixed %.0f + history %.0f = total %.0f chars"
              % (fixed / len(steps), hist / len(steps), tot / len(steps)))
        print("  估算 token(2.05 chars/tok): %.0f tok/步" % (tot / len(steps) / 2.05))
    print("压缩调用: %d 次" % len(fits))
    if fits:
        b = sum(f["before"] for f in fits)
        a = sum(f["after"] for f in fits)
        d = sum(f["dropped"] for f in fits if f["dropped"] > 0)
        print("  压缩输入: 拟合前 %.1fM -> 拟合后 %.1fM chars, 共丢弃 %d 行" % (b / 1e6, a / 1e6, d))
        print("  平均每次压缩调用输入: %.0f chars -> 估算 %.0f tok" % (a / len(fits), a / len(fits) / 2.05))
    if steps and fits:
        st = sum(s["total"] for s in steps)
        ct = sum(f["after"] for f in fits)
        print("  成本占比: 主步 %.1f%% vs 压缩调用 %.1f%%" % (100 * st / (st + ct), 100 * ct / (st + ct)))
    print("压缩完成事件: %d, purge 行: %d" % (compacted, purges))
    # 每 agent 分布
    per = defaultdict(lambda: [0, 0, 0])
    for s in steps:
        per[s["agent"]][0] += 1
        per[s["agent"]][1] += s["total"]
        per[s["agent"]][2] += s["fixed"]
    print("按 agent 主步分布:")
    for a, (n, t, fx) in sorted(per.items(), key=lambda x: -x[1][1])[:8]:
        print("  %-22s 步 %3d  总字符 %8.1fM  fixed 占 %.1f%%" % (a, n, t / 1e6, 100 * fx / t))


main()
