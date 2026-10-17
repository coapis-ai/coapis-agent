#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""运行时验证：dream 台账落库（照 _app.py 的初始化方式，补齐探针进程缺的接线）。"""
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, "/app")

from coapis.foundation.migrations import ensure_migrated  # noqa: E402
from coapis.foundation.repository_factory import RepositoryFactory  # noqa: E402
from coapis.agents.memory.reme_light_memory_manager import (  # noqa: E402
    ReMeLightMemoryManager,
)

WS = Path("/apps/ai/coapis/workspaces/admin")
DATA_DIR = Path("/apps/ai/coapis")


def main() -> None:
    ensure_migrated()
    RepositoryFactory.initialize(edition="community", data_dir=DATA_DIR)
    print("RepositoryFactory 已初始化, data_dir =", DATA_DIR)

    mr = RepositoryFactory.get_memory_repository()
    print("memory_repository:", type(mr).__name__)
    methods = [m for m in dir(mr) if "outcome" in m.lower() or "dream" in m.lower()]
    print("台账相关方法:", methods)

    before = mr.list_outcomes("admin") if hasattr(mr, "list_outcomes") else None
    print("台账条数（前）:", len(before) if before is not None else "n/a")

    mm = ReMeLightMemoryManager(
        working_dir=str(WS), agent_id="user:admin", username="admin",
    )
    out = asyncio.run(mm.dream())
    print("dream() 返回:", out)

    after = mr.list_outcomes("admin") if hasattr(mr, "list_outcomes") else None
    print("台账条数（后）:", len(after) if after is not None else "n/a")
    if after:
        for row in after[-3:]:
            print("  台账行:", {k: v for k, v in dict(row).items()
                                if k in ("outcome_type", "status", "created_at",
                                         "source", "summary", "level", "result")})


main()
