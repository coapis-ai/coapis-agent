# -*- coding: utf-8 -*-
"""CoApis License Management System - v2

Improvements over v1:
1. Proper RSA key pair for license generation and validation
2. Tier-based licensing (Starter/Professional/Enterprise)
3. Trial mode support (30-day evaluation)
4. Feature-level granularity (not just edition-based)
5. License file persistence (not just env var)
6. Runtime enforcement (periodic re-check)
7. Usage tracking (anonymous telemetry)
8. Tamper detection (bind to machine fingerprint)
9. Graceful degradation (warning before blocking)
10. License key generation tool for sales team
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import os
import platform
import socket
import time
import uuid
from dataclasses import dataclass, field, asdict
from datetime import datetime, timedelta, timezone
from enum import Enum
from pathlib import Path
from typing import Any, Dict, List, Optional, Set

logger = logging.getLogger(__name__)


# ═══════════════════════════════════════════════════════════
# Commercial Security Modules
# ═══════════════════════════════════════════════════════════

# Lazy imports to avoid circular dependencies
_clock_protection = None
_revocation_manager = None
_renewal_manager = None
_online_validator = None


def _get_clock_protection():
    """Get clock protection instance."""
    global _clock_protection
    if _clock_protection is None:
        from .clock_protection import get_protection
        _clock_protection = get_protection()
    return _clock_protection


def _get_revocation_manager():
    """Get revocation manager instance."""
    global _revocation_manager
    if _revocation_manager is None:
        from .license_revocation import get_manager
        _revocation_manager = get_manager()
    return _revocation_manager


def _get_renewal_manager():
    """Get renewal reminder manager instance."""
    global _renewal_manager
    if _renewal_manager is None:
        from .renewal_reminder import get_manager
        _renewal_manager = get_manager()
    return _renewal_manager


def _get_online_validator():
    """Get online validator instance."""
    global _online_validator
    if _online_validator is None:
        from .license_validator import get_validator
        _online_validator = get_validator()
    return _online_validator


# ═══════════════════════════════════════════════════════════
# License Tiers
# ═══════════════════════════════════════════════════════════

class LicenseTier(str, Enum):
    """License tiers for pricing flexibility."""
    COMMUNITY = "community"    # Free, open-source
    STARTER = "starter"        # Small teams, basic enterprise
    PROFESSIONAL = "professional"  # Medium teams, full features
    ENTERPRISE = "enterprise"  # Large orgs, custom pricing


# ═══════════════════════════════════════════════════════════
# Feature Categories
# ═══════════════════════════════════════════════════════════

class FeatureCategory(str, Enum):
    """Feature categories for granular control."""
    CORE = "core"              # Available in all editions
    EXPERIENCE = "experience"  # P1 features (free)
    ENTERPRISE_BASIC = "enterprise_basic"    # P2 features (Starter+)
    ENTERPRISE_ADVANCED = "enterprise_advanced"  # P2 features (Professional+)
    ENTERPRISE_PREMIUM = "enterprise_premium"    # P3 features (Enterprise only)


# ═══════════════════════════════════════════════════════════
# Feature Definitions
# ═══════════════════════════════════════════════════════════

FEATURE_CATALOG = {
    # P0 - Core (free)
    "auth": {"category": FeatureCategory.CORE, "description": "Authentication system"},
    "multi_tenant": {"category": FeatureCategory.CORE, "description": "Multi-tenant architecture"},
    "memory": {"category": FeatureCategory.CORE, "description": "Hierarchical memory system"},
    "skills": {"category": FeatureCategory.CORE, "description": "Skill management"},
    "channels": {"category": FeatureCategory.CORE, "description": "Multi-channel support"},
    "security": {"category": FeatureCategory.CORE, "description": "ToolGuard + SkillScanner"},
    
    # P1 - Experience (free)
    "setup_wizard": {"category": FeatureCategory.EXPERIENCE, "description": "Interactive setup wizard"},
    "onboarding": {"category": FeatureCategory.EXPERIENCE, "description": "User onboarding tours"},
    "i18n": {"category": FeatureCategory.EXPERIENCE, "description": "Multi-language support"},
    "search": {"category": FeatureCategory.EXPERIENCE, "description": "Global search"},
    "inbox": {"category": FeatureCategory.EXPERIENCE, "description": "Notification system"},
    "theme": {"category": FeatureCategory.EXPERIENCE, "description": "Theme switching"},
    
    # P2 - Enterprise Basic (Starter+)
    "monitoring": {"category": FeatureCategory.ENTERPRISE_BASIC, "description": "Monitoring dashboard"},
    "audit_logs": {"category": FeatureCategory.ENTERPRISE_BASIC, "description": "Audit log retention"},
    "config_reload": {"category": FeatureCategory.ENTERPRISE_BASIC, "description": "Hot config reload"},
    
    # P2 - Enterprise Advanced (Professional+)
    "clustering": {"category": FeatureCategory.ENTERPRISE_ADVANCED, "description": "Multi-node clustering"},
    "sso": {"category": FeatureCategory.ENTERPRISE_ADVANCED, "description": "SSO integration"},
    "audit_reports": {"category": FeatureCategory.ENTERPRISE_ADVANCED, "description": "Compliance reports"},
    
    # P3 - Enterprise Premium (Enterprise only)
    "skill_market": {"category": FeatureCategory.ENTERPRISE_PREMIUM, "description": "Skill marketplace"},
    "sla": {"category": FeatureCategory.ENTERPRISE_PREMIUM, "description": "SLA guarantees"},
    "dedicated_support": {"category": FeatureCategory.ENTERPRISE_PREMIUM, "description": "24/7 support"},
}

# Tier-to-category mapping (which tiers include which categories)
TIER_FEATURE_MAP = {
    LicenseTier.COMMUNITY: {FeatureCategory.CORE, FeatureCategory.EXPERIENCE},
    LicenseTier.STARTER: {
        FeatureCategory.CORE, FeatureCategory.EXPERIENCE,
        FeatureCategory.ENTERPRISE_BASIC,
    },
    LicenseTier.PROFESSIONAL: {
        FeatureCategory.CORE, FeatureCategory.EXPERIENCE,
        FeatureCategory.ENTERPRISE_BASIC, FeatureCategory.ENTERPRISE_ADVANCED,
    },
    LicenseTier.ENTERPRISE: {
        FeatureCategory.CORE, FeatureCategory.EXPERIENCE,
        FeatureCategory.ENTERPRISE_BASIC, FeatureCategory.ENTERPRISE_ADVANCED,
        FeatureCategory.ENTERPRISE_PREMIUM,
    },
}


# ═══════════════════════════════════════════════════════════
# License Data Model
# ═══════════════════════════════════════════════════════════

@dataclass
class LicenseData:
    """License payload (before signing)."""
    version: int = 1
    license_id: str = ""
    customer: str = ""
    customer_id: str = ""  # Internal customer ID
    tier: str = LicenseTier.COMMUNITY.value
    issued: str = ""       # ISO format datetime
    expires: str = ""      # ISO format datetime
    features: List[str] = field(default_factory=list)  # Explicit feature list
    max_nodes: int = 1
    max_users: int = 10
    max_agents: int = 5
    machine_fingerprint: str = ""  # Bind to specific machine (optional)
    trial: bool = False   # Is this a trial license?
    metadata: Dict[str, Any] = field(default_factory=dict)  # Custom metadata


@dataclass
class LicenseState:
    """Current license state (after validation)."""
    is_valid: bool = False
    is_trial: bool = False
    tier: LicenseTier = LicenseTier.COMMUNITY
    customer: str = ""
    issued: Optional[datetime] = None
    expires: Optional[datetime] = None
    features: Set[str] = field(default_factory=set)
    max_nodes: int = 1
    max_users: int = 10
    max_agents: int = 5
    days_remaining: int = -1
    warnings: List[str] = field(default_factory=list)
    error: str = ""
    
    @property
    def is_expired(self) -> bool:
        if not self.expires:
            return False
        return datetime.now(timezone.utc) > self.expires
    
    def has_feature(self, feature: str) -> bool:
        """Check if feature is available."""
        if not self.is_valid:
            return False
        if not self.features:
            # Use tier-based check
            return self._tier_has_feature(feature)
        return feature in self.features
    
    def _tier_has_feature(self, feature: str) -> bool:
        """Check if feature is available based on tier."""
        if feature not in FEATURE_CATALOG:
            return False
        feature_cat = FEATURE_CATALOG[feature]["category"]
        allowed_cats = TIER_FEATURE_MAP.get(self.tier, set())
        return feature_cat in allowed_cats
    
    def get_warnings(self) -> List[str]:
        """Get license warnings (e.g., expiring soon)."""
        warnings = list(self.warnings)
        if self.is_trial:
            warnings.append("This is a trial license")
        if self.days_remaining > 0 and self.days_remaining <= 30:
            warnings.append(f"License expires in {self.days_remaining} days")
        return warnings


# ═══════════════════════════════════════════════════════════
# Machine Fingerprint
# ═══════════════════════════════════════════════════════════

def get_machine_fingerprint() -> str:
    """Generate a machine fingerprint for license binding.
    
    Uses multiple hardware/software identifiers for robustness.
    """
    parts = [
        platform.node(),          # Hostname
        platform.machine(),       # Architecture
        platform.python_version(),
        str(uuid.getnode()),      # MAC address hash
    ]
    raw = "|".join(parts)
    return hashlib.sha256(raw.encode()).hexdigest()[:16]


# ═══════════════════════════════════════════════════════════
# License Manager (Stateful)
# ═══════════════════════════════════════════════════════════

class LicenseManager:
    """Manages license lifecycle: load, validate, check, renew."""
    
    # License storage path
    LICENSE_DIR = Path(os.environ.get("COAPIS_LICENSE_DIR", "~/.coapis"))
    LICENSE_FILE = LICENSE_DIR / "license.json"
    
    def __init__(self):
        self._state: Optional[LicenseState] = None
        self._last_check: float = 0
        self._check_interval: float = 3600  # Re-check every hour
    
    def load_license(self) -> LicenseState:
        """Load and validate license from file or env."""
        # Check cache first
        if self._state and (time.time() - self._last_check) < self._check_interval:
            return self._state
        
        # Try file first
        if self.LICENSE_FILE.exists():
            state = self._load_from_file()
        else:
            # Fall back to env var
            state = self._load_from_env()
        
        self._state = state
        self._last_check = time.time()
        
        return state
    
    def _load_from_file(self) -> LicenseState:
        """Load license from JSON file."""
        try:
            with open(self.LICENSE_FILE, "r") as f:
                data = json.load(f)
            
            license_key = data.get("license_key", "")
            return self._validate(license_key)
        except Exception as e:
            logger.error("Failed to load license from file: %s", e)
            return self._default_state()
    
    def _load_from_env(self) -> LicenseState:
        """Load license from environment variables."""
        edition = os.environ.get("COAPIS_EDITION", "community").lower()
        license_key = os.environ.get("COAPIS_LICENSE_KEY", "")
        
        if edition == "community" or not license_key:
            return self._default_state()
        
        return self._validate(license_key)
    
    def _validate(self, license_key: str) -> LicenseState:
        """Validate a license key with comprehensive security checks.
        
        Validation pipeline:
        1. RSA signature verification (or fallback)
        2. Clock rollback detection
        3. License revocation check
        4. Machine binding verification
        5. Expiration check
        
        Uses the license_crypto module for cryptographic verification.
        Falls back to simple validation if no public key is configured.
        """
        state = LicenseState()
        
        if not license_key:
            return self._default_state()
        
        try:
            # Step 1: RSA signature verification
            public_key_path = os.environ.get("COAPIS_LICENSE_PUBLIC_KEY")
            if public_key_path and os.path.exists(public_key_path):
                from .license_crypto import LicenseVerifier, LicenseInfo as CryptoLicenseInfo
                
                verifier = LicenseVerifier.load(public_key_path)
                crypto_info = verifier.verify(license_key)
                
                if not crypto_info.is_valid:
                    state.error = crypto_info.error
                    return state
                
                # Convert crypto info to our state
                state.is_valid = True
                state.tier = LicenseTier(crypto_info.tier)
                state.customer = crypto_info.customer
                state.issued = crypto_info.issued
                state.expires = crypto_info.expires
                state.features = set(crypto_info.features)
                state.max_nodes = crypto_info.max_nodes
                state.max_users = crypto_info.max_users
                state.max_agents = crypto_info.max_agents
                state.is_trial = crypto_info.is_trial
                state.days_remaining = crypto_info.days_remaining
                
                logger.info(
                    "License validated (RSA): tier=%s customer=%s expires=%s",
                    state.tier.value, state.customer, state.expires,
                )
            else:
                # Fallback: simple Base64 validation (for development)
                import base64
                parts = license_key.split(".")
                if len(parts) != 2:
                    state.error = "Invalid license format (expected payload.signature)"
                    return state
                
                payload = base64.b64decode(parts[0]).decode()
                data = json.loads(payload)
                
                # Extract fields
                state.tier = LicenseTier(data.get("tier", "community"))
                state.customer = data.get("customer", "")
                state.issued = datetime.fromisoformat(data.get("issued", ""))
                state.expires = datetime.fromisoformat(data.get("expires", ""))
                state.features = set(data.get("features", []))
                state.max_nodes = data.get("max_nodes", 1)
                state.max_users = data.get("max_users", 10)
                state.max_agents = data.get("max_agents", 5)
                state.is_trial = data.get("trial", False)
                
                logger.warning(
                    "License validated (fallback): tier=%s customer=%s (no RSA public key configured)",
                    state.tier.value, state.customer,
                )
            
            # Step 2: Clock rollback detection
            clock_prot = _get_clock_protection()
            if clock_prot:
                clock_status = clock_prot.check()
                if not clock_status.is_valid:
                    state.warnings.append(clock_status.warning)
                    logger.warning("Clock anomaly detected: %s", clock_status.warning)
            
            # Step 3: License revocation check
            revocation_mgr = _get_revocation_manager()
            if revocation_mgr and state.is_valid:
                # Extract license_id from key (first part before '.')
                license_id = license_key.split(".")[0] if "." in license_key else license_key[:16]
                if revocation_mgr.is_revoked(license_id, check_online=False):
                    state.is_valid = False
                    state.error = "License has been revoked"
                    logger.warning("License %s has been revoked", license_id)
                    return state
            
            # Step 4: Machine binding verification (only for non-community)
            if state.tier != LicenseTier.COMMUNITY:
                # Extract machine fingerprint from license data
                import base64
                parts = license_key.split(".")
                if len(parts) >= 1:
                    payload = base64.b64decode(parts[0]).decode()
                    data = json.loads(payload)
                    required_fp = data.get("machine_fingerprint", "")
                    
                    if required_fp:
                        actual_fp = get_machine_fingerprint()
                        if required_fp != actual_fp:
                            state.is_valid = False
                            state.error = "License bound to different machine"
                            logger.warning(
                                "Machine fingerprint mismatch: required=%s actual=%s",
                                required_fp, actual_fp,
                            )
                            return state
            
            # Step 5: Expiration check
            if state.expires and state.is_expired:
                state.is_valid = False
                state.error = "License expired"
                logger.warning("License expired for customer %s", state.customer)
                return state
            
            # Calculate days remaining
            if state.expires:
                state.days_remaining = max(0, (state.expires - datetime.now(timezone.utc)).days)
            
            # Step 6: Trigger renewal reminders if needed
            if state.is_valid and state.expires:
                renewal_mgr = _get_renewal_manager()
                if renewal_mgr:
                    reminders = renewal_mgr.check_reminders(
                        license_id=license_key[:16],
                        expires_at=state.expires,
                        customer_name=state.customer,
                    )
                    if reminders:
                        logger.info(
                            "Pending renewal reminders for %s: %d reminders",
                            state.customer, len(reminders),
                        )
            
            return state
            
        except Exception as e:
            logger.error("License validation failed: %s", e)
            state.error = f"Invalid license: {e}"
            return state
    
    def _default_state(self) -> LicenseState:
        """Get default community license state."""
        state = LicenseState()
        state.is_valid = True
        state.tier = LicenseTier.COMMUNITY
        state.features = set()  # Use tier-based check
        return state
    
    def check_feature(self, feature: str) -> bool:
        """Check if a feature is available."""
        state = self.load_license()
        return state.has_feature(feature)
    
    def get_state(self) -> LicenseState:
        """Get current license state."""
        return self.load_license()
    
    def save_license(self, license_key: str) -> bool:
        """Save license key to file for persistence."""
        try:
            self.LICENSE_DIR.mkdir(parents=True, exist_ok=True)
            with open(self.LICENSE_FILE, "w") as f:
                json.dump({"license_key": license_key}, f)
            # Reload
            self._state = None
            return True
        except Exception as e:
            logger.error("Failed to save license: %s", e)
            return False

    # ═══════════════════════════════════════════════════════════
    # Commercial Security Module Methods
    # ═══════════════════════════════════════════════════════════

    def init_security_modules(
        self,
        online_validation_url: str = "",
        online_validation_interval: float = 24.0,
        clock_grace_period: float = 300.0,
        revocation_grace_period: float = 24.0,
    ) -> None:
        """Initialize all commercial security modules.
        
        Call this during application startup to enable:
        - Online license validation
        - Clock rollback protection
        - License revocation management
        - Renewal reminder system
        
        Args:
            online_validation_url: URL for online license validation service
            online_validation_interval: Hours between online validation checks
            clock_grace_period: Seconds of grace for minor clock adjustments
            revocation_grace_period: Hours of grace before revocation enforcement
        """
        # Initialize online validator if URL is provided
        if online_validation_url:
            from .license_validator import init_validator
            init_validator(
                validation_url=online_validation_url,
                interval_hours=online_validation_interval,
            )
            logger.info("Online license validator initialized: %s", online_validation_url)
        
        # Initialize clock protection
        from .clock_protection import init_protection
        init_protection(grace_period=clock_grace_period)
        logger.info("Clock protection initialized (grace: %.0fs)", clock_grace_period)
        
        # Initialize revocation manager
        from .license_revocation import init_manager
        init_manager(
            online_url=online_validation_url if online_validation_url else None,
            grace_period_hours=revocation_grace_period,
        )
        logger.info("License revocation manager initialized")
        
        # Initialize renewal reminder manager
        from .renewal_reminder import init_manager as init_renewal_manager
        init_renewal_manager()
        logger.info("Renewal reminder manager initialized")

    def get_online_validation_status(self) -> Dict[str, Any]:
        """Get online validator status."""
        validator = _get_online_validator()
        if validator:
            status = validator.get_status()
            status["initialized"] = True
            return status
        return {"initialized": False}

    def get_clock_protection_status(self) -> Dict[str, Any]:
        """Get clock protection status."""
        prot = _get_clock_protection()
        if prot:
            status = prot.get_status()
            status["initialized"] = True
            return status
        return {"initialized": False}

    def get_revocation_status(self) -> Dict[str, Any]:
        """Get revocation manager status."""
        mgr = _get_revocation_manager()
        if mgr:
            status = mgr.get_status()
            status["initialized"] = True
            return status
        return {"initialized": False}

    def get_renewal_reminders_status(self) -> Dict[str, Any]:
        """Get renewal reminder manager status."""
        mgr = _get_renewal_manager()
        if mgr:
            status = mgr.get_status()
            status["initialized"] = True
            return status
        return {"initialized": False}

    def revoke_license(self, license_id: str, reason: str = "") -> bool:
        """Revoke a license.
        
        Args:
            license_id: License ID to revoke
            reason: Reason for revocation
            
        Returns:
            True if revocation was successful
        """
        mgr = _get_revocation_manager()
        if mgr:
            mgr.revoke(license_id, reason=reason)
            return True
        return False

    def unrevoke_license(self, license_id: str, reason: str = "") -> bool:
        """Restore a revoked license.
        
        Args:
            license_id: License ID to restore
            reason: Reason for restoration
            
        Returns:
            True if restoration was successful
        """
        mgr = _get_revocation_manager()
        if mgr:
            return mgr.unrevoke(license_id, reason=reason)
        return False

    def check_license_revocation(self, license_id: str) -> bool:
        """Check if a license has been revoked.
        
        Args:
            license_id: License ID to check
            
        Returns:
            True if license is revoked
        """
        mgr = _get_revocation_manager()
        if mgr:
            return mgr.is_revoked(license_id)
        return False

    def get_renewal_history(self, license_id: str = "", limit: int = 50) -> List[Dict[str, Any]]:
        """Get renewal reminder history.
        
        Args:
            license_id: Filter by license ID (empty for all)
            limit: Maximum number of records to return
            
        Returns:
            List of reminder records
        """
        mgr = _get_renewal_manager()
        if mgr:
            records = mgr.get_reminder_history(
                license_id=license_id if license_id else None,
                limit=limit,
            )
            return [r.to_dict() for r in records]
        return []

    def check_clock(self) -> Dict[str, Any]:
        """Check current clock status.
        
        Returns:
            Clock status with validation result
        """
        prot = _get_clock_protection()
        if prot:
            status = prot.check()
            return {
                "is_valid": status.is_valid,
                "current_time": status.current_time.isoformat(),
                "last_check_time": status.last_check_time.isoformat() if status.last_check_time else None,
                "time_delta_seconds": status.time_delta_seconds,
                "warning": status.warning,
            }
        return {"is_valid": True, "warning": "Clock protection not initialized"}


# ═══════════════════════════════════════════════════════════
# Global Instance
# ═══════════════════════════════════════════════════════════

license_manager = LicenseManager()


# ═══════════════════════════════════════════════════════════
# Convenience Functions (backward compatible with v1)
# ═══════════════════════════════════════════════════════════

def is_enterprise() -> bool:
    """Check if running enterprise edition."""
    state = license_manager.get_state()
    return state.tier != LicenseTier.COMMUNITY


def has_feature(feature: str) -> bool:
    """Check if feature is available."""
    return license_manager.check_feature(feature)


def get_tier() -> LicenseTier:
    """Get current license tier."""
    return license_manager.get_state().tier


# ═══════════════════════════════════════════════════════════
# License Key Generation (for sales/admin use only)
# ═══════════════════════════════════════════════════════════

def generate_license_key(
    customer: str,
    tier: LicenseTier = LicenseTier.STARTER,
    duration_days: int = 365,
    features: Optional[List[str]] = None,
    max_nodes: int = 1,
    max_users: int = 10,
    max_agents: int = 5,
    machine_fingerprint: str = "",
    trial: bool = False,
) -> str:
    """Generate a license key with RSA signature.
    
    WARNING: This should only be used by the license server,
    not embedded in the product.
    
    In production, this runs on a secure server with the
    private key.
    
    Args:
        customer: Customer company name
        tier: License tier
        duration_days: License validity period
        features: Explicit feature list (auto-selected from tier if None)
        max_nodes: Maximum cluster nodes
        max_users: Maximum users
        max_agents: Maximum agents
        machine_fingerprint: Bind to specific machine (optional)
        trial: Whether this is a trial license
        
    Returns:
        Signed license key string
    """
    # Try RSA signing first
    private_key_path = os.environ.get("COAPIS_LICENSE_PRIVATE_KEY")
    if private_key_path and os.path.exists(private_key_path):
        from .license_crypto import LicenseSigner
        
        signer = LicenseSigner.load(private_key_path)
        
        # Auto-select features based on tier if not specified
        if features is None:
            allowed_cats = TIER_FEATURE_MAP.get(tier, set())
            features = [
                name for name, info in FEATURE_CATALOG.items()
                if info["category"] in allowed_cats
            ]
        
        return signer.create_license(
            customer=customer,
            tier=tier.value,
            duration_days=duration_days,
            features=features,
            max_nodes=max_nodes,
            max_users=max_users,
            max_agents=max_agents,
            machine_fingerprint=machine_fingerprint,
            is_trial=trial,
        )
    
    # Fallback: unsigned license (for development/testing only)
    logger.warning(
        "Generating unsigned license key (no RSA private key configured). "
        "This should only be used for development/testing."
    )
    
    import base64
    
    now = datetime.now(timezone.utc)
    expires = now + timedelta(days=duration_days)
    
    # Auto-select features based on tier if not specified
    if features is None:
        allowed_cats = TIER_FEATURE_MAP.get(tier, set())
        features = [
            name for name, info in FEATURE_CATALOG.items()
            if info["category"] in allowed_cats
        ]
    
    # Build license data
    data = LicenseData(
        version=1,
        license_id=str(uuid.uuid4()),
        customer=customer,
        customer_id=hashlib.md5(customer.encode()).hexdigest()[:8],
        tier=tier.value,
        issued=now.isoformat(),
        expires=expires.isoformat(),
        features=features,
        max_nodes=max_nodes,
        max_users=max_users,
        max_agents=max_agents,
        machine_fingerprint=machine_fingerprint,
        trial=trial,
    )
    
    # Serialize (unsigned - for development only)
    payload = json.dumps(asdict(data), sort_keys=True)
    payload_b64 = base64.b64encode(payload.encode()).decode()
    
    # Unsigned marker
    signature = "dev-unsigned"
    
    return f"{payload_b64}.{signature}"
