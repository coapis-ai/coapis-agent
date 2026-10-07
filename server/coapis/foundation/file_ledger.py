# -*- coding: utf-8 -*-
"""File ledger service (community edition, M2).

Append-only ledger of files materialized in user workspaces
(``workspaces/{username}/files/...``).

Design rules (review report §5.2):

* **Fire-and-forget** — every public method swallows its own exceptions;
  a broken ledger must never break the message path.
* **Two entry points** — hooks live in ``file_io.py`` (agent writes) and
  ``files.py`` (uploads); nothing else writes to the ledger except the
  reconcile sweep (``source='reconcile'``).
* **Append-only** — no DELETE is ever issued; read paths deduplicate by
  ``file_path`` keeping the newest row.
* **Attribution** — ``user_id`` stores the username (token_usage
  convention); ``session_id`` / ``agent_id`` come from the unified
  session contextvars when available.
"""

from __future__ import annotations

import asyncio
import logging
import time
from collections import OrderedDict
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Optional

from sqlalchemy import select

from ..constant import WORKING_DIR, WORKSPACES_DIR
from .db.engine import get_session
from .db.models.files import FileRecord

logger = logging.getLogger(__name__)

#: Recognized write sources (anything else is stored as ``other``).
VALID_SOURCES = frozenset(
    {"upload", "write_file", "edit_file", "append_file", "reconcile"}
)

#: Deliverables-ledger status states (approved plan C1, three-state machine).
VALID_STATUSES = frozenset({"draft", "delivered", "archived"})


class FileLedgerService:
    """File-ledger operations. Thread-safe (sync, short transactions)."""

    def __init__(self, workspaces_dir: Optional[Path] = None) -> None:
        self._ws = Path(workspaces_dir) if workspaces_dir else WORKSPACES_DIR

    # ── internals ─────────────────────────────────────────────────────

    def _files_root(self, username: str) -> Path:
        return self._ws / username / "files"

    @staticmethod
    def _normalize_rel(p: Path, root: Path) -> Optional[str]:
        """Return the POSIX-style relative path, or None if outside root."""
        try:
            rel = p.resolve().relative_to(root.resolve())
        except (ValueError, OSError, RuntimeError):
            return None
        return rel.as_posix()

    # ── write ─────────────────────────────────────────────────────────

    def record(
        self,
        username: Optional[str],
        abs_path: Optional[str],
        *,
        session_id: Optional[str] = None,
        agent_id: Optional[str] = None,
        source: str = "other",
        title: Optional[str] = None,
    ) -> bool:
        """Insert one ledger row. Returns True on success, False otherwise.

        Never raises — all errors are swallowed (debug log).
        """
        try:
            username = (username or "").strip()
            if not abs_path:
                return False
            p = Path(abs_path)
            rel = None
            uid = username
            if username:
                rel = self._normalize_rel(p, self._files_root(username))
            # Fallback: legacy shared WORKING_DIR/files/ — writes from
            # contexts without a user (historical behaviour, system jobs).
            if rel is None:
                rel = self._normalize_rel(p, WORKING_DIR / "files")
                uid = username or "shared"
            if rel is None:
                return False  # outside ledger-managed roots → not ledgered
            try:
                size = p.stat().st_size if p.exists() else 0
            except OSError:
                size = 0
            rec = FileRecord(
                user_id=uid,
                session_id=session_id or None,
                agent_id=agent_id or None,
                file_path=rel,
                size_bytes=size,
                source=source if source in VALID_SOURCES else "other",
                created_at=time.time(),
                title=(title or None),
            )
            with get_session() as s:
                s.add(rec)
            return True
        except Exception as exc:  # pragma: no cover - defensive
            logger.debug("file ledger record failed (ignored): %s", exc)
            return False

    # ── read ──────────────────────────────────────────────────────────

    def list_records(
        self,
        username: str,
        *,
        session_id: Optional[str] = None,
        source: Optional[str] = None,
        limit: int = 20,
        offset: int = 0,
    ) -> dict[str, Any]:
        """List distinct files (newest version wins), newest first."""
        try:
            q = select(FileRecord).where(FileRecord.user_id == username)
            if session_id:
                q = q.where(FileRecord.session_id == session_id)
            if source:
                q = q.where(FileRecord.source == source)
            with get_session() as s:
                rows = s.execute(q.order_by(FileRecord.id.desc())).all()
            # dedupe by file_path, keeping the newest row (first in desc-id
            # order); insertion order of the dict is therefore newest-first
            latest: "OrderedDict[str, dict]" = OrderedDict()
            for r in rows:
                d = r[0].to_dict()
                latest.setdefault(d["file_path"], d)  # desc id ⇒ first write wins
            items = list(latest.values())
            total = len(items)
            items = items[offset : offset + limit]
            # NOTE: keep "id" exposed — the status/archive endpoints
            # resolve records by this integer primary key.
            return {
                "items": items,
                "total": total,
                "limit": limit,
                "offset": offset,
            }
        except Exception as exc:  # pragma: no cover - defensive
            logger.warning("file ledger list failed: %s", exc)
            return {"items": [], "total": 0, "limit": limit, "offset": offset}

    # ── deliverables ledger (approved plan C1) ─────────────────────────

    def resolve_path(
        self, username: str, record_id: int
    ) -> Optional[str]:
        """Map a ledger row id to its file_path (owner-checked).

        Returns None when the row does not exist or belongs to someone
        else. Never raises.
        """
        try:
            with get_session() as s:
                row = s.execute(
                    select(FileRecord.file_path).where(
                        FileRecord.id == record_id,
                        FileRecord.user_id == username,
                    )
                ).scalar_one_or_none()
            return row
        except Exception as exc:  # pragma: no cover - defensive
            logger.warning("file ledger resolve failed: %s", exc)
            return None

    def update_record_status(
        self,
        username: str,
        file_path: str,
        status: str,
        title: Optional[str] = None,
        description: Optional[str] = None,
    ) -> bool:
        """Move the newest row of ``(username, file_path)`` to *status*.

        Optionally refreshes ``title`` / ``description`` and stamps
        ``updated_at``. Returns False for invalid status or a missing
        row. Never raises.
        """
        try:
            if status not in VALID_STATUSES:
                return False
            with get_session() as s:
                row = s.execute(
                    select(FileRecord)
                    .where(
                        FileRecord.user_id == username,
                        FileRecord.file_path == file_path,
                    )
                    .order_by(FileRecord.id.desc())
                    .limit(1)
                ).scalar_one_or_none()
                if row is None:
                    return False
                row.status = status
                row.updated_at = time.time()
                if title is not None:
                    row.title = title
                if description is not None:
                    row.description = description
            return True
        except Exception as exc:  # pragma: no cover - defensive
            logger.warning("file ledger status update failed: %s", exc)
            return False

    def _distinct_latest(
        self,
        username: str,
        *,
        session_id: Optional[str] = None,
    ) -> list[dict[str, Any]]:
        """Distinct files (newest row wins) with ledger metadata.

        Shared by :meth:`list_deliverables` and :meth:`count_deliverables`.
        Never raises.
        """
        try:
            q = select(FileRecord).where(FileRecord.user_id == username)
            if session_id:
                q = q.where(FileRecord.session_id == session_id)
            with get_session() as s:
                rows = s.execute(q.order_by(FileRecord.id.desc())).all()
            latest: "OrderedDict[str, dict]" = OrderedDict()
            for r in rows:
                d = r[0].to_dict()
                latest.setdefault(d["file_path"], d)
            return list(latest.values())
        except Exception as exc:  # pragma: no cover - defensive
            logger.warning("file ledger deliverables failed: %s", exc)
            return []

    def list_deliverables(
        self,
        username: str,
        *,
        status: Optional[str] = None,
        session_id: Optional[str] = None,
        limit: int = 50,
    ) -> list[dict[str, Any]]:
        """Distinct files (newest row wins) with ledger metadata.

        Filters by the *current* status of the newest row; ordered by
        ``updated_at`` (falling back to ``created_at``) descending.
        Never raises.
        """
        items = self._distinct_latest(username, session_id=session_id)
        if status:
            items = [d for d in items if d.get("status") == status]
        items.sort(
            key=lambda d: (d.get("updated_at") or d.get("created_at") or 0),
            reverse=True,
        )
        # NOTE: keep "id" exposed — clients need it to target the
        # status/archive endpoints.
        return items[:limit]

    def count_deliverables(
        self,
        username: str,
        *,
        status: Optional[str] = None,
        session_id: Optional[str] = None,
    ) -> int:
        """Total distinct-file count (unlimited) for the same filters as
        :meth:`list_deliverables`. Never raises (returns 0 on failure).
        """
        items = self._distinct_latest(username, session_id=session_id)
        if status:
            items = [d for d in items if d.get("status") == status]
        return len(items)

    def archive_file(self, username: str, file_path: str) -> bool:
        """Mark the newest row of ``file_path`` as archived (soft only)."""
        return self.update_record_status(username, file_path, "archived")

    def stats(self, username: str) -> dict[str, Any]:
        """Aggregate stats: distinct files, total size, by source / ext."""
        try:
            with get_session() as s:
                rows = s.execute(
                    select(FileRecord).where(
                        FileRecord.user_id == username
                    ).order_by(FileRecord.id)
                ).all()
            first: dict[str, FileRecord] = {}
            last: dict[str, FileRecord] = {}
            for r in rows:
                fr = r[0]
                first.setdefault(fr.file_path, fr)
                last[fr.file_path] = fr
            by_source: dict[str, int] = {}
            by_ext: dict[str, int] = {}
            total_size = 0
            for fr in last.values():
                total_size += int(fr.size_bytes or 0)
                name = fr.file_path.rsplit("/", 1)[-1]
                ext = "." + name.rsplit(".", 1)[1].lower() if "." in name else "(none)"
                by_ext[ext] = by_ext.get(ext, 0) + 1
            for fr in first.values():
                by_source[fr.source] = by_source.get(fr.source, 0) + 1
            return {
                "total_files": len(last),
                "total_size": total_size,
                "by_source": dict(sorted(by_source.items())),
                "by_extension": dict(sorted(by_ext.items())),
            }
        except Exception as exc:  # pragma: no cover - defensive
            logger.warning("file ledger stats failed: %s", exc)
            return {
                "total_files": 0,
                "total_size": 0,
                "by_source": {},
                "by_extension": {},
            }

    # ── reconcile ─────────────────────────────────────────────────────

    def reconcile(self) -> dict[str, int]:
        """Backfill ledger rows for files missing from the ledger.

        Scans every ``{ws}/*/files/**``; inserts one row per missing
        ``(user_id, file_path)`` with ``source='reconcile'``. Idempotent.
        Returns ``{"scanned": n, "inserted": m}``.
        """
        scanned = 0
        inserted = 0
        try:
            if not self._ws.exists():
                return {"scanned": 0, "inserted": 0}
            for user_dir in sorted(self._ws.iterdir()):
                if not user_dir.is_dir():
                    continue
                username = user_dir.name
                root = user_dir / "files"
                if not root.is_dir():
                    continue
                files = [
                    p for p in root.rglob("*") if p.is_file()
                ]
                scanned += len(files)
                if not files:
                    continue
                # existing (user_id, file_path) pairs
                with get_session() as s:
                    existing_rows = s.execute(
                        select(FileRecord.file_path).where(
                            FileRecord.user_id == username
                        )
                    ).all()
                existing = {row[0] for row in existing_rows}
                missing = []
                for p in files:
                    try:
                        rel = p.resolve().relative_to(root.resolve()).as_posix()
                    except (ValueError, OSError, RuntimeError):
                        continue
                    if rel in existing:
                        continue
                    try:
                        size = p.stat().st_size
                    except OSError:
                        size = 0
                    missing.append((rel, size))
                if not missing:
                    continue
                with get_session() as s:
                    now = time.time()
                    for rel, size in missing:
                        s.add(
                            FileRecord(
                                user_id=username,
                                file_path=rel,
                                size_bytes=size,
                                source="reconcile",
                                created_at=now,
                            )
                        )
                inserted += len(missing)
            # Legacy shared root: WORKING_DIR/files (system/anonymous writes)
            shared_root = WORKING_DIR / "files"
            if shared_root.is_dir():
                files = [p for p in shared_root.rglob("*") if p.is_file()]
                scanned += len(files)
                if files:
                    with get_session() as s:
                        existing_rows = s.execute(
                            select(FileRecord.file_path).where(
                                FileRecord.user_id == "shared"
                            )
                        ).all()
                    existing = {row[0] for row in existing_rows}
                    missing = []
                    for p in files:
                        try:
                            rel = p.resolve().relative_to(
                                shared_root.resolve()
                            ).as_posix()
                        except (ValueError, OSError, RuntimeError):
                            continue
                        if rel in existing:
                            continue
                        try:
                            size = p.stat().st_size
                        except OSError:
                            size = 0
                        missing.append((rel, size))
                    if missing:
                        now = time.time()
                        with get_session() as s:
                            for rel, size in missing:
                                s.add(
                                    FileRecord(
                                        user_id="shared",
                                        file_path=rel,
                                        size_bytes=size,
                                        source="reconcile",
                                        created_at=now,
                                    )
                                )
                        inserted += len(missing)
        except Exception as exc:  # pragma: no cover - defensive
            logger.warning("file ledger reconcile failed: %s", exc)
        return {"scanned": scanned, "inserted": inserted}


# ── module-level convenience (singleton) ────────────────────────────────────

_ledger: Optional[FileLedgerService] = None


def get_file_ledger() -> FileLedgerService:
    global _ledger
    if _ledger is None:
        _ledger = FileLedgerService()
    return _ledger


def record_file_event(
    username: Optional[str],
    abs_path: Optional[str],
    *,
    session_id: Optional[str] = None,
    agent_id: Optional[str] = None,
    source: str = "other",
    title: Optional[str] = None,
) -> bool:
    """Fire-and-forget ledger hook (never raises)."""
    try:
        return get_file_ledger().record(
            username, abs_path, session_id=session_id, agent_id=agent_id,
            source=source, title=title,
        )
    except Exception as exc:  # pragma: no cover - defensive
        logger.debug("file ledger event failed (ignored): %s", exc)
        return False


async def start_file_ledger_maintenance(hour: int = 3) -> None:
    """Initial reconcile at startup, then a daily sweep at local ``hour:00``.

    Runs forever; every iteration is individually guarded so a failure
    can never kill the loop.
    """
    while True:
        try:
            loop = asyncio.get_running_loop()
            res = await loop.run_in_executor(None, get_file_ledger().reconcile)
            logger.info("file ledger reconcile: %s", res)
        except Exception as exc:  # pragma: no cover - defensive
            logger.warning("file ledger reconcile failed: %s", exc)
        now = datetime.now()
        nxt = now.replace(hour=hour, minute=0, second=0, microsecond=0)
        if nxt <= now:
            nxt += timedelta(days=1)
        try:
            await asyncio.sleep((nxt - now).total_seconds())
        except asyncio.CancelledError:
            raise
