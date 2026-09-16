# -*- coding: utf-8 -*-
"""First-boot migration: users.json → coapis.db (one-time, P1).

Runs automatically on first boot. Idempotent: safe to re-run; skips if
coapis.db already has users. After migration, the old JSON files are
renamed to ``*.migrated-<timestamp>`` as backup — they are NOT used at
runtime anymore.

Migration steps:
  1. Check if coapis.db exists and has users → skip if yes
  2. Read users.json (list or dict-wrapped format)
  3. Convert int IDs → UUID hex strings (deterministic: uuid.UUID(int=old_id))
  4. Insert into coapis.db (users, user_preferences, user_settings,
     audit_logs, point_transactions, token_usage, external_bindings)
  5. Rename users.json → users.json.migrated-<timestamp> (backup)

Usage:
    from coapis.foundation.migrations import ensure_migrated
    ensure_migrated()  # call before RepositoryFactory.initialize()
"""

from __future__ import annotations

import json
import logging
import shutil
import time
import uuid as uuid_mod
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional
from .external_identity_store_sqlite import _COLUMN_KEYS

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _now_iso() -> str:
    """Current local time as ISO-8601 string (default for created_at)."""
    return datetime.now().isoformat(timespec="seconds")


def _deterministic_uuid(old_id: Any) -> str:
    """Convert a legacy int ID to a deterministic UUID hex string.

    uuid.UUID(int=old_id) is a one-to-one mapping:
      1 → '00000000-0000-0000-0000-000000000001'
      2 → '00000000-0000-0000-0000-000000000002'
    Reversible: uuid.UUID(hex=uuid_str).int gives back the original int.
    """
    if old_id is None:
        return str(uuid_mod.uuid4())
    if isinstance(old_id, str):
        # Already a UUID or string ID
        try:
            return str(uuid_mod.UUID(hex=old_id))
        except (ValueError, AttributeError):
            return str(uuid_mod.uuid4())
    if isinstance(old_id, int):
        return str(uuid_mod.UUID(int=old_id))
    return str(uuid_mod.uuid4())


def _load_json_list(path: Path) -> List[Dict[str, Any]]:
    """Load a JSON file that may be a list or dict-wrapped list."""
    if not path.exists():
        return []
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
    except (json.JSONDecodeError, OSError):
        return []
    if isinstance(data, dict):
        for key in ("users", "audit_logs", "user_preferences", "api_keys",
                    "point_transactions", "token_usage", "external_bindings",
                    "user_settings", "bindings"):
            if key in data:
                value = data[key]
                if isinstance(value, list):
                    return value
                if isinstance(value, dict):
                    # 旧版格式: {"users": {username: user_dict, ...}}
                    return list(value.values())
        return []
    return data if isinstance(data, list) else []


# ---------------------------------------------------------------------------
# Core migration
# ---------------------------------------------------------------------------

def ensure_migrated(
    system_dir: Optional[Path] = None,
    db_path: Optional[Path] = None,
) -> bool:
    """Run first-boot migration if needed. Returns True if migration was performed.

    Args:
        system_dir: Directory containing users.json etc. Defaults to SYSTEM_DIR.
        db_path: Path for coapis.db. Defaults to system_dir / 'coapis.db'.
    """
    from ..constant import SYSTEM_DIR
    system_dir = system_dir or SYSTEM_DIR
    db_path = db_path or (system_dir / "coapis.db")

    # F6: migration is INCREMENTAL. The only skip condition is "users.json no
    # longer exists" (it is renamed by a prior migration). We deliberately do
    # NOT skip on "SQLite already has users" — that all-or-nothing gate was the
    # bug that stranded N-1 users in JSON while SQLite kept 1 (split-brain).
    # INSERT OR REPLACE + deterministic UUIDs make re-imports idempotent & safe.
    users_file = system_dir / "users.json"
    if not users_file.exists():
        logger.info(
            "Migration skipped: users.json not found at %s (already migrated)",
            users_file,
        )
        return False

    # Report current state for logging only (NOT a skip gate).
    existing_count = 0
    if db_path.exists():
        try:
            import sqlite3
            conn = sqlite3.connect(str(db_path))
            existing_count = conn.execute("SELECT COUNT(*) FROM users").fetchone()[0]
            conn.close()
        except Exception:
            pass

    logger.info(
        "Starting migration: %s → %s (SQLite already has %d users; importing any missing)",
        users_file, db_path, existing_count,
    )

    try:
        _do_migrate(system_dir, db_path)
        logger.info("Migration completed successfully")
        return True
    except Exception as e:
        logger.error("Migration failed: %s", e, exc_info=True)
        raise


def _guarded_table_migrate(conn, system_dir: Path, table: str, migrate_fn) -> int:
    """F6: run one per-table migration at most once.

    Append-only tables (audit_logs / api_keys / point_transactions /
    token_usage) are imported with bare INSERT.  If a previous run crashed
    mid-migration (users.json not yet backed up), a re-run would duplicate
    every row.  The per-table marker ensures each table is imported exactly
    once; a partial table import on crash can leave a few duplicates, but
    the whole table is never re-duplicated.
    """
    if get_migration_flag(conn, f"migrated_{table}") == "done":
        logger.info("Table %s already migrated (marker set), skipping", table)
        return 0
    count = migrate_fn(conn, system_dir)
    set_migration_flag(conn, f"migrated_{table}", "done")
    return count


def _do_migrate(system_dir: Path, db_path: Path) -> None:
    """Perform the actual migration. Called by ensure_migrated()."""
    import sqlite3

    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")

    try:
        _create_schema(conn)
        users_migrated = _migrate_users(conn, system_dir)
        if users_migrated == 0:
            # 兜底：users.json 缺失/不可解析时，尝试从旧版 user_system.db 导入
            legacy_migrated = _migrate_legacy_users_db(conn, system_dir)
            if legacy_migrated:
                logger.warning(
                    "users.json yielded 0 users; imported %d users from legacy %s",
                    legacy_migrated, system_dir / "user_system.db",
                )
        # F6: append-only tables (bare INSERT) are guarded by per-table
        # idempotency markers so a crash-recovery re-run never re-duplicates
        # a whole table.  UPSERT tables (users/preferences/settings/
        # external_bindings) are naturally re-runnable and stay unguarded.
        _guarded_table_migrate(conn, system_dir, "audit_logs", _migrate_audit_logs)
        _migrate_preferences(conn, system_dir)
        _migrate_settings(conn, system_dir)
        _guarded_table_migrate(conn, system_dir, "api_keys", _migrate_api_keys)
        _guarded_table_migrate(conn, system_dir, "point_transactions", _migrate_point_transactions)
        _guarded_table_migrate(conn, system_dir, "token_usage", _migrate_token_usage)
        _migrate_external_bindings(conn, system_dir)
        # F6: completion marker — records that the JSON→SQLite migration ran,
        # so the "already migrated?" check never relies on the users>0 heuristic.
        set_migration_flag(conn, "json_migration", "done")
        conn.commit()
    finally:
        conn.close()

    # Backup original JSON files
    _backup_json_files(system_dir)


def _create_schema(conn) -> None:
    """创建表结构与基础数据（幂等）。

    SQL 脚本位于 ``foundation/sql/``（决策 D-8：结构 + 基础数据全部脚本化，
    代码里不再内联 DDL）：
    - ``community_schema.sql`` 数据库结构（唯一事实来源）
    - ``community_seed.sql``   必须的基础数据（为空则跳过）

    注意：CREATE TABLE IF NOT EXISTS 不会改动已存在的表，所以先调用
    ``_ensure_users_columns`` 给旧库补齐新增列（password_set_by_user /
    onboarding_completed），再应用 schema，保证全新库与升级库最终同构。
    """
    from .sql import load_community_schema, load_community_seed

    _ensure_users_columns(conn)
    conn.executescript(load_community_schema())
    seed = load_community_seed().strip()
    if seed:
        conn.executescript(seed)
    conn.commit()


def _ensure_users_columns(conn) -> None:
    """给已存在的 ``users`` 表补齐新增列（幂等，升级路径）。

    CREATE TABLE IF NOT EXISTS 从不动已存在的表，旧库缺 password_set_by_user /
    onboarding_completed 两列会导致 create_user/update_user 静默丢字段。这里
    读 PRAGMA 判断缺哪列就补哪列。
    """
    import sqlite3
    try:
        cur = conn.execute("PRAGMA table_info(users)")
        existing = {row[1] for row in cur.fetchall()}
    except sqlite3.Error:
        return  # users 表还没建，CREATE TABLE 会按新 schema 建
    for name, ddl in (
        ("password_set_by_user", "INTEGER DEFAULT 0"),
        ("onboarding_completed", "INTEGER DEFAULT 1"),
    ):
        if name not in existing:
            try:
                conn.execute(f"ALTER TABLE users ADD COLUMN {name} {ddl}")
                logger.info("[migrations] added missing column users.%s", name)
            except sqlite3.Error as e:
                logger.warning("[migrations] failed to add users.%s: %s", name, e)
    conn.commit()


def set_migration_flag(conn, key: str, value: str) -> None:
    """写入迁移完成标记（F6）。"""
    conn.execute(
        "INSERT OR REPLACE INTO migration_state (key, value, updated_at) VALUES (?, ?, ?)",
        (key, value, time.time()),
    )
    conn.commit()


def get_migration_flag(conn, key: str):
    """读取迁移完成标记（F6）。不存在返回 None。"""
    import sqlite3
    try:
        row = conn.execute(
            "SELECT value FROM migration_state WHERE key = ?", (key,)
        ).fetchone()
        return row[0] if row else None
    except sqlite3.Error:
        return None


def _migrate_users(conn, system_dir: Path) -> int:
    """Migrate users.json → users table. Returns count of migrated users."""
    users = _load_json_list(system_dir / "users.json")
    count = 0
    for user in users:
        old_id = user.get("id")
        new_id = _deterministic_uuid(old_id)
        user_data = {
            "id": new_id,
            "username": user.get("username", ""),
            "password_hash": user.get("password_hash", ""),
            "salt": user.get("salt", ""),
            "display_name": user.get("display_name"),
            "email": user.get("email"),
            "avatar_url": user.get("avatar_url"),
            "token_quota_monthly": user.get("token_quota_monthly", 1000000),
            "token_used_monthly": user.get("token_used_monthly", 0),
            "role": user.get("role", "user"),
            "is_active": 1 if user.get("is_active", True) else 0,
            "created_at": user.get("created_at"),
            "updated_at": user.get("updated_at"),
            "last_login_at": user.get("last_login_at") or user.get("last_login"),
            "muga_key": user.get("muga_key"),
            # F1 收口：这两个字段旧 users.json 里有，SQLite 表原本没有，迁移时带过来，
            # 否则改成 SQLite 单一事实源后「首次设密码 / 引导」状态会丢。
            "password_set_by_user": 1 if user.get("password_set_by_user", False) else 0,
            "onboarding_completed": 1 if user.get("onboarding_completed", True) else 0,
        }
        # Remove None values for optional fields
        for key in list(user_data.keys()):
            if key not in ("id", "username", "password_hash", "salt", "role", "is_active") and user_data[key] is None:
                del user_data[key]

        columns = ", ".join(user_data.keys())
        placeholders = ", ".join(["?"] * len(user_data))
        conn.execute(
            f"INSERT OR REPLACE INTO users ({columns}) VALUES ({placeholders})",
            tuple(user_data.values()),
        )
        count += 1

    logger.info("Migrated %d users", count)
    return count


def _migrate_legacy_users_db(conn, system_dir: Path) -> int:
    """兜底导入：从旧版的 user_system.db 读取 users（与现 users 表同构）。

    仅在 users.json 迁移不到任何用户时调用（见 ``_do_migrate``）。
    旧库只读打开；任何异常都返回 0，不阻断迁移主流程。
    """
    import sqlite3

    legacy_db = system_dir / "user_system.db"
    if not legacy_db.exists():
        return 0
    try:
        src_conn = sqlite3.connect(f"file:{legacy_db}?mode=ro", uri=True)
        src_conn.row_factory = sqlite3.Row
        try:
            rows = [dict(r) for r in src_conn.execute("SELECT * FROM users")]
        except sqlite3.OperationalError:
            return 0
        finally:
            src_conn.close()
    except sqlite3.Error:
        return 0

    count = 0
    for user in rows:
        old_id = user.get("id")
        new_id = _deterministic_uuid(old_id)
        user_data = {
            "id": new_id,
            "username": user.get("username", ""),
            "password_hash": user.get("password_hash", ""),
            "salt": user.get("salt", ""),
            "display_name": user.get("display_name"),
            "email": user.get("email"),
            "avatar_url": user.get("avatar_url"),
            "token_quota_monthly": user.get("token_quota_monthly", 1000000),
            "token_used_monthly": user.get("token_used_monthly", 0),
            "role": user.get("role", "user"),
            "is_active": 1 if user.get("is_active", True) else 0,
            "created_at": user.get("created_at"),
            "updated_at": user.get("updated_at"),
            "last_login_at": user.get("last_login_at") or user.get("last_login"),
            "muga_key": user.get("muga_key"),
        }
        for key in list(user_data.keys()):
            if key not in ("id", "username", "password_hash", "salt", "role", "is_active") and user_data[key] is None:
                del user_data[key]
        columns = ", ".join(user_data.keys())
        placeholders = ", ".join(["?"] * len(user_data))
        conn.execute(
            f"INSERT OR REPLACE INTO users ({columns}) VALUES ({placeholders})",
            tuple(user_data.values()),
        )
        count += 1
    return count


def _migrate_audit_logs(conn, system_dir: Path) -> int:
    """Migrate audit_logs.json → audit_logs table."""
    logs = _load_json_list(system_dir / "audit_logs.json")
    count = 0
    for log in logs:
        user_id = _deterministic_uuid(log.get("user_id"))
        details = log.get("details")
        if isinstance(details, dict):
            details = json.dumps(details, ensure_ascii=False)
        conn.execute(
            """INSERT INTO audit_logs
               (user_id, username, action, resource_type, resource_id, details, ip_address, user_agent, created_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                user_id,
                log.get("username", ""),
                log.get("action", ""),
                log.get("resource_type"),
                log.get("resource_id"),
                details,
                log.get("ip_address", ""),
                log.get("user_agent", ""),
                log.get("created_at"),
            ),
        )
        count += 1
    logger.info("Migrated %d audit logs", count)
    return count


def _migrate_preferences(conn, system_dir: Path) -> int:
    """Migrate user_preferences.json → user_preferences table."""
    prefs = _load_json_list(system_dir / "user_preferences.json")
    count = 0
    for p in prefs:
        user_id = _deterministic_uuid(p.get("user_id"))
        settings = p.get("settings", {})
        if isinstance(settings, dict):
            settings = json.dumps(settings, ensure_ascii=False)
        conn.execute(
            """INSERT OR REPLACE INTO user_preferences (user_id, username, settings, updated_at)
               VALUES (?, ?, ?, ?)""",
            (user_id, p.get("username"), settings, p.get("updated_at")),
        )
        count += 1
    logger.info("Migrated %d preferences", count)
    return count


def _migrate_settings(conn, system_dir: Path) -> int:
    """Migrate user_settings.json → user_settings table."""
    settings = _load_json_list(system_dir / "user_settings.json")
    count = 0
    for s in settings:
        user_id = _deterministic_uuid(s.get("user_id"))
        conn.execute(
            """INSERT OR REPLACE INTO user_settings (user_id, setting_key, setting_value, updated_at)
               VALUES (?, ?, ?, ?)""",
            (user_id, s.get("setting_key", ""), s.get("setting_value"), s.get("updated_at")),
        )
        count += 1
    logger.info("Migrated %d settings", count)
    return count


def _migrate_api_keys(conn, system_dir: Path) -> int:
    """Migrate api_keys.json → api_keys table."""
    keys = _load_json_list(system_dir / "api_keys.json")
    count = 0
    for k in keys:
        user_id = _deterministic_uuid(k.get("user_id"))
        scopes = k.get("scopes", "[]")
        if isinstance(scopes, list):
            scopes = json.dumps(scopes)
        conn.execute(
            """INSERT INTO api_keys (user_id, name, key_prefix, key_hash, scopes, is_active, created_at, last_used_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                user_id,
                k.get("name", ""),
                k.get("key_prefix", ""),
                k.get("key_hash", ""),
                scopes,
                1 if k.get("is_active", True) else 0,
                k.get("created_at"),
                k.get("last_used_at"),
            ),
        )
        count += 1
    logger.info("Migrated %d API keys", count)
    return count


def _migrate_point_transactions(conn, system_dir: Path) -> int:
    """Migrate point_transactions.json → point_transactions table."""
    txs = _load_json_list(system_dir / "point_transactions.json")
    count = 0
    for t in txs:
        user_id = _deterministic_uuid(t.get("user_id"))
        conn.execute(
            """INSERT INTO point_transactions
               (user_id, amount, balance_after, transaction_type, description, reference_id, created_at)
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (
                user_id,
                t.get("amount", 0),
                t.get("balance_after", 0),
                t.get("transaction_type", ""),
                t.get("description", ""),
                t.get("reference_id", ""),
                t.get("created_at"),
            ),
        )
        count += 1
    logger.info("Migrated %d point transactions", count)
    return count


def _migrate_token_usage(conn, system_dir: Path) -> int:
    """Migrate token_usage.json → token_usage table."""
    records = _load_json_list(system_dir / "token_usage.json")
    count = 0
    for r in records:
        user_id = _deterministic_uuid(r.get("user_id"))
        conn.execute(
            """INSERT INTO token_usage
               (user_id, username, agent_id, model, input_tokens, output_tokens, total_tokens, cost_cents, created_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                user_id,
                r.get("username", ""),
                r.get("agent_id"),
                r.get("model", ""),
                r.get("input_tokens", 0),
                r.get("output_tokens", 0),
                r.get("total_tokens", 0),
                r.get("cost_cents", 0.0),
                r.get("created_at"),
            ),
        )
        count += 1
    logger.info("Migrated %d token usage records", count)
    return count


def _migrate_external_bindings(conn, system_dir: Path) -> int:
    """Migrate external identity bindings → external_bindings table.

    The community edition keeps bindings in ``external_identity_mappings.json``
    (shape ``{"bindings": [{user_id, provider, external_id, external_name,
    email, source, status, last_login_at, login_count, created_at}]}``).  We map
    each binding to the same columns the ``SqliteExternalIdentityStore`` uses
    and keep the original dict in ``extra_data`` so the round-trip is lossless.
    A legacy ``external_bindings.json`` (a bare list) is also honoured.
    """
    def _insert(b: Dict[str, Any]) -> bool:
        # NOTE: community binding.user_id is the local *username* — the app
        # layer (external_auth.py) uses it directly as a username, so it must
        # be preserved verbatim (no UUID conversion).
        user_id = str(b.get("user_id") or "")
        provider = str(b.get("provider") or b.get("external_system") or "")
        ext_id = str(b.get("external_id") or b.get("external_user_id") or "")
        if not (user_id and provider and ext_id):
            return False
        original = {k: v for k, v in b.items() if k not in _COLUMN_KEYS}
        conn.execute(
            """INSERT OR REPLACE INTO external_bindings
               (user_id, external_system, external_user_id, display_name,
                email, extra_data, created_at)
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (
                user_id,
                provider,
                ext_id,
                b.get("external_name") or b.get("display_name"),
                b.get("email"),
                json.dumps(original, ensure_ascii=False),
                b.get("created_at") or _now_iso(),
            ),
        )
        return True

    count = 0
    # Community shape: external_identity_mappings.json -> {"bindings": [...]}
    data = _load_json_dict(system_dir / "external_identity_mappings.json")
    for b in data.get("bindings", []):
        if _insert(b):
            count += 1
    # Legacy shape: external_bindings.json (a bare list).
    for b in _load_json_list(system_dir / "external_bindings.json"):
        if _insert(b):
            count += 1
    logger.info("Migrated %d external bindings", count)
    return count

def _load_json_dict(path: Path) -> Dict[str, Any]:
    """Load a JSON object from path; return {} if missing/invalid."""
    if not path.exists():
        return {}
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, dict) else {}
    except (json.JSONDecodeError, OSError):
        logger.warning("Could not load JSON dict from %s", path)
        return {}

def _backup_json_files(system_dir: Path) -> None:
    """Rename JSON data files to .migrated-<timestamp> backups."""
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    json_files = [
        "users.json",
        "audit_logs.json",
        "user_preferences.json",
        "user_settings.json",
        "api_keys.json",
        "point_transactions.json",
        "token_usage.json",
        "external_bindings.json",
    ]
    for fname in json_files:
        fpath = system_dir / fname
        if fpath.exists():
            backup = system_dir / f"{fname}.migrated-{ts}"
            shutil.move(str(fpath), str(backup))
            logger.info("Backed up %s → %s", fname, backup.name)
