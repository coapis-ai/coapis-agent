# -*- coding: utf-8 -*-
"""License revocation system for CoApis.

Provides license revocation management with:
- Local revocation list
- Online revocation check
- Revocation reasons tracking
- Grace period before enforcement

Usage:
    from coapis.license_revocation import LicenseRevocationManager

    manager = LicenseRevocationManager()

    # Revoke a license
    manager.revoke("license-id", reason="non-payment")

    # Check if license is revoked
    if manager.is_revoked("license-id"):
        print("License has been revoked")
"""

from __future__ import annotations

import json
import logging
import os
import time
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


@dataclass
class RevocationRecord:
    license_id: str
    revoked_at: datetime
    reason: str
    enforced_at: Optional[datetime] = None
    grace_period_hours: float = 24.0
    metadata: Dict[str, Any] = field(default_factory=dict)

    def is_enforced(self) -> bool:
        """Check if revocation has been enforced (grace period expired)."""
        if self.enforced_at:
            return True

        if self.revoked_at is None:
            return False

        grace_end = self.revoked_at + __import__("datetime").timedelta(hours=self.grace_period_hours)
        return datetime.now() > grace_end

    def to_dict(self) -> Dict[str, Any]:
        return {
            "license_id": self.license_id,
            "revoked_at": self.revoked_at.isoformat() if self.revoked_at else None,
            "reason": self.reason,
            "enforced_at": self.enforced_at.isoformat() if self.enforced_at else None,
            "grace_period_hours": self.grace_period_hours,
            "metadata": self.metadata,
        }


class LicenseRevocationManager:
    """Manage license revocations with local and online support."""

    def __init__(
        self,
        storage_dir: Optional[str] = None,
        online_url: Optional[str] = None,
        grace_period_hours: float = 24.0,
    ):
        self.storage_dir = storage_dir or os.path.join(
            os.path.expanduser("~"), ".coapis", "security"
        )
        self.online_url = online_url
        self.grace_period_hours = grace_period_hours
        self._storage_file = os.path.join(self.storage_dir, "revocations.json")
        self._revocations: Dict[str, RevocationRecord] = {}

        # Ensure storage directory exists
        os.makedirs(self.storage_dir, exist_ok=True)

        # Load existing revocations
        self._load_revocations()

    def _load_revocations(self) -> None:
        """Load revocation records from storage."""
        if os.path.exists(self._storage_file):
            try:
                with open(self._storage_file, "r") as f:
                    data = json.load(f)

                for record_data in data:
                    record = RevocationRecord(
                        license_id=record_data["license_id"],
                        revoked_at=datetime.fromisoformat(record_data["revoked_at"]),
                        reason=record_data.get("reason", ""),
                        enforced_at=datetime.fromisoformat(record_data["enforced_at"]) if record_data.get("enforced_at") else None,
                        grace_period_hours=record_data.get("grace_period_hours", self.grace_period_hours),
                        metadata=record_data.get("metadata", {}),
                    )
                    self._revocations[record.license_id] = record
            except Exception as e:
                logger.warning(f"Failed to load revocations: {e}")

    def _save_revocations(self) -> None:
        """Save revocation records to storage."""
        try:
            data = [record.to_dict() for record in self._revocations.values()]
            with open(self._storage_file, "w") as f:
                json.dump(data, f, indent=2)
        except Exception as e:
            logger.error(f"Failed to save revocations: {e}")

    def revoke(
        self,
        license_id: str,
        reason: str = "",
        grace_period_hours: Optional[float] = None,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> RevocationRecord:
        """
        Revoke a license.

        Args:
            license_id: License ID to revoke
            reason: Reason for revocation
            grace_period_hours: Hours before enforcement (default: 24)
            metadata: Additional metadata

        Returns:
            RevocationRecord
        """
        if grace_period_hours is None:
            grace_period_hours = self.grace_period_hours

        record = RevocationRecord(
            license_id=license_id,
            revoked_at=datetime.now(),
            reason=reason,
            grace_period_hours=grace_period_hours,
            metadata=metadata or {},
        )

        self._revocations[license_id] = record
        self._save_revocations()

        logger.info(f"License {license_id} revoked: {reason}")

        # Try to sync with online service
        if self.online_url:
            self._sync_online(license_id, reason)

        return record

    def is_revoked(self, license_id: str, check_online: bool = True) -> bool:
        """
        Check if a license has been revoked.

        Args:
            license_id: License ID to check
            check_online: Whether to check online revocation list

        Returns:
            True if license is revoked and enforcement has started
        """
        # Check local revocations
        if license_id in self._revocations:
            record = self._revocations[license_id]
            if record.is_enforced():
                return True

        # Check online revocations
        if check_online and self.online_url:
            try:
                import httpx

                async def check():
                    async with httpx.AsyncClient(timeout=5.0) as client:
                        response = await client.post(
                            f"{self.online_url}/revoked",
                            json={"license_id": license_id},
                        )
                        return response.json().get("revoked", False)

                import asyncio
                return asyncio.run(check())
            except Exception as e:
                logger.warning(f"Online revocation check failed: {e}")

        return False

    def get_revocation_record(self, license_id: str) -> Optional[RevocationRecord]:
        """Get revocation record for a license."""
        return self._revocations.get(license_id)

    def get_all_revocations(self) -> List[RevocationRecord]:
        """Get all revocation records."""
        return list(self._revocations.values())

    def get_enforced_revocations(self) -> List[RevocationRecord]:
        """Get all enforced revocations."""
        return [r for r in self._revocations.values() if r.is_enforced()]

    def unrevoke(
        self,
        license_id: str,
        reason: str = "",
    ) -> bool:
        """
        Un-revoke a license (restore it).

        Args:
            license_id: License ID to restore
            reason: Reason for restoration

        Returns:
            True if license was found and restored
        """
        if license_id in self._revocations:
            record = self._revocations.pop(license_id)
            self._save_revocations()

            logger.info(f"License {license_id} restored: {reason}")

            # Try to sync with online service
            if self.online_url:
                self._sync_online_restore(license_id, reason)

            return True

        return False

    def _sync_online(self, license_id: str, reason: str) -> None:
        """Sync revocation with online service."""
        try:
            import httpx

            async def sync():
                async with httpx.AsyncClient(timeout=5.0) as client:
                    await client.post(
                        f"{self.online_url}/revoke",
                        json={"license_id": license_id, "reason": reason},
                    )

            import asyncio
            asyncio.run(sync())
        except Exception as e:
            logger.warning(f"Online revocation sync failed: {e}")

    def _sync_online_restore(self, license_id: str, reason: str) -> None:
        """Sync license restoration with online service."""
        try:
            import httpx

            async def sync():
                async with httpx.AsyncClient(timeout=5.0) as client:
                    await client.post(
                        f"{self.online_url}/restore",
                        json={"license_id": license_id, "reason": reason},
                    )

            import asyncio
            asyncio.run(sync())
        except Exception as e:
            logger.warning(f"Online restore sync failed: {e}")

    def get_status(self) -> Dict[str, Any]:
        """Get revocation manager status."""
        return {
            "total_revocations": len(self._revocations),
            "enforced_revocations": len(self.get_enforced_revocations()),
            "online_url": self.online_url,
            "grace_period_hours": self.grace_period_hours,
            "storage_file": self._storage_file,
        }


# Global instance
_manager: Optional[LicenseRevocationManager] = None


def get_manager() -> Optional[LicenseRevocationManager]:
    """Get global revocation manager instance."""
    return _manager


def init_manager(
    online_url: Optional[str] = None,
    grace_period_hours: float = 24.0,
) -> LicenseRevocationManager:
    """Initialize global revocation manager."""
    global _manager
    _manager = LicenseRevocationManager(
        online_url=online_url,
        grace_period_hours=grace_period_hours,
    )
    return _manager


def shutdown_manager() -> None:
    """Shutdown global revocation manager."""
    global _manager
    _manager = None
