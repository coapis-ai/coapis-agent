# -*- coding: utf-8 -*-
"""Community-edition SQLite store for external identity (SSO) data.

Mirrors the community JSON file shapes exactly so the app layer
(``app/external_identity.py`` / ``app/routers/external_auth.py``) works
unchanged when this store is injected via
``RepositoryFactory.inject_external_identity_store()``.

Scope (data-layer-unified-sqlite-plan v1.2, P1 user domain):
- **bindings** (user data) → SQLite ``external_bindings`` table
  (single source of truth, same DB as the user repository).
- **systems** (admin config, like settings.json) → stay in
  ``external_systems_config.json``; the store reads that file.

Binding row mapping (DB columns ↔ community JSON keys):
    external_system  ↔ provider
    external_user_id ↔ external_id
    display_name     ↔ external_name
    extra_data       ↔ original community dict (lossless round-trip:
                       source / status / last_login_at / login_count …)
"""
from __future__ import annotations

import json
import logging
import os
import sqlite3
import threading
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

from ..constant import SYSTEM_DIR

logger = logging.getLogger(__name__)

_DB_FILE = "coapis.db"
_SYSTEMS_CONFIG_FILE = "external_systems_config.json"

_COLUMN_KEYS = (
    "user_id", "provider", "external_id",
    "external_name", "display_name", "email", "created_at",
)

# ── 域A：external_systems 表字段 ─────────────────────────────
_SYSTEMS_COLUMNS = (
    "provider_id", "name", "icon", "description", "login_type", "sso",
    "status", "show_on_login", "display_order", "user_mapping", "client_id",
    "credential", "auth_mode", "base_urls", "identity_token_ttl", "extra_data",
    "created_at", "updated_at",
)
# 顶层直接映射到列的字段；其余（如 shared_secret_use_global / shared_secret）进 extra_data
_SYSTEMS_DIRECT = {
    "provider_id", "name", "icon", "description", "login_type", "sso",
    "status", "show_on_login", "display_order", "user_mapping", "client_id",
    "credential", "auth_mode", "base_urls", "identity_token_ttl",
    "created_at", "updated_at",
}


def _sys_dumps(value: Any, kind: str) -> str:
    if value is None:
        value = [] if kind == "list" else {}
    try:
        return json.dumps(value, ensure_ascii=False)
    except (TypeError, ValueError):
        return json.dumps([] if kind == "list" else {}, ensure_ascii=False)


def _sys_loads(text: Optional[str], kind: str) -> Any:
    if text is None or text == "":
        return [] if kind == "list" else {}
    try:
        return json.loads(text)
    except (TypeError, ValueError):
        return [] if kind == "list" else {}


def _sys_text(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, datetime):
        return value.isoformat()
    return value if isinstance(value, str) else str(value)


class SqliteExternalIdentityStore:
    """SQLite-backed external identity store (community edition).

    ``data_dir`` is the system directory (``coapis.db`` lives inside it),
    same convention as :class:`SqliteUserRepository`.
    """

    def __init__(self, db_path: Path) -> None:
        """``db_path`` is the full path to ``coapis.db`` — the *same file* the
        user repository uses (the factory passes the resolved
        ``COAPIS_DATABASE_URL`` target), so bindings and users live in one DB.
        """
        self._db_path = Path(db_path)
        self._db_path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        self._conn = sqlite3.connect(str(self._db_path), check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.commit()
        self._ensure_table()

    # ── schema ──────────────────────────────────────────────────────

    def _ensure_table(self) -> None:
        self._conn.execute(
            """CREATE TABLE IF NOT EXISTS external_bindings (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
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
        # 域A：系统配置表（与 community_schema.sql 一致；store 自包含，独立于 factory 建表）
        self._conn.execute(
            """CREATE TABLE IF NOT EXISTS external_systems (
                provider_id TEXT PRIMARY KEY,
                name TEXT NOT NULL,
                icon TEXT,
                description TEXT,
                login_type TEXT NOT NULL,
                sso TEXT NOT NULL DEFAULT '{}',
                status INTEGER NOT NULL DEFAULT 1,
                show_on_login INTEGER NOT NULL DEFAULT 1,
                display_order INTEGER NOT NULL DEFAULT 0,
                user_mapping TEXT NOT NULL DEFAULT '{}',
                client_id TEXT,
                credential TEXT NOT NULL DEFAULT '{}',
                auth_mode TEXT NOT NULL DEFAULT 'password',
                base_urls TEXT NOT NULL DEFAULT '[]',
                identity_token_ttl INTEGER,
                extra_data TEXT NOT NULL DEFAULT '{}',
                created_at TEXT,
                updated_at TEXT
            )"""
        )
        self._conn.commit()

    # ── systems (域A：external_systems 表) ─────────────────────────

    def _systems_upsert_sql(self) -> str:
        col_sql = ", ".join(_SYSTEMS_COLUMNS)
        ph_sql = ", ".join(f":{c}" for c in _SYSTEMS_COLUMNS)
        updates = ", ".join(f"{c}=excluded.{c}" for c in _SYSTEMS_COLUMNS if c != "provider_id")
        return (
            f"INSERT INTO external_systems ({col_sql}) VALUES ({ph_sql}) "
            f"ON CONFLICT(provider_id) DO UPDATE SET {updates}"
        )

    def _systems_seed_sql(self) -> str:
        col_sql = ", ".join(_SYSTEMS_COLUMNS)
        ph_sql = ", ".join(f":{c}" for c in _SYSTEMS_COLUMNS)
        return f"INSERT OR IGNORE INTO external_systems ({col_sql}) VALUES ({ph_sql})"

    @staticmethod
    def _system_dict_to_row(system: Dict[str, Any]) -> Dict[str, Any]:
        """系统 dict → 行。非 _SYSTEMS_DIRECT 的顶层字段进 extra_data（保真）。"""
        extra = {k: v for k, v in system.items() if k not in _SYSTEMS_DIRECT}
        return {
            "provider_id": system.get("provider_id"),
            "name": system.get("name", ""),
            "icon": _sys_text(system.get("icon")),
            "description": _sys_text(system.get("description")),
            "login_type": system.get("login_type") or "password",
            "sso": _sys_dumps(system.get("sso"), "dict"),
            "status": int(system.get("status", 1)),
            "show_on_login": int(bool(system.get("show_on_login", True))),
            "display_order": int(system.get("display_order") or 0),
            "user_mapping": _sys_dumps(system.get("user_mapping"), "dict"),
            "client_id": _sys_text(system.get("client_id")),
            "credential": _sys_dumps(system.get("credential"), "dict"),
            "auth_mode": system.get("auth_mode") or "password",
            "base_urls": _sys_dumps(system.get("base_urls"), "list"),
            "identity_token_ttl": (
                int(system["identity_token_ttl"])
                if system.get("identity_token_ttl") is not None else None
            ),
            "extra_data": _sys_dumps(extra, "dict"),
            "created_at": _sys_text(system.get("created_at")),
            "updated_at": _sys_text(system.get("updated_at")),
        }

    @staticmethod
    def _system_row_to_dict(row) -> Dict[str, Any]:
        """行 → 系统 dict。extra_data 字段合并回顶层（与 JSON 结构一致）。"""
        d = dict(row)
        d["sso"] = _sys_loads(d.get("sso"), "dict")
        d["user_mapping"] = _sys_loads(d.get("user_mapping"), "dict")
        d["credential"] = _sys_loads(d.get("credential"), "dict")
        d["base_urls"] = _sys_loads(d.get("base_urls"), "list")
        d["show_on_login"] = bool(int(d.get("show_on_login", 1)))
        d["status"] = int(d.get("status", 1))
        d["display_order"] = int(d.get("display_order") or 0)
        extra = _sys_loads(d.get("extra_data"), "dict")
        d.pop("extra_data", None)
        d.update(extra)
        return d

    def load_systems(self) -> List[Dict[str, Any]]:
        """域A：从 external_systems 表读系统配置（extra_data 合并回顶层）。"""
        try:
            with self._lock, self._conn:
                rows = self._conn.execute(
                    "SELECT * FROM external_systems ORDER BY display_order"
                ).fetchall()
            return [self._system_row_to_dict(r) for r in rows]
        except sqlite3.Error as exc:
            logger.warning("load systems from DB failed: %s", exc)
            return []

    def get_system_by_id(self, provider_id: str) -> Optional[Dict[str, Any]]:
        for s in self.load_systems():
            if s.get("provider_id") == provider_id:
                return s
        return None

    def save_systems(self, systems: List[Dict[str, Any]]) -> None:
        """域A：reconcile upsert 到 external_systems 表。

        服务层 load-all -> modify -> save-all 模式：空列表 = 清空；否则删除
        不在列表内的 provider_id，再 upsert 列表内全部（删除系统才真正生效）。
        密钥字段（shared_secret_use_global / shared_secret）进 extra_data，
        与 community_schema 的 D1 约定一致（密钥实际来自 env，此处仅存引用标记）。
        JSON 文件 external_systems_config.json 保留为只读备份，不再写入。
        """
        try:
            with self._lock, self._conn:
                ids = [s.get("provider_id") for s in (systems or []) if s.get("provider_id")]
                if not ids:
                    self._conn.execute("DELETE FROM external_systems")
                else:
                    ph = ",".join("?" * len(ids))
                    self._conn.execute(
                        f"DELETE FROM external_systems WHERE provider_id NOT IN ({ph})", ids
                    )
                    for s in systems:
                        if s.get("provider_id"):
                            self._conn.execute(
                                self._systems_upsert_sql(), self._system_dict_to_row(s)
                            )
                self._conn.commit()
        except sqlite3.Error as exc:
            logger.warning("save systems to DB failed: %s", exc)
            raise
        logger.info("external identity store: saved %d systems to SQLite",
                    len(systems or []))

    def seed_systems(self, systems: List[Dict[str, Any]]) -> int:
        """迁移用：INSERT OR IGNORE 播种 external_systems（幂等，不覆盖已有行）。"""
        count = 0
        with self._lock, self._conn:
            for s in systems or []:
                if not isinstance(s, dict) or not s.get("provider_id"):
                    continue
                self._conn.execute(
                    self._systems_seed_sql(), self._system_dict_to_row(s)
                )
                count += 1
            self._conn.commit()
        return count


    # ── bindings (SQLite user domain) ───────────────────────────────

    def load_bindings(self) -> List[Dict[str, Any]]:
        """Load all bindings (community shape: provider / external_id / external_name).

        The column fields are the canonical identity keys; ``extra_data`` holds
        the remaining original fields (source / status / last_login_at /
        login_count / …).  We merge them so the round-trip returns the full
        original binding dict losslessly.
        """
        with self._lock:
            rows = self._conn.execute(
                "SELECT * FROM external_bindings ORDER BY id"
            ).fetchall()
        bindings: List[Dict[str, Any]] = []
        for r in rows:
            base = {
                "user_id": r["user_id"],
                "provider": r["external_system"],
                "external_id": r["external_user_id"],
                "external_name": r["display_name"],
                "email": r["email"],
                "created_at": r["created_at"],
            }
            extra = r["extra_data"]
            if extra:
                try:
                    data = json.loads(extra)
                    if isinstance(data, dict):
                        base.update(data)
                except (json.JSONDecodeError, TypeError):
                    pass
            bindings.append(base)
        return bindings

    def save_bindings(self, bindings: List[Dict[str, Any]]) -> None:
        """Replace the full bindings list (app layer does read-modify-write)."""
        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        with self._conn:
            self._conn.execute("DELETE FROM external_bindings")
            for b in bindings:
                if not isinstance(b, dict):
                    continue
                provider = b.get("provider", "")
                ext_id = str(b.get("external_id", ""))
                user_id = str(b.get("user_id", ""))
                if not (provider and ext_id and user_id):
                    continue
                display = b.get("external_name") or b.get("display_name", "")
                email = b.get("email", "")
                created = b.get("created_at") or now
                # keep the original dict (minus column-backed keys) losslessly
                extra = {
                    k: v for k, v in b.items()
                    if k not in _COLUMN_KEYS
                }
                self._conn.execute(
                    """INSERT OR REPLACE INTO external_bindings
                       (user_id, external_system, external_user_id, display_name,
                        email, extra_data, created_at)
                       VALUES (?, ?, ?, ?, ?, ?, ?)""",
                    (user_id, provider, ext_id, display, email,
                     json.dumps(extra, ensure_ascii=False), created),
                )
        logger.info("external identity store: saved %d bindings to SQLite",
                    len(bindings))

    # ── lifecycle ───────────────────────────────────────────────────

    def close(self) -> None:
        try:
            self._conn.close()
        except sqlite3.Error:
            pass
