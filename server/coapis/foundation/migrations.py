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
import hashlib
import uuid as uuid_mod
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

from sqlalchemy import text

from .external_identity_impl import _COLUMN_KEYS

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
    # T3（bug① 治本）区分两种情况：文件不存在 → 无遗留数据，返回 []；
    # 存在但读不出合法 JSON → 真实故障，显式失败。旧行为静默 `return []` = bug①。
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
    except (json.JSONDecodeError, OSError) as e:
        logger.error("legacy JSON unreadable at %s: %r — 拒绝静默跳过，向上抛出", path, e)
        raise RuntimeError(
            f"遗留数据文件存在但无法解析（{path}）：{type(e).__name__}: {e}"
        ) from e
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
        # Already migrated (users.json renamed to .migrated-<ts>). Older
        # first-boot migrations wrote users WITHOUT a meaningful role, so
        # admin accounts could land as plain "user" and silently lose the
        # whole admin-panel UI. Recover lost roles from the .migrated-*
        # backups (promotion-only, idempotent, best-effort — never blocks
        # startup).
        try:
            _backfill_roles_from_backups(system_dir, db_path)
        except Exception as e:  # noqa: BLE001 — backfill must never block startup
            logger.warning("Role backfill from backups failed: %s", e)
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


def _crows(conn, sql):
    """双类型兼容查询执行（raw sqlite3.Connection / SQLAlchemy Connection）。

    ``conn`` 来自 ensure_migrated/ensure_domain 路径时是 raw sqlite3；B-tier runtime
    路径传的是 SA Connection。SQLAlchemy ≥2.0 strict 模式拒绝裸字符串 SQL，仅当报
    "not executable" 类错误才回退 TextClause —— 真实 DB 错误一律原样抛出。
    """
    try:
        return conn.execute(sql).fetchall()  # type: ignore[arg-type]
    except Exception as ex:  # noqa: BLE001 — raw sqlite3 对合法 SQL 字符串不会报此类错
        if getattr(type(ex), "__name__", "") != "ObjectNotExecutableError":
            raise
        from sqlalchemy import text as _t

        return conn.execute(_t(sql)).fetchall()  # type: ignore[union-attr]


def _cexec(conn, sql) -> None:
    """双类型兼容单语句执行（无结果集），语义同 :func:`_crows`。"""
    try:
        conn.execute(sql)  # type: ignore[arg-type]
    except Exception as ex:  # noqa: BLE001 — 同上：仅 "not executable" 回退 text()
        if getattr(type(ex), "__name__", "") != "ObjectNotExecutableError":
            raise
        from sqlalchemy import text as _t

        conn.execute(_t(sql))  # type: ignore[union-attr]


def _create_schema(conn) -> None:
    """确保 ``conn`` 所在数据库具备完整表结构（幂等）。

    T2 单一事实来源 = ORM metadata（:mod:`coapis.foundation.db.models`），
    Alembic 迁移链也从同一份 metadata 生成。旧 raw-DDL 文件
    （community_schema.sql / community_seed.sql）已无任何运行时引用，
    待清理批次统一删除：

    - 全新库 → 按外键顺序逐表创建（每表 checkfirst，重复应用安全）；
    - 存量库 → 已有表整体跳过（等价 CREATE IF NOT EXISTS），建完后再由
      ``_ensure_users_columns`` 补齐旧 users 表的两个新增列。

    **先建表、后补列**：SA Connection 事务内对不存在的表执行 ALTER 会污染整个
    连接的事务；全新库的 users 本就带新列（ORM metadata），只有 legacy raw-DDL
    老表才需要 ALTER，此时表必然已存在。

    seed 文件删除前已核实不含任何数据行（纯注释占位），无需移植：
    admin 引导在运行时发生 —— app/routers/auth.py::register，首个注册用户
    自动获得 admin 角色。
    """
    import coapis.foundation.db.models  # noqa: F401 -- register all models on Base.metadata

    from sqlalchemy import create_engine, inspect as sa_inspect, text as _text

    from .db.base import Base

    def _row(sql):  # type-agnostic execute：raw sqlite3 / SA Connection（2.x strict）都支持
        try:
            return conn.execute(sql).fetchone()  # type: ignore[arg-type]
        except Exception:
            return conn.execute(_text(sql)).fetchone()

    row = _row("PRAGMA database_list")
    db_file = str(row[2]) if len(row) > 2 and row[2] else ""
    if not Path(db_file).exists():
        raise RuntimeError(
            f"_create_schema: expected a file-backed SQLite DB, got {db_file!r}"
        )

    engine = create_engine(
        f"sqlite:///{Path(db_file)}", connect_args={"check_same_thread": False}
    )
    try:
        with engine.begin() as sa_conn:
            existing = set(sa_inspect(sa_conn).get_table_names())
            for table in Base.metadata.sorted_tables:  # FK-safe order
                if table.name not in existing:
                    table.create(bind=sa_conn)
    finally:
        engine.dispose()

    # 建表完成后再补列（见 docstring：SA 事务内对不存在的表 ALTER 会污染连接）
    _ensure_users_columns(conn)

    # T3（bug① 根因之一）：这里**不再内部 commit**。旧代码无条件 `conn.commit()`，
    # 当调用方用 SA Connection + engine.begin() 包着跑时（repository_factory），
    # 会提前终止外层事务 → 后续 SQL 全部 InvalidRequestError("Can't operate on
    # closed transaction")——而该错误又被 ensure_runtime_domain_migrated 的逐域
    # try/except warn+continue 吞掉，表现为"B档迁移静默迁了个寂寞"。
    # 现在事务所有权归调用方：raw sqlite3 路径由各自显式 commit（DDL 本就自动提交）；
    # SA 路径由 engine.begin() / ensure_runtime_domain_migrated 末尾统一收尾。


def _ensure_users_columns(conn) -> None:
    """给已存在的 ``users`` 表补齐新增列（幂等，升级路径）。

    CREATE TABLE IF NOT EXISTS 从不动已存在的表，旧库缺 password_set_by_user /
    onboarding_completed 两列会导致 create_user/update_user 静默丢字段。这里
    读 PRAGMA 判断缺哪列就补哪列；``conn`` 双类型兼容（raw sqlite3 / SA）。
    """
    try:
        rows = _crows(conn, "PRAGMA table_info(users)")  # users 表不存在时返回空 → 稍后 CREATE 按新 schema 建
    except Exception as ex:  # noqa: BLE001 — 检查阶段异常一律跳过，交由全新建表兜底（保持旧语义）
        logger.debug("[migrations] _ensure_users_columns skipped: %s", ex)
        return

    if not rows:  # users 表尚不存在 → 无列可补，交由建表路径按新 schema 创建
        return

    existing = {row[1] for row in rows}
    added_any = False
    for name, ddl in (
        ("password_set_by_user", "INTEGER DEFAULT 0"),
        ("onboarding_completed", "INTEGER DEFAULT 1"),
    ):
        if name not in existing:
            try:
                _cexec(conn, f"ALTER TABLE users ADD COLUMN {name} {ddl}")
                logger.info("[migrations] added missing column users.%s", name)
                added_any = True
            except Exception as e:  # noqa: BLE001 — 保持旧语义：失败告警不中断（如并发重复加列）
                logger.warning("[migrations] failed to add users.%s: %s", name, e)

    if added_any and hasattr(conn, "commit"):
        conn.commit()  # raw sqlite3 / SA Connection；Engine 无 commit，事务归其上下文管理


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
        # 明文密码 → 哈希（与 create_user 一致：迁移后不保留明文）。
        if user.get("password") and not user.get("password_hash"):
            salt = uuid_mod.uuid4().hex
            user_data["password_hash"] = hashlib.sha256(
                f"{user['password']}:{salt}".encode("utf-8")
            ).hexdigest()
            user_data["salt"] = salt
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


_ROLE_LEVEL: Dict[str, int] = {"user": 0, "advanced": 1, "admin": 2}


def _role_level(role: Any) -> int:
    """Rank a role for promotion-only backfill; unknown roles rank lowest."""
    return _ROLE_LEVEL.get(str(role or "").strip().lower(), 0)


def _backfill_roles_from_backups(system_dir: Path, db_path: Path) -> int:
    """Recover user roles lost by older first-boot migrations.

    Early migration versions (before F1's role mapping existed) wrote users
    into SQLite without a meaningful ``role`` — admin accounts landed as
    plain ``user`` and lost the entire admin-panel UI.  The original
    ``users.json`` is preserved as ``users.json.migrated-<timestamp>`` after
    migration, so this pass scans those backups and re-applies the original
    role to the live row — but **promotion-only**: a live user is only
    upgraded when the backup's role level is strictly higher (e.g. a live
    ``user`` upgraded to backup ``admin``).  It never downgrades, never
    touches matching roles, and is idempotent (re-running changes nothing).

    Best-effort: any failure is swallowed by the caller; returns the number
    of users promoted.
    """
    import glob
    import sqlite3

    backups = sorted(glob.glob(str(system_dir / "users.json.migrated-*")))
    if not backups or not db_path.exists():
        return 0

    # Collect the strongest role per username across all backups.
    backup_roles: Dict[str, str] = {}
    for bpath in backups:
        for u in _load_json_list(Path(bpath)):
            username = u.get("username")
            role = u.get("role")
            if not username or not role or _role_level(role) <= 0:
                continue
            existing = backup_roles.get(username)
            if existing is None or _role_level(role) > _role_level(existing):
                backup_roles[username] = role
    if not backup_roles:
        return 0

    conn = sqlite3.connect(str(db_path), timeout=30.0)
    conn.row_factory = sqlite3.Row
    promoted = 0
    try:
        for username, role in backup_roles.items():
            row = conn.execute(
                "SELECT role FROM users WHERE username = ?", (username,)
            ).fetchone()
            if row is None:
                continue  # user no longer exists — nothing to backfill
            live_role = row["role"]
            if _role_level(role) > _role_level(live_role):
                conn.execute(
                    "UPDATE users SET role = ?, updated_at = ? WHERE username = ?",
                    (role, time.time(), username),
                )
                promoted += 1
                logger.info(
                    "[backfill] restored role: %s %s -> %s (from users.json backup)",
                    username, live_role, role,
                )
        conn.commit()
    finally:
        conn.close()
    return promoted


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
    records = _load_json_list(system_dir / "token_usage_details.json")
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


# ---------------------------------------------------------------------------
# B 档：运行时域 JSON → DB 迁移（token_usage 日聚合/明细、知识库、权限配置）
# 全部按「表空且文件有数据才迁」自守幂等，无额外 flag。
# ---------------------------------------------------------------------------

def _migrate_token_usage_daily(conn, system_dir: Path) -> int:
    """token_usage.json（日聚合 {date: {provider:model: {...}}}）→ token_usage_daily 表。"""
    path = system_dir / "token_usage.json"
    if not path.exists():
        return 0
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as e:
        # T3（bug①）：文件存在但解析失败是真实故障，禁止静默按"无数据"跳过。
        logger.error("legacy token_usage.json unreadable at %s: %r", path, e)
        raise RuntimeError(
            f"遗留数据文件存在但无法解析（{path}）：{type(e).__name__}: {e}"
        ) from e
    if not isinstance(data, dict):
        return 0
    existing = conn.execute(text("SELECT COUNT(*) FROM token_usage_daily")).fetchone()
    if existing and int(existing[0]) > 0:
        return 0  # 表非空 → 已迁移过
    count = 0
    for day, entries in data.items():
        if not isinstance(entries, dict):
            continue
        for entry in entries.values():
            if not isinstance(entry, dict):
                continue
            conn.execute(
                text(
                    "INSERT INTO token_usage_daily "
                    "(date, provider_id, model_name, prompt_tokens, "
                    " completion_tokens, call_count, last_updated) "
                    "VALUES (:day, :pid, :mid, :pt, :ct, :cc, :ts) "
                    "ON CONFLICT(date, provider_id, model_name) DO UPDATE SET "
                    "prompt_tokens = excluded.prompt_tokens, "
                    "completion_tokens = excluded.completion_tokens, "
                    "call_count = excluded.call_count, "
                    "last_updated = excluded.last_updated"
                ),
                {
                    "day": str(day),
                    "pid": str(entry.get("provider_id", "") or ""),
                    "mid": str(entry.get("model_name", "") or ""),
                    "pt": int(entry.get("prompt_tokens", 0) or 0),
                    "ct": int(entry.get("completion_tokens", 0) or 0),
                    "cc": int(entry.get("call_count", 0) or 0),
                    "ts": str(entry.get("last_updated", "") or ""),
                },
            )
            count += 1
    logger.info("Migrated %d token usage daily rows", count)
    return count


def _migrate_token_usage_details_retry(conn, system_dir: Path) -> int:
    """B 档补跑：M0 误读 token_usage.json 致明细未入库；表空时补迁 details 文件。"""
    existing = conn.execute(text("SELECT COUNT(*) FROM token_usage")).fetchone()
    if existing and int(existing[0]) > 0:
        return 0  # 表非空 → 已有明细
    records = _load_json_list(system_dir / "token_usage_details.json")
    if not records:
        return 0
    count = 0
    for r in records:
        if not isinstance(r, dict):
            continue
        created_at = r.get("created_at", "")
        if isinstance(created_at, str):
            try:
                created_at = datetime.fromisoformat(created_at).timestamp()
            except (ValueError, TypeError):
                created_at = time.time()
        elif not isinstance(created_at, (int, float)):
            created_at = time.time()
        conn.execute(
            text(
                """INSERT INTO token_usage
                   (user_id, username, agent_id, model, input_tokens,
                    output_tokens, total_tokens, cost_cents, created_at)
                   VALUES (:uid, :uname, :aid, :model, :it, :ot, :tt, :cost, :ts)""",
            ),
            {
                "uid": r.get("user_id", ""),
                "uname": r.get("username", ""),
                "aid": r.get("agent_id"),
                "model": r.get("model", ""),
                "it": r.get("input_tokens", 0),
                "ot": r.get("output_tokens", 0),
                "tt": r.get("total_tokens", 0),
                "cost": r.get("cost_cents", 0.0),
                "ts": created_at,
            },
        )
        count += 1
    logger.info("Migrated %d token usage detail rows (retry)", count)
    return count


def _migrate_permissions(conn, system_dir: Path) -> int:
    """permissions.json（整个配置 dict）→ permissions_config 表（key='all' 单行）。"""
    path = system_dir / "permissions.json"
    if not path.exists():
        return 0
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as e:
        # T3（bug①）：文件存在但解析失败是真实故障，禁止静默按"无数据"跳过。
        logger.error("legacy permissions.json unreadable at %s: %r", path, e)
        raise RuntimeError(
            f"遗留数据文件存在但无法解析（{path}）：{type(e).__name__}: {e}"
        ) from e
    if not isinstance(data, dict):
        return 0
    existing = conn.execute(text("SELECT COUNT(*) FROM permissions_config")).fetchone()
    if existing and int(existing[0]) > 0:
        return 0
    conn.execute(
        text("INSERT OR IGNORE INTO permissions_config (key, value) VALUES ('all', :v)"),
        {"v": json.dumps(data, ensure_ascii=False)},
    )
    logger.info("Migrated permissions config")
    return 1


def ensure_runtime_domain_migrated(conn, system_dir: Path) -> None:
    """B 档：运行时域 JSON → DB 迁移（幂等，表空且文件有数据才迁）。

    与 ensure_domain_migrated 独立：domain_migration flag 已在存量实例打平，
    新域用自己的表空判断做自守，不受旧 flag 影响。
    """
    system_dir = Path(system_dir)
    # 确保 B 档表存在（幂等）：存量实例的 DB 早于 B 档建表，
    # permissions_config / token_usage_daily 可能缺失（ORM 导入顺序 / 首次建表
    # 时机都不保证覆盖到）。T2：_create_schema 由 ORM metadata 驱动
    # （与 Alembic 同一事实来源），重复应用安全。
    _create_schema(conn)
    # T3（bug① 治本）：不再逐域 try/except warn+continue。旧行为把 NameError /
    # JSON 解析失败降级成一条 warning，服务照常启动、数据静默丢失——正是 bug①
    # 长期未被发现的原因。现在任何一域迁移异常都直接向上抛出（调用方事务回滚），
    # 以显式错误终止启动；修复文件后重启即可幂等续跑。
    totals = {}
    for name, fn in (
        ("token_usage_daily", _migrate_token_usage_daily),
        ("token_usage_details", _migrate_token_usage_details_retry),
        ("permissions", _migrate_permissions),
    ):
        totals[name] = fn(conn, system_dir)
    if any(totals.values()):
        conn.commit()
        logger.info(f"Runtime domain migration complete: {totals}")


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


# ---------------------------------------------------------------------------
# M1 四域落库迁移（域A外部系统 / 域C标签 / 域B场景 / 域D用户场景）
# ---------------------------------------------------------------------------

def ensure_domain_migrated(data_dir: Path, system_dir: Path, db_path: Path) -> bool:
    """M1：把 tags.json / scenes.json / user_scenes.json / external_systems_config.json
    播种到对应的 SQLite 表。

    数据源路径（与服务层 fallback 路径保持一致）：
      - tags.json / scenes.json / user_scenes.json → data_dir（WORKING_DIR）
      - external_systems_config.json → system_dir（SYSTEM_DIR）

    与 ``ensure_migrated`` 独立：存量实例的 users.json 已被删除，
    ``ensure_migrated`` 不会再运行，因此本函数有独立的幂等标志
    （migration_state.domain_migration）。

    幂等性：
      - 标志已置 → 直接跳过；
      - 即使强制重跑，seed 全部走 INSERT OR IGNORE，不覆盖已有行。

    JSON 文件保留为只读备份，不删除、不重命名（D2/D5 决策）。
    """
    import sqlite3

    from .scene_repository_sqlite import SqliteSceneRepository
    from .tag_repository_sqlite import SqliteTagRepository
    from .user_scene_repository_sqlite import SqliteUserSceneSettingsRepo
    # Phase 1: 外部身份仓储 SQLAlchemy 化（走全局 engine；生产工厂路径下与
    # db_path 同一文件；测试需先 init_engine 到目标库）。
    from .external_identity_impl import SqlaExternalIdentityStore

    system_dir = Path(system_dir)
    db_path = Path(db_path)

    conn = None
    tag_repo = scene_repo = us_repo = ext_store = None
    try:
        conn = sqlite3.connect(str(db_path), timeout=30.0)
        conn.row_factory = sqlite3.Row

        if get_migration_flag(conn, "domain_migration") == "done":
            return False

        # 确保 4 张新表存在（schema 全量 IF NOT EXISTS，幂等）
        _create_schema(conn)
        conn.commit()

        system_dir.mkdir(parents=True, exist_ok=True)
        tag_repo = SqliteTagRepository(db_path)
        scene_repo = SqliteSceneRepository(db_path)
        us_repo = SqliteUserSceneSettingsRepo(db_path)
        ext_store = SqlaExternalIdentityStore()

        # 域C：tags.json {"version", "tags": [...]}
        tags = _load_json_dict(data_dir / "tags.json").get("tags") or []
        if not isinstance(tags, list):
            tags = []

        # 域B：scenes.json {"version", "scenes": [...]}
        scenes = _load_json_dict(data_dir / "scenes.json").get("scenes") or []
        if not isinstance(scenes, list):
            scenes = []

        # 域D：user_scenes.json {"version", "user_scenes": [...]}
        user_scenes = _load_json_dict(data_dir / "user_scenes.json").get("user_scenes") or []
        if not isinstance(user_scenes, list):
            user_scenes = []

        # 域A：external_systems_config.json {"systems": [...]}
        systems = _load_json_dict(system_dir / "external_systems_config.json").get("systems") or []
        if not isinstance(systems, list):
            systems = []

        n_tags = tag_repo.seed_many(tags)
        n_scenes = scene_repo.seed_many(scenes)
        n_us = us_repo.seed_many(user_scenes)
        n_sys = ext_store.seed_systems(systems)

        set_migration_flag(conn, "domain_migration", "done")
        conn.commit()

        logger.info(
            "M1 domain migration done: tags=%d scenes=%d user_scenes=%d external_systems=%d",
            n_tags, n_scenes, n_us, n_sys,
        )
        return True
    except Exception as exc:  # noqa: BLE001 — 迁移失败不应阻断启动，仅告警
        logger.error("M1 domain migration failed: %s", exc, exc_info=True)
        return False
    finally:
        for repo in (tag_repo, scene_repo, us_repo, ext_store):
            if repo is not None:
                try:
                    repo.close()
                except Exception:  # noqa: BLE001
                    pass
        if conn is not None:
            conn.close()
