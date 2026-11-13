"""contract 测试的库隔离（B0 门禁）。

contract 测试会写台账/文件登记——必须落在临时库，绝不落进开发环境数据卷。

设计要点（2026-11-13 踩坑定稿）：
- 库文件 session 级建一次（create_all 全表，毫秒级）；
- **COAPIS_DATABASE_URL 与 engine 单例逐测试设置/复位**——session 级 env
  泄漏会污染同一进程里的后续测试（实测：test_foundation 的企业注入用例
  在 contract 之后跑到，读到 contract 的 tmp 库 URL 直接 DatabaseConfigError）；
- 复位 engine 单例三件套（_engine/_session_factory/_explicit_url），
  后续测试按原环境重建。
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest
from sqlalchemy import create_engine

from coapis.foundation.db.base import Base
from coapis.foundation.db.engine import init_engine


@pytest.fixture(scope="session")
def contract_db_url(tmp_path_factory):
    db_file = tmp_path_factory.mktemp("contract_db") / "contract.db"
    url = f"sqlite:///{db_file}"

    import coapis.foundation.db.models  # noqa: F401  触发全部表注册

    Base.metadata.create_all(create_engine(url))
    yield url
    Path(db_file).unlink(missing_ok=True)


@pytest.fixture(autouse=True)
def contract_scratch_database(contract_db_url):
    saved = os.environ.get("COAPIS_DATABASE_URL")
    os.environ["COAPIS_DATABASE_URL"] = contract_db_url
    init_engine(contract_db_url)
    try:
        yield
    finally:
        if saved is None:
            os.environ.pop("COAPIS_DATABASE_URL", None)
        else:
            os.environ["COAPIS_DATABASE_URL"] = saved
        import coapis.foundation.db.engine as engine_mod

        engine_mod._engine = None
        if hasattr(engine_mod, "_session_factory"):
            engine_mod._session_factory = None
        engine_mod._explicit_url = None
