# -*- coding: utf-8 -*-
"""Tests for CoApis commercial security modules.

This test suite validates:
- Clock rollback detection
- License revocation management
- Renewal reminder system
- Online license validation
- Feature flag system
- License management integration

Usage:
    pytest tests/commercial/ -v
"""

from __future__ import annotations

import json
import os
import sys
import tempfile
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict

import pytest

# Add server directory to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from coapis.clock_protection import ClockProtection, ClockStatus
from coapis.license_revocation import LicenseRevocationManager, RevocationRecord
from coapis.renewal_reminder import (
    RenewalReminderManager,
    ReminderConfig,
    ReminderRecord,
    ReminderType,
)
from coapis.features import FeatureFlagsV2, LicenseTier, FeatureCategory
from coapis.license_manager import LicenseManager, LicenseState


# ═══════════════════════════════════════════════════════════
# Clock Protection Tests
# ═══════════════════════════════════════════════════════════


class TestClockProtection:
    """Test clock rollback detection and protection."""

    def setup_method(self):
        """Setup test fixtures."""
        self.temp_dir = tempfile.mkdtemp()
        self.protection = ClockProtection(
            storage_dir=self.temp_dir,
            grace_period=300.0,  # 5 minutes
        )

    def teardown_method(self):
        """Cleanup test fixtures."""
        import shutil

        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_initial_check(self):
        """Test initial clock check."""
        status = self.protection.check()

        assert status.is_valid is True
        assert status.warning == "Initial clock check"
        assert status.time_delta_seconds == 0.0

    def test_normal_time_progression(self):
        """Test normal time progression."""
        # First check
        status1 = self.protection.check()
        assert status1.is_valid is True

        # Wait a bit
        time.sleep(0.1)

        # Second check
        status2 = self.protection.check()
        assert status2.is_valid is True
        assert status2.time_delta_seconds > 0

    def test_minor_clock_adjustment(self):
        """Test minor clock adjustment within grace period."""
        # First check
        self.protection.check()

        # Simulate minor clock adjustment (within grace period)
        past_time = datetime.now() - timedelta(seconds=10)
        status = self.protection.check(past_time)

        assert status.is_valid is True
        assert status.time_delta_seconds < 0
        assert "Minor clock adjustment" in status.warning

    def test_clock_rollback_detection(self):
        """Test clock rollback detection beyond grace period."""
        # First check
        self.protection.check()

        # Simulate clock rollback beyond grace period
        past_time = datetime.now() - timedelta(hours=1)
        status = self.protection.check(past_time)

        assert status.is_valid is False
        assert status.time_delta_seconds < -300
        assert "Clock rollback detected" in status.warning

    def test_persistent_storage(self):
        """Test clock state persistence."""
        # First check
        self.protection.check()

        # Create new instance with same storage
        protection2 = ClockProtection(storage_dir=self.temp_dir)
        status = protection2.check()

        assert status.last_check_time is not None

    def test_status_dict(self):
        """Test status to_dict method."""
        status = self.protection.check()
        status_dict = status.to_dict()

        assert "is_valid" in status_dict
        assert "current_time" in status_dict
        assert "time_delta_seconds" in status_dict


# ═══════════════════════════════════════════════════════════
# License Revocation Tests
# ═══════════════════════════════════════════════════════════


class TestLicenseRevocation:
    """Test license revocation management."""

    def setup_method(self):
        """Setup test fixtures."""
        self.temp_dir = tempfile.mkdtemp()
        self.manager = LicenseRevocationManager(
            storage_dir=self.temp_dir,
            grace_period_hours=24.0,
        )

    def teardown_method(self):
        """Cleanup test fixtures."""
        import shutil

        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_revoke_license(self):
        """Test license revocation."""
        record = self.manager.revoke(
            license_id="test-license-1",
            reason="non-payment",
        )

        assert record.license_id == "test-license-1"
        assert record.reason == "non-payment"
        assert record.is_enforced() is False  # Within grace period

    def test_check_revocation(self):
        """Test revocation check."""
        # Revoke license
        self.manager.revoke("test-license-2", reason="violation")

        # Check revocation
        is_revoked = self.manager.is_revoked("test-license-2")
        assert is_revoked is False  # Within grace period

    def test_unrevoke_license(self):
        """Test license restoration."""
        # Revoke and restore
        self.manager.revoke("test-license-3", reason="test")
        success = self.manager.unrevoke("test-license-3", reason="mistake")

        assert success is True
        assert self.manager.is_revoked("test-license-3") is False

    def test_revocation_persistence(self):
        """Test revocation persistence."""
        # Revoke license
        self.manager.revoke("test-license-4", reason="test")

        # Create new manager with same storage
        manager2 = LicenseRevocationManager(storage_dir=self.temp_dir)

        # Check persistence
        record = manager2.get_revocation_record("test-license-4")
        assert record is not None
        assert record.license_id == "test-license-4"

    def test_status(self):
        """Test status method."""
        self.manager.revoke("test-license-5", reason="test")
        status = self.manager.get_status()

        assert status["total_revocations"] == 1
        assert "storage_file" in status


# ═══════════════════════════════════════════════════════════
# Renewal Reminder Tests
# ═══════════════════════════════════════════════════════════


class TestRenewalReminder:
    """Test renewal reminder system."""

    def setup_method(self):
        """Setup test fixtures."""
        self.temp_dir = tempfile.mkdtemp()
        self.config = ReminderConfig(
            initial_days=30,
            secondary_days=14,
            urgent_days=7,
            final_days=1,
        )
        self.manager = RenewalReminderManager(
            storage_dir=self.temp_dir,
            config=self.config,
        )

    def teardown_method(self):
        """Cleanup test fixtures."""
        import shutil

        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_check_reminders_30_days(self):
        """Test reminder check for 30 days until expiry."""
        expires_at = datetime.now() + timedelta(days=30)
        reminders = self.manager.check_reminders(
            license_id="test-license",
            expires_at=expires_at,
            customer_name="Test Customer",
        )

        assert len(reminders) == 1
        assert reminders[0].reminder_type == ReminderType.INITIAL

    def test_check_reminders_14_days(self):
        """Test reminder check for 14 days until expiry."""
        expires_at = datetime.now() + timedelta(days=14)
        reminders = self.manager.check_reminders(
            license_id="test-license",
            expires_at=expires_at,
            customer_name="Test Customer",
        )

        assert len(reminders) == 1
        assert reminders[0].reminder_type == ReminderType.SECONDARY

    def test_check_reminders_7_days(self):
        """Test reminder check for 7 days until expiry."""
        expires_at = datetime.now() + timedelta(days=7)
        reminders = self.manager.check_reminders(
            license_id="test-license",
            expires_at=expires_at,
            customer_name="Test Customer",
        )

        assert len(reminders) == 1
        assert reminders[0].reminder_type == ReminderType.URGENT

    def test_check_reminders_expired(self):
        """Test reminder check for expired license."""
        expires_at = datetime.now() - timedelta(hours=1)
        reminders = self.manager.check_reminders(
            license_id="test-license",
            expires_at=expires_at,
            customer_name="Test Customer",
        )

        assert len(reminders) == 1
        assert reminders[0].reminder_type == ReminderType.EXPIRED

    def test_no_reminders_past_grace(self):
        """Test no reminders after grace period."""
        expires_at = datetime.now() - timedelta(days=10)
        reminders = self.manager.check_reminders(
            license_id="test-license",
            expires_at=expires_at,
            customer_name="Test Customer",
        )

        assert len(reminders) == 0

    def test_reminder_history(self):
        """Test reminder history tracking."""
        expires_at = datetime.now() + timedelta(days=30)
        reminders = self.manager.check_reminders(
            license_id="test-license",
            expires_at=expires_at,
            customer_name="Test Customer",
        )

        # Send reminder
        if reminders:
            import asyncio

            asyncio.run(self.manager.send_reminder(reminders[0]))

        # Check history
        history = self.manager.get_reminder_history("test-license")
        assert len(history) == 1


# ═══════════════════════════════════════════════════════════
# Feature Flags Tests
# ═══════════════════════════════════════════════════════════


class TestFeatureFlags:
    """Test feature flag system."""

    def test_community_tier(self):
        """Test community tier features."""
        flags = FeatureFlagsV2()
        flags._state = LicenseState(
            is_valid=True,
            tier=LicenseTier.COMMUNITY,
        )
        flags._initialized = True

        # Core features should be available
        assert flags.has_feature("auth") is True

        # Enterprise features should not be available
        assert flags.has_feature("clustering") is False

    def test_starter_tier(self):
        """Test starter tier features."""
        flags = FeatureFlagsV2()
        flags._state = LicenseState(
            is_valid=True,
            tier=LicenseTier.STARTER,
        )
        flags._initialized = True

        # Core and basic enterprise features should be available
        assert flags.has_feature("auth") is True
        assert flags.has_feature("monitoring") is True

        # Advanced features should not be available
        assert flags.has_feature("clustering") is False

    def test_professional_tier(self):
        """Test professional tier features."""
        flags = FeatureFlagsV2()
        flags._state = LicenseState(
            is_valid=True,
            tier=LicenseTier.PROFESSIONAL,
        )
        flags._initialized = True

        # Core, basic, and advanced features should be available
        assert flags.has_feature("auth") is True
        assert flags.has_feature("monitoring") is True
        assert flags.has_feature("clustering") is True

        # Premium features should not be available
        assert flags.has_feature("skill_market") is False

    def test_enterprise_tier(self):
        """Test enterprise tier features."""
        flags = FeatureFlagsV2()
        flags._state = LicenseState(
            is_valid=True,
            tier=LicenseTier.ENTERPRISE,
        )
        flags._initialized = True

        # All features should be available
        assert flags.has_feature("auth") is True
        assert flags.has_feature("monitoring") is True
        assert flags.has_feature("clustering") is True
        assert flags.has_feature("skill_market") is True


# ═══════════════════════════════════════════════════════════
# License Manager Integration Tests
# ═══════════════════════════════════════════════════════════


class TestLicenseManagerIntegration:
    """Test license manager integration with security modules."""

    def test_security_modules_initialization(self):
        """Test security modules initialization."""
        manager = LicenseManager()

        # Initialize with dummy URL (won't actually connect)
        manager.init_security_modules(
            online_validation_url="",
            online_validation_interval=24.0,
            clock_grace_period=300.0,
            revocation_grace_period=24.0,
        )

        # Check modules are initialized
        clock_status = manager.get_clock_protection_status()
        assert clock_status["initialized"] is True

        revocation_status = manager.get_revocation_status()
        assert revocation_status["initialized"] is True

        renewal_status = manager.get_renewal_reminders_status()
        assert renewal_status["initialized"] is True

    def test_license_revocation_flow(self):
        """Test license revocation flow."""
        manager = LicenseManager()
        manager.init_security_modules()

        # Revoke license
        success = manager.revoke_license("test-license", reason="test")
        assert success is True

        # Check revocation
        is_revoked = manager.check_license_revocation("test-license")
        assert is_revoked is False  # Within grace period

        # Restore license
        success = manager.unrevoke_license("test-license", reason="mistake")
        assert success is True

    def test_clock_check(self):
        """Test clock check method."""
        manager = LicenseManager()
        manager.init_security_modules()

        # Check clock
        clock_status = manager.check_clock()
        assert clock_status["is_valid"] is True
        assert "current_time" in clock_status


# ═══════════════════════════════════════════════════════════
# Run Tests
# ═══════════════════════════════════════════════════════════

if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])
