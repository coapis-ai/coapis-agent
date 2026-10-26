#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""只读诊断专用连接闸门。

为什么需要它：``sqlite3.connect(path)`` 的默认语义是「文件不存在就建一个
0 字节库」。诊断脚本传错路径（尤其是相对路径）时，不会报错，而是**在进程
CWD 里静默创建一个空库**——这就是数据根目录反复长出 ``auth.db`` /
``coapis_core.db`` 这类 0 字节文件的根因。

本模块提供唯一允许的探测入口：
- 路径必须是绝对路径，否则直接抛错（相对路径 = 在 CWD 建库的入口）
- 文件必须已存在，否则直接抛错（绝不创建）
- 以 ``mode=ro`` URI 打开，SQLite 层面再兜一道：只读连接无法建库/写入

用法::

    from _probe_db import connect_ro
    con = connect_ro("/apps/ai/coapis-dev/system/coapis.db")
"""
from __future__ import annotations

import sqlite3
from pathlib import Path


def connect_ro(db_path: str | Path, *, row_factory: bool = True) -> sqlite3.Connection:
    """以只读方式打开一个**必须已存在**的 SQLite 库。

    Raises:
        FileNotFoundError: 路径为空、相对路径、或文件不存在。
    """
    raw = str(db_path).strip()
    if not raw:
        raise FileNotFoundError("db_path 为空：拒绝连接（裸 sqlite3.connect 会建 0 字节库）")

    path = Path(raw)
    if not path.is_absolute():
        raise FileNotFoundError(
            f"db_path 必须是绝对路径，收到相对路径 {raw!r}；"
            f"相对路径会按进程 CWD（当前 {Path.cwd()}）解析并建库"
        )
    if not path.is_file():
        raise FileNotFoundError(
            f"库文件不存在：{path}（只读闸门拒绝创建空库，请检查路径）"
        )

    con = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    if row_factory:
        con.row_factory = sqlite3.Row
    return con


def require_table(con: sqlite3.Connection, table: str) -> None:
    """表不存在时给出清晰错误，而不是让 SQLite 的 OperationalError 猜谜。"""
    hit = con.execute(
        "select 1 from sqlite_master where type='table' and name=?", (table,)
    ).fetchone()
    if hit is None:
        tables = [
            r[0]
            for r in con.execute(
                "select name from sqlite_master where type='table' order by name"
            )
        ]
        raise KeyError(f"表 {table!r} 不存在；现有表：{tables}")
