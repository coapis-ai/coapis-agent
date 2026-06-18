# -*- coding: utf-8 -*-
"""License renewal reminder system for CoApis.

Provides automated renewal reminders with:
- Configurable reminder schedule
- Multiple notification channels (email, in-app, webhook)
- Reminder history tracking
- Grace period management

Usage:
    from coapis.renewal_reminder import RenewalReminderManager

    manager = RenewalReminderManager()

    # Check for upcoming renewals
    reminders = manager.check_reminders()

    # Send reminders
    for reminder in reminders:
        manager.send_reminder(reminder)
"""

from __future__ import annotations

import json
import logging
import os
import time
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from enum import Enum
from typing import Any, Callable, Dict, List, Optional

logger = logging.getLogger(__name__)


class ReminderChannel(str, Enum):
    EMAIL = "email"
    IN_APP = "in_app"
    WEBHOOK = "webhook"
    DINGTALK = "dingtalk"
    WECOM = "wecom"


class ReminderType(str, Enum):
    INITIAL = "initial"        # 30 days before
    SECONDARY = "secondary"    # 14 days before
    URGENT = "urgent"          # 7 days before
    FINAL = "final"            # 1 day before
    EXPIRED = "expired"        # After expiration
    GRACE = "grace"            # During grace period


@dataclass
class ReminderRecord:
    license_id: str
    customer_name: str
    reminder_type: ReminderType
    days_until_expiry: int
    sent_at: datetime
    channel: ReminderChannel
    status: str = "pending"  # pending, sent, failed
    message: str = ""
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "license_id": self.license_id,
            "customer_name": self.customer_name,
            "reminder_type": self.reminder_type.value,
            "days_until_expiry": self.days_until_expiry,
            "sent_at": self.sent_at.isoformat(),
            "channel": self.channel.value,
            "status": self.status,
            "message": self.message,
            "metadata": self.metadata,
        }


@dataclass
class ReminderConfig:
    """Configuration for reminder schedule."""
    initial_days: int = 30
    secondary_days: int = 14
    urgent_days: int = 7
    final_days: int = 1
    expired_hours: int = 24
    grace_period_days: int = 7

    channels: List[ReminderChannel] = field(
        default_factory=lambda: [ReminderChannel.EMAIL, ReminderChannel.IN_APP]
    )

    email_template: str = "default"
    webhook_url: Optional[str] = None


class RenewalReminderManager:
    """Manage license renewal reminders."""

    def __init__(
        self,
        storage_dir: Optional[str] = None,
        config: Optional[ReminderConfig] = None,
    ):
        self.storage_dir = storage_dir or os.path.join(
            os.path.expanduser("~"), ".coapis", "reminders"
        )
        self.config = config or ReminderConfig()
        self._storage_file = os.path.join(self.storage_dir, "reminders.json")
        self._sent_reminders: Dict[str, List[ReminderRecord]] = {}
        self._handlers: Dict[ReminderChannel, Callable] = {}

        # Ensure storage directory exists
        os.makedirs(self.storage_dir, exist_ok=True)

        # Load existing reminders
        self._load_reminders()

    def _load_reminders(self) -> None:
        """Load reminder history from storage."""
        if os.path.exists(self._storage_file):
            try:
                with open(self._storage_file, "r") as f:
                    data = json.load(f)

                for license_id, records in data.items():
                    self._sent_reminders[license_id] = [
                        ReminderRecord(**r) for r in records
                    ]
            except Exception as e:
                logger.warning(f"Failed to load reminders: {e}")

    def _save_reminders(self) -> None:
        """Save reminder history to storage."""
        try:
            data = {}
            for license_id, records in self._sent_reminders.items():
                data[license_id] = [r.to_dict() for r in records]

            with open(self._storage_file, "w") as f:
                json.dump(data, f, indent=2)
        except Exception as e:
            logger.error(f"Failed to save reminders: {e}")

    def register_handler(self, channel: ReminderChannel, handler: Callable) -> None:
        """Register a handler for a notification channel."""
        self._handlers[channel] = handler

    def check_reminders(
        self,
        license_id: str,
        expires_at: datetime,
        customer_name: str = "",
    ) -> List[ReminderRecord]:
        """
        Check what reminders need to be sent.

        Args:
            license_id: License ID
            expires_at: License expiration time
            customer_name: Customer name for personalization

        Returns:
            List of ReminderRecord that need to be sent
        """
        now = datetime.now()
        days_until = (expires_at - now).days
        hours_until = (expires_at - now).total_seconds() / 3600

        reminders = []

        # Determine which reminders are due
        if days_until <= -self.config.grace_period_days:
            # Already past grace period - no more reminders
            return reminders

        if days_until < 0 and hours_until > -self.config.expired_hours:
            # Just expired
            reminders.append(self._create_reminder(
                license_id, customer_name, ReminderType.EXPIRED, 0
            ))
        elif days_until == 0:
            # Expires today
            reminders.append(self._create_reminder(
                license_id, customer_name, ReminderType.FINAL, 0
            ))
        elif days_until <= self.config.urgent_days:
            # Urgent reminder
            reminders.append(self._create_reminder(
                license_id, customer_name, ReminderType.URGENT, days_until
            ))
        elif days_until <= self.config.secondary_days:
            # Secondary reminder
            reminders.append(self._create_reminder(
                license_id, customer_name, ReminderType.SECONDARY, days_until
            ))
        elif days_until <= self.config.initial_days:
            # Initial reminder
            reminders.append(self._create_reminder(
                license_id, customer_name, ReminderType.INITIAL, days_until
            ))

        # Filter out already sent reminders
        already_sent = self._get_sent_types(license_id)
        reminders = [r for r in reminders if r.reminder_type not in already_sent]

        return reminders

    def _create_reminder(
        self,
        license_id: str,
        customer_name: str,
        reminder_type: ReminderType,
        days_until: int,
    ) -> ReminderRecord:
        """Create a reminder record."""
        messages = {
            ReminderType.INITIAL: f"您的许可证将在 {days_until} 天后到期，请及时续费。",
            ReminderType.SECONDARY: f"您的许可证将在 {days_until} 天后到期，请尽快续费。",
            ReminderType.URGENT: f"您的许可证将在 {days_until} 天后到期，请立即续费。",
            ReminderType.FINAL: "您的许可证今天到期，请立即续费以避免服务中断。",
            ReminderType.EXPIRED: "您的许可证已到期，请尽快续费以恢复服务。",
            ReminderType.GRACE: "您的许可证已进入宽限期，请尽快续费。",
        }

        return ReminderRecord(
            license_id=license_id,
            customer_name=customer_name,
            reminder_type=reminder_type,
            days_until_expiry=days_until,
            sent_at=datetime.now(),
            channel=self.config.channels[0] if self.config.channels else ReminderChannel.IN_APP,
            message=messages.get(reminder_type, ""),
        )

    def _get_sent_types(self, license_id: str) -> List[ReminderType]:
        """Get list of already sent reminder types for a license."""
        if license_id not in self._sent_reminders:
            return []

        return [r.reminder_type for r in self._sent_reminders[license_id] if r.status == "sent"]

    async def send_reminder(self, reminder: ReminderRecord) -> bool:
        """
        Send a reminder through configured channels.

        Args:
            reminder: ReminderRecord to send

        Returns:
            True if sent successfully
        """
        success = False

        for channel in self.config.channels:
            try:
                if channel in self._handlers:
                    handler = self._handlers[channel]
                    result = handler(reminder)

                    # Handle async handlers
                    if hasattr(result, "__await__"):
                        result = await result

                    if result:
                        reminder.status = "sent"
                        success = True
                    else:
                        reminder.status = "failed"
                else:
                    # Default handler - just log
                    logger.info(f"Reminder sent via {channel.value}: {reminder.message}")
                    reminder.status = "sent"
                    success = True

            except Exception as e:
                logger.error(f"Failed to send reminder via {channel.value}: {e}")
                reminder.status = "failed"

        # Record the reminder
        if reminder.license_id not in self._sent_reminders:
            self._sent_reminders[reminder.license_id] = []

        self._sent_reminders[reminder.license_id].append(reminder)
        self._save_reminders()

        return success

    def get_reminder_history(
        self,
        license_id: Optional[str] = None,
        limit: int = 50,
    ) -> List[ReminderRecord]:
        """
        Get reminder history.

        Args:
            license_id: Filter by license ID (None for all)
            limit: Maximum number of records to return

        Returns:
            List of ReminderRecord
        """
        if license_id:
            return self._sent_reminders.get(license_id, [])[:limit]

        # Get all reminders
        all_reminders = []
        for records in self._sent_reminders.values():
            all_reminders.extend(records)

        # Sort by sent_at descending
        all_reminders.sort(key=lambda r: r.sent_at, reverse=True)

        return all_reminders[:limit]

    def get_status(self) -> Dict[str, Any]:
        """Get reminder manager status."""
        return {
            "total_reminders_sent": sum(
                len(r) for r in self._sent_reminders.values()
            ),
            "unique_licenses": len(self._sent_reminders),
            "config": {
                "initial_days": self.config.initial_days,
                "secondary_days": self.config.secondary_days,
                "urgent_days": self.config.urgent_days,
                "final_days": self.config.final_days,
                "channels": [c.value for c in self.config.channels],
            },
            "storage_file": self._storage_file,
        }


# Global instance
_manager: Optional[RenewalReminderManager] = None


def get_manager() -> Optional[RenewalReminderManager]:
    """Get global renewal reminder manager instance."""
    return _manager


def init_manager(
    config: Optional[ReminderConfig] = None,
) -> RenewalReminderManager:
    """Initialize global renewal reminder manager."""
    global _manager
    _manager = RenewalReminderManager(config=config)
    return _manager


def shutdown_manager() -> None:
    """Shutdown global renewal reminder manager."""
    global _manager
    _manager = None
