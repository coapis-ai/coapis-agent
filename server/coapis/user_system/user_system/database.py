# -*- coding: utf-8 -*-
# -*- coding: utf-8 -*-
# Copyright 2026 以太吃虾 & CoApis Contributors
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

"""User system database layer - SQLite-based persistence.

All tables are created lazily on first access.
When USER_SYSTEM_ENABLED=False, all operations are no-ops.
"""
from __future__ import annotations

import logging
import sqlite3
import threading
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

from ..constant import WORKING_DIR

logger = logging.getLogger(__name__)

# Database file location
USER_DB_PATH = WORKING_DIR / "data" / "user_system.db"


class UserSystemDB:
    """Thread-safe SQLite database for user system."""

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
        self._initialized = True
        logger.info(f"UserSystemDB initialized at {USER_DB_PATH}")

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
                token_quota_reset_date TEXT,
                role TEXT DEFAULT 'user',
                is_active INTEGER DEFAULT 1,
                created_at REAL,
                updated_at REAL,
                last_login_at REAL,
                consecutive_login_days INTEGER DEFAULT 0,
                last_login_date TEXT
            )
        """)

        # Point transactions table
        cur.execute("""
            CREATE TABLE IF NOT EXISTS point_transactions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                username TEXT NOT NULL,
                type TEXT NOT NULL,
                amount INTEGER NOT NULL,
                source TEXT NOT NULL,
                description TEXT,
                created_at REAL,
                FOREIGN KEY (user_id) REFERENCES users(id)
            )
        """)
        cur.execute(
            "CREATE INDEX IF NOT EXISTS idx_point_transactions_user "
            "ON point_transactions(username)"
        )

        # Token usage table
        cur.execute("""
            CREATE TABLE IF NOT EXISTS token_usage (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                username TEXT NOT NULL,
                agent_id TEXT,
                model TEXT NOT NULL,
                input_tokens INTEGER DEFAULT 0,
                output_tokens INTEGER DEFAULT 0,
                total_tokens INTEGER DEFAULT 0,
                cost_cents REAL DEFAULT 0,
                created_at REAL,
                FOREIGN KEY (user_id) REFERENCES users(id)
            )
        """)
        cur.execute(
            "CREATE INDEX IF NOT EXISTS idx_token_usage_user "
            "ON token_usage(username)"
        )

        # User settings table (key-value per user)
        cur.execute("""
            CREATE TABLE IF NOT EXISTS user_settings (
                user_id INTEGER NOT NULL,
                username TEXT NOT NULL,
                setting_key TEXT NOT NULL,
                setting_value TEXT,
                PRIMARY KEY (user_id, setting_key),
                FOREIGN KEY (user_id) REFERENCES users(id)
            )
        """)

        # API keys table
        cur.execute("""
            CREATE TABLE IF NOT EXISTS api_keys (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                username TEXT NOT NULL,
                key_hash TEXT NOT NULL,
                key_prefix TEXT NOT NULL,
                name TEXT,
                rate_limit INTEGER DEFAULT 10,
                quota_monthly INTEGER DEFAULT 1000,
                quota_used INTEGER DEFAULT 0,
                is_active INTEGER DEFAULT 1,
                created_at REAL,
                last_used_at REAL,
                expires_at REAL,
                FOREIGN KEY (user_id) REFERENCES users(id)
            )
        """)

        self._connection.commit()
        logger.info("User system tables created/verified")

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

    def close(self):
        """Close connection."""
        if self._connection:
            self._connection.close()


def get_db() -> UserSystemDB:
    """Get or create the singleton database instance."""
    return UserSystemDB()
