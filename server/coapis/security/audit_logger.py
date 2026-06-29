"""Security audit logger - dedicated to sandbox security events.

Extends HashChainAuditLogger with security-specific event types:
- path_check: path whitelist check (success/fail)
- command_block: command blocked by guard engine
- command_audit: command audited (executed but logged)
- tool_denied: tool not in whitelist
- input_block: input blocked by input guard
- evasion_detect: shell evasion pattern detected
"""

import json
import logging
import os
from datetime import datetime
from pathlib import Path
from typing import Optional

from .audit_chain import HashChainAuditLogger


class SecurityAuditLogger:
    """Security-focused audit logger.

    Writes security events in two places:
    1. HashChainAuditLogger (tamper-proof chain) for compliance
    2. security_audit.log (plain JSON Lines) for quick grep/tail
    """

    _instance: Optional["SecurityAuditLogger"] = None

    def __init__(self, log_dir: Optional[str] = None):
        if log_dir is None:
            log_dir = os.environ.get(
                "COAPIS_SECURITY_AUDIT_LOG_DIR",
                os.environ.get("COAPIS_SYSTEM_DIR", "/apps/ai/coapis/system"),
            )
        self.log_dir = Path(log_dir)
        self.log_dir.mkdir(parents=True, exist_ok=True)

        # Hash chain for tamper-proof logging
        self.chain = HashChainAuditLogger(str(self.log_dir))

        # Plain log for quick grep/tail
        self.plain_log = self.log_dir / "security_audit.log"
        self._logger = self._setup_plain_logger()

    @classmethod
    def get_instance(cls) -> "SecurityAuditLogger":
        """Singleton pattern - one logger per process."""
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    @classmethod
    def reset_instance(cls):
        """Reset singleton (for testing)."""
        cls._instance = None

    def _setup_plain_logger(self) -> logging.Logger:
        """Setup plain text logger for quick grep/tail."""
        logger = logging.getLogger("security_audit")
        logger.setLevel(logging.INFO)
        # Avoid duplicate handlers on re-init
        if not logger.handlers:
            handler = logging.FileHandler(self.plain_log, encoding="utf-8")
            handler.setFormatter(logging.Formatter("%(message)s"))
            logger.addHandler(handler)
            # Prevent propagation to root logger
            logger.propagate = False
        return logger

    def _write(self, event_type: str, data: dict):
        """Write event to both chain and plain log."""
        # 1. Hash chain (tamper-proof)
        self.chain.log_event(event_type, data)

        # 2. Plain log (quick grep)
        entry = {
            "timestamp": datetime.now().isoformat(),
            "event": event_type,
            **data,
        }
        self._logger.info(json.dumps(entry, ensure_ascii=False))

    # ─── Security-specific event methods ───

    def log_path_check(
        self,
        user: str,
        path: str,
        operation: str,
        allowed: bool,
        reason: str = "",
        agent_id: str = "",
    ):
        """Log path whitelist check result."""
        self._write("path_check", {
            "user": user,
            "agent_id": agent_id,
            "path": path,
            "operation": operation,
            "allowed": allowed,
            "reason": reason,
            "level": "INFO" if allowed else "WARNING",
        })

    def log_command_block(
        self,
        user: str,
        command: str,
        level: str,
        action: str,
        reason: str,
        agent_id: str = "",
        matched_rules: list = None,
    ):
        """Log command blocked by guard engine."""
        self._write("command_block", {
            "user": user,
            "agent_id": agent_id,
            "command": command[:200],  # Truncate long commands
            "level": level,
            "action": action,
            "reason": reason,
            "matched_rules": matched_rules or [],
            "severity": "WARNING" if action == "block" else "INFO",
        })

    def log_command_audit(
        self,
        user: str,
        command: str,
        level: str,
        action: str,
        agent_id: str = "",
        matched_rules: list = None,
    ):
        """Log command audited (executed but recorded)."""
        self._write("command_audit", {
            "user": user,
            "agent_id": agent_id,
            "command": command[:200],
            "level": level,
            "action": action,
            "matched_rules": matched_rules or [],
            "severity": "INFO",
        })

    def log_tool_denied(
        self,
        user: str,
        tool_name: str,
        reason: str,
        agent_id: str = "",
    ):
        """Log tool not in whitelist."""
        self._write("tool_denied", {
            "user": user,
            "agent_id": agent_id,
            "tool": tool_name,
            "reason": reason,
            "severity": "WARNING",
        })

    def log_input_block(
        self,
        user: str,
        input_summary: str,
        reason: str,
        agent_id: str = "",
        matched_rules: list = None,
    ):
        """Log input blocked by input guard."""
        self._write("input_block", {
            "user": user,
            "agent_id": agent_id,
            "input": input_summary[:200],
            "reason": reason,
            "matched_rules": matched_rules or [],
            "severity": "WARNING",
        })

    def log_evasion_detect(
        self,
        user: str,
        command: str,
        flags: list,
        agent_id: str = "",
    ):
        """Log shell evasion pattern detected."""
        self._write("evasion_detect", {
            "user": user,
            "agent_id": agent_id,
            "command": command[:200],
            "flags": flags,
            "severity": "WARNING",
        })

    def log_tool_execute(
        self,
        user: str,
        tool_name: str,
        action: str,
        level: str = "L0",
        duration_ms: float = 0,
        agent_id: str = "",
    ):
        """Log tool execution (success/fail)."""
        self._write("tool_execute", {
            "user": user,
            "agent_id": agent_id,
            "tool": tool_name,
            "action": action,
            "level": level,
            "duration_ms": round(duration_ms, 2),
            "severity": "INFO",
        })
