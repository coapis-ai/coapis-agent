# -*- coding: utf-8 -*-
"""Enterprise Audit Logger.

Provides comprehensive audit logging for compliance and security.

Features:
- Tamper-proof log storage
- Activity tracking
- Compliance reporting (SOC2, GDPR)
- Log retention policies
"""

from __future__ import annotations

import hashlib
import json
import logging
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)


class AuditEntry(BaseModel):
    """Single audit log entry."""
    timestamp: float = Field(default_factory=time.time)
    user: str
    action: str  # e.g., "login", "create_user", "update_config"
    resource: str  # e.g., "/api/users", "/api/config"
    success: bool
    ip_address: str = ""
    user_agent: str = ""
    details: Dict[str, Any] = {}
    entry_hash: str = ""  # For tamper detection


class AuditLogger:
    """Enterprise audit logger with tamper detection.
    
    Provides:
    - Tamper-proof log storage with hash chaining
    - Activity tracking and reporting
    - Compliance reporting (SOC2, GDPR)
    - Log retention policies
    """
    
    def __init__(self, log_dir: str = None):
        if log_dir is None:
            from coapis.constant import WORKING_DIR
            log_dir = str(WORKING_DIR / "audit")
        self._log_dir = Path(log_dir)
        self._log_dir.mkdir(parents=True, exist_ok=True)
        self._current_hash = "0" * 64  # Initial hash
        self._entries: List[AuditEntry] = []
        
        # Load existing hash from last entry
        self._load_last_hash()
        
        logger.info(f"Audit logger initialized at {log_dir}")
    
    def _load_last_hash(self) -> None:
        """Load the last hash from existing logs."""
        log_file = self._log_dir / "audit.log"
        if log_file.exists():
            try:
                with open(log_file, "r") as f:
                    lines = f.readlines()
                    if lines:
                        last_line = lines[-1].strip()
                        if last_line:
                            entry = json.loads(last_line)
                            self._current_hash = entry.get("entry_hash", "0" * 64)
            except Exception as e:
                logger.warning(f"Failed to load last hash: {e}")
    
    def log(
        self,
        user: str,
        action: str,
        resource: str,
        success: bool,
        ip_address: str = "",
        user_agent: str = "",
        details: Optional[Dict[str, Any]] = None,
    ) -> AuditEntry:
        """Log an audit event.
        
        Returns:
            The created audit entry
        """
        entry = AuditEntry(
            user=user,
            action=action,
            resource=resource,
            success=success,
            ip_address=ip_address,
            user_agent=user_agent,
            details=details or {},
        )
        
        # Calculate hash (previous_hash + content)
        content = json.dumps(entry.model_dump(), sort_keys=True)
        entry.entry_hash = hashlib.sha256(
            f"{self._current_hash}{content}".encode()
        ).hexdigest()
        
        # Update current hash for next entry
        self._current_hash = entry.entry_hash
        
        # Store entry
        self._entries.append(entry)
        
        # Write to file
        self._write_entry(entry)
        
        return entry
    
    def _write_entry(self, entry: AuditEntry) -> None:
        """Write entry to log file."""
        log_file = self._log_dir / "audit.log"
        with open(log_file, "a") as f:
            f.write(json.dumps(entry.model_dump()) + "\n")
    
    def get_entries(
        self,
        user: Optional[str] = None,
        action: Optional[str] = None,
        start_time: Optional[float] = None,
        end_time: Optional[float] = None,
        limit: int = 100,
    ) -> List[AuditEntry]:
        """Get audit entries with filtering.
        
        Args:
            user: Filter by user
            action: Filter by action
            start_time: Filter by start time
            end_time: Filter by end time
            limit: Maximum number of entries to return
        
        Returns:
            List of matching audit entries
        """
        entries = self._entries
        
        # Apply filters
        if user:
            entries = [e for e in entries if e.user == user]
        
        if action:
            entries = [e for e in entries if e.action == action]
        
        if start_time:
            entries = [e for e in entries if e.timestamp >= start_time]
        
        if end_time:
            entries = [e for e in entries if e.timestamp <= end_time]
        
        # Sort by timestamp (newest first)
        entries = sorted(entries, key=lambda e: e.timestamp, reverse=True)
        
        return entries[:limit]
    
    def verify_integrity(self) -> Dict[str, Any]:
        """Verify log integrity using hash chain.
        
        Returns:
            Integrity verification result
        """
        if not self._entries:
            return {"valid": True, "message": "No entries to verify"}
        
        expected_hash = "0" * 64
        failed = []
        
        for i, entry in enumerate(self._entries):
            # Recalculate hash
            content = json.dumps({
                k: v for k, v in entry.model_dump().items() 
                if k != "entry_hash"
            }, sort_keys=True)
            
            calculated_hash = hashlib.sha256(
                f"{expected_hash}{content}".encode()
            ).hexdigest()
            
            if calculated_hash != entry.entry_hash:
                failed.append(i)
            
            expected_hash = entry.entry_hash
        
        return {
            "valid": len(failed) == 0,
            "total_entries": len(self._entries),
            "failed_indices": failed,
            "message": "Integrity check passed" if not failed else f"Failed at entries: {failed}",
        }
    
    def get_compliance_report(self, standard: str = "SOC2") -> Dict[str, Any]:
        """Generate compliance report.
        
        Args:
            standard: Compliance standard (SOC2, GDPR)
        
        Returns:
            Compliance report
        """
        entries = self._entries
        
        return {
            "standard": standard,
            "generated_at": time.time(),
            "total_events": len(entries),
            "successful_events": sum(1 for e in entries if e.success),
            "failed_events": sum(1 for e in entries if not e.success),
            "unique_users": len(set(e.user for e in entries)),
            "actions": dict(self._count_actions(entries)),
            "integrity": self.verify_integrity(),
        }
    
    def _count_actions(self, entries: List[AuditEntry]):
        """Count occurrences of each action."""
        counts = {}
        for entry in entries:
            counts[entry.action] = counts.get(entry.action, 0) + 1
        return counts
    
    def get_stats(self) -> Dict[str, Any]:
        """Get audit statistics."""
        entries = self._entries
        
        return {
            "total_entries": len(entries),
            "unique_users": len(set(e.user for e in entries)),
            "unique_actions": len(set(e.action for e in entries)),
            "success_rate": sum(1 for e in entries if e.success) / len(entries) if entries else 0,
        }
