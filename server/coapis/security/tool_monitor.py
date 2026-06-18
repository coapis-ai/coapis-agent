"""Tool call monitoring and anomaly detection with blocking support."""

import time
import logging
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

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
        # Blocking state: user_id → unblock_timestamp
        self._blocked_users: Dict[str, float] = {}
        # Track last block time per user to avoid re-blocking on old alerts
        self._last_block_time: Dict[str, float] = {}
        self._block_duration = 300  # 5 minutes
        self._cooldown_after_unblock = 60  # 60s grace after block expires
        # Separate anomaly counters (NOT subject to alert dedup)
        # These track raw anomaly events for blocking decisions.
        # Key: user_id, Value: list of (timestamp, severity) tuples
        self._anomaly_events: Dict[str, List[tuple]] = defaultdict(list)
        # Thresholds for auto-blocking (based on _anomaly_events, not alerts)
        self._critical_block_threshold = 3   # 3 critical events → block
        self._total_anomaly_block_threshold = 8  # 8 total anomalies → block

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

        # Track raw anomaly event for blocking decisions (not deduplicated)
        self._anomaly_events[user_id].append((now, severity))
        # Trim old events (keep last 10 minutes)
        self._anomaly_events[user_id] = [
            (ts, sev) for ts, sev in self._anomaly_events[user_id]
            if now - ts < 600
        ]

    def should_block(self, user_id: str) -> Tuple[bool, str]:
        """Check if a user should be blocked from executing tool calls.

        Blocking rules (auto-unblock after _block_duration seconds):
        - 3+ critical alerts in recent window → block
        - 5+ high_frequency alerts → block
        - 5+ shell_heavy alerts → block

        Returns:
            (blocked, reason) tuple
        """
        now = time.time()

        # Check if already blocked and not yet expired
        unblock_at = self._blocked_users.get(user_id, 0)
        if unblock_at > now:
            remaining = int(unblock_at - now)
            return True, f"用户被临时封禁，剩余 {remaining}s 自动解封"

        # Expired block → enter cooldown to avoid re-blocking on old alerts
        if unblock_at > 0:
            self._blocked_users.pop(user_id, None)
            self._last_block_time[user_id] = now
            logger.info(
                "User %s block expired, entering %ds cooldown",
                user_id, self._cooldown_after_unblock,
            )

        # Cooldown: after unblock, give grace period before re-evaluating
        last_block = self._last_block_time.get(user_id, 0)
        if last_block > 0 and now - last_block < self._cooldown_after_unblock:
            return False, ""

        # Count from raw anomaly events (not subject to alert dedup)
        recent_events = [
            (ts, sev) for ts, sev in self._anomaly_events.get(user_id, [])
            if now - ts < 300  # last 5 minutes
        ]

        critical_count = sum(1 for _, sev in recent_events if sev == "critical")
        total_count = len(recent_events)

        if critical_count >= self._critical_block_threshold:
            reason = f"安全告警过多: {critical_count}次critical级告警(阈值{self._critical_block_threshold})"
            self._blocked_users[user_id] = now + self._block_duration
            logger.warning("Blocking user %s: %s", user_id, reason)
            return True, reason

        if total_count >= self._total_anomaly_block_threshold:
            reason = f"异常行为累积: {total_count}次异常事件(阈值{self._total_anomaly_block_threshold})"
            self._blocked_users[user_id] = now + self._block_duration
            logger.warning("Blocking user %s: %s", user_id, reason)
            return True, reason

        return False, ""

    def unblock_user(self, user_id: str) -> bool:
        """Manually unblock a user. Returns True if was blocked."""
        if user_id in self._blocked_users:
            self._blocked_users.pop(user_id)
            logger.info("Manually unblocked user %s", user_id)
            return True
        return False

    def is_blocked(self, user_id: str) -> bool:
        """Quick check if user is currently blocked."""
        unblock_at = self._blocked_users.get(user_id, 0)
        if unblock_at > time.time():
            return True
        if unblock_at > 0:
            self._blocked_users.pop(user_id, None)
        return False

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


# ---------------------------------------------------------------------------
# Lazy singleton
# ---------------------------------------------------------------------------

_monitor_instance: Optional[ToolCallMonitor] = None


def get_tool_call_monitor() -> ToolCallMonitor:
    """Return the global ToolCallMonitor singleton."""
    global _monitor_instance
    if _monitor_instance is None:
        _monitor_instance = ToolCallMonitor()
    return _monitor_instance
