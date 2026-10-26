# -*- coding: utf-8 -*-
"""静态护栏：禁止「拿不到工作区就回退进程 CWD」与「裸 sqlite3.connect」回归。

这两条是数据根目录反复长出 0 字节 ``*.db`` 的全部根因：

1. ``Path.cwd()`` 兜底 —— 容器里 CWD 是 ``/app``，生产数据根是
   ``/apps/ai/coapis-dev``；工具一旦 ``Path.cwd() / "files" / "x.db"`` 就在
   启动目录里建库。
2. 裸 ``sqlite3.connect(path)`` —— 默认语义「不存在就建」，路径写错不报
   错，只在 CWD 留下空库。诊断脚本必须走 ``scripts/_probe_db.connect_ro``
   （绝对路径 + 文件必须存在 + ``mode=ro``）。

用 AST 扫描，注释/文档字符串里的字面量不算违规。
"""
from __future__ import annotations

import ast
from pathlib import Path

SERVER = Path(__file__).resolve().parents[1]
TOOLS = SERVER / "coapis" / "agents" / "tools"
SCRIPTS = SERVER / "scripts"


def _calls(tree: ast.AST) -> list[ast.Call]:
    return [n for n in ast.walk(tree) if isinstance(n, ast.Call)]


def _callee_name(node: ast.Call) -> str:
    fn = node.func
    if isinstance(fn, ast.Attribute):
        return fn.attr
    if isinstance(fn, ast.Name):
        return fn.id
    return ""


def _py_files(root: Path) -> list[Path]:
    return sorted(p for p in root.rglob("*.py") if "__pycache__" not in p.parts)


def test_tools_never_fall_back_to_process_cwd() -> None:
    """工具层禁止 Path.cwd()：无工作区上下文时走 _paths 隔离目录。"""
    offenders: list[str] = []
    for path in _py_files(TOOLS):
        if path.name == "_paths.py":
            continue  # 唯一允许引用 CWD 的地方（仅用于 WARN 文案）
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for call in _calls(tree):
            if _callee_name(call) == "cwd" and isinstance(call.func, ast.Attribute):
                if isinstance(call.func.value, ast.Name) and call.func.value.id == "Path":
                    offenders.append(f"{path.name}:{call.lineno}")
    assert not offenders, (
        "工具层出现 Path.cwd() 兜底（会把产物写进进程 CWD）："
        + ", ".join(offenders)
        + " —— 改用 coapis/agents/tools/_paths.py 的 workspace_dir()/files_dir()"
    )


def test_probe_scripts_never_use_bare_sqlite_connect() -> None:
    """诊断脚本禁止裸 sqlite3.connect：必须走 _probe_db.connect_ro。"""
    offenders: list[str] = []
    for path in _py_files(SCRIPTS):
        if path.name == "_probe_db.py":
            continue
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for call in _calls(tree):
            if _callee_name(call) != "connect":
                continue
            fn = call.func
            if isinstance(fn, ast.Attribute) and isinstance(fn.value, ast.Name):
                if fn.value.id == "sqlite3":
                    offenders.append(f"{path.name}:{call.lineno}")
    assert not offenders, (
        "诊断脚本使用裸 sqlite3.connect（对不存在的文件会静默建 0 字节库）："
        + ", ".join(offenders)
        + " —— 改用 from _probe_db import connect_ro"
    )


def test_working_dir_is_absolute() -> None:
    """WORKING_DIR 必须是绝对路径，否则所有相对拼接都随启动目录漂移。"""
    from coapis.constant import WORKING_DIR

    assert Path(WORKING_DIR).is_absolute(), f"WORKING_DIR 非绝对路径：{WORKING_DIR}"
    assert Path(WORKING_DIR) != Path.cwd(), (
        "WORKING_DIR 与进程 CWD 相同：任何相对路径兜底都会直接落在数据根"
    )
