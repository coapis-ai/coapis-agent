# -*- coding: utf-8 -*-
"""Clock protection for CoApis license validation.

Detects and prevents clock rollback attacks that could extend
license validity beyond expiration.

Features:
- Persistent timestamp storage
- Clock skew detection
- Grace period for minor adjustments
- Tamper detection

Usage:
    from coapis.clock_protection import ClockProtection

    protection = ClockProtection()

    # Check current time
    if protection.check():
        print("Clock is valid")
    else:
        print("Clock rollback detected!")
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import time
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)


@dataclass
class ClockStatus:
    is_valid: bool
    current_time: datetime
    last_check_time: Optional[datetime]
    time_delta_seconds: float
    warning: str = ""

    def to_dict(self) -> dict:
        return {
            "is_valid": self.is_valid,
            "current_time": self.current_time.isoformat(),
            "last_check_time": self.last_check_time.isoformat() if self.last_check_time else None,
            "time_delta_seconds": self.time_delta_seconds,
            "warning": self.warning,
        }


class ClockProtection:
    """Detect and prevent clock rollback attacks."""

    # Default grace period for minor clock adjustments (in seconds)
    DEFAULT_GRACE_PERIOD = 300  # 5 minutes

    def __init__(
        self,
        storage_dir: Optional[str] = None,
        grace_period: float = DEFAULT_GRACE_PERIOD,
    ):
        self.storage_dir = storage_dir or os.path.join(
            os.path.expanduser("~"), ".coapis", "security"
        )
        self.grace_period = grace_period
        self._storage_file = os.path.join(self.storage_dir, "clock_state.json")
        self._last_check_time: Optional[float] = None
        self._checksum_file = os.path.join(self.storage_dir, "clock_checksum")

        # Ensure storage directory exists
        os.makedirs(self.storage_dir, exist_ok=True)

        # Load state
        self._load_state()

    def _load_state(self) -> None:
        """Load clock state from storage."""
        if os.path.exists(self._storage_file):
            try:
                with open(self._storage_file, "r") as f:
                    data = json.load(f)
                self._last_check_time = data.get("last_check_time")
            except Exception as e:
                logger.warning(f"Failed to load clock state: {e}")

    def _save_state(self) -> None:
        """Save clock state to storage."""
        try:
            data = {"last_check_time": self._last_check_time}
            with open(self._storage_file, "w") as f:
                json.dump(data, f, indent=2)

            # Save checksum for tamper detection
            checksum = self._calculate_checksum()
            with open(self._checksum_file, "w") as f:
                f.write(checksum)
        except Exception as e:
            logger.warning(f"Failed to save clock state: {e}")

    def _calculate_checksum(self) -> str:
        """Calculate checksum for tamper detection."""
        if os.path.exists(self._storage_file):
            with open(self._storage_file, "rb") as f:
                content = f.read()
            return hashlib.sha256(content).hexdigest()
        return ""

    def _verify_checksum(self) -> bool:
        """Verify checksum to detect tampering."""
        if not os.path.exists(self._checksum_file):
            return True  # No previous checksum

        try:
            with open(self._checksum_file, "r") as f:
                stored_checksum = f.read().strip()

            current_checksum = self._calculate_checksum()
            return stored_checksum == current_checksum
        except Exception as e:
            logger.warning(f"Checksum verification failed: {e}")
            return False

    def check(self, current_time: Optional[datetime] = None) -> ClockStatus:
        """
        Check if clock has been rolled back.

        Args:
            current_time: Current time (defaults to now)

        Returns:
            ClockStatus with validation result
        """
        if current_time is None:
            current_time = datetime.now()

        current_timestamp = current_time.timestamp()
        last_check = self._last_check_time

        if last_check is None:
            # First time check - just record the time
            self._last_check_time = current_timestamp
            self._save_state()

            return ClockStatus(
                is_valid=True,
                current_time=current_time,
                last_check_time=None,
                time_delta_seconds=0.0,
                warning="Initial clock check",
            )

        # Calculate time delta
        time_delta = current_timestamp - last_check

        # Check for clock rollback
        if time_delta < -self.grace_period:
            # Clock was rolled back beyond grace period
            logger.warning(
                f"Clock rollback detected! Delta: {time_delta:.0f}s "
                f"(grace period: {self.grace_period:.0f}s)"
            )

            return ClockStatus(
                is_valid=False,
                current_time=current_time,
                last_check_time=datetime.fromtimestamp(last_check),
                time_delta_seconds=time_delta,
                warning=f"Clock rollback detected ({time_delta:.0f}s)",
            )
        elif time_delta < 0:
            # Minor clock adjustment within grace period
            logger.info(f"Minor clock adjustment detected: {time_delta:.0f}s")

            # Update last check time
            self._last_check_time = current_timestamp
            self._save_state()

            return ClockStatus(
                is_valid=True,
                current_time=current_time,
                last_check_time=datetime.fromtimestamp(last_check),
                time_delta_seconds=time_delta,
                warning=f"Minor clock adjustment ({time_delta:.0f}s)",
            )
        else:
            # Normal time progression
            self._last_check_time = current_timestamp
            self._save_state()

            return ClockStatus(
                is_valid=True,
                current_time=current_time,
                last_check_time=datetime.fromtimestamp(last_check),
                time_delta_seconds=time_delta,
                warning="",
            )

    def get_status(self) -> dict:
        """Get clock protection status."""
        status = self.check()
        return {
            "clock_status": status.to_dict(),
            "grace_period": self.grace_period,
            "storage_file": self._storage_file,
            "checksum_valid": self._verify_checksum(),
        }

    def reset(self) -> None:
        """Reset clock protection state (for testing or reinstallation)."""
        self._last_check_time = None
        self._save_state()
        logger.info("Clock protection state reset")


# Global instance
_protection: Optional[ClockProtection] = None


def get_protection() -> Optional[ClockProtection]:
    """Get global clock protection instance."""
    return _protection


def init_protection(grace_period: float = ClockProtection.DEFAULT_GRACE_PERIOD) -> ClockProtection:
    """Initialize global clock protection."""
    global _protection
    _protection = ClockProtection(grace_period=grace_period)
    return _protection


def shutdown_protection() -> None:
    """Shutdown global clock protection."""
    global _protection
    _protection = None
