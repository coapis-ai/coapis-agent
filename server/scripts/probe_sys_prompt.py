#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""实测系统提示词真实组成与固定开销（只读诊断）。

分解 sys_prompt：AGENTS.md / SOUL.md / PROFILE.md / 记忆段 / 技能索引 / 其他。
"""
import sys
from pathlib import Path

sys.path.insert(0, "/app")

from coapis.agents.prompt import build_system_prompt_from_working_dir  # noqa: E402


def main() -> None:
    roots = sys.argv[1:] or ["/apps/ai/coapis/agents/global_default"]
    for r in roots:
        wd = Path(r)
        if not wd.is_dir():
            print("skip (missing):", r)
            continue
        p = build_system_prompt_from_working_dir(working_dir=wd, agent_id=wd.name)
        print("=== %s" % r)
        print("sys_prompt chars: %d" % len(p))
        for fn in ("AGENTS.md", "SOUL.md", "PROFILE.md", "MEMORY.md", "USER.md"):
            f = wd / fn
            if f.is_file():
                print("   %-12s %d chars (file)" % (fn, len(f.read_text(encoding="utf-8"))))
        # 技能索引段
        i = p.find("skill_manager")
        print("   skill_manager 提及位置:", i, "| 技能索引段可见:", "trigger_keywords" in p or "技能索引" in p)
        print("   记忆标记:", "<!-- memory:start -->" in p)
        print("   尾部 300:", repr(p[-300:]))


main()
