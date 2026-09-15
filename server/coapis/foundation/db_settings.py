"""社区版 · 数据库配置（决策 D-7/D-8/D-9，2026-09-15）。

单一环境变量：``COAPIS_DATABASE_URL``（可选）。

规则
----
- **未设置 / 空**：使用默认路径 ``<WORKING_DIR>/system/coapis.db``。
- **设置后必须是 SQLite**，支持两种写法：

  - 相对路径（推荐，D-9）::

        COAPIS_DATABASE_URL=system/coapis.db

    相对 WORKING_DIR 解析，文件永远落在挂载卷内。

  - 绝对路径 URL::

        COAPIS_DATABASE_URL=sqlite:////abs/path/coapis.db

    同样必须落在 WORKING_DIR 内。

- **不支持 PostgreSQL 等其它 scheme**（D-8）：社区版仅 SQLite；
  企业版用 ``COAPIS_DATABASE_URL=postgresql://...``。
- **数据库文件必须在挂载的 WORKING_DIR 内**（D-9）：所有环境的
  docker-compose 都把宿主机目录映射到容器内 WORKING_DIR，
  容器重建不丢数据；指向挂载外的路径直接报错（fail-fast）。
"""

from __future__ import annotations

import os
from pathlib import Path
from urllib.parse import urlsplit

from ..constant import WORKING_DIR, SYSTEM_DIR

DEFAULT_DB_FILENAME = "coapis.db"


class DatabaseConfigError(RuntimeError):
    """数据库配置错误：fail-fast，不允许带着错误位置启动。"""


def resolve_db_path() -> Path:
    """解析并校验社区版 SQLite 数据库文件路径。

    返回已 resolve 的绝对路径（一定位于 WORKING_DIR 内）。
    """
    raw = os.environ.get("COAPIS_DATABASE_URL", "").strip()
    if not raw:
        return SYSTEM_DIR / DEFAULT_DB_FILENAME

    candidate = _parse(raw)
    # D-9：相对路径必须相对 WORKING_DIR 解析（而非 CWD），保证落点确定、
    # 一定在挂载卷内。绝对路径保持原样。
    if not candidate.is_absolute():
        candidate = WORKING_DIR / candidate
    resolved = candidate.resolve()
    work = WORKING_DIR.resolve()
    if resolved != work and work not in resolved.parents:
        raise DatabaseConfigError(
            f"COAPIS_DATABASE_URL points to {resolved}, which is outside the "
            f"mounted working dir {work}. The database file must live inside the "
            "mounted working dir (decision D-9) so it survives container "
            "rebuilds. Use a relative path (resolved against WORKING_DIR) or "
            f"an absolute path inside {work}."
        )
    return resolved


def _parse(raw: str) -> Path:
    """把 COAPIS_DATABASE_URL 解析成 Path（未做 WORKING_DIR 校验）。

    URL 约定与 SQLAlchemy 一致：
    - ``sqlite:////abs/path``（4 斜杠）→ 绝对路径
    - ``sqlite:///rel/path``（3 斜杠）→ 相对路径（相对 WORKING_DIR）
    """
    if raw.startswith("sqlite://"):
        rest = raw[len("sqlite://"):]
        if rest.startswith("//"):
            # sqlite:////abs/path -> "/abs/path"
            return Path(rest[1:])
        if rest.startswith("/"):
            # sqlite:///rel/path -> "rel/path"
            return Path(rest[1:])
        if not rest:
            raise DatabaseConfigError(f"COAPIS_DATABASE_URL '{raw}' has no path part.")
        return Path(rest)
    if "://" in raw:
        scheme = raw.split("://", 1)[0]
        raise DatabaseConfigError(
            f"Unsupported database scheme '{scheme}': the community edition "
            "only supports SQLite (default: <WORKING_DIR>/system/coapis.db). "
            "PostgreSQL is for the enterprise edition."
        )
    # 裸路径（相对或绝对）
    return Path(raw)
