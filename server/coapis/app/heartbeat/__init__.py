"""
HeartbeatRepo: unified heartbeat config storage in system/heartbeat.json.

Key format: "{user}:{agent_id}" (e.g. "admin:global_default")
Storage: system/heartbeat.json (JSON file, easy to migrate to DB later)
"""
from __future__ import annotations

import json
import logging
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Optional

from ...constant import SYSTEM_DIR

logger = logging.getLogger(__name__)

# Defaults
DEFAULT_INTERVAL_SECONDS = 3600   # 60 minutes
DEFAULT_TIMEOUT_SECONDS = 300     # 5 minutes
DEFAULT_TARGET = "main"

HEARTBEAT_FILE = SYSTEM_DIR / "heartbeat.json"


def _default_entry() -> Dict[str, Any]:
    return {
        "enabled": False,
        "interval_seconds": DEFAULT_INTERVAL_SECONDS,
        "target": DEFAULT_TARGET,
        "active_hours": None,
        "timeout_seconds": DEFAULT_TIMEOUT_SECONDS,
        "updated_at": None,
    }


class HeartbeatRepo:
    """Thread-safe read/write for system/heartbeat.json."""

    def __init__(self, path: Optional[Path] = None):
        self._path = path or HEARTBEAT_FILE
        self._lock = threading.Lock()

    # ── Load / Save ──

    def _load_all(self) -> Dict[str, Any]:
        if not self._path.exists():
            return {}
        try:
            with open(self._path, "r", encoding="utf-8") as f:
                return json.load(f)
        except (json.JSONDecodeError, OSError) as e:
            logger.warning("heartbeat.json read error: %s, returning empty", e)
            return {}

    def _save_all(self, data: Dict[str, Any]) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self._path.with_suffix(".tmp")
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
        tmp.replace(self._path)

    # ── Public API ──

    def get(self, key: str) -> Dict[str, Any]:
        """Get heartbeat config for a key. Returns defaults if missing."""
        with self._lock:
            data = self._load_all()
            entry = data.get(key)
            if entry is None:
                return _default_entry()
            # Merge with defaults to fill missing fields
            result = _default_entry()
            result.update(entry)
            return result

    def update(self, key: str, payload: Dict[str, Any]) -> Dict[str, Any]:
        """Update heartbeat config for a key. Returns the saved entry."""
        with self._lock:
            data = self._load_all()
            entry = data.get(key, _default_entry())
            # Update only provided fields
            for field in ("enabled", "interval_seconds", "target",
                          "active_hours", "timeout_seconds"):
                if field in payload:
                    entry[field] = payload[field]
            entry["updated_at"] = datetime.now(timezone.utc).isoformat()
            data[key] = entry
            self._save_all(data)
            return entry

    def list_enabled(self) -> Dict[str, Dict[str, Any]]:
        """Return all enabled heartbeat entries {key: config}."""
        with self._lock:
            data = self._load_all()
            return {k: v for k, v in data.items()
                    if v.get("enabled", False)}

    def delete(self, key: str) -> bool:
        """Delete a heartbeat entry. Returns True if existed."""
        with self._lock:
            data = self._load_all()
            if key in data:
                del data[key]
                self._save_all(data)
                return True
            return False


# Singleton for app-wide usage
_repo: Optional[HeartbeatRepo] = None


def get_heartbeat_repo() -> HeartbeatRepo:
    global _repo
    if _repo is None:
        _repo = HeartbeatRepo()
    return _repo
