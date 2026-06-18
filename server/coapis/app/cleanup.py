# -*- coding: utf-8 -*-
"""
Cleanup & Archive module — Cold/Hot data lifecycle management.

Architecture:
  - Hot data (JSON): recent chats, active sessions, current MEMORY.md
  - Warm data (DB): 7-90 day history in SQLite (OSS) or PostgreSQL (Enterprise)
  - Cold data (gzip): >90 day archives in backups/

Database abstraction:
  - Open Source: SQLite via stdlib sqlite3
  - Enterprise: PostgreSQL via psycopg2 (asyncpg for async)
  - Config: COAPIS_DB_BACKEND = "sqlite" | "postgresql"
"""
from __future__ import annotations

import datetime
import gzip
import json
import logging
import os
import shutil
import sqlite3
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any, Dict, List, Optional, Protocol, Tuple

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants & defaults
# ---------------------------------------------------------------------------

class DataLifecycle(str, Enum):
    HOT = "hot"      # <N days/messages — stay in JSON
    WARM = "warm"    # N-M days — archived to DB
    COLD = "cold"    # >M days — compressed to gzip backups


DEFAULT_RULES: Dict[str, Dict[str, int]] = {
    "chat_messages":   {"hot_limit": 50,  "warm_days": 90},
    "sessions":        {"hot_days": 7,    "warm_days": 30},
    "dialog_logs":     {"hot_days": 7,    "warm_days": 30},
    "tool_results":    {"hot_days": 3,    "warm_days": 7},
    "browser_cache":   {"hot_days": 1,    "warm_days": 3},
    "evolution":       {"hot_days": 30,   "warm_days": 90},
}


# ---------------------------------------------------------------------------
# DB Backend Protocol (strategy pattern for SQLite ↔ PgSQL switch)
# ---------------------------------------------------------------------------

class DBBackend(Protocol):
    """Abstract database backend interface."""

    def connect(self) -> Any: ...
    def close(self) -> None: ...
    def execute(self, sql: str, params: tuple = ()) -> Any: ...
    def executemany(self, sql: str, params_list: list) -> Any: ...
    def fetchall(self) -> list: ...
    def fetchone(self) -> Any: ...
    def commit(self) -> None: ...
    def ensure_schema(self) -> None: ...


# ---------------------------------------------------------------------------
# SQLite Backend (Open Source)
# ---------------------------------------------------------------------------

class SQLiteBackend:
    """SQLite implementation of DBBackend."""

    def __init__(self, db_path: Path):
        self.db_path = db_path
        self._conn: Optional[sqlite3.Connection] = None
        self._last_cursor: Optional[sqlite3.Cursor] = None

    def connect(self) -> sqlite3.Connection:
        if self._conn is None:
            self.db_path.parent.mkdir(parents=True, exist_ok=True)
            self._conn = sqlite3.connect(
                str(self.db_path),
                check_same_thread=False,
            )
            self._conn.row_factory = sqlite3.Row
            self._conn.execute("PRAGMA journal_mode=WAL")
            self._conn.execute("PRAGMA busy_timeout=5000")
        return self._conn

    def close(self) -> None:
        if self._conn:
            self._conn.close()
            self._conn = None

    def execute(self, sql: str, params: tuple = ()) -> sqlite3.Cursor:
        conn = self.connect()
        self._last_cursor = conn.execute(sql, params)
        return self._last_cursor

    def executemany(self, sql: str, params_list: list) -> sqlite3.Cursor:
        conn = self.connect()
        self._last_cursor = conn.executemany(sql, params_list)
        return self._last_cursor

    def fetchall(self) -> list:
        """Return last cursor's rows (used after execute)."""
        if self._last_cursor is not None:
            return self._last_cursor.fetchall()
        return []

    def fetchone(self):
        """Return last cursor's single row."""
        if self._last_cursor is not None:
            return self._last_cursor.fetchone()
        return None

    def commit(self) -> None:
        conn = self.connect()
        conn.commit()

    def ensure_schema(self) -> None:
        conn = self.connect()
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS archived_messages (
                id          TEXT PRIMARY KEY,
                chat_id     TEXT NOT NULL,
                user_id     TEXT NOT NULL,
                role        TEXT NOT NULL,
                content     TEXT,
                metadata    TEXT,
                created_at  TEXT NOT NULL,
                archived_at TEXT NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_am_chat_id ON archived_messages(chat_id);
            CREATE INDEX IF NOT EXISTS idx_am_user_id ON archived_messages(user_id);
            CREATE INDEX IF NOT EXISTS idx_am_created  ON archived_messages(created_at);

            CREATE TABLE IF NOT EXISTS archived_sessions (
                id          TEXT PRIMARY KEY,
                user_id     TEXT NOT NULL,
                agent_id    TEXT,
                session_data TEXT,
                created_at  TEXT NOT NULL,
                last_active TEXT NOT NULL,
                archived_at TEXT NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_as_user_id ON archived_sessions(user_id);
            CREATE INDEX IF NOT EXISTS idx_as_active  ON archived_sessions(last_active);

            CREATE TABLE IF NOT EXISTS archived_dialogs (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id     TEXT NOT NULL,
                file_name   TEXT NOT NULL,
                file_data   BLOB,
                original_size INTEGER,
                compressed_size INTEGER,
                date_from   TEXT NOT NULL,
                date_to     TEXT NOT NULL,
                archived_at TEXT NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_ad_user_id ON archived_dialogs(user_id);

            CREATE TABLE IF NOT EXISTS cleanup_log (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id     TEXT,
                action      TEXT NOT NULL,
                data_type   TEXT NOT NULL,
                items_count INTEGER DEFAULT 0,
                bytes_freed INTEGER DEFAULT 0,
                details     TEXT,
                executed_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS cleanup_rules (
                id          TEXT PRIMARY KEY,
                rules_json  TEXT NOT NULL,
                updated_at  TEXT NOT NULL
            );
        """)
        conn.commit()


# ---------------------------------------------------------------------------
# PostgreSQL Backend (Enterprise) — stub with same interface
# ---------------------------------------------------------------------------

class PostgreSQLBackend:
    """
    PostgreSQL implementation using psycopg2 (sync) or asyncpg.

    Connection string from env: COAPIS_PG_DSN
      e.g. postgresql://user:pass@host:5432/coapis
    """

    def __init__(self, dsn: Optional[str] = None):
        self.dsn = dsn or os.getenv(
            "COAPIS_PG_DSN",
            "postgresql://coapis:coapis@localhost:5432/coapis",
        )
        self._conn = None

    def connect(self):
        try:
            import psycopg2
        except ImportError:
            raise ImportError(
                "psycopg2 is required for PostgreSQL backend. "
                "Install with: pip install psycopg2-binary"
            )
        if self._conn is None or self._conn.closed:
            self._conn = psycopg2.connect(self.dsn)
        return self._conn

    def close(self) -> None:
        if self._conn and not self._conn.closed:
            self._conn.close()
            self._conn = None

    def execute(self, sql: str, params: tuple = ()):
        conn = self.connect()
        cur = conn.cursor()
        # Convert ? placeholders to %s for psycopg2
        sql_pg = sql.replace("?", "%s")
        cur.execute(sql_pg, params)
        return cur

    def executemany(self, sql: str, params_list: list):
        conn = self.connect()
        cur = conn.cursor()
        sql_pg = sql.replace("?", "%s")
        cur.executemany(sql_pg, params_list)
        return cur

    def fetchall(self) -> list:
        """Return last cursor's rows (used after execute)."""
        if self._last_cursor is not None:
            return self._last_cursor.fetchall()
        return []

    def fetchone(self):
        """Return last cursor's single row."""
        if self._last_cursor is not None:
            return self._last_cursor.fetchone()
        return None

    def commit(self) -> None:
        conn = self.connect()
        conn.commit()

    def ensure_schema(self) -> None:
        conn = self.connect()
        cur = conn.cursor()
        cur.execute("""
            CREATE TABLE IF NOT EXISTS archived_messages (
                id          TEXT PRIMARY KEY,
                chat_id     TEXT NOT NULL,
                user_id     TEXT NOT NULL,
                role        TEXT NOT NULL,
                content     TEXT,
                metadata    TEXT,
                created_at  TIMESTAMPTZ NOT NULL,
                archived_at TIMESTAMPTZ NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_am_chat_id ON archived_messages(chat_id);
            CREATE INDEX IF NOT EXISTS idx_am_user_id ON archived_messages(user_id);
            CREATE INDEX IF NOT EXISTS idx_am_created ON archived_messages(created_at);
        """)
        cur.execute("""
            CREATE TABLE IF NOT EXISTS archived_sessions (
                id           TEXT PRIMARY KEY,
                user_id      TEXT NOT NULL,
                agent_id     TEXT,
                session_data TEXT,
                created_at   TIMESTAMPTZ NOT NULL,
                last_active  TIMESTAMPTZ NOT NULL,
                archived_at  TIMESTAMPTZ NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_as_user_id ON archived_sessions(user_id);
            CREATE INDEX IF NOT EXISTS idx_as_active  ON archived_sessions(last_active);
        """)
        cur.execute("""
            CREATE TABLE IF NOT EXISTS archived_dialogs (
                id               SERIAL PRIMARY KEY,
                user_id          TEXT NOT NULL,
                file_name        TEXT NOT NULL,
                file_data        BYTEA,
                original_size    INTEGER,
                compressed_size  INTEGER,
                date_from        DATE NOT NULL,
                date_to          DATE NOT NULL,
                archived_at      TIMESTAMPTZ NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_ad_user_id ON archived_dialogs(user_id);
        """)
        cur.execute("""
            CREATE TABLE IF NOT EXISTS cleanup_log (
                id          SERIAL PRIMARY KEY,
                user_id     TEXT,
                action      TEXT NOT NULL,
                data_type   TEXT NOT NULL,
                items_count INTEGER DEFAULT 0,
                bytes_freed INTEGER DEFAULT 0,
                details     TEXT,
                executed_at TIMESTAMPTZ NOT NULL
            );
        """)
        cur.execute("""
            CREATE TABLE IF NOT EXISTS cleanup_rules (
                id          TEXT PRIMARY KEY,
                rules_json  TEXT NOT NULL,
                updated_at  TIMESTAMPTZ NOT NULL
            );
        """)
        conn.commit()


# ---------------------------------------------------------------------------
# CleanupEngine — main orchestrator
# ---------------------------------------------------------------------------

@dataclass
class CleanupStats:
    """Result of a cleanup run."""
    data_type: str = ""
    items_archived: int = 0
    items_deleted: int = 0
    bytes_freed: int = 0
    details: Dict[str, Any] = field(default_factory=dict)


class CleanupEngine:
    """
    Manages data lifecycle: hot → warm (DB archive) → cold (gzip).
    One engine per workspace.
    """

    def __init__(
        self,
        workspace_dir: Path,
        db_backend: Optional[DBBackend] = None,
        rules: Optional[Dict[str, Dict[str, int]]] = None,
    ):
        self.workspace_dir = Path(workspace_dir)
        self.chat_dir = self.workspace_dir / "chat"
        self.session_dir = self.workspace_dir / "sessions"
        self.dialog_dir = self._resolve_dialog_dir()
        self.tool_results_dir = self._resolve_tool_results_dir()
        self.browser_dir = self._resolve_browser_dir()
        self.evolution_dir = self.workspace_dir / "evolution"
        self.backup_dir = self.workspace_dir / "backups"

        # DB backend
        if db_backend is None:
            backend_type = os.getenv("COAPIS_DB_BACKEND", "sqlite").lower()
            if backend_type == "postgresql":
                self.db = PostgreSQLBackend()
            else:
                self.db = SQLiteBackend(self.workspace_dir / "history.db")
        else:
            self.db = db_backend

        self.rules = rules or self._load_rules()

    def _resolve_dialog_dir(self) -> Path:
        """Find dialog dir — could be in workspace or in agent workspace."""
        for candidate in [
            self.workspace_dir / "dialog",
            self.workspace_dir / "dialogs",
        ]:
            if candidate.exists():
                return candidate
        return self.workspace_dir / "dialog"

    def _resolve_tool_results_dir(self) -> Path:
        for candidate in [
            self.workspace_dir / "tool_results",
            self.workspace_dir / "tool_result",
        ]:
            if candidate.exists():
                return candidate
        return self.workspace_dir / "tool_results"

    def _resolve_browser_dir(self) -> Path:
        return self.workspace_dir / "browser"

    def _load_rules(self) -> Dict[str, Dict[str, int]]:
        """Load rules from DB or use defaults."""
        try:
            self.db.connect()
            self.db.ensure_schema()
            self.db.execute(
                "SELECT rules_json FROM cleanup_rules WHERE id = ?",
                ("default",),
            )
            row = self.db.fetchone() if hasattr(self.db, 'fetchone') else None
            if row:
                return json.loads(row[0])
        except Exception:
            pass
        return dict(DEFAULT_RULES)

    def save_rules(self, rules: Dict[str, Dict[str, int]]) -> None:
        """Persist rules to DB."""
        self.rules = rules
        now = datetime.datetime.now(datetime.timezone.utc).isoformat()
        self.db.connect()
        self.db.ensure_schema()
        self.db.execute(
            "INSERT OR REPLACE INTO cleanup_rules (id, rules_json, updated_at) VALUES (?, ?, ?)",
            ("default", json.dumps(rules), now),
        )
        self.db.commit()

    # ------------------------------------------------------------------
    # Storage overview
    # ------------------------------------------------------------------

    def get_storage_overview(self) -> Dict[str, Any]:
        """Return hot/warm/cold size breakdown."""
        def _dir_size(p: Path) -> int:
            if not p.exists():
                return 0
            return sum(f.stat().st_size for f in p.rglob("*") if f.is_file())

        hot_bytes = 0
        warm_bytes = 0

        # Hot: chats.json, active sessions, MEMORY.md
        for chats_file in self.chat_dir.rglob("chats.json"):
            hot_bytes += chats_file.stat().st_size
        for f in self.session_dir.glob("*.json"):
            hot_bytes += f.stat().st_size
        mem = self.workspace_dir / "MEMORY.md"
        if mem.exists():
            hot_bytes += mem.stat().st_size

        # Warm: DB file size
        db_path = self.workspace_dir / "history.db"
        if db_path.exists():
            warm_bytes = db_path.stat().st_size

        # Cold: backups
        cold_bytes = _dir_size(self.backup_dir)

        # Other: dialog logs, tool results, browser, evolution
        dialog_bytes = _dir_size(self.dialog_dir)
        tool_bytes = _dir_size(self.tool_results_dir)
        browser_bytes = _dir_size(self.browser_dir)
        evo_bytes = _dir_size(self.evolution_dir)

        total = hot_bytes + warm_bytes + cold_bytes + dialog_bytes + tool_bytes + browser_bytes + evo_bytes

        return {
            "hot": {
                "bytes": hot_bytes,
                "human": _human_size(hot_bytes),
                "items": ["chats.json", "sessions", "MEMORY.md"],
            },
            "warm": {
                "bytes": warm_bytes,
                "human": _human_size(warm_bytes),
                "items": ["history.db (archived messages, sessions, dialogs)"],
            },
            "cold": {
                "bytes": cold_bytes,
                "human": _human_size(cold_bytes),
                "items": ["backups/*.tar.gz"],
            },
            "other": {
                "dialog_bytes": dialog_bytes,
                "dialog_human": _human_size(dialog_bytes),
                "tool_results_bytes": tool_bytes,
                "tool_results_human": _human_size(tool_bytes),
                "browser_bytes": browser_bytes,
                "browser_human": _human_size(browser_bytes),
                "evolution_bytes": evo_bytes,
                "evolution_human": _human_size(evo_bytes),
            },
            "total_bytes": total,
            "total_human": _human_size(total),
            "workspace": str(self.workspace_dir),
        }

    # ------------------------------------------------------------------
    # Chat message rotation
    # ------------------------------------------------------------------

    def archive_chat_messages(self, chat_id: str, user_id: str, messages: list) -> CleanupStats:
        """
        Archive old messages beyond hot_limit. Returns updated (trimmed) messages.
        """
        stats = CleanupStats(data_type="chat_messages")
        rule = self.rules.get("chat_messages", DEFAULT_RULES["chat_messages"])
        hot_limit = rule.get("hot_limit", 50)

        if len(messages) <= hot_limit:
            return stats

        # Split: older messages go to DB
        to_archive = messages[:-hot_limit]
        now = datetime.datetime.now(datetime.timezone.utc).isoformat()

        rows = []
        for msg in to_archive:
            msg_id = msg.get("id", f"{chat_id}_{hash(json.dumps(msg, ensure_ascii=False))}")
            rows.append((
                str(msg_id),
                chat_id,
                user_id,
                msg.get("role", "unknown"),
                json.dumps(msg.get("content", ""), ensure_ascii=False),
                json.dumps({k: v for k, v in msg.items() if k not in ("role", "content", "id")}, ensure_ascii=False),
                msg.get("created_at", now),
                now,
            ))

        self.db.connect()
        self.db.ensure_schema()
        self.db.executemany(
            "INSERT OR IGNORE INTO archived_messages "
            "(id, chat_id, user_id, role, content, metadata, created_at, archived_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            rows,
        )
        self.db.commit()

        stats.items_archived = len(to_archive)
        stats.bytes_freed = sum(len(json.dumps(m, ensure_ascii=False)) for m in to_archive)
        stats.details = {"chat_id": chat_id, "archived_count": len(to_archive)}
        logger.info(
            "Archived %d messages for chat %s (kept %d hot)",
            len(to_archive), chat_id, hot_limit,
        )
        return stats

    def get_archived_messages(
        self,
        chat_id: str,
        before: Optional[str] = None,
        limit: int = 50,
    ) -> list:
        """Retrieve archived messages for a chat."""
        self.db.connect()
        self.db.ensure_schema()
        if before:
            self.db.execute(
                "SELECT * FROM archived_messages WHERE chat_id = ? AND created_at < ? "
                "ORDER BY created_at DESC LIMIT ?",
                (chat_id, before, limit),
            )
        else:
            self.db.execute(
                "SELECT * FROM archived_messages WHERE chat_id = ? "
                "ORDER BY created_at DESC LIMIT ?",
                (chat_id, limit),
            )
        rows = self.db.fetchall() if hasattr(self.db, 'fetchall') else []
        messages = []
        for row in rows:
            msg = {
                "id": row[0],
                "role": row[3],
                "content": json.loads(row[4]) if row[4] else "",
                "created_at": row[6],
            }
            if row[5]:
                msg.update(json.loads(row[5]))
            messages.append(msg)
        return list(reversed(messages))  # chronological order

    # ------------------------------------------------------------------
    # Session archival
    # ------------------------------------------------------------------

    def archive_expired_sessions(self) -> CleanupStats:
        """Archive sessions inactive for > hot_days."""
        stats = CleanupStats(data_type="sessions")
        if not self.session_dir.exists():
            return stats

        rule = self.rules.get("sessions", DEFAULT_RULES["sessions"])
        hot_days = rule.get("hot_days", 7)
        cutoff = datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(days=hot_days)

        self.db.connect()
        self.db.ensure_schema()

        archived = 0
        freed = 0
        for session_file in self.session_dir.glob("*.json"):
            try:
                mtime = datetime.datetime.fromtimestamp(
                    session_file.stat().st_mtime,
                    tz=datetime.timezone.utc,
                )
                if mtime < cutoff:
                    data = session_file.read_text(encoding="utf-8")
                    session_id = session_file.stem
                    user_id = session_id.split("_")[0] if "_" in session_id else "unknown"
                    file_size = session_file.stat().st_size

                    self.db.execute(
                        "INSERT OR REPLACE INTO archived_sessions "
                        "(id, user_id, agent_id, session_data, created_at, last_active, archived_at) "
                        "VALUES (?, ?, ?, ?, ?, ?, ?)",
                        (
                            session_id,
                            user_id,
                            "",
                            data,
                            mtime.isoformat(),
                            mtime.isoformat(),
                            datetime.datetime.now(datetime.timezone.utc).isoformat(),
                        ),
                    )
                    session_file.unlink()
                    archived += 1
                    freed += file_size
            except Exception as e:
                logger.warning("Failed to archive session %s: %s", session_file, e)

        self.db.commit()
        stats.items_archived = archived
        stats.bytes_freed = freed
        logger.info("Archived %d sessions, freed %s", archived, _human_size(freed))
        return stats

    # ------------------------------------------------------------------
    # Dialog log compression
    # ------------------------------------------------------------------

    def compress_old_dialogs(self) -> CleanupStats:
        """Compress dialog logs older than hot_days to gzip, archive > warm_days to DB."""
        stats = CleanupStats(data_type="dialog_logs")
        if not self.dialog_dir.exists():
            return stats

        rule = self.rules.get("dialog_logs", DEFAULT_RULES["dialog_logs"])
        hot_days = rule.get("hot_days", 7)
        warm_days = rule.get("warm_days", 30)
        now = datetime.datetime.now(datetime.timezone.utc)

        compressed = 0
        archived = 0
        freed = 0

        for jsonl_file in sorted(self.dialog_dir.glob("*.jsonl")):
            try:
                date_str = jsonl_file.stem  # e.g. "2026-05-01"
                file_date = datetime.datetime.strptime(date_str, "%Y-%m-%d").replace(
                    tzinfo=datetime.timezone.utc
                )
                age_days = (now - file_date).days

                if age_days > warm_days:
                    # Archive to DB then delete
                    file_data = jsonl_file.read_bytes()
                    gz_data = gzip.compress(file_data, compresslevel=9)

                    self.db.connect()
                    self.db.ensure_schema()
                    self.db.execute(
                        "INSERT INTO archived_dialogs "
                        "(user_id, file_name, file_data, original_size, compressed_size, "
                        "date_from, date_to, archived_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                        (
                            self.workspace_dir.name,
                            jsonl_file.name,
                            gz_data,
                            len(file_data),
                            len(gz_data),
                            date_str,
                            date_str,
                            now.isoformat(),
                        ),
                    )
                    self.db.commit()
                    jsonl_file.unlink()
                    freed += len(file_data)
                    archived += 1

                elif age_days > hot_days and not jsonl_file.name.endswith(".gz"):
                    # Compress in-place
                    original_size = jsonl_file.stat().st_size
                    with open(jsonl_file, "rb") as f_in:
                        with gzip.open(str(jsonl_file) + ".gz", "wb", compresslevel=9) as f_out:
                            shutil.copyfileobj(f_in, f_out)
                    gz_size = (jsonl_file.parent / (jsonl_file.name + ".gz")).stat().st_size
                    jsonl_file.unlink()
                    freed += original_size - gz_size
                    compressed += 1

            except Exception as e:
                logger.warning("Failed to process dialog %s: %s", jsonl_file, e)

        stats.items_archived = archived
        stats.items_deleted = compressed
        stats.bytes_freed = freed
        logger.info(
            "Dialog cleanup: %d archived, %d compressed, freed %s",
            archived, compressed, _human_size(freed),
        )
        return stats

    # ------------------------------------------------------------------
    # Tool results cleanup
    # ------------------------------------------------------------------

    def cleanup_tool_results(self) -> CleanupStats:
        """Delete tool result files older than hot_days."""
        stats = CleanupStats(data_type="tool_results")
        if not self.tool_results_dir.exists():
            return stats

        rule = self.rules.get("tool_results", DEFAULT_RULES["tool_results"])
        hot_days = rule.get("hot_days", 3)
        cutoff = datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(days=hot_days)

        deleted = 0
        freed = 0
        for f in self.tool_results_dir.rglob("*"):
            if f.is_file():
                mtime = datetime.datetime.fromtimestamp(
                    f.stat().st_mtime, tz=datetime.timezone.utc
                )
                if mtime < cutoff:
                    size = f.stat().st_size
                    f.unlink()
                    deleted += 1
                    freed += size

        stats.items_deleted = deleted
        stats.bytes_freed = freed
        logger.info("Cleaned %d tool results, freed %s", deleted, _human_size(freed))
        return stats

    # ------------------------------------------------------------------
    # Browser cache cleanup
    # ------------------------------------------------------------------

    def cleanup_browser_cache(self) -> CleanupStats:
        """Remove Chrome cache directories."""
        stats = CleanupStats(data_type="browser_cache")
        user_data = self.browser_dir / "user_data"
        if not user_data.exists():
            return stats

        cache_dirs = [
            user_data / "Default" / "Cache",
            user_data / "Default" / "Code Cache",
            user_data / "Default" / "Service Worker" / "CacheStorage",
            user_data / "GrShaderCache",
            user_data / "ShaderCache",
        ]

        freed = 0
        for d in cache_dirs:
            if d.exists():
                size = sum(f.stat().st_size for f in d.rglob("*") if f.is_file())
                shutil.rmtree(d, ignore_errors=True)
                freed += size

        # Clean old screenshots
        rule = self.rules.get("browser_cache", DEFAULT_RULES["browser_cache"])
        hot_days = rule.get("hot_days", 1)
        cutoff = datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(days=hot_days)
        for png in self.browser_dir.glob("page-*.png"):
            mtime = datetime.datetime.fromtimestamp(png.stat().st_mtime, tz=datetime.timezone.utc)
            if mtime < cutoff:
                freed += png.stat().st_size
                png.unlink()

        stats.bytes_freed = freed
        logger.info("Cleaned browser cache, freed %s", _human_size(freed))
        return stats

    # ------------------------------------------------------------------
    # Full cleanup run
    # ------------------------------------------------------------------

    def run_full_cleanup(self, user_id: str = "system") -> List[CleanupStats]:
        """Execute all cleanup tasks. Returns list of stats."""
        results = []
        now = datetime.datetime.now(datetime.timezone.utc).isoformat()

        # 1. Chat message rotation
        chats_file = self.chat_dir / "chats.json"
        if chats_file.exists():
            try:
                with open(chats_file, encoding="utf-8") as f:
                    data = json.load(f)
                chats = data.get("chats", [])
                modified = False
                for chat in chats:
                    msgs = chat.get("messages", [])
                    if len(msgs) > self.rules.get("chat_messages", {}).get("hot_limit", 50):
                        stat = self.archive_chat_messages(
                            chat.get("id", ""), user_id, msgs
                        )
                        if stat.items_archived > 0:
                            # Trim messages in-place
                            hot_limit = self.rules.get("chat_messages", {}).get("hot_limit", 50)
                            chat["messages"] = msgs[-hot_limit:]
                            results.append(stat)
                            modified = True
                if modified:
                    with open(chats_file, "w", encoding="utf-8") as f:
                        json.dump(data, f, ensure_ascii=False, indent=2)
            except Exception as e:
                logger.error("Chat rotation failed: %s", e)

        # 2. Session archival
        results.append(self.archive_expired_sessions())

        # 3. Dialog compression
        results.append(self.compress_old_dialogs())

        # 4. Tool results cleanup
        results.append(self.cleanup_tool_results())

        # 5. Browser cache cleanup
        results.append(self.cleanup_browser_cache())

        # Log to DB
        self.db.connect()
        self.db.ensure_schema()
        for stat in results:
            self.db.execute(
                "INSERT INTO cleanup_log "
                "(user_id, action, data_type, items_count, bytes_freed, details, executed_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?)",
                (
                    user_id,
                    "auto_cleanup",
                    stat.data_type,
                    stat.items_archived + stat.items_deleted,
                    stat.bytes_freed,
                    json.dumps(stat.details, ensure_ascii=False),
                    now,
                ),
            )
        self.db.commit()

        return results

    def get_cleanup_history(self, limit: int = 20) -> list:
        """Retrieve recent cleanup log entries."""
        self.db.connect()
        self.db.ensure_schema()
        self.db.execute(
            "SELECT * FROM cleanup_log ORDER BY executed_at DESC LIMIT ?",
            (limit,),
        )
        rows = self.db.fetchall() if hasattr(self.db, 'fetchall') else []
        return [
            {
                "id": r[0], "user_id": r[1], "action": r[2],
                "data_type": r[3], "items_count": r[4],
                "bytes_freed": r[5], "details": r[6], "executed_at": r[7],
            }
            for r in rows
        ]

    def close(self) -> None:
        self.db.close()


# ---------------------------------------------------------------------------
# Factory
# ---------------------------------------------------------------------------

_engine_cache: Dict[str, CleanupEngine] = {}


def get_cleanup_engine(workspace_dir: str | Path) -> CleanupEngine:
    """Get or create a CleanupEngine for a workspace."""
    key = str(Path(workspace_dir).resolve())
    if key not in _engine_cache:
        _engine_cache[key] = CleanupEngine(Path(workspace_dir))
    return _engine_cache[key]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _human_size(n: int) -> str:
    """Convert bytes to human-readable string."""
    for unit in ("B", "KB", "MB", "GB"):
        if abs(n) < 1024:
            return f"{n:.1f}{unit}"
        n /= 1024  # type: ignore
    return f"{n:.1f}TB"
