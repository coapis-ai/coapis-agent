# -*- coding: utf-8 -*-
"""Enterprise License Manager.

Manages license validation and feature entitlements.

License Tiers:
- Starter: Basic enterprise features (monitoring, basic SSO)
- Professional: Advanced features (SSO, audit, skill market)
- Enterprise: All features including clustering
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


class LicenseInfo(BaseModel):
    """License information."""
    customer_name: str
    license_key: str
    tier: str = Field(..., description="starter|professional|enterprise")
    issued_at: float
    expires_at: float
    max_nodes: int = 1
    max_users: int = 100
    features: List[str] = []


class LicenseManager:
    """Manages enterprise license validation and feature entitlements.
    
    Features:
    - License validation
    - Feature entitlement checks
    - License status monitoring
    - Grace period management
    """
    
    # Feature to tier mapping
    TIER_FEATURES = {
        "starter": ["monitoring", "sso"],
        "professional": ["monitoring", "sso", "audit", "skill_market"],
        "enterprise": ["monitoring", "sso", "audit", "skill_market", "clustering"],
    }
    
    def __init__(self, license_file: str = None):
        if license_file is None:
            from coapis.constant import WORKING_DIR
            license_file = str(WORKING_DIR / "license.json")
        self._license_file = Path(license_file)
        self._license: Optional[LicenseInfo] = None
        self._cache_time: float = 0
        
        # Try to load existing license
        self._load_license()
    
    def _load_license(self) -> None:
        """Load license from file."""
        if self._license_file.exists():
            try:
                with open(self._license_file, "r") as f:
                    data = json.load(f)
                    self._license = LicenseInfo(**data)
                    logger.info(f"License loaded for {self._license.customer_name}")
            except Exception as e:
                logger.warning(f"Failed to load license: {e}")
    
    def activate(self, license_key: str) -> Dict[str, Any]:
        """Activate a license.
        
        Args:
            license_key: The license key to activate
        
        Returns:
            Activation result
        """
        # In production, this would validate with license server
        # For now, parse the license key
        
        try:
            # Decode license key (in production, this would be signed)
            parts = license_key.split("-")
            if len(parts) != 5:
                return {
                    "success": False,
                    "error": "Invalid license key format",
                }
            
            # Create license info
            self._license = LicenseInfo(
                customer_name=parts[0],
                license_key=license_key,
                tier=parts[1],
                issued_at=time.time(),
                expires_at=time.time() + 365 * 24 * 3600,  # 1 year
                max_nodes=int(parts[2]),
                max_users=int(parts[3]),
                features=self.TIER_FEATURES.get(parts[1], []),
            )
            
            # Save to file
            self._save_license()
            
            return {
                "success": True,
                "license": self._license.model_dump(),
            }
            
        except Exception as e:
            return {
                "success": False,
                "error": str(e),
            }
    
    def _save_license(self) -> None:
        """Save license to file."""
        if self._license:
            self._license_file.parent.mkdir(parents=True, exist_ok=True)
            with open(self._license_file, "w") as f:
                json.dump(self._license.model_dump(), f, indent=2)
    
    def is_valid(self) -> bool:
        """Check if current license is valid."""
        if not self._license:
            return False
        
        # Check expiration
        if self._license.expires_at < time.time():
            logger.warning("License has expired")
            return False
        
        return True
    
    def is_feature_entitled(self, feature: str) -> bool:
        """Check if a feature is entitled by current license.
        
        Args:
            feature: Feature name to check
        
        Returns:
            True if feature is entitled
        """
        if not self._license:
            return False
        
        return feature in self._license.features
    
    def get_status(self) -> Dict[str, Any]:
        """Get current license status.
        
        Returns:
            License status information
        """
        if not self._license:
            return {
                "installed": False,
                "message": "No license installed",
                "upgrade_url": "https://coapis.dev/enterprise",
            }
        
        # Check expiration
        expires_in = self._license.expires_at - time.time()
        is_expired = expires_in <= 0
        
        return {
            "installed": True,
            "valid": not is_expired,
            "customer": self._license.customer_name,
            "tier": self._license.tier,
            "expires_at": self._license.expires_at,
            "expires_in_days": int(expires_in / 86400) if not is_expired else 0,
            "max_nodes": self._license.max_nodes,
            "max_users": self._license.max_users,
            "features": self._license.features,
        }
    
    def get_grace_period(self) -> Dict[str, Any]:
        """Get grace period information.
        
        Returns:
            Grace period status
        """
        if not self._license:
            return {"in_grace_period": False}
        
        # 30 day grace period after expiration
        grace_end = self._license.expires_at + 30 * 24 * 3600
        now = time.time()
        
        if self._license.expires_at <= now <= grace_end:
            return {
                "in_grace_period": True,
                "grace_ends_at": grace_end,
                "days_remaining": int((grace_end - now) / 86400),
            }
        
        return {"in_grace_period": False}
