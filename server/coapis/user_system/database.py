# -*- coding: utf-8 -*-
# Copyright 2026 蜜蜂 & CoApis Contributors
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

"""User system persistence layer - supports both SQLite and JSON file modes.

Open-source version uses JSON files (users.json, audit_logs.json).
Enterprise version can override _is_database_enabled() to use SQLite.
"""
from __future__ import annotations

import json
import logging
import os
import sqlite3
import threading
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

from ..constant import SYSTEM_DIR

logger = logging.getLogger(__name__)

# Database file location
USER_DB_PATH = SYSTEM_DIR / "user_system.db"

# JSON file location (for non-database mode)
_USERS_JSON = SYSTEM_DIR / "users.json"
_AUDIT_LOGS_JSON = SYSTEM_DIR / "audit_logs.json"
_SETTINGS_JSON = SYSTEM_DIR / "user_settings.json"
_PREFERENCES_JSON = SYSTEM_DIR / "user_preferences.json"
_API_KEYS_JSON = SYSTEM_DIR / "api_keys.json"
_POINTS_JSON = SYSTEM_DIR / "point_transactions.json"


# Open-source version: always use JSON mode.
# Enterprise version can override _is_database_enabled() to use SQLite.


def _is_database_enabled() -> bool:
    """Check if database mode is enabled.

    Open-source version always returns False (JSON mode).
    Enterprise version can override this to return True for SQLite.
    """
    return False


class UserSystemDB:
    """Thread-safe user system persistence - SQLite or JSON file mode."""

    _instance: Optional["UserSystemDB"] = None
    _lock = threading.Lock()

    def __new__(cls):
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = super().__new__(cls)
                    cls._instance._initialized = False
        return cls._instance

    def __init__(self):
        if self._initialized:
            return
        
        self._use_database = _is_database_enabled()
        
        if self._use_database:
            # SQLite mode
            self._db_dir = USER_DB_PATH.parent
            self._db_dir.mkdir(parents=True, exist_ok=True)
            self._connection = sqlite3.connect(
                str(USER_DB_PATH),
                check_same_thread=False,
            )
            self._connection.row_factory = sqlite3.Row
            self._connection.execute("PRAGMA journal_mode=WAL")
            self._connection.execute("PRAGMA foreign_keys=ON")
            self._create_tables()
            logger.info(f"UserSystemDB initialized in DATABASE mode at {USER_DB_PATH}")
        else:
            # JSON file mode
            SYSTEM_DIR.mkdir(parents=True, exist_ok=True)
            self._json_lock = threading.Lock()
            logger.info("UserSystemDB initialized in JSON file mode")
        
        self._initialized = True

    # ==================== SQLite Methods ====================
    
    def _create_tables(self):
        """Create all tables if they don't exist."""
        cur = self._connection.cursor()

        # Users table
        cur.execute("""
            CREATE TABLE IF NOT EXISTS users (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                username TEXT UNIQUE NOT NULL,
                email TEXT,
                display_name TEXT,
                avatar_url TEXT,
                password_hash TEXT,
                salt TEXT,
                level INTEGER DEFAULT 0,
                points INTEGER DEFAULT 0,
                total_points_earned INTEGER DEFAULT 0,
                total_points_spent INTEGER DEFAULT 0,
                token_quota_monthly INTEGER DEFAULT 1000000,
                token_used_monthly INTEGER DEFAULT 0,
                token_used_total INTEGER DEFAULT 0,
                chat_count INTEGER DEFAULT 0,
                agent_count INTEGER DEFAULT 0,
                skill_count INTEGER DEFAULT 0,
                last_login_at REAL,
                last_login_ip TEXT,
                created_at REAL DEFAULT (strftime('%s', 'now')),
                updated_at REAL DEFAULT (strftime('%s', 'now'))
            )
        """)

        # ── Schema migration: add columns missing from earlier versions ──
        self._add_column_if_not_exists("users", "role TEXT DEFAULT 'user'")
        self._add_column_if_not_exists("users", "is_active INTEGER DEFAULT 1")
        self._add_column_if_not_exists("users", "muga_key TEXT")

        # User settings table
        cur.execute("""
            CREATE TABLE IF NOT EXISTS user_settings (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                setting_key TEXT NOT NULL,
                setting_value TEXT,
                created_at REAL DEFAULT (strftime('%s', 'now')),
                updated_at REAL DEFAULT (strftime('%s', 'now')),
                FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE,
                UNIQUE(user_id, setting_key)
            )
        """)

        # User preferences table
        cur.execute("""
            CREATE TABLE IF NOT EXISTS user_preferences (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                preference_key TEXT NOT NULL,
                preference_value TEXT,
                created_at REAL DEFAULT (strftime('%s', 'now')),
                updated_at REAL DEFAULT (strftime('%s', 'now')),
                FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE,
                UNIQUE(user_id, preference_key)
            )
        """)

        # API keys table
        cur.execute("""
            CREATE TABLE IF NOT EXISTS api_keys (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                key_hash TEXT UNIQUE NOT NULL,
                key_prefix TEXT NOT NULL,
                name TEXT,
                scopes TEXT DEFAULT '["read","write"]',
                last_used_at REAL,
                expires_at REAL,
                is_active INTEGER DEFAULT 1,
                created_at REAL DEFAULT (strftime('%s', 'now')),
                FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
            )
        """)

        # Point transactions table
        cur.execute("""
            CREATE TABLE IF NOT EXISTS point_transactions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                amount INTEGER NOT NULL,
                balance_after INTEGER NOT NULL,
                transaction_type TEXT NOT NULL,
                description TEXT,
                reference_id TEXT,
                created_at REAL DEFAULT (strftime('%s', 'now')),
                FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
            )
        """)

        # Token usage table
        cur.execute("""
            CREATE TABLE IF NOT EXISTS token_usage (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL DEFAULT 0,
                username TEXT NOT NULL DEFAULT 'anonymous',
                agent_id TEXT,
                model TEXT NOT NULL,
                input_tokens INTEGER DEFAULT 0,
                output_tokens INTEGER DEFAULT 0,
                total_tokens INTEGER DEFAULT 0,
                cost_cents REAL DEFAULT 0.0,
                created_at REAL DEFAULT (strftime('%s', 'now'))
            )
        """)

        # Audit logs table
        cur.execute("""
            CREATE TABLE IF NOT EXISTS audit_logs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER,
                username TEXT,
                action TEXT NOT NULL,
                resource_type TEXT,
                resource_id TEXT,
                details TEXT,
                ip_address TEXT,
                user_agent TEXT,
                created_at REAL DEFAULT (strftime('%s', 'now'))
            )
        """)

        self._connection.commit()

    def _add_column_if_not_exists(self, table: str, column_def: str):
        """Add a column to a table if it doesn't exist (SQLite migration helper)."""
        col_name = column_def.split()[0]
        try:
            self._connection.execute(f"SELECT {col_name} FROM {table} LIMIT 0")
        except sqlite3.OperationalError:
            try:
                self._connection.execute(f"ALTER TABLE {table} ADD COLUMN {column_def}")
                logger.info(f"Migration: Added column '{col_name}' to '{table}'")
            except sqlite3.OperationalError:
                pass

    def execute(self, sql: str, params: tuple = ()) -> sqlite3.Cursor:
        """Thread-safe execute."""
        return self._connection.execute(sql, params)

    def executemany(self, sql: str, params_list: list) -> sqlite3.Cursor:
        """Thread-safe executemany."""
        return self._connection.executemany(sql, params_list)

    def commit(self):
        """Commit transaction."""
        self._connection.commit()

    def fetch_one(self, sql: str, params: tuple = ()) -> Optional[Dict[str, Any]]:
        """Fetch one row as dict."""
        row = self._connection.execute(sql, params).fetchone()
        return dict(row) if row else None

    def fetch_all(self, sql: str, params: tuple = ()) -> List[Dict[str, Any]]:
        """Fetch all rows as dict list."""
        rows = self._connection.execute(sql, params).fetchall()
        return [dict(r) for r in rows]

    # ==================== JSON File Methods ====================
    
    def _load_json(self, file_path: Path) -> List[Dict[str, Any]]:
        """Load data from JSON file.

        Supports two formats:
        1. Plain list:  [{"username": "a", ...}, ...]
        2. Wrapped dict: {"users": {"a": {...}, "b": {...}}}  → extracts values as list
        """
        if not file_path.exists():
            return []
        try:
            with open(file_path, "r", encoding="utf-8") as f:
                data = json.load(f)
                if isinstance(data, list):
                    return data
                # Handle {"users": {"username": {...}}} wrapper
                if isinstance(data, dict):
                    for key in ("users", "items", "data"):
                        if key in data and isinstance(data[key], dict):
                            return list(data[key].values())
                        if key in data and isinstance(data[key], list):
                            return data[key]
                return []
        except (json.JSONDecodeError, OSError) as e:
            logger.warning("Failed to load %s: %s", file_path, e)
            return []

    def _save_json(self, file_path: Path, data: List[Dict[str, Any]]) -> None:
        """Save data to JSON file atomically.

        For users.json, writes wrapped format: {"users": {"username": {...}}}
        to stay compatible with auth user_store.py.
        """
        try:
            # Detect wrapped-dict format by checking if original file uses it
            save_data: Any = data
            if file_path.name == "users.json" and data and isinstance(data, list):
                # Convert list → {"users": {"username": {...}}}
                wrapped = {}
                for u in data:
                    uname = u.get("username")
                    if uname:
                        wrapped[uname] = u
                save_data = {"users": wrapped}

            tmp_file = file_path.with_suffix(".tmp")
            with open(tmp_file, "w", encoding="utf-8") as f:
                json.dump(save_data, f, ensure_ascii=False, indent=2)
            os.replace(tmp_file, file_path)
        except OSError as e:
            logger.warning("Failed to save %s: %s", file_path, e)

    def _find_by_key(self, data: List[Dict], key: str, value: Any) -> Optional[Dict]:
        """Find first item by key-value."""
        for item in data:
            if item.get(key) == value:
                return item
        return None

    def _find_index_by_key(self, data: List[Dict], key: str, value: Any) -> int:
        """Find index of first item by key-value."""
        for i, item in enumerate(data):
            if item.get(key) == value:
                return i
        return -1

    # ==================== Unified Interface ====================
    
    def get_user_by_username(self, username: str) -> Optional[Dict[str, Any]]:
        """Get user by username."""
        if self._use_database:
            return self.fetch_one("SELECT * FROM users WHERE username = ?", (username,))
        
        # JSON mode
        with self._json_lock:
            users = self._load_json(_USERS_JSON)
            return self._find_by_key(users, "username", username)

    def insert_user(self, user_data: Dict[str, Any]) -> int:
        """Insert a new user, return user ID."""
        if self._use_database:
            now = time.time()
            cur = self.execute(
                "INSERT INTO users (username, email, display_name, password_hash, salt, "
                "level, points, role, is_active, muga_key, created_at, updated_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    user_data.get("username"),
                    user_data.get("email"),
                    user_data.get("display_name"),
                    user_data.get("password_hash"),
                    user_data.get("salt"),
                    user_data.get("level", 0),
                    user_data.get("points", 0),
                    user_data.get("role", "user"),
                    user_data.get("is_active", 1),
                    user_data.get("muga_key"),
                    now,
                    now,
                ),
            )
            self.commit()
            return cur.lastrowid
        
        # JSON mode
        with self._json_lock:
            users = self._load_json(_USERS_JSON)
            new_id = max([u.get("id", 0) for u in users], default=0) + 1
            user_data["id"] = new_id
            user_data["created_at"] = time.time()
            user_data["updated_at"] = time.time()
            users.append(user_data)
            self._save_json(_USERS_JSON, users)
            return new_id

    def update_user(self, username: str, update_data: Dict[str, Any]) -> bool:
        """Update user by username."""
        if self._use_database:
            set_parts = []
            params = []
            for key, value in update_data.items():
                if key not in ("id", "username", "created_at"):
                    set_parts.append(f"{key} = ?")
                    params.append(value)
            if not set_parts:
                return False
            set_parts.append("updated_at = ?")
            params.append(time.time())
            params.append(username)
            self.execute(
                f"UPDATE users SET {', '.join(set_parts)} WHERE username = ?",
                tuple(params),
            )
            self.commit()
            return True
        
        # JSON mode
        with self._json_lock:
            users = self._load_json(_USERS_JSON)
            idx = self._find_index_by_key(users, "username", username)
            if idx == -1:
                return False
            users[idx].update(update_data)
            users[idx]["updated_at"] = time.time()
            self._save_json(_USERS_JSON, users)
            return True

    def count_users(self) -> int:
        """Count all users."""
        if self._use_database:
            row = self.fetch_one("SELECT COUNT(*) as total FROM users")
            return row["total"] if row else 0
        with self._json_lock:
            return len(self._load_json(_USERS_JSON))

    def count_active_users(self) -> int:
        """Count active users."""
        if self._use_database:
            row = self.fetch_one("SELECT COUNT(*) as total FROM users WHERE is_active = 1")
            return row["total"] if row else 0
        with self._json_lock:
            users = self._load_json(_USERS_JSON)
            return sum(1 for u in users if u.get("is_active", True))

    def list_users(self) -> List[Dict[str, Any]]:
        """List all users."""
        if self._use_database:
            return self.fetch_all("SELECT * FROM users ORDER BY created_at DESC")
        
        # JSON mode
        with self._json_lock:
            users = self._load_json(_USERS_JSON)
            return sorted(users, key=lambda x: x.get("created_at", 0), reverse=True)

    def user_exists(self, username: str) -> bool:
        """Check if a user with given username exists."""
        return self.get_user_by_username(username) is not None

    def email_exists(self, email: str) -> bool:
        """Check if a user with given email exists."""
        if not email:
            return False
        if self._use_database:
            return self.fetch_one("SELECT 1 FROM users WHERE email = ?", (email,)) is not None
        with self._json_lock:
            users = self._load_json(_USERS_JSON)
            return any(u.get("email") == email for u in users)

    def get_user_by_id(self, user_id: int) -> Optional[Dict[str, Any]]:
        """Get user by ID."""
        if self._use_database:
            return self.fetch_one("SELECT * FROM users WHERE id = ?", (user_id,))
        with self._json_lock:
            users = self._load_json(_USERS_JSON)
            return self._find_by_key(users, "id", user_id)

    def update_user_by_id(self, user_id: int, update_data: Dict[str, Any]) -> bool:
        """Update user by ID."""
        if self._use_database:
            set_parts = []
            params = []
            for key, value in update_data.items():
                if key not in ("id", "username", "created_at"):
                    set_parts.append(f"{key} = ?")
                    params.append(value)
            if not set_parts:
                return False
            set_parts.append("updated_at = ?")
            params.append(time.time())
            params.append(user_id)
            self.execute(
                f"UPDATE users SET {', '.join(set_parts)} WHERE id = ?",
                tuple(params),
            )
            self.commit()
            return True

        with self._json_lock:
            users = self._load_json(_USERS_JSON)
            for u in users:
                if u.get("id") == user_id:
                    for k, v in update_data.items():
                        if k not in ("id", "username", "created_at"):
                            u[k] = v
                    u["updated_at"] = time.time()
                    self._save_json(_USERS_JSON, users)
                    return True
            return False

    def delete_user_by_id(self, user_id: int) -> bool:
        """Delete user by ID."""
        if self._use_database:
            self.execute("DELETE FROM users WHERE id = ?", (user_id,))
            self.commit()
            return True

        with self._json_lock:
            users = self._load_json(_USERS_JSON)
            new_users = [u for u in users if u.get("id") != user_id]
            if len(new_users) < len(users):
                self._save_json(_USERS_JSON, new_users)
                return True
            return False

    def get_user_by_email(self, email: str) -> Optional[Dict[str, Any]]:
        """Get user by email."""
        if not email:
            return None
        if self._use_database:
            return self.fetch_one("SELECT * FROM users WHERE email = ?", (email,))
        with self._json_lock:
            users = self._load_json(_USERS_JSON)
            return next((u for u in users if u.get("email") == email), None)

    def delete_user(self, username: str) -> bool:
        """Delete a user by username."""
        if self._use_database:
            existing = self.fetch_one("SELECT 1 FROM users WHERE username = ?", (username,))
            if not existing:
                return False
            self.execute("DELETE FROM users WHERE username = ?", (username,))
            self.commit()
            return True
        with self._json_lock:
            users = self._load_json(_USERS_JSON)
            idx = self._find_index_by_key(users, "username", username)
            if idx < 0:
                return False
            users.pop(idx)
            self._save_json(_USERS_JSON, users)
            return True

    def list_users_page(self, page: int = 1, page_size: int = 20, search: Optional[str] = None) -> tuple:
        """List users with pagination and optional search. Returns (users_list, total_count)."""
        all_users = self.list_users()

        # Apply search filter
        if search:
            q = search.lower()
            all_users = [
                u for u in all_users
                if q in (u.get("username", "")).lower()
                or q in (u.get("display_name", "")).lower()
                or q in (u.get("email", "") or "").lower()
            ]

        total = len(all_users)
        start = (page - 1) * page_size
        return all_users[start:start + page_size], total

    def insert_audit_log(
        self,
        user_id: int,
        username: str,
        action: str,
        resource_type: str,
        resource_id: str,
        details: Optional[Dict[str, Any]] = None,
        ip_address: str = "",
        user_agent: str = "",
    ):
        """Insert an audit log entry."""
        if self._use_database:
            details_str = json.dumps(details) if details else "{}"
            self.execute(
                "INSERT INTO audit_logs (user_id, username, action, resource_type, resource_id, details, ip_address, user_agent, created_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (user_id, username, action, resource_type, resource_id, details_str, ip_address, user_agent, time.time()),
            )
            self.commit()
            return
        
        # JSON mode
        log_entry = {
            "user_id": user_id,
            "username": username,
            "action": action,
            "resource_type": resource_type,
            "resource_id": resource_id,
            "details": details or {},
            "ip_address": ip_address,
            "user_agent": user_agent,
            "created_at": time.time(),
        }
        with self._json_lock:
            logs = self._load_json(_AUDIT_LOGS_JSON)
            logs.append(log_entry)
            # Keep only last 10000 entries
            if len(logs) > 10000:
                logs = logs[-10000:]
            self._save_json(_AUDIT_LOGS_JSON, logs)

    def insert_point_transaction(
        self,
        user_id: int,
        amount: int,
        balance_after: int,
        transaction_type: str,
        description: str = "",
        reference_id: str = "",
    ):
        """Insert a point transaction."""
        if self._use_database:
            self.execute(
                "INSERT INTO point_transactions (user_id, amount, balance_after, transaction_type, description, reference_id, created_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?)",
                (user_id, amount, balance_after, transaction_type, description, reference_id, time.time()),
            )
            self.commit()
            return
        
        # JSON mode
        tx = {
            "user_id": user_id,
            "amount": amount,
            "balance_after": balance_after,
            "transaction_type": transaction_type,
            "description": description,
            "reference_id": reference_id,
            "created_at": time.time(),
        }
        with self._json_lock:
            transactions = self._load_json(_POINTS_JSON)
            transactions.append(tx)
            if len(transactions) > 50000:
                transactions = transactions[-50000:]
            self._save_json(_POINTS_JSON, transactions)

    def insert_token_usage(
        self,
        user_id: int,
        username: str,
        agent_id: Optional[str],
        model: str,
        input_tokens: int,
        output_tokens: int,
        total_tokens: int,
        cost_cents: float = 0.0,
    ):
        """Insert token usage record."""
        if self._use_database:
            self.execute(
                "INSERT INTO token_usage (user_id, username, agent_id, model, input_tokens, output_tokens, total_tokens, cost_cents, created_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (user_id, username, agent_id, model, input_tokens, output_tokens, total_tokens, cost_cents, time.time()),
            )
            self.commit()
            return
        
        # JSON mode - use token_usage_details.json (already implemented in token_usage module)
        from ..token_usage.db_writer import save_token_usage
        save_token_usage(
            user_id=user_id,
            username=username,
            agent_id=agent_id,
            model=model,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            total_tokens=total_tokens,
            cost_cents=cost_cents,
        )

    def get_user_token_usage(self, username: str, start_date: Optional[str] = None, end_date: Optional[str] = None) -> Dict[str, Any]:
        """Get token usage summary for a user."""
        if self._use_database:
            sql = "SELECT * FROM token_usage WHERE username = ?"
            params = [username]
            if start_date:
                import datetime
                start_ts = datetime.datetime.strptime(start_date, "%Y-%m-%d").timestamp()
                sql += " AND created_at >= ?"
                params.append(start_ts)
            if end_date:
                import datetime
                end_ts = datetime.datetime.strptime(end_date, "%Y-%m-%d").timestamp() + 86399
                sql += " AND created_at <= ?"
                params.append(end_ts)
            
            records = self.fetch_all(sql, tuple(params))
            
            total_input = sum(r.get("input_tokens", 0) for r in records)
            total_output = sum(r.get("output_tokens", 0) for r in records)
            total_tokens = sum(r.get("total_tokens", 0) for r in records)
            
            return {
                "username": username,
                "total_input_tokens": total_input,
                "total_output_tokens": total_output,
                "total_tokens": total_tokens,
                "total_calls": len(records),
            }
        
        # JSON mode
        from ..token_usage.db_writer import get_user_token_usage
        return get_user_token_usage(username, start_date, end_date)

    def get_agent_token_usage(self, agent_id: str, start_date: Optional[str] = None, end_date: Optional[str] = None) -> Dict[str, Any]:
        """Get token usage summary for an agent."""
        if self._use_database:
            sql = "SELECT * FROM token_usage WHERE agent_id = ?"
            params = [agent_id]
            if start_date:
                import datetime
                start_ts = datetime.datetime.strptime(start_date, "%Y-%m-%d").timestamp()
                sql += " AND created_at >= ?"
                params.append(start_ts)
            if end_date:
                import datetime
                end_ts = datetime.datetime.strptime(end_date, "%Y-%m-%d").timestamp() + 86399
                sql += " AND created_at <= ?"
                params.append(end_ts)
            
            records = self.fetch_all(sql, tuple(params))
            
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
        
        # JSON mode
        from ..token_usage.db_writer import get_agent_token_usage
        return get_agent_token_usage(agent_id, start_date, end_date)

    def close(self):
        """Close connection."""
        if self._use_database and hasattr(self, '_connection') and self._connection:
            self._connection.close()


def get_db() -> UserSystemDB:
    """Get or create the singleton database instance."""
    return UserSystemDB()
