# -*- coding: utf-8 -*-
# Copyright 2026 蜜蜂 & CoApis Contributors
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU Affero General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU Affero General Public License for more details.
#
# You should have received a copy of the GNU Affero General Public License
# along with this program.  If not, see <https://www.gnu.org/licenses/>.

"""Audit log routes.

Provides access to security audit logs including blocked actions,
authentication events, and permission violations.
"""

import logging
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, HTTPException, Query, Request

from ...constant import DATA_DIR
from ..permissions.decorators import require_permission

logger = logging.getLogger(__name__)

router = APIRouter(tags=["audit"])

# ── Storage ─────────────────────────────────────────────────────────
AUDIT_DIR = DATA_DIR / "logs" / "audit"
AUDIT_FILE = AUDIT_DIR / "audit.jsonl"

# In-memory cache for recent audit entries
_audit_entries: List[Dict[str, Any]] = []
_MAX_AUDIT_ENTRIES = 10000


def _load_audit_entries():
    """Load audit entries from file."""
    global _audit_entries
    if not AUDIT_FILE.exists():
        _audit_entries = []
        return
    try:
        _audit_entries = []
        with open(AUDIT_FILE, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line:
                    import json
                    try:
                        entry = json.loads(line)
                        _audit_entries.append(entry)
                    except json.JSONDecodeError:
                        continue
        # Keep only recent entries
        if len(_audit_entries) > _MAX_AUDIT_ENTRIES:
            _audit_entries = _audit_entries[-_MAX_AUDIT_ENTRIES:]
    except Exception as e:
        logger.warning(f"Failed to load audit entries: {e}")
        _audit_entries = []


def _append_audit_entry(entry: Dict[str, Any]):
    """Append an audit entry to file and memory."""
    global _audit_entries
    _audit_entries.append(entry)
    if len(_audit_entries) > _MAX_AUDIT_ENTRIES:
        _audit_entries = _audit_entries[-_MAX_AUDIT_ENTRIES:]
    try:
        import json
        AUDIT_DIR.mkdir(parents=True, exist_ok=True)
        with open(AUDIT_FILE, "a", encoding="utf-8") as f:
            f.write(json.dumps(entry, ensure_ascii=False) + "\n")
    except Exception as e:
        logger.warning(f"Failed to write audit entry: {e}")


# Load entries on startup
_load_audit_entries()


@router.get("/audit/logs")
@require_permission("admin:admin")
async def get_audit_logs(
    request: Request,
    limit: int = Query(100, ge=1, le=1000),
    offset: int = Query(0, ge=0),
    level: Optional[str] = Query(None),
    action: Optional[str] = Query(None),
    user_id: Optional[str] = Query(None),
) -> Dict[str, Any]:
    """Get audit log entries."""
    global _audit_entries
    # Reload from file to get latest entries
    _load_audit_entries()

    entries = _audit_entries
    # Apply filters
    if level:
        entries = [e for e in entries if e.get("level") == level]
    if action:
        entries = [e for e in entries if e.get("action") == action]
    if user_id:
        entries = [e for e in entries if e.get("user_id") == user_id]

    # Sort by timestamp descending
    entries = sorted(entries, key=lambda e: e.get("timestamp", 0), reverse=True)

    # Paginate
    total = len(entries)
    entries = entries[offset:offset + limit]

    return {
        "total": total,
        "limit": limit,
        "offset": offset,
        "entries": entries,
    }


@router.get("/audit/stats")
@require_permission("admin:admin")
async def get_audit_stats(request: Request) -> Dict[str, Any]:
    """Get audit log statistics."""
    global _audit_entries
    _load_audit_entries()

    total = len(_audit_entries)
    by_level = {}
    by_action = {}
    for entry in _audit_entries:
        level = entry.get("level", "unknown")
        action = entry.get("action", "unknown")
        by_level[level] = by_level.get(level, 0) + 1
        by_action[action] = by_action.get(action, 0) + 1

    return {
        "total_entries": total,
        "by_level": by_level,
        "by_action": by_action,
        "recent_activity": _audit_entries[-10:] if _audit_entries else [],
    }


@router.post("/audit/logs")
@require_permission("admin:admin")
async def log_audit_event(
    request: Request,
    entry: Dict[str, Any] = ...,
) -> Dict[str, Any]:
    """Manually log an audit event."""
    entry.setdefault("timestamp", time.time())
    entry.setdefault("source", "manual")
    _append_audit_entry(entry)
    return {"status": "ok", "entry": entry}


@router.delete("/audit/logs")
@require_permission("admin:admin")
async def clear_audit_logs(
    request: Request,
    confirm: str = Query("", description='传入 "CLEAR_ALL" 以确认清除'),
    backup: bool = Query(True, description="清除前是否自动备份"),
) -> Dict[str, Any]:
    """Clear all audit logs — requires confirm=CLEAR_ALL to proceed."""
    if confirm != "CLEAR_ALL":
        raise HTTPException(
            status_code=400,
            detail='必须传入 confirm="CLEAR_ALL" 才能清除审计日志，此操作不可撤销',
        )

    # Auto-backup before clearing
    if backup and AUDIT_FILE.exists() and AUDIT_FILE.stat().st_size > 0:
        import shutil
        backup_path = AUDIT_DIR / f"audit_backup_{int(time.time())}.jsonl"
        try:
            shutil.copy2(AUDIT_FILE, backup_path)
        except Exception as e:
            logger.warning(f"Backup failed: {e}")

    global _audit_entries
    _audit_entries = []
    try:
        if AUDIT_FILE.exists():
            AUDIT_FILE.write_text("", encoding="utf-8")
    except Exception as e:
        logger.warning(f"Failed to clear audit file: {e}")
    return {"status": "ok", "message": "Audit logs cleared"}
