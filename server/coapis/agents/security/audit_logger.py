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

"""Structured audit logging for security events.

Records tool calls, permission checks, and violations in a structured format
for downstream analysis, alerting, and compliance.
"""
from __future__ import annotations

import json
import logging
import os
import time
import uuid
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Any, Dict, Optional

logger = logging.getLogger("coapis.audit")


@dataclass
class AuditEvent:
    """Structured audit event."""
    event_id: str
    timestamp: float
    event_type: str  # "tool_call", "path_check", "command_check", "permission_denied"
    username: str
    user_role: str
    workspace_dir: str
    tool_name: str = ""
    target_path: str = ""
    command: str = ""
    result: str = ""  # "allowed", "denied", "error"
    reason: str = ""
    metadata: Dict[str, Any] = None
    # Phase 1: command risk classification fields
    risk_level: str = ""          # "auto" | "confirm" | "block" | "denied"
    command_category: str = ""    # "file_delete" | "container" | "dangerous" | ...
    confirm_result: str = ""      # "approved" | "denied" | "timeout" | "skipped"

    def to_dict(self) -> Dict[str, Any]:
        d = asdict(self)
        if d["metadata"] is None:
            d["metadata"] = {}
        return d

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), ensure_ascii=False, default=str)


class AuditLogger:
    """Structured audit logger with file sink."""

    _instance: Optional["AuditLogger"] = None
    _enabled: bool = True
    _log_file: Optional[Path] = None

    @classmethod
    def initialize(cls, log_file: str | Path | None = None) -> "AuditLogger":
        """Initialize the audit logger singleton.

        Args:
            log_file: Optional path to append audit events (JSONL format).
                      If None, logs only to stderr via logging.
        """
        if cls._instance is not None:
            return cls._instance

        cls._instance = cls()
        if log_file:
            cls._log_file = Path(log_file)
            cls._log_file.parent.mkdir(parents=True, exist_ok=True)

        logger.info(f"AuditLogger initialized (file={log_file})")
        return cls._instance

    @classmethod
    def get_instance(cls) -> Optional["AuditLogger"]:
        """Get audit logger instance, or None if not initialized."""
        return cls._instance

    @classmethod
    def log(cls, event: AuditEvent) -> None:
        """Log an audit event (class-level convenience method)."""
        if cls._instance is None:
            return
        cls._instance._emit(event)

    def _emit(self, event: AuditEvent) -> None:
        """Emit event to all sinks."""
        if not self._enabled:
            return

        json_str = event.to_json()

        # Log to logging system
        if event.result == "denied":
            logger.warning(json_str)
        else:
            logger.info(json_str)

        # Append to file if configured
        if self._log_file:
            try:
                with open(self._log_file, "a", encoding="utf-8") as f:
                    f.write(json_str + "\n")
            except OSError:
                pass  # Don't fail the main flow on audit write errors

        # Note: Removed SQLite database dependency for open source version
        # Audit logs are stored in JSONL file only (configured via log_file parameter)


def create_audit_event(
    event_type: str,
    tool_name: str = "",
    target_path: str = "",
    command: str = "",
    result: str = "allowed",
    reason: str = "",
    metadata: Dict[str, Any] | None = None,
) -> AuditEvent:
    """Create an audit event from current context.

    Pulls username, role, workspace_dir from contextvars automatically.
    """
    from ...config.context import (
        get_current_username,
        get_current_user_role,
        get_current_workspace_dir,
    )

    return AuditEvent(
        event_id=uuid.uuid4().hex[:12],
        timestamp=time.time(),
        event_type=event_type,
        username=get_current_username() or "anonymous",
        user_role=get_current_user_role() or "user",
        workspace_dir=str(get_current_workspace_dir() or Path("/")),
        tool_name=tool_name,
        target_path=target_path,
        command=command,
        result=result,
        reason=reason,
        metadata=metadata or {},
    )
