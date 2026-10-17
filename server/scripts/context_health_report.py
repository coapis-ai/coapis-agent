#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Context/tool/skill optimisation health report (片4-6 §9 全局验收).

Reads a coapis log file and prints the seven acceptance metrics, each with
the evidence line that produced it.  Read-only: this script never touches
runtime state, so it is safe to run against a live dev/production log.

    python context_health_report.py --log /apps/ai/coapis-dev/coapis.log
    python context_health_report.py --log ... --date 2026-10-17 --json

Why a script: every number in the 施工单 acceptance table was measured by
hand with ad-hoc greps, and one of those greps ("Memory compression is
triggered") measures agentscope's own logger, which is not routed into the
coapis log.  A metric that reads the wrong string reports "compression never
runs" while compression is in fact running.  This script encodes the
*observable* signals that coapis itself emits, and states the unit and the
source of every number so a wrong reading cannot be mistaken for a fact.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from collections import Counter
from typing import Any

# --- log patterns ----------------------------------------------------------
#
# Every pattern below is a line coapis itself writes.  Patterns that only
# agentscope writes are listed in INVISIBLE and reported as such, never as
# a zero.
PATTERNS = {
    # gate measurement, one line per reasoning step
    "budget": r"Context budget (?P<agent>[^ ]+): fixed=(?P<fixed>\d+) \(sys=(?P<sys>\d+) tools=(?P<tools>\d+)\) history=(?P<history>\d+) total=(?P<total>\d+) allowance=(?P<allowance>\d+) trigger=(?P<trigger>\d+) fixed_pct=(?P<pct>[\d.]+)% window=(?P<window>\d+) src=(?P<src>\w+) cpt=(?P<cpt>[\d.]+)",
    # compaction config built at agent construction
    "compaction_cfg": r"Memory compaction enabled: trigger=(?P<trigger>\d+) formatted chars \(= (?P<tokens>\d+) tokens at (?P<cpt>[\d.]+) chars/token\), window=(?P<window>\d+) \((?P<src>\w+)\)",
    # window provenance
    "window_self": r"window=(?P<window>\d+) \(model_self_report\)",
    "window_fallback": r"\(config_fallback\)",
    # fixed-overhead constraint firing (B0/D8)
    "overhead_shed": r"fixed-overhead: agent '(?P<agent>[^']*)' fixed (?P<fixed>\d+)/(?P<allowance>\d+) chars \((?P<pct>[\d.]+)% > cap (?P<cap>[\d.]+)%\); shed (?P<action>[^ ]+) -> now (?P<now>\d+) chars",
    # compaction input fitting (the compression request itself)
    "fit_start": r"context fit start: (?P<rows>\d+) rows, (?P<chars>\d+) chars, row_budget (?P<budget>\d+)",
    "fit_round": r"context fit round (?P<round>\d+): total (?P<before>\d+) -> (?P<after>\d+) \(row_budget (?P<budget>\d+), floor (?P<floor>\d+), deleted (?P<deleted>\d+) rows, cut (?P<cut>\d+) chars, rows (?P<rows>\d+)\)",
    "compaction_fit": r"Context budget for compaction:(?P<agent>[^ ]+) fitted (?P<before>\d+) -> (?P<after>\d+) chars \(window budget (?P<budget>\d+): (?P<dropped>\d+) row\(s\) dropped, (?P<cut>\d+) chars truncated\)",
    "compaction_unfit": r"Context budget for compaction:(?P<agent>[^ ]+) fitted to (?P<after>\d+) chars, still (?P<over>\d+) over the (?P<budget>\d+)-char budget \((?P<dropped>\d+) row\(s\) dropped, (?P<cut>\d+) chars truncated\)",
    # compression completing: coapis archives + purges what upstream marked
    "compressed": r"Archived \+ purged (?P<n>\d+) compressed message\(s\); (?P<remain>\d+) remain in working memory",
    # refusals
    "overflow": r"Context overflow for agent (?P<agent>[^ ]+)",
    "over_trigger": r"Context over trigger \((?P<total>\d+) > (?P<trigger>\d+) chars\) for agent (?P<agent>[^ ]+)",
    # doc pagination (B3/B4)
    "doc_page": r"doc[-_]pages?|doc_reader mode=(?P<mode>\w+)",
}

# agentscope writes these; coapis' log sink does not receive them.
INVISIBLE = [
    "Memory compression is triggered",
    "Finished compressing",
]


def _iter_lines(path: str, date: str | None):
    with open(path, "r", encoding="utf-8", errors="replace") as fh:
        for line in fh:
            if date and not line.startswith(date):
                continue
            yield line


def _compiles() -> dict[str, re.Pattern[str]]:
    return {k: re.compile(v) for k, v in PATTERNS.items()}


def report(path: str, date: str | None) -> dict[str, Any]:
    rx = _compiles()
    hits: dict[str, list[str]] = {k: [] for k in PATTERNS}
    for line in _iter_lines(path, date):
        for key, pat in rx.items():
            m = pat.search(line)
            if m:
                hits[key].append(line.rstrip())
                break

    out: dict[str, Any] = {"log": path, "date": date or "all"}

    # 1. window provenance
    srcs = Counter()
    for line in hits["budget"]:
        m = rx["budget"].search(line)
        srcs[m.group("src")] += 1
    out["window_source"] = dict(srcs)

    # 2. fixed overhead: last reading + max pct
    fixed_rows = []
    for line in hits["budget"]:
        m = rx["budget"].search(line)
        fixed_rows.append(
            {
                "agent": m.group("agent"),
                "fixed": int(m.group("fixed")),
                "sys": int(m.group("sys")),
                "tools": int(m.group("tools")),
                "history": int(m.group("history")),
                "allowance": int(m.group("allowance")),
                "trigger": int(m.group("trigger")),
                "pct": float(m.group("pct")),
                "window": int(m.group("window")),
                "src": m.group("src"),
                "cpt": float(m.group("cpt")),
            },
        )
    out["fixed_overhead"] = {
        "samples": len(fixed_rows),
        "last": fixed_rows[-1] if fixed_rows else None,
        "max_pct": max((r["pct"] for r in fixed_rows), default=0.0),
        "max_fixed": max((r["fixed"] for r in fixed_rows), default=0),
        "max_history": max((r["history"] for r in fixed_rows), default=0),
    }

    # 3. fixed-overhead constraint actions
    out["overhead_shed_events"] = len(hits["overhead_shed"])

    # 4. compression: what coapis can see
    out["compression"] = {
        "purges": len(hits["compressed"]),
        "messages_purged": sum(
            int(rx["compressed"].search(l).group("n")) for l in hits["compressed"]
        ),
        "compaction_fits": len(hits["compaction_fit"]) + len(hits["compaction_unfit"]),
        "compaction_unfit": len(hits["compaction_unfit"]),
        # coverage = share of the compressible prefix that survived into the
        # summary prompt.  1.0 means the summary saw everything it purged.
        # Measured on the fit rounds, which report before/after directly.
        "min_coverage": min(
            (
                int(rx["fit_round"].search(l).group("after"))
                / max(1, int(rx["fit_round"].search(l).group("before")))
                for l in hits["fit_round"]
                if int(rx["fit_round"].search(l).group("deleted")) > 0
            ),
            default=1.0,
        ),
        "rows_dropped_max": max(
            (int(rx["fit_round"].search(l).group("deleted")) for l in hits["fit_round"]),
            default=0,
        ),
        "invisible_to_log": INVISIBLE,
    }

    # 5. refusals / soft over-threshold
    out["overflow"] = len(hits["overflow"])
    out["over_trigger"] = len(hits["over_trigger"])

    # 6. compaction config as built
    cfgs = []
    for line in hits["compaction_cfg"]:
        m = rx["compaction_cfg"].search(line)
        cfgs.append(
            {
                "trigger": int(m.group("trigger")),
                "window": int(m.group("window")),
                "src": m.group("src"),
                "cpt": float(m.group("cpt")),
            },
        )
    out["compaction_config"] = {"builds": len(cfgs), "last": cfgs[-1] if cfgs else None}

    # 7. doc pagination
    out["doc_pagination_lines"] = len(hits["doc_page"])

    return out


def render(r: dict[str, Any]) -> str:
    fo = r["fixed_overhead"]
    last = fo["last"]
    comp = r["compression"]
    lines = [
        f"=== context health  log={r['log']}  scope={r['date']} ===",
        f"window source        : {r['window_source'] or 'no samples'}",
        f"fixed overhead       : samples={fo['samples']} max_fixed={fo['max_fixed']} "
        f"max_pct={fo['max_pct']:.1f}% max_history={fo['max_history']}",
        f"  last reading       : {last}",
        f"overhead shed events : {r['overhead_shed_events']}",
        f"compression          : purges={comp['purges']} "
        f"messages_purged={comp['messages_purged']} "
        f"compaction_fits={comp['compaction_fits']} "
        f"unfit={comp['compaction_unfit']} min_coverage={comp['min_coverage']:.2f}",
        f"  log-invisible      : {', '.join(comp['invisible_to_log'])}",
        f"hard refusals        : {r['overflow']}",
        f"soft over-trigger    : {r['over_trigger']}",
        f"compaction config    : {r['compaction_config']}",
        f"doc pagination lines : {r['doc_pagination_lines']}",
    ]
    return "\n".join(lines)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--log", required=True)
    ap.add_argument("--date", default=None, help="YYYY-MM-DD prefix filter")
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args()
    r = report(args.log, args.date)
    print(json.dumps(r, ensure_ascii=False, indent=2) if args.json else render(r))
    return 0


if __name__ == "__main__":
    sys.exit(main())
