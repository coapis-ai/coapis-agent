#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""One-off backfill: promote historical session signals into memory_timelines.

Usage (inside the server container):
    cd /app && python -m scripts.backfill_timeline [--dry-run]

Safe to re-run: the timeline ``dedup_key`` makes appends idempotent.
"""

from __future__ import annotations

import argparse
import sys
import time

from coapis.agents.memory.signal_extractor import extract_signals_from_session
from coapis.constant import WORKSPACES_DIR
from coapis.foundation.memory_timeline import TimelineEntry
from coapis.foundation.repository_factory import RepositoryFactory


def backfill_one_user(user_id: str, dry_run: bool) -> int:
    sess_dir = WORKSPACES_DIR / user_id / "sessions"
    if not sess_dir.is_dir():
        return 0
    files = sorted(
        (p for p in sess_dir.rglob("*.json")),
        key=lambda p: p.stat().st_mtime,
        reverse=True,
    )
    tl = RepositoryFactory.get_memory_timeline_repository()
    n = 0
    for f in files:
        for cand in extract_signals_from_session(f):
            if dry_run:
                n += 1
                continue
            tl.append(TimelineEntry(
                user_id=user_id,
                agent_id=None,
                session_id=f.stem,
                signal_type=cand["signal_type"],
                content=cand["content"],
                source="backfill",
                importance=0.6,
            ))
            n += 1
    return n


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dry-run", action="store_true",
                        help="count signals without writing")
    args = parser.parse_args(argv)

    RepositoryFactory.initialize()
    t0 = time.monotonic()
    total = 0
    for user_dir in sorted(WORKSPACES_DIR.iterdir()):
        if not user_dir.is_dir():
            continue
        n = backfill_one_user(user_dir.name, args.dry_run)
        if n:
            print(f"  {user_dir.name}: {n}")
        total += n
    verb = "would promote" if args.dry_run else "promoted"
    print(f"{verb} {total} signals in {time.monotonic() - t0:.2f}s")
    return 0


if __name__ == "__main__":
    sys.exit(main())
