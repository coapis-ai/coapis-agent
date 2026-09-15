"""社区版 SQLite SQL 脚本（D-8：数据库结构 + 必须的基础数据全部脚本化）。

- ``community_schema.sql`` — 数据库结构（唯一事实来源，幂等）
- ``community_seed.sql``   — 必须的基础数据（幂等；当前为空占位）

初始化时由 ``foundation/migrations.py::_create_schema`` 统一执行；
``user_repository_sqlite.py::_create_tables`` 作为访问兜底执行同一份结构脚本。
"""

from __future__ import annotations

from pathlib import Path

_SQL_DIR = Path(__file__).parent


def _read(name: str) -> str:
    path = _SQL_DIR / name
    if not path.exists():
        raise RuntimeError(f"Missing SQL script: {path}")
    return path.read_text(encoding="utf-8")


def load_community_schema() -> str:
    """数据库结构脚本（community_schema.sql）。"""
    return _read("community_schema.sql")


def load_community_seed() -> str:
    """基础数据脚本（community_seed.sql）。"""
    return _read("community_seed.sql")
