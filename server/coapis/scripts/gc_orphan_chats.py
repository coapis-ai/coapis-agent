#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""批次 A1「索引 GC」——一次性清理脚本（在容器内跑）。

为什么是脚本而不是接口：接口只能看到「已经加载进内存」的工作区。实测
（dev，2026-10-27）POST /api/chats/admin/gc-orphans 只扫到 1 个索引 0 条
条目，而磁盘上是 25 个索引 447 条、其中 393 条（88%）会话文件不存在。
空壳索引属于没被加载的用户，只能按磁盘目录扫。

判定复用运行时的 ``_session_file_exists``（coapis/app/routers/chats.py），
不在这里重写目录规则 —— 两处各写一份路径逻辑正是「索引条目被误判为不
存在」的来源。它返回 None（判不了）时一律保留，绝不因为探测不到就动用
户的会话。

归档不是删除：条目原样写进 <workspace>/.trash/chat_archive/<时间戳>.json，
一份文件即可整份还原。

用法（容器内）：
    python -m coapis.scripts.gc_orphan_chats            # 只看，不动数据
    python -m coapis.scripts.gc_orphan_chats --apply    # 真正归档
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime, timezone

from coapis.app.runner.session import SafeJSONSession

SKIP_PARTS = ("/backups/", "/.trash/", "/data_archive/", "/.baseline-wt/")


def _verdict(session_obj, session_id: str, user_id: str):
    """与路由层同语义：True 存在 / False 不存在 / None 判不了。"""
    if session_obj is None or not session_id:
        return None
    try:
        path = session_obj._get_save_path(session_id, user_id=user_id)
    except Exception:
        return None
    return os.path.exists(path)


def session_dirs_for(index_path: str):
    """索引文件对应的 sessions 目录（按 workspace.py 的目录规则）。

    <ws>/chat/chats.json                -> <ws>/sessions
    <ws>/chats/chats.json               -> <ws>/sessions
    <ws>/agents/<aid>/chat/chats.json   -> <ws>/agents/<aid>/sessions, <ws>/sessions
    """
    d = os.path.dirname(os.path.abspath(index_path))
    base = os.path.basename(d)
    if base in ("chat", "chats", "sessions"):
        d = os.path.dirname(d)
    dirs = [os.path.join(d, "sessions")]
    parent = os.path.dirname(d)
    if os.path.basename(parent) == "agents":
        ws = os.path.dirname(parent)
        dirs.append(os.path.join(ws, "sessions"))
    return dirs


def load_index(path: str):
    with open(path, encoding="utf-8") as f:
        data = json.load(f)
    if isinstance(data, dict):
        return data
    return {"version": 1, "chats": data if isinstance(data, list) else []}


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--root", default=os.environ.get("WORKSPACE_DIR", "/apps/ai/coapis"))
    ap.add_argument("--apply", action="store_true", help="真正归档（默认只报告）")
    ap.add_argument("--limit", type=int, default=0, help="只处理前 N 个索引（调试用）")
    args = ap.parse_args()

    root = os.path.abspath(args.root)
    indexes = []
    for base, dirs, files in os.walk(root):
        dirs[:] = [d for d in dirs if d not in ("backups", ".trash", "data_archive", ".baseline-wt", "node_modules")]
        if "chats.json" in files:
            indexes.append(os.path.join(base, "chats.json"))
    indexes.sort()
    if args.limit:
        indexes = indexes[: args.limit]

    print(f"数据根 {root} / 索引 {len(indexes)} 个 / 模式 {'APPLY' if args.apply else 'DRY-RUN'}")

    grand_total = grand_orphan = grand_kept = 0
    touched = []
    for idx in indexes:
        try:
            data = load_index(idx)
        except Exception as exc:
            print(f"  跳过（读不了）{idx}: {exc}")
            continue
        chats = data.get("chats") or []
        if not chats:
            continue

        dirs = session_dirs_for(idx)
        sessions = [SafeJSONSession(save_dir=d) for d in dirs]

        kept, dropped = [], []
        for spec in chats:
            sid = spec.get("session_id") or spec.get("id")
            uid = spec.get("user_id") or ""
            verdicts = [_verdict(s, sid, uid) for s in sessions]
            if True in verdicts:
                kept.append(spec)
            elif False in verdicts:
                dropped.append(spec)
            else:
                kept.append(spec)  # 判不了 -> 保留

        grand_total += len(chats)
        grand_kept += len(kept)
        grand_orphan += len(dropped)
        rel = os.path.relpath(idx, root)
        if not dropped:
            continue
        touched.append((rel, len(chats), len(kept), len(dropped)))
        print(f"  {rel}: 共 {len(chats)} 条，留 {len(kept)}，归档 {len(dropped)}")

        if not args.apply:
            continue

        ws_dir = os.path.dirname(os.path.dirname(os.path.abspath(idx)))
        archive_dir = os.path.join(ws_dir, ".trash", "chat_archive")
        os.makedirs(archive_dir, exist_ok=True)
        stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        payload = {
            "version": data.get("version", 1),
            "archived_at": stamp,
            "archived_by": "gc_orphan_chats",
            "source_index": os.path.abspath(idx),
            "reason": "index entry whose session file does not exist",
            "chats": dropped,
        }
        apath = os.path.join(archive_dir, f"{stamp}_{os.path.basename(ws_dir)}.json")
        with open(apath, "w", encoding="utf-8") as f:
            json.dump(payload, f, ensure_ascii=False, indent=2)

        # 原索引先留一份快照，再写精简版
        snap = os.path.join(archive_dir, f"{stamp}_{os.path.basename(ws_dir)}_index-before.json")
        with open(snap, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)

        data["chats"] = kept
        tmp = os.path.join(archive_dir, f"{stamp}_tmp_index.json")
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        os.replace(tmp, idx)
        print(f"      -> 归档 {len(dropped)} 条到 {os.path.relpath(apath, root)}")

    print("-" * 68)
    print(f"合计：索引条目 {grand_total}，保留 {grand_kept}，空壳 {grand_orphan}"
          f"（{100.0 * grand_orphan / max(1, grand_total):.1f}%），涉及 {len(touched)} 个索引")
    if not args.apply:
        print("DRY-RUN：没有改动任何文件。加 --apply 才真正归档。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
