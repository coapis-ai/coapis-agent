# -*- coding: utf-8 -*-
"""Online license validation service for CoApis.

Provides periodic online validation to prevent offline license tampering.
Supports:
- Periodic validation (configurable interval)
- License revocation check
- Validation result caching
- Graceful fallback when offline

Usage:
    from coapis.license_validator import OnlineLicenseValidator

    validator = OnlineLicenseValidator(
        validation_url="https://license.coapis.com/validate",
        interval_hours=24,
    )

    # Validate license
    result = validator.validate(license_key)

    if result.is_valid:
        print("License is valid")
    else:
        print(f"Validation failed: {result.reason}")
"""

from __future__ import annotations

import asyncio
import logging
import os
import time
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from enum import Enum
from typing import Any, Dict, Optional

import httpx

logger = logging.getLogger(__name__)


class ValidationStatus(str, Enum):
    VALID = "valid"
    EXPIRED = "expired"
    REVOKED = "revoked"
    INVALID = "invalid"
    OFFLINE = "offline"
    UNKNOWN = "unknown"


@dataclass
class ValidationResult:
    is_valid: bool
    status: ValidationStatus
    message: str
    expires_at: Optional[datetime] = None
    features: list = field(default_factory=list)
    max_users: int = 0
    max_nodes: int = 0
    cache_until: float = 0.0

    def to_dict(self) -> Dict[str, Any]:
        return {
            "is_valid": self.is_valid,
            "status": self.status.value,
            "message": self.message,
            "expires_at": self.expires_at.isoformat() if self.expires_at else None,
            "features": self.features,
            "max_users": self.max_users,
            "max_nodes": self.max_nodes,
            "cache_until": self.cache_until,
        }


class OnlineLicenseValidator:
    """Online license validator with caching and fallback."""

    def __init__(
        self,
        validation_url: str,
        interval_hours: float = 24.0,
        cache_dir: Optional[str] = None,
        timeout: float = 10.0,
    ):
        self.validation_url = validation_url.rstrip("/")
        self.interval_hours = interval_hours
        self.interval_seconds = interval_hours * 3600
        self.timeout = timeout
        self.cache_dir = cache_dir or os.path.join(os.path.expanduser("~"), ".coapis", "cache")
        self._cache: Dict[str, ValidationResult] = {}
        self._last_check: float = 0.0
        self._is_initialized = False

        # Ensure cache directory exists
        os.makedirs(self.cache_dir, exist_ok=True)

    def _get_cache_file(self, license_key: str) -> str:
        """Get cache file path for a license key."""
        import hashlib

        key_hash = hashlib.sha256(license_key.encode()).hexdigest()[:16]
        return os.path.join(self.cache_dir, f"license_{key_hash}.json")

    def _load_cache(self, license_key: str) -> Optional[ValidationResult]:
        """Load validation result from cache."""
        cache_file = self._get_cache_file(license_key)
        if os.path.exists(cache_file):
            try:
                import json

                with open(cache_file, "r") as f:
                    data = json.load(f)

                cache_time = data.get("cached_at", 0)
                cache_until = data.get("cache_until", 0)

                # Check if cache is still valid
                if time.time() < cache_until:
                    logger.debug(f"Cache hit for license {license_key[:8]}...")
                    return ValidationResult(
                        is_valid=data["is_valid"],
                        status=ValidationStatus(data["status"]),
                        message=data["message"],
                        expires_at=datetime.fromisoformat(data["expires_at"]) if data.get("expires_at") else None,
                        features=data.get("features", []),
                        max_users=data.get("max_users", 0),
                        max_nodes=data.get("max_nodes", 0),
                        cache_until=cache_until,
                    )
            except Exception as e:
                logger.warning(f"Failed to load cache: {e}")

        return None

    def _save_cache(self, license_key: str, result: ValidationResult) -> None:
        """Save validation result to cache."""
        cache_file = self._get_cache_file(license_key)
        try:
            import json

            data = {
                "is_valid": result.is_valid,
                "status": result.status.value,
                "message": result.message,
                "expires_at": result.expires_at.isoformat() if result.expires_at else None,
                "features": result.features,
                "max_users": result.max_users,
                "max_nodes": result.max_nodes,
                "cached_at": time.time(),
                "cache_until": result.cache_until,
            }

            with open(cache_file, "w") as f:
                json.dump(data, f, indent=2)
        except Exception as e:
            logger.warning(f"Failed to save cache: {e}")

    async def validate(self, license_key: str) -> ValidationResult:
        """Validate license with online check and caching."""
        # Check cache first
        cached = self._load_cache(license_key)
        if cached:
            return cached

        # Check if we need to do online validation
        now = time.time()
        if now - self._last_check < self.interval_seconds:
            logger.debug("Online validation interval not reached, using offline validation")
            return self._offline_fallback(license_key)

        self._last_check = now

        # Try online validation
        try:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                response = await client.post(
                    f"{self.validation_url}/validate",
                    json={"license_key": license_key},
                )

                if response.status_code == 200:
                    data = response.json()
                    result = ValidationResult(
                        is_valid=data.get("valid", False),
                        status=ValidationStatus(data.get("status", "unknown")),
                        message=data.get("message", ""),
                        expires_at=datetime.fromisoformat(data["expires_at"]) if data.get("expires_at") else None,
                        features=data.get("features", []),
                        max_users=data.get("max_users", 0),
                        max_nodes=data.get("max_nodes", 0),
                        cache_until=now + self.interval_seconds,
                    )

                    self._save_cache(license_key, result)
                    return result
                else:
                    logger.warning(f"Online validation failed with status {response.status_code}")
                    return self._offline_fallback(license_key)

        except Exception as e:
            logger.warning(f"Online validation failed: {e}")
            return self._offline_fallback(license_key)

    def _offline_fallback(self, license_key: str) -> ValidationResult:
        """Fallback to offline validation when online is unavailable."""
        from coapis.license_manager import LicenseManager

        try:
            manager = LicenseManager()
            info = manager.validate_license(license_key)

            if info:
                result = ValidationResult(
                    is_valid=info.is_valid,
                    status=ValidationStatus.VALID if info.is_valid else ValidationStatus.INVALID,
                    message=info.message if info.message else "Offline validation",
                    expires_at=info.expires_at,
                    features=info.features,
                    max_users=info.max_users,
                    max_nodes=info.max_nodes,
                    cache_until=time.time() + self.interval_seconds,
                )
                self._save_cache(license_key, result)
                return result
        except Exception as e:
            logger.error(f"Offline validation failed: {e}")

        # Final fallback - allow operation but log warning
        logger.warning("All validation methods failed, allowing operation with warning")
        return ValidationResult(
            is_valid=True,
            status=ValidationStatus.OFFLINE,
            message="Offline mode - validation unavailable",
            cache_until=time.time() + 3600,  # Cache for 1 hour
        )

    async def check_revocation(self, license_id: str) -> bool:
        """Check if license has been revoked."""
        try:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                response = await client.post(
                    f"{self.validation_url}/revoked",
                    json={"license_id": license_id},
                )

                if response.status_code == 200:
                    return response.json().get("revoked", False)
                else:
                    logger.warning(f"Revocation check failed with status {response.status_code}")
                    return False

        except Exception as e:
            logger.warning(f"Revocation check failed: {e}")
            return False

    async def periodic_validation(self) -> None:
        """Run periodic validation for all active licenses."""
        from coapis.license_manager import LicenseManager

        try:
            manager = LicenseManager()
            active_licenses = manager.get_active_licenses()

            for license_key in active_licenses:
                await self.validate(license_key)
        except Exception as e:
            logger.error(f"Periodic validation failed: {e}")

    def get_status(self) -> Dict[str, Any]:
        """Get validator status."""
        return {
            "validation_url": self.validation_url,
            "interval_hours": self.interval_hours,
            "last_check": self._last_check,
            "cache_dir": self.cache_dir,
            "is_initialized": self._is_initialized,
        }


# Global validator instance
_validator: Optional[OnlineLicenseValidator] = None


def get_validator() -> Optional[OnlineLicenseValidator]:
    """Get global validator instance."""
    return _validator


def init_validator(
    validation_url: str = "https://license.coapis.com/validate",
    interval_hours: float = 24.0,
) -> OnlineLicenseValidator:
    """Initialize global validator."""
    global _validator
    _validator = OnlineLicenseValidator(
        validation_url=validation_url,
        interval_hours=interval_hours,
    )
    return _validator


def shutdown_validator() -> None:
    """Shutdown global validator."""
    global _validator
    _validator = None
