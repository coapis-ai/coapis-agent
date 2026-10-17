#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""AST 静态检查：browser_use 函数体里引用了但从未绑定的名字（只读）。"""
import ast
import sys

SRC = sys.argv[1] if len(sys.argv) > 1 else "coapis/agents/tools/browser_control.py"
tree = ast.parse(open(SRC, encoding="utf-8").read())

glob = set()
for n in tree.body:
    if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
        glob.add(n.name)
    elif isinstance(n, ast.Assign):
        for t in ast.walk(n):
            if isinstance(t, ast.Name):
                glob.add(t.id)
    elif isinstance(n, (ast.Import, ast.ImportFrom)):
        for a in n.names:
            glob.add((a.asname or a.name).split(".")[0])
    elif isinstance(n, (ast.AnnAssign, ast.AugAssign)):
        if isinstance(n.target, ast.Name):
            glob.add(n.target.id)

for fn in ast.walk(tree):
    if isinstance(fn, (ast.AsyncFunctionDef, ast.FunctionDef)) and fn.name == "browser_use":
        bound = set()
        a = fn.args
        for p in list(a.args) + list(a.kwonlyargs):
            bound.add(p.arg)
        for st in ast.walk(fn):
            if isinstance(st, ast.Name) and isinstance(st.ctx, ast.Store):
                bound.add(st.id)
            if isinstance(st, (ast.FunctionDef, ast.AsyncFunctionDef)):
                bound.add(st.name)
                for p in list(st.args.args) + list(st.args.kwonlyargs):
                    bound.add(p.arg)
            if isinstance(st, (ast.Import, ast.ImportFrom)):
                for i in st.names:
                    bound.add((i.asname or i.name).split(".")[0])
            if isinstance(st, (ast.Global, ast.Nonlocal)):
                bound.update(st.names)
            if isinstance(st, ast.ExceptHandler) and st.name:
                bound.add(st.name)
            if isinstance(st, ast.arg):
                bound.add(st.arg)
            if isinstance(st, (ast.ListComp, ast.GeneratorExp, ast.SetComp, ast.DictComp)):
                for g in st.generators:
                    for t in ast.walk(g.target):
                        if isinstance(t, ast.Name):
                            bound.add(t.id)
        used = {}
        for st in ast.walk(fn):
            if isinstance(st, ast.Name) and isinstance(st.ctx, ast.Load):
                used.setdefault(st.id, st.lineno)
        missing = {k: v for k, v in used.items()
                   if k not in bound and k not in glob and k not in dir(__builtins__)}
        print("browser_use 签名参数=%d" % len(bound))
        print("引用但未绑定的名字（运行时必 NameError）:")
        for k, v in sorted(missing.items(), key=lambda x: x[1]):
            print("   line %-5d %s" % (v, k))
        if not missing:
            print("   （无）")
