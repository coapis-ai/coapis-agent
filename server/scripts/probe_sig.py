#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""browser_use 参数完备性 + _get_executor 作用域检查（只读）。"""
import ast
import sys

SRC = sys.argv[1] if len(sys.argv) > 1 else "coapis/agents/tools/browser_control.py"
t = ast.parse(open(SRC, encoding="utf-8").read())

KEYS = ("path", "filename", "paths_json", "screenshot_type", "level", "port",
        "port_min", "port_max", "include_static", "snapshot_filename",
        "file_path", "private_mode", "cdp_port", "executable_path",
        "slowly", "width", "height", "frame_selector", "headed")

for fn in ast.walk(t):
    if isinstance(fn, (ast.AsyncFunctionDef, ast.FunctionDef)) and fn.name == "browser_use":
        ps = [p.arg for p in fn.args.args] + [p.arg for p in fn.args.kwonlyargs]
        print("browser_use 参数数 = %d" % len(ps))
        for k in KEYS:
            print("   %-18s %s" % (k, "有" if k in ps else "**缺**"))

print("\n_get_executor 作用域：")
for fn in ast.walk(t):
    if not isinstance(fn, (ast.AsyncFunctionDef, ast.FunctionDef)):
        continue
    has_def = any(isinstance(s, (ast.FunctionDef, ast.AsyncFunctionDef))
                  and s.name == "_get_executor" for s in ast.walk(fn))
    uses = [s.lineno for s in ast.walk(fn)
            if isinstance(s, ast.Name) and s.id == "_get_executor"
            and isinstance(s.ctx, ast.Load)]
    if has_def and uses:
        print("   def@%d 在 %s 内定义并被使用 %d 处  OK" % (fn.lineno, fn.name, len(uses)))
    elif uses and not has_def:
        print("   **风险** %s (def@%d) 使用 _get_executor %d 处，本函数内未定义: %s"
              % (fn.name, fn.lineno, len(uses), uses[:5]))
