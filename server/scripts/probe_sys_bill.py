#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""系统提示词分段账单（只读）：复现 _build_sys_prompt 的各段尺寸。"""
import sys
from pathlib import Path

sys.path.insert(0, "/app")

WS = Path(sys.argv[1]) if len(sys.argv) > 1 else Path("/apps/ai/coapis/workspaces/admin")

from coapis.agents.prompt import build_system_prompt_from_working_dir  # noqa: E402

files = ["AGENTS.md", "SOUL.md", "PROFILE.md"]
base = build_system_prompt_from_working_dir(
    working_dir=WS, agent_id="user:admin", heartbeat_enabled=False,
    language="zh", memory_manager=None, enabled_files=files,
)
print("structural base:", len(base))

for f in files + ["MEMORY.md", "HEARTBEAT.md", "AGENTS.md"]:
    p = WS / f
    print("  file %-14s %s" % (f, len(p.read_text(encoding='utf-8')) if p.exists() else "-"))

# 继承的全局模板文件
try:
    from coapis.agents.global_agent_utils import get_template_agents
    for d in get_template_agents():
        for f in files:
            p = Path(d) / f
            if p.exists():
                print("  tpl %-22s %-12s %d" % (Path(d).name, f, len(p.read_text(encoding='utf-8'))))
except Exception as e:
    print("tpl scan:", e)

# 多模态提示
try:
    from coapis.agents.prompt import build_multimodal_hint
    print("multimodal hint:", len(build_multimodal_hint() or ""))
except Exception as e:
    print("multimodal:", e)

# 环境上下文
from coapis.app.runner.utils import build_env_context  # noqa: E402
print("env context:", len(build_env_context(session_id="x", user_id="admin", channel="console", working_dir=str(WS))))

# 技能索引
try:
    import re
    sk = WS / "skills"
    names = sorted(p.name for p in sk.iterdir() if p.is_dir()) if sk.exists() else []
    print("skills dirs:", len(names))
    # 索引行长度
    idx = 0
    for n in names:
        md = sk / n / "SKILL.md"
        desc = ""
        if md.exists():
            t = md.read_text(encoding="utf-8")
            m = re.search(r"description:\s*(.+)", t)
            if m:
                desc = m.group(1)[:120]
        idx += len(n) + len(desc) + 8
    print("skill index approx:", idx)
except Exception as e:
    print("skills:", e)

# 固定尾段
plan = len("## 任务规划") + 300
deps = 350
print("plan note ~", plan, " runtime deps ~", deps)
