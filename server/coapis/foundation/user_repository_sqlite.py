# -*- coding: utf-8 -*-
"""SQLite User Repository — Community edition primary backend (P1).

Single-file DB at SYSTEM_DIR/coapis.db with WAL + busy_timeout.
Schema: users.id TEXT (UUID), all FKs TEXT.
Thread safety: single connection + threading.Lock (same pattern as enterprise).
"""

from __future__ import annotations

import json
import logging
import sqlite3
import threading
import time
import uuid as uuid_mod
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

from .user_repository import User, UserRepository

logger = logging.getLogger(__name__)


def _gen_user_id() -> str:
    """Generate a new UUID hex string for a user."""
    return str(uuid_mod.uuid4())


def _normalize_id(user_id: Any) -> str:
    """Convert int (legacy) or str to UUID hex string."""
    if user_id is None:
        return ""
    if isinstance(user_id, int):
        return str(uuid_mod.UUID(int=user_id))
    return str(user_id)


# Columns in the users table (for filtering INSERT/UPDATE)
_USER_COLUMNS = frozenset({
    "id", "username", "password_hash", "salt", "display_name", "email",
    "avatar_url", "token_quota_monthly", "token_used_monthly", "role",
    "is_active", "created_at", "updated_at", "last_login_at", "muga_key",
})


class SqliteUserRepository(UserRepository):
    """SQLite-backed user repository (Community edition)."""

    def __init__(self, db_path: Path):
        self._db_path = db_path
        self._db_path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        self._connection = sqlite3.connect(
            str(db_path),
            check_same_thread=False,
            timeout=10.0,
        )
        self._connection.row_factory = sqlite3.Row
        self._connection.execute("PRAGMA journal_mode=WAL")
        self._connection.execute("PRAGMA busy_timeout=5000")
        self._connection.execute("PRAGMA foreign_keys=ON")
        self._create_tables()
        logger.info("SqliteUserRepository initialized at %s", db_path)

    # ------------------------------------------------------------------
    # Schema
    # ------------------------------------------------------------------

    def _create_tables(self):
        """创建所有表（幂等）。

        结构定义在 ``sql/community_schema.sql``（唯一事实来源，决策 D-8），
        不再在代码里内联 DDL。
        """
        from .sql import load_community_schema

        cur = self._connection.cursor()
        cur.executescript(load_community_schema())
        self._connection.commit()

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _execute(self, sql: str, params: tuple = ()) -> sqlite3.Cursor:
        with self._lock:
            cur = self._connection.execute(sql, params)
            self._connection.commit()
            return cur

    def _fetch_one(self, sql: str, params: tuple = ()) -> Optional[Dict[str, Any]]:
        with self._lock:
            row = self._connection.execute(sql, params).fetchone()
        if row is None:
            return None
        return dict(row)

    def _fetch_all(self, sql: str, params: tuple = ()) -> List[Dict[str, Any]]:
        with self._lock:
            rows = self._connection.execute(sql, params).fetchall()
        return [dict(r) for r in rows]

    # ------------------------------------------------------------------
    # User CRUD (1-14)
    # ------------------------------------------------------------------

    def create_user(self, user_data: Dict[str, Any]) -> str:
        user_id = user_data.get("id") or _gen_user_id()
        user_id = _normalize_id(user_id)
        now = time.time()

        # Handle plaintext password → hash
        if "password" in user_data and "password_hash" not in user_data:
            import hashlib, secrets
            salt = secrets.token_hex(16)
            pw_hash = hashlib.sha256((salt + str(user_data.pop("password"))).encode("utf-8")).hexdigest()
            user_data["password_hash"] = pw_hash
            user_data["salt"] = salt
        # Remove plaintext password if present alongside hash
        user_data.pop("password", None)

        user_data.setdefault("created_at", now)
        user_data.setdefault("updated_at", now)
        user_data["id"] = user_id
        user_data["is_active"] = 1 if user_data.get("is_active", True) else 0

        # Filter to valid schema columns only
        clean_data = {k: v for k, v in user_data.items() if k in _USER_COLUMNS}
        columns = ", ".join(clean_data.keys())
        placeholders = ", ".join(["?"] * len(clean_data))
        sql = f"INSERT INTO users ({columns}) VALUES ({placeholders})"
        self._execute(sql, tuple(clean_data.values()))
        return user_id

    def get_user_by_id(self, user_id: Any) -> Optional[Dict[str, Any]]:
        uid = _normalize_id(user_id)
        return self._fetch_one("SELECT * FROM users WHERE id = ?", (uid,))

    def get_user_by_username(self, username: str) -> Optional[Dict[str, Any]]:
        return self._fetch_one("SELECT * FROM users WHERE username = ?", (username,))

    def get_user_by_email(self, email: str) -> Optional[Dict[str, Any]]:
        if not email:
            return None
        return self._fetch_one("SELECT * FROM users WHERE email = ?", (email,))

    def update_user(self, username: str, update_data: Dict[str, Any]) -> bool:
        user = self.get_user_by_username(username)
        if not user:
            return False
        return self._update_user_fields(user["id"], update_data)

    def update_user_by_id(self, user_id: Any, update_data: Dict[str, Any]) -> bool:
        uid = _normalize_id(user_id)
        return self._update_user_fields(uid, update_data)

    def _update_user_fields(self, uid: str, update_data: Dict[str, Any]) -> bool:
        """Shared UPDATE logic: filter to valid columns, convert is_active."""
        set_clauses = []
        params: list = []
        for key, value in update_data.items():
            if key not in _USER_COLUMNS or key == "id":
                continue
            if key == "is_active":
                value = 1 if value else 0
            set_clauses.append(f"{key} = ?")
            params.append(value)
        if set_clauses:
            set_clauses.append("updated_at = ?")
            params.append(time.time())
            params.append(uid)
            sql = f"UPDATE users SET {', '.join(set_clauses)} WHERE id = ?"
            self._execute(sql, tuple(params))
            return True
        return False

    def delete_user(self, username: str) -> bool:
        user = self.get_user_by_username(username)
        if not user:
            return False
        self._execute("DELETE FROM users WHERE id = ?", (user["id"],))
        return True

    def delete_user_by_id(self, user_id: Any) -> bool:
        uid = _normalize_id(user_id)
        user = self._fetch_one("SELECT id FROM users WHERE id = ?", (uid,))
        if not user:
            return False
        self._execute("DELETE FROM users WHERE id = ?", (uid,))
        return True

    def list_users(self) -> List[Dict[str, Any]]:
        return self._fetch_all("SELECT * FROM users ORDER BY created_at DESC")

    def list_users_page(
        self, page: int = 1, page_size: int = 20, search: Optional[str] = None
    ) -> tuple:
        offset = (page - 1) * page_size
        if search:
            like = f"%{search}%"
            total = self._fetch_one(
                "SELECT COUNT(*) as cnt FROM users WHERE username LIKE ? OR email LIKE ? OR display_name LIKE ?",
                (like, like, like),
            )["cnt"]
            rows = self._fetch_all(
                "SELECT * FROM users WHERE username LIKE ? OR email LIKE ? OR display_name LIKE ? ORDER BY created_at DESC LIMIT ? OFFSET ?",
                (like, like, like, page_size, offset),
            )
        else:
            total = self._fetch_one("SELECT COUNT(*) as cnt FROM users")["cnt"]
            rows = self._fetch_all(
                "SELECT * FROM users ORDER BY created_at DESC LIMIT ? OFFSET ?",
                (page_size, offset),
            )
        return rows, total

    def user_exists(self, username: str) -> bool:
        row = self._fetch_one("SELECT 1 FROM users WHERE username = ?", (username,))
        return row is not None

    def email_exists(self, email: str) -> bool:
        if not email:
            return False
        row = self._fetch_one("SELECT 1 FROM users WHERE email = ?", (email,))
        return row is not None

    def count_users(self) -> int:
        return self._fetch_one("SELECT COUNT(*) as cnt FROM users")["cnt"]

    def count_active_users(self) -> int:
        return self._fetch_one("SELECT COUNT(*) as cnt FROM users WHERE is_active = 1")["cnt"]

    # ------------------------------------------------------------------
    # Audit / Points / Token (15-19)
    # ------------------------------------------------------------------

    def insert_audit_log(
        self,
        user_id: Any,
        username: str,
        action: str,
        resource_type: str,
        resource_id: str,
        details: Optional[Dict[str, Any]] = None,
        ip_address: str = "",
        user_agent: str = "",
    ) -> None:
        details_json = json.dumps(details, ensure_ascii=False) if details else None
        self._execute(
            """INSERT INTO audit_logs
               (user_id, username, action, resource_type, resource_id, details, ip_address, user_agent, created_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                _normalize_id(user_id),
                username,
                action,
                resource_type,
                resource_id,
                details_json,
                ip_address,
                user_agent,
                time.time(),
            ),
        )

    def insert_point_transaction(
        self,
        user_id: Any,
        amount: int,
        balance_after: int,
        transaction_type: str,
        description: str = "",
        reference_id: str = "",
    ) -> None:
        self._execute(
            """INSERT INTO point_transactions
               (user_id, amount, balance_after, transaction_type, description, reference_id, created_at)
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (_normalize_id(user_id), amount, balance_after, transaction_type, description, reference_id, time.time()),
        )

    def insert_token_usage(
        self,
        user_id: Any,
        username: str,
        agent_id: Optional[str],
        model: str,
        input_tokens: int,
        output_tokens: int,
        total_tokens: int,
        cost_cents: float = 0.0,
    ) -> None:
        self._execute(
            """INSERT INTO token_usage
               (user_id, username, agent_id, model, input_tokens, output_tokens, total_tokens, cost_cents, created_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                _normalize_id(user_id),
                username,
                agent_id,
                model,
                input_tokens,
                output_tokens,
                total_tokens,
                cost_cents,
                time.time(),
            ),
        )

    def get_user_token_usage(
        self,
        username: str,
        start_date: Optional[str] = None,
        end_date: Optional[str] = None,
    ) -> Dict[str, Any]:
        user = self.get_user_by_username(username)
        if not user:
            return {}

        sql = "SELECT * FROM token_usage WHERE username = ?"
        params: list = [username]
        if start_date:
            start_ts = datetime.strptime(start_date, "%Y-%m-%d").timestamp()
            sql += " AND created_at >= ?"
            params.append(start_ts)
        if end_date:
            end_ts = datetime.strptime(end_date, "%Y-%m-%d").timestamp() + 86399
            sql += " AND created_at <= ?"
            params.append(end_ts)

        records = self._fetch_all(sql, tuple(params))

        total_input = sum(r.get("input_tokens", 0) for r in records)
        total_output = sum(r.get("output_tokens", 0) for r in records)
        total_tokens = sum(r.get("total_tokens", 0) for r in records)
        total_cost = sum(r.get("cost_cents", 0) for r in records)

        models: Dict[str, int] = {}
        for r in records:
            m = r.get("model", "unknown")
            models[m] = models.get(m, 0) + r.get("total_tokens", 0)

        return {
            "username": username,
            "total_input_tokens": total_input,
            "total_output_tokens": total_output,
            "total_tokens": total_tokens,
            "total_cost_cents": total_cost,
            "total_calls": len(records),
            "top_models": [{"model": m, "tokens": t} for m, t in sorted(models.items(), key=lambda x: -x[1])],
        }

    def get_agent_token_usage(
        self,
        agent_id: str,
        start_date: Optional[str] = None,
        end_date: Optional[str] = None,
    ) -> Dict[str, Any]:
        sql = "SELECT * FROM token_usage WHERE agent_id = ?"
        params: list = [agent_id]
        if start_date:
            start_ts = datetime.strptime(start_date, "%Y-%m-%d").timestamp()
            sql += " AND created_at >= ?"
            params.append(start_ts)
        if end_date:
            end_ts = datetime.strptime(end_date, "%Y-%m-%d").timestamp() + 86399
            sql += " AND created_at <= ?"
            params.append(end_ts)

        records = self._fetch_all(sql, tuple(params))

        total_input = sum(r.get("input_tokens", 0) for r in records)
        total_output = sum(r.get("output_tokens", 0) for r in records)
        total_tokens = sum(r.get("total_tokens", 0) for r in records)

        return {
            "agent_id": agent_id,
            "total_input_tokens": total_input,
            "total_output_tokens": total_output,
            "total_tokens": total_tokens,
            "total_calls": len(records),
        }

    # ------------------------------------------------------------------
    # Preferences (20-23)
    # ------------------------------------------------------------------

    def get_user_preferences(self, username: str) -> Optional[Dict[str, Any]]:
        user = self.get_user_by_username(username)
        if not user:
            return None
        row = self._fetch_one("SELECT * FROM user_preferences WHERE user_id = ?", (user["id"],))
        if row is None:
            return None
        # Flatten: the 'settings' column stores the whole prefs dict as JSON.
        # Callers (user_preferences._row_to_response) read TOP-LEVEL keys
        # (row.get("theme"), row.get("language"), ...), so surface them at the
        # top level to match the JSON backend exactly. (No 'user_id' key — the
        # JSON records carry username/updated_at but not user_id, so we keep
        # the two backends byte-for-byte equivalent.)
        prefs = {}
        raw_settings = row.get("settings")
        if raw_settings and isinstance(raw_settings, str):
            try:
                parsed = json.loads(raw_settings)
                if isinstance(parsed, dict):
                    prefs = parsed
            except (json.JSONDecodeError, TypeError):
                prefs = {}
        result = dict(prefs)
        result["username"] = row.get("username")
        result["updated_at"] = row.get("updated_at")
        return result

    def save_user_preferences(self, username: str, prefs_data: Dict[str, Any]) -> None:
        user = self.get_user_by_username(username)
        if not user:
            return
        # Serialize the whole prefs dict into the 'settings' JSON column
        settings_json = json.dumps(prefs_data, ensure_ascii=False)
        existing = self._fetch_one("SELECT id FROM user_preferences WHERE user_id = ?", (user["id"],))
        if existing:
            self._execute(
                "UPDATE user_preferences SET settings = ?, updated_at = ? WHERE user_id = ?",
                (settings_json, time.time(), user["id"]),
            )
        else:
            self._execute(
                "INSERT INTO user_preferences (user_id, username, settings, updated_at) VALUES (?, ?, ?, ?)",
                (user["id"], username, settings_json, time.time()),
            )

    def get_user_preference(self, user_id: Any, key: str) -> Optional[str]:
        uid = _normalize_id(user_id)
        row = self._fetch_one(
            "SELECT setting_value FROM user_settings WHERE user_id = ? AND setting_key = ?",
            (uid, key),
        )
        return row["setting_value"] if row else None

    def set_user_preference(self, user_id: Any, key: str, value: str) -> bool:
        uid = _normalize_id(user_id)
        self._execute(
            """INSERT INTO user_settings (user_id, setting_key, setting_value, updated_at)
               VALUES (?, ?, ?, ?)
               ON CONFLICT(user_id, setting_key) DO UPDATE SET
                 setting_value = excluded.setting_value,
                 updated_at = excluded.updated_at""",
            (uid, key, value, time.time()),
        )
        return True

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    def close(self) -> None:
        with self._lock:
            if self._connection:
                self._connection.close()
                self._connection = None  # type: ignore
