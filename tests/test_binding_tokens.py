# -*- coding: utf-8 -*-
"""外部绑定 token 一等公民列（B 方案）专项测试。

验证：
  1. 新库：save_bindings 带 token 字段 → 落到列而非 extra_data；
     load_bindings 原样读回（round-trip）；
  2. 旧库（无 token 列，token 藏在 extra_data）：run_migrations() 后
     列回填、extra_data 清除、load_bindings 读到 token；
  3. token 刷新：再次 save_bindings 更新 token → 列值为最新；
  4. 迁移幂等：run_migrations() 连跑两次不报错。

独立运行：python tests/test_binding_tokens.py
"""

import json
import os
import sqlite3
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "server"))

RESULTS: list = []


def check(name: str, cond: bool, detail: str = ""):
    RESULTS.append((name, bool(cond), detail))
    print(f"[{'PASS' if cond else 'FAIL'}] {name}" + (f"  ({detail})" if detail and not cond else ""))


def _stub_agentscope_runtime():
    import importlib
    try:
        importlib.import_module("agentscope_runtime.engine.schemas.exception")
        return
    except Exception:  # noqa: BLE001
        pass
    from unittest.mock import MagicMock
    for name in (
        "agentscope_runtime",
        "agentscope_runtime.engine",
        "agentscope_runtime.engine.schemas",
        "agentscope_runtime.engine.schemas.exception",
    ):
        sys.modules.setdefault(name, MagicMock())


def _reset_env(tmp: Path):
    import coapis.constant as constant
    from coapis.foundation.repository_factory import RepositoryFactory

    RepositoryFactory.reset()
    from coapis.foundation.db import engine as eng
    eng.reset_engine()

    system_dir = tmp / "system"
    system_dir.mkdir(parents=True, exist_ok=True)
    constant.SYSTEM_DIR = system_dir
    constant.WORKING_DIR = tmp
    os.environ.pop("COAPIS_DATABASE_URL", None)
    return system_dir


def _insert_legacy_row(db_path: Path, extra: dict):
    """模拟旧版本写入的一行绑定：无 token 列，token 在 extra_data 里。"""
    conn = sqlite3.connect(str(db_path))
    conn.execute(
        """INSERT INTO external_bindings
           (user_id, external_system, external_user_id, display_name,
            email, extra_data, created_at)
           VALUES (?, ?, ?, ?, ?, ?, ?)""",
        (
            "liuliangxu", "oa", "liuliangxu", "刘良旭",
            "liuliangxu@example.com",
            json.dumps(extra, ensure_ascii=False),
            "2026-09-24T08:00:00",
        ),
    )
    conn.commit()
    conn.close()


def main():
    _stub_agentscope_runtime()
    tmp = Path(tempfile.mkdtemp(prefix="binding_token_test_"))
    _reset_env(tmp)

    from coapis.foundation.db.migrate import run_migrations
    from coapis.foundation.repository_factory import RepositoryFactory

    run_migrations()
    RepositoryFactory.reset()
    RepositoryFactory.initialize()
    store = RepositoryFactory.get_external_identity_store()
    check("store 可用", store is not None)

    db_path = tmp / "system" / "coapis.db"
    check("DB 文件存在", db_path.exists())

    # ---- 1. 新库 round-trip：token 落列，不进 extra_data ----
    store.save_bindings([
        {
            "user_id": "liuliangxu", "provider": "oa",
            "external_id": "liuliangxu", "external_name": "刘良旭",
            "email": "liuliangxu@example.com",
            "created_at": "2026-09-24T08:00:00",
            "token": "tok_v1", "refresh_token": "rt_v1",
            "expires_at": "2026-09-24T20:00:00",
            "token_updated_at": "2026-09-24T08:00:01",
            "note": "自由字段应留在 extra_data",
        },
    ])
    loaded = store.load_bindings()
    b = next(x for x in loaded if x["external_id"] == "liuliangxu")
    check("round-trip: token 读回", b.get("token") == "tok_v1", str(b))
    check("round-trip: refresh_token 读回", b.get("refresh_token") == "rt_v1")
    check("round-trip: expires_at 读回", b.get("expires_at") == "2026-09-24T20:00:00")
    check("round-trip: token_updated_at 读回", b.get("token_updated_at") == "2026-09-24T08:00:01")

    conn = sqlite3.connect(str(db_path))
    row = conn.execute(
        "SELECT external_access_token, external_refresh_token, "
        "token_expires_at, token_updated_at, extra_data FROM external_bindings"
    ).fetchone()
    conn.close()
    check("列值: external_access_token=tok_v1", row[0] == "tok_v1", str(row))
    check("列值: token_updated_at 落列", row[3] == "2026-09-24T08:00:01")
    extra = json.loads(row[4])
    check("extra_data 不含 token 键",
          all(k not in extra for k in ("token", "refresh_token", "expires_at", "token_updated_at")),
          str(extra))
    check("extra_data 保留自由字段", extra.get("note") == "自由字段应留在 extra_data", str(extra))

    # ---- 3. token 刷新：再 save 一次，列值更新 ----
    b["token"] = "tok_v2"
    b["token_updated_at"] = "2026-09-24T09:30:00"
    store.save_bindings([b])
    row2 = sqlite3.connect(str(db_path)).execute(
        "SELECT external_access_token, token_updated_at FROM external_bindings"
    ).fetchone()
    check("刷新: token 列更新为 tok_v2", row2[0] == "tok_v2", str(row2))
    check("刷新: token_updated_at 更新", row2[1] == "2026-09-24T09:30:00")
    loaded2 = store.load_bindings()
    b2 = next(x for x in loaded2 if x["external_id"] == "liuliangxu")
    check("刷新: load_bindings 读到新 token", b2.get("token") == "tok_v2")

    # ---- 4. 迁移幂等 ----
    run_migrations()
    check("幂等: 二次 run_migrations 无异常", True)

    # ---- 2. 旧库迁移回填 ----
    tmp2 = Path(tempfile.mkdtemp(prefix="binding_token_legacy_"))
    _reset_env(tmp2)
    db2 = tmp2 / "system" / "coapis.db"
    db2.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(db2))
    conn.execute(
        """CREATE TABLE external_bindings (
            id INTEGER NOT NULL PRIMARY KEY AUTOINCREMENT,
            user_id TEXT NOT NULL,
            external_system TEXT NOT NULL,
            external_user_id TEXT NOT NULL,
            display_name TEXT NOT NULL DEFAULT '',
            email TEXT NOT NULL DEFAULT '',
            extra_data TEXT NOT NULL DEFAULT '{}',
            created_at TEXT NOT NULL,
            UNIQUE(external_system, external_user_id)
        )"""
    )
    conn.commit()
    conn.close()
    _insert_legacy_row(
        db2,
        {
            "token": "legacy_tok", "refresh_token": "legacy_rt",
            "expires_at": "2026-09-24T18:00:00",
            "token_updated_at": "2026-09-24T08:00:01",
            "dept": "研发部",
        },
    )

    from coapis.foundation.db import engine as eng2
    eng2.init_engine(f"sqlite:///{db2}")
    run_migrations()
    RepositoryFactory.reset()
    RepositoryFactory.initialize()
    store2 = RepositoryFactory.get_external_identity_store()
    loaded3 = store2.load_bindings()
    check("旧库: 迁出后 1 行绑定", len(loaded3) == 1, str(loaded3))
    lb = loaded3[0]
    check("旧库: token 回填到 dict", lb.get("token") == "legacy_tok", str(lb))
    check("旧库: refresh_token 回填", lb.get("refresh_token") == "legacy_rt")
    check("旧库: expires_at 回填", lb.get("expires_at") == "2026-09-24T18:00:00")
    row3 = sqlite3.connect(str(db2)).execute(
        "SELECT external_access_token, extra_data FROM external_bindings"
    ).fetchone()
    check("旧库: 列值 = legacy_tok", row3[0] == "legacy_tok", str(row3))
    extra3 = json.loads(row3[1])
    check("旧库: extra_data 已清除 token 键",
          all(k not in extra3 for k in ("token", "refresh_token", "expires_at", "token_updated_at")),
          str(extra3))
    check("旧库: extra_data 保留 dept", extra3.get("dept") == "研发部", str(extra3))

    # ---- 汇总 ----
    passed = sum(1 for _, ok, _ in RESULTS if ok)
    total = len(RESULTS)
    print(f"\n===== 绑定 token 列（B 方案）：{passed}/{total} 通过 =====")
    RepositoryFactory.reset()
    eng2.reset_engine()
    if passed != total:
        for name, ok, detail in RESULTS:
            if not ok:
                print(f"  FAIL: {name} {detail}")
        sys.exit(1)
    import shutil
    shutil.rmtree(tmp, ignore_errors=True)
    shutil.rmtree(tmp2, ignore_errors=True)
    print("OK")


if __name__ == "__main__":
    main()
