"""Tamper-proof audit log with hash chain verification."""

import hashlib
import json
import time
from pathlib import Path
from typing import Dict, Any, List, Optional


class HashChainAuditLogger:
    """Audit logger with hash chain for tamper detection.

    Each log entry includes the hash of the previous entry,
    creating an immutable chain. Any modification to a past
    entry will break the chain.
    """

    def __init__(self, log_dir: str):
        self.log_dir = Path(log_dir)
        self.log_dir.mkdir(parents=True, exist_ok=True)
        self.log_file = self.log_dir / "audit_chain.jsonl"
        self._last_hash = self._load_last_hash()

    def _load_last_hash(self) -> str:
        """Load the hash of the last log entry."""
        if not self.log_file.exists():
            return "GENESIS"

        try:
            with open(self.log_file, "r", encoding="utf-8") as f:
                lines = f.readlines()
                if lines:
                    last_entry = json.loads(lines[-1])
                    return last_entry.get("hash", "GENESIS")
        except (json.JSONDecodeError, KeyError):
            pass
        return "GENESIS"

    def log_event(self, event_type: str, data: Dict[str, Any]) -> str:
        """Record an audit event and return its hash.

        Args:
            event_type: Type of event (auth, tool_call, file_op, etc.)
            data: Event data dictionary

        Returns:
            SHA-256 hash of the entry
        """
        entry = {
            "timestamp": time.time(),
            "event_type": event_type,
            "data": data,
            "prev_hash": self._last_hash,
        }

        # Compute hash (exclude 'hash' field itself)
        entry_str = json.dumps(entry, sort_keys=True, ensure_ascii=False)
        entry["hash"] = hashlib.sha256(entry_str.encode("utf-8")).hexdigest()

        # Append to log file
        with open(self.log_file, "a", encoding="utf-8") as f:
            f.write(json.dumps(entry, ensure_ascii=False) + "\n")

        self._last_hash = entry["hash"]
        return entry["hash"]

    def log_tool_call(
        self,
        username: str,
        tool_name: str,
        args_summary: str,
        success: bool,
        duration_ms: float,
    ) -> str:
        """Log a tool execution event."""
        return self.log_event(
            "tool_call",
            {
                "user": username,
                "tool": tool_name,
                "args": args_summary,
                "success": success,
                "duration_ms": round(duration_ms, 2),
            },
        )

    def log_auth_event(
        self,
        username: str,
        action: str,
        success: bool,
        detail: str = "",
    ) -> str:
        """Log an authentication event."""
        return self.log_event(
            "auth",
            {
                "user": username,
                "action": action,
                "success": success,
                "detail": detail,
            },
        )

    def log_file_op(
        self,
        username: str,
        operation: str,
        path: str,
        success: bool,
    ) -> str:
        """Log a file operation event."""
        return self.log_event(
            "file_op",
            {
                "user": username,
                "operation": operation,
                "path": path,
                "success": success,
            },
        )

    def verify_chain(self) -> Dict[str, Any]:
        """Verify the integrity of the audit log chain.

        Returns:
            Dict with verification results
        """
        if not self.log_file.exists():
            return {"valid": True, "entries": 0, "message": "No log file"}

        try:
            with open(self.log_file, "r", encoding="utf-8") as f:
                lines = f.readlines()
        except Exception as e:
            return {"valid": False, "error": str(e)}

        prev_hash = "GENESIS"
        broken_at = None

        for line_num, line in enumerate(lines, 1):
            try:
                entry = json.loads(line)
            except json.JSONDecodeError:
                broken_at = line_num
                break

            # Verify prev_hash link
            if entry.get("prev_hash") != prev_hash:
                broken_at = line_num
                break

            # Verify entry hash
            stored_hash = entry.pop("hash", None)
            if stored_hash is None:
                broken_at = line_num
                break

            entry_str = json.dumps(entry, sort_keys=True, ensure_ascii=False)
            computed_hash = hashlib.sha256(entry_str.encode("utf-8")).hexdigest()

            if computed_hash != stored_hash:
                broken_at = line_num
                break

            prev_hash = stored_hash

        if broken_at:
            return {
                "valid": False,
                "entries": len(lines),
                "broken_at_line": broken_at,
                "message": f"Chain broken at line {broken_at}",
            }

        return {
            "valid": True,
            "entries": len(lines),
            "message": f"All {len(lines)} entries verified",
        }

    def get_recent_entries(self, limit: int = 100) -> List[Dict[str, Any]]:
        """Get recent audit entries."""
        if not self.log_file.exists():
            return []

        try:
            with open(self.log_file, "r", encoding="utf-8") as f:
                lines = f.readlines()
            entries = [json.loads(line) for line in lines[-limit:]]
            return entries
        except Exception:
            return []
