# -*- coding: utf-8 -*-
"""隔离测试：迁移 role 回补（_backfill_roles_from_backups）。

模拟场景：老实例已经跑过首次迁移（users.json 已重命名为
users.json.migrated-<ts>），但旧版迁移把 admin 写成了 user。
验证 ensure_migrated 走 early-return 路径时会从备份恢复 role。
"""
import json
import sqlite3
import sys
import tempfile
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from coapis.foundation.migrations import ensure_migrated  # noqa: E402


def _setup(tmp: Path) -> Path:
    """建一个'已迁移过的老实例'：备份 users.json + 一个 role 被丢的 coapis.db。"""
    # 备份文件（迁移后保留的原始 users.json）
    backup_users = {
        "users": {
            "admin": {"id": 1, "username": "admin", "role": "admin",
                      "password_hash": "x", "salt": "y", "is_active": True},
            "alice": {"id": 2, "username": "alice", "role": "user",
                      "password_hash": "x", "salt": "y", "is_active": True},
            "bob": {"id": 3, "username": "bob", "role": "advanced",
                    "password_hash": "x", "salt": "y", "is_active": True},
        }
    }
    (tmp / "users.json.migrated-20260101_000000").write_text(
        json.dumps(backup_users, ensure_ascii=False), encoding="utf-8")

    # 当前 DB：admin 被旧迁移降成了 user（bug 现场）
    db = tmp / "coapis.db"
    conn = sqlite3.connect(str(db))
    conn.execute("""CREATE TABLE users (
        id TEXT PRIMARY KEY, username TEXT, password_hash TEXT, salt TEXT,
        display_name TEXT, email TEXT, avatar_url TEXT,
        token_quota_monthly INTEGER, token_used_monthly INTEGER,
        role TEXT, is_active INTEGER, created_at TEXT, updated_at REAL,
        last_login_at TEXT, muga_key TEXT,
        password_set_by_user INTEGER DEFAULT 0, onboarding_completed INTEGER DEFAULT 1)""")
    conn.execute("CREATE TABLE IF NOT EXISTS migration_state (key TEXT PRIMARY KEY, value TEXT, updated_at REAL)")
    for uid, uname, role in [("u1", "admin", "user"), ("u2", "alice", "user"), ("u3", "bob", "advanced")]:
        conn.execute(
            "INSERT INTO users (id, username, password_hash, salt, role, is_active, token_quota_monthly, token_used_monthly) "
            "VALUES (?,?,?,?,?,?,?,?)",
            (uid, uname, "x", "y", role, 1, 1000000, 0))
    conn.commit()
    conn.close()
    return db


def main() -> None:
    with tempfile.TemporaryDirectory() as td:
        tmp = Path(td)
        db = _setup(tmp)

        # 注意：users.json 不存在（已迁移），ensure_migrated 应走 early-return
        assert not (tmp / "users.json").exists()

        changed = ensure_migrated(system_dir=tmp, db_path=db)
        assert changed is False, f"expected already-migrated (False), got {changed}"

        conn = sqlite3.connect(str(db))
        conn.row_factory = sqlite3.Row
        roles = {r["username"]: r["role"] for r in conn.execute("SELECT username, role FROM users")}
        conn.close()
        print("after backfill:", roles)

        assert roles["admin"] == "admin", f"admin should be restored to admin, got {roles['admin']}"
        assert roles["alice"] == "user", f"alice should stay user, got {roles['alice']}"
        assert roles["bob"] == "advanced", f"bob should stay advanced, got {roles['bob']}"

        # 幂等：再跑一次，不应再变
        changed2 = ensure_migrated(system_dir=tmp, db_path=db)
        assert changed2 is False
        conn = sqlite3.connect(str(db))
        conn.row_factory = sqlite3.Row
        roles2 = {r["username"]: r["role"] for r in conn.execute("SELECT username, role FROM users")}
        conn.close()
        assert roles2 == roles, f"not idempotent: {roles} -> {roles2}"
        print("idempotent re-run OK:", roles2)

        # 反向保护：live 已是 admin，备份也是 admin，不降级、不重复
        # （已在上面 admin 案例覆盖）

    print("\n✅ ALL BACKFILL TESTS PASSED")


if __name__ == "__main__":
    main()
