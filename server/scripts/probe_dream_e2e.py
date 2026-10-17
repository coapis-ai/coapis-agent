#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""D2 验证：dream 全链路实测（写入端生成每日笔记 → 整合 MEMORY.md → 台账）。"""
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, "/app")

from coapis.agents.memory.reme_light_memory_manager import (  # noqa: E402
    ReMeLightMemoryManager,
)

WS = Path("/apps/ai/coapis/workspaces/admin")
AGENT_ID = "user:admin"
USERNAME = "admin"


def snapshot(tag: str) -> None:
    mem = WS / "MEMORY.md"
    print("  [%s] MEMORY.md: %s" % (
        tag,
        ("%d chars" % len(mem.read_text(encoding="utf-8"))) if mem.exists() else "不存在",
    ))
    md = WS / "memory"
    if md.is_dir():
        files = sorted(md.glob("*.md"))
        print("  [%s] memory/: %d 个文件 %s" % (
            tag, len(files), [f.name for f in files][-4:],
        ))
    else:
        print("  [%s] memory/: 不存在" % tag)


async def main() -> None:
    print("=== dream 前 ===")
    snapshot("前")

    mm = ReMeLightMemoryManager(
        working_dir=str(WS), agent_id=AGENT_ID, username=USERNAME,
    )
    out = await mm.dream()
    print("dream() 返回:", out)

    print("=== dream 后 ===")
    snapshot("后")

    today = WS / "memory" / "2026-10-17.md"
    if today.exists():
        txt = today.read_text(encoding="utf-8")
        print("=== 每日笔记前 600 字 ===")
        print(txt[:600])

    # 台账
    try:
        from coapis.foundation.repository_factory import RepositoryFactory
        mr = RepositoryFactory.get_memory_repository()
        rows = mr.list_outcomes(USERNAME) if hasattr(mr, "list_outcomes") else None
        print("=== 台账 ===", "rows:", rows[-2:] if rows else "无 list_outcomes")
    except Exception as exc:  # noqa: BLE001
        print("台账查询失败:", type(exc).__name__, exc)


asyncio.run(main())
