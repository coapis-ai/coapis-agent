"""Tool call monitoring and anomaly detection."""

import time
import logging
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Dict, List, Optional

logger = logging.getLogger(__name__)


@dataclass
class ToolCallRecord:
    user_id: str
    tool_name: str
    args_summary: str
    timestamp: float
    success: bool
    duration_ms: float


@dataclass
class Alert:
    user_id: str
    alert_type: str
    message: str
    timestamp: float
    severity: str = "warning"  # warning, critical


class ToolCallMonitor:
    """Monitor tool calls and detect anomalous behavior.

    Features:
    - Per-user call frequency tracking
    - Dangerous tool combination detection
    - High failure rate detection
    - Output statistics
    """

    def __init__(self, max_records_per_user: int = 1000):
        self.records: Dict[str, List[ToolCallRecord]] = defaultdict(list)
        self.max_records = max_records_per_user
        self.alerts: List[Alert] = []

    def record_call(self, record: ToolCallRecord):
        """Record a tool call and check for anomalies."""
        user_records = self.records[record.user_id]
        user_records.append(record)

        # Trim old records
        if len(user_records) > self.max_records:
            self.records[record.user_id] = user_records[-self.max_records:]

        # Run anomaly detection
        self._check_anomaly(record)

    def _check_anomaly(self, record: ToolCallRecord):
        """Check for anomalous patterns."""
        user_records = self.records[record.user_id]
        now = time.time()

        # 1. High frequency detection (100+ calls in 1 minute)
        recent = [r for r in user_records if now - r.timestamp < 60]
        if len(recent) > 100:
            self._add_alert(
                record.user_id,
                "high_frequency",
                f"High frequency: {len(recent)} calls/min",
                "warning",
            )

        # 2. Suspicious shell usage
        recent_tools = [r.tool_name for r in recent]
        shell_count = recent_tools.count("execute_shell_command")
        if shell_count > 20:
            self._add_alert(
                record.user_id,
                "shell_heavy",
                f"Heavy shell usage: {shell_count} calls/min",
                "warning",
            )

        # 3. High failure rate
        recent_failures = [r for r in recent if not r.success]
        if len(recent_failures) > 10 and len(recent) > 20:
            failure_rate = len(recent_failures) / len(recent)
            self._add_alert(
                record.user_id,
                "high_failure_rate",
                f"Failure rate: {failure_rate:.0%} ({len(recent_failures)}/{len(recent)})",
                "warning",
            )

        # 4. Very long execution
        if record.duration_ms > 30000:  # 30 seconds
            self._add_alert(
                record.user_id,
                "slow_execution",
                f"Slow tool: {record.tool_name} took {record.duration_ms:.0f}ms",
                "warning",
            )

    def _add_alert(
        self,
        user_id: str,
        alert_type: str,
        message: str,
        severity: str,
    ):
        """Add an alert (deduplicate within 5 minutes)."""
        now = time.time()
        # Check for duplicate alert within 5 minutes
        for existing in self.alerts:
            if (
                existing.user_id == user_id
                and existing.alert_type == alert_type
                and now - existing.timestamp < 300
            ):
                return

        alert = Alert(
            user_id=user_id,
            alert_type=alert_type,
            message=message,
            timestamp=now,
            severity=severity,
        )
        self.alerts.append(alert)
        logger.warning("Security alert [%s] for user %s: %s", severity, user_id, message)

        # Keep only last 1000 alerts
        if len(self.alerts) > 1000:
            self.alerts = self.alerts[-1000:]

    def get_user_stats(self, user_id: str) -> Dict[str, any]:
        """Get tool usage statistics for a user."""
        records = self.records.get(user_id, [])
        if not records:
            return {"total_calls": 0, "tool_distribution": {}, "recent_alerts": []}

        tool_counts: Dict[str, int] = defaultdict(int)
        total_duration = 0.0
        successes = 0
        for r in records:
            tool_counts[r.tool_name] += 1
            total_duration += r.duration_ms
            if r.success:
                successes += 1

        recent_alerts = [
            {
                "type": a.alert_type,
                "message": a.message,
                "severity": a.severity,
                "timestamp": a.timestamp,
            }
            for a in self.alerts
            if a.user_id == user_id
        ][-5:]

        return {
            "total_calls": len(records),
            "tool_distribution": dict(tool_counts),
            "success_rate": successes / len(records) if records else 0,
            "avg_duration_ms": total_duration / len(records) if records else 0,
            "recent_alerts": recent_alerts,
        }

    def get_global_stats(self) -> Dict[str, any]:
        """Get global monitoring statistics."""
        total_calls = sum(len(r) for r in self.records.values())
        total_alerts = len(self.alerts)
        active_users = len(self.records)

        return {
            "total_calls": total_calls,
            "total_alerts": total_alerts,
            "active_users": active_users,
            "recent_critical": [
                {
                    "user": a.user_id,
                    "type": a.alert_type,
                    "message": a.message,
                }
                for a in self.alerts
                if a.severity == "critical"
            ][-10:],
        }
