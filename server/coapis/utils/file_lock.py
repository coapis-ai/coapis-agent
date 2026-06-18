"""Thread-safe JSON file operations with file locking.

Provides atomic read/write for JSON files to prevent data corruption
in concurrent scenarios (multiple requests, async tasks).

Usage:
    from coapis.utils.file_lock import safe_read_json, safe_write_json

    data = safe_read_json(path, default={"users": {}})
    safe_write_json(path, data)
"""
from __future__ import annotations

import fcntl
import json
import logging
import os
import tempfile
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


def safe_read_json(path: Path, default: Any = None) -> Any:
    """Read JSON file with shared lock (multiple readers allowed).

    Returns *default* if file doesn't exist or is corrupted.
    """
    if not path.exists():
        return default if default is not None else {}

    try:
        with open(path, "r", encoding="utf-8") as f:
            fcntl.flock(f.fileno(), fcntl.LOCK_SH)
            try:
                data = json.load(f)
            finally:
                fcntl.flock(f.fileno(), fcntl.LOCK_UN)
        return data
    except (json.JSONDecodeError, OSError) as e:
        logger.error(f"Failed to read JSON from {path}: {e}")
        return default if default is not None else {}


def safe_write_json(path: Path, data: Any, mode: int = 0o600) -> bool:
    """Write JSON file atomically with exclusive lock.

    Uses write-to-temp-then-rename pattern to prevent partial reads.
    Returns True on success.
    """
    path.parent.mkdir(parents=True, exist_ok=True)

    try:
        # Write to temporary file first (atomic on POSIX)
        fd, tmp_path = tempfile.mkstemp(
            dir=str(path.parent),
            suffix=".tmp",
            prefix=f".{path.stem}.",
        )
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                fcntl.flock(f.fileno(), fcntl.LOCK_EX)
                try:
                    json.dump(data, f, indent=2, ensure_ascii=False)
                    f.flush()
                    os.fsync(f.fileno())
                finally:
                    fcntl.flock(f.fileno(), fcntl.LOCK_UN)

            # Set permissions before rename
            os.chmod(tmp_path, mode)

            # Atomic rename (on same filesystem)
            os.replace(tmp_path, str(path))
            return True
        except Exception:
            # Cleanup temp file on failure
            try:
                os.unlink(tmp_path)
            except OSError:
                pass
            raise
    except OSError as e:
        logger.error(f"Failed to write JSON to {path}: {e}")
        return False


def _rotate_jsonl_if_needed(path: Path, max_bytes: int = 10 * 1024 * 1024) -> None:
    """Rotate a JSONL file when it exceeds *max_bytes* (default 10 MB).

    Keeps at most one archived copy (``<name>.1.jsonl``).
    Safe to call under the same exclusive lock as the writer.
    """
    try:
        if not path.exists() or path.stat().st_size < max_bytes:
            return
        archive = path.with_name(path.stem + ".1.jsonl")
        if archive.exists():
            archive.unlink()
        # Atomic rename on most POSIX filesystems
        path.rename(archive)
    except OSError as exc:
        logger.warning("JSONL rotation failed for %s: %s", path, exc)


def safe_append_jsonl(path: Path, record: Any) -> bool:
    """Append a JSON record to a JSONL file with exclusive lock.

    Each record is written as a single line (no pretty-print).
    Automatically rotates the file when it exceeds 10 MB.
    Returns True on success.
    """
    path.parent.mkdir(parents=True, exist_ok=True)

    try:
        # Rotate BEFORE opening so the fd points to the (possibly new) file.
        _rotate_jsonl_if_needed(path)
        with open(path, "a", encoding="utf-8") as f:
            fcntl.flock(f.fileno(), fcntl.LOCK_EX)
            try:
                f.write(json.dumps(record, ensure_ascii=False) + "\n")
                f.flush()
                os.fsync(f.fileno())
            finally:
                fcntl.flock(f.fileno(), fcntl.LOCK_UN)
        return True
    except OSError as e:
        logger.error(f"Failed to append JSONL to {path}: {e}")
        return False
