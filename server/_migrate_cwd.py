#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""一次性迁移：把工具层 22 处 Path.cwd() 兜底改为 _paths 隔离目录。"""
import pathlib
import re
import sys

TOOLS = pathlib.Path("coapis/agents/tools")

# (文件名, 旧片段, 新片段, 需要的 import)
SIMPLE_RETURN = "return Path.cwd()"

files = {}
for p in TOOLS.glob("*.py"):
    if p.name == "_paths.py":
        continue
    files[p] = p.read_text(encoding="utf-8")

changed = []
for p, src in files.items():
    if "Path.cwd()" not in src:
        continue
    s = src
    name = p.stem
    # 1) 纯 return Path.cwd()
    s = s.replace(
        SIMPLE_RETURN,
        f'return workspace_dir("{name}")',
    )
    # 2) Path.cwd() / "files" 前缀
    s = re.sub(r'Path\.cwd\(\) / "files"', f'files_dir("{name}")', s)
    # 3) 其余 Path.cwd() / xxx
    s = re.sub(r'Path\.cwd\(\)', f'workspace_dir("{name}")', s)
    if s == src:
        continue
    # 补 import：放在最后一个顶层 import 之后
    if "from ._paths import" not in s:
        if "workspace_dir(" in s and "files_dir(" in s:
            imp = "from ._paths import files_dir, workspace_dir\n"
        elif "workspace_dir(" in s:
            imp = "from ._paths import workspace_dir\n"
        else:
            imp = "from ._paths import files_dir\n"
        # 找到最后一个顶层 import 行
        lines = s.splitlines(keepends=True)
        last = -1
        for i, ln in enumerate(lines):
            if re.match(r"^(import |from )\S", ln):
                last = i
        if last < 0:
            print("!! no import anchor", p)
            sys.exit(1)
        lines.insert(last + 1, "\n" + imp)
        s = "".join(lines)
    p.write_text(s, encoding="utf-8")
    changed.append(p.name)

print("changed:", len(changed))
for c in sorted(changed):
    print("  ", c)
print("remaining Path.cwd():")
for p in TOOLS.glob("*.py"):
    if p.name == "_paths.py":
        continue
    for i, ln in enumerate(p.read_text(encoding="utf-8").splitlines(), 1):
        if "Path.cwd()" in ln:
            print("   ", p.name, i, ln.strip())
