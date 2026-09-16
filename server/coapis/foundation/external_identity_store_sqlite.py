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
        self._conn.commit()

    # ── systems (JSON config domain, read-only) ─────────────────────

    def load_systems(self) -> List[Dict[str, Any]]:
        """Return all external system configs (from JSON config file)."""
        cfg_file = SYSTEM_DIR / _SYSTEMS_CONFIG_FILE
        if not cfg_file.exists():
            return []
        try:
            data = json.loads(cfg_file.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            return []
        systems = data.get("systems", []) if isinstance(data, dict) else data
        return [s for s in systems if isinstance(s, dict)]

    def get_system_by_id(self, provider_id: str) -> Optional[Dict[str, Any]]:
        for s in self.load_systems():
            if s.get("provider_id") == provider_id:
                return s
        return None

    def save_systems(self, systems: List[Dict[str, Any]]) -> None:
        """Persist the external systems config.

        External systems are *admin configuration* (SSO endpoints, credentials,
        outbound identity), not per-user data — they intentionally stay in
        ``external_systems_config.json`` (same domain as ``settings.json``),
        mirroring how the community edition keeps other config files.
        """
        config_data = {"systems": systems or []}
        path = SYSTEM_DIR / _SYSTEMS_CONFIG_FILE
        try:
            SYSTEM_DIR.mkdir(parents=True, exist_ok=True)
        except Exception:
            pass
        tmp_path = path.with_suffix(".json.tmp")
        try:
            with open(tmp_path, "w", encoding="utf-8") as f:
                json.dump(config_data, f, ensure_ascii=False, indent=2)
            os.replace(tmp_path, path)
        except Exception:
            try:
                if tmp_path.exists():
                    tmp_path.unlink()
            except Exception:
                pass
            raise


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
