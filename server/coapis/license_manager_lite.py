# -*- coding: utf-8 -*-
"""Lightweight license manager for community edition.

Full license management is in coapis-enterprise package.
This provides basic tier detection and default community settings.

When coapis-enterprise is installed, the enterprise plugin's license
manager takes precedence. Otherwise, this defaults to Community tier.

License:
    Apache-2.0 (open source)
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from enum import Enum
from typing import Any, Dict, List, Optional, Set

logger = logging.getLogger(__name__)


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
    # Enterprise categories are defined in coapis-enterprise package


# ═══════════════════════════════════════════════════════════
# Feature Catalog (Open Source Features Only)
# ═══════════════════════════════════════════════════════════

FEATURE_CATALOG: Dict[str, Dict[str, Any]] = {
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
}


# ═══════════════════════════════════════════════════════════
# License State
# ═══════════════════════════════════════════════════════════


@dataclass
class LicenseState:
    """License state for community edition.
    
    For enterprise features, the state is managed by the enterprise plugin.
    """
    tier: LicenseTier = LicenseTier.COMMUNITY
    is_valid: bool = True
    is_trial: bool = False
    customer: str = ""
    issued: Optional[datetime] = None
    expires: Optional[datetime] = None
    features: Set[str] = field(default_factory=set)
    max_nodes: int = 1
    max_users: int = 100
    max_agents: int = 10
    error: Optional[str] = None
    
    @property
    def days_remaining(self) -> int:
        """Get days until license expires."""
        if not self.expires:
            return 9999  # Never expires (community)
        delta = self.expires - datetime.now(timezone.utc)
        return max(0, delta.days)
    
    def has_feature(self, feature: str) -> bool:
        """Check if a feature is available.
        
        For enterprise features, this delegates to the enterprise plugin.
        """
        # Check open-source features
        if feature in self.features:
            return True
        
        # Check feature catalog
        if feature in FEATURE_CATALOG:
            feat_info = FEATURE_CATALOG[feature]
            if feat_info["category"] in (FeatureCategory.CORE, FeatureCategory.EXPERIENCE):
                return True
        
        # Enterprise features - check plugin
        try:
            from .enterprise_plugin import get_enterprise_plugin
            plugin = get_enterprise_plugin()
            if plugin:
                try:
                    from .enterprise_plugin import EnterpriseFeature
                    feature_enum = EnterpriseFeature(feature)
                    return plugin.is_feature_available(feature_enum)
                except ValueError:
                    pass
        except (ImportError, AttributeError):
            pass
        
        return False
    
    def get_warnings(self) -> List[str]:
        """Get license warnings."""
        warnings = []
        if self.is_trial and self.days_remaining <= 7:
            warnings.append(f"Trial expires in {self.days_remaining} days")
        return warnings


# ═══════════════════════════════════════════════════════════
# License Manager
# ═══════════════════════════════════════════════════════════


class LicenseManager:
    """Lightweight license manager for community edition.
    
    When coapis-enterprise is installed, this delegates to the
    enterprise plugin's license manager. Otherwise, it provides
    default community edition settings.
    """
    
    _state: Optional[LicenseState] = None
    
    def get_state(self) -> LicenseState:
        """Get current license state.
        
        If enterprise plugin is installed, delegates to its license manager.
        Otherwise, returns default community state.
        """
        # Check if enterprise plugin has license manager
        try:
            from .enterprise_plugin import get_enterprise_plugin
            plugin = get_enterprise_plugin()
            if plugin:
                lic_manager = plugin.get_license_manager()
                if lic_manager:
                    return lic_manager.get_state()
        except (ImportError, AttributeError):
            pass
        
        # Return cached or default community state
        if self._state is None:
            self._state = LicenseState()
        
        return self._state
    
    def has_feature(self, feature: str) -> bool:
        """Check if a feature is available."""
        return self.get_state().has_feature(feature)
    
    def is_enterprise(self) -> bool:
        """Check if running enterprise edition."""
        return self.get_state().tier != LicenseTier.COMMUNITY
    
    def is_enterprise_package_installed(self) -> bool:
        """Check if the enterprise package is installed."""
        try:
            import coapis_enterprise
            return True
        except ImportError:
            return False
    
    def get_tier(self) -> LicenseTier:
        """Get current license tier."""
        return self.get_state().tier
    
    def init_security_modules(
        self,
        online_validation_url: str = "",
        online_validation_interval: float = 24,
        clock_grace_period: float = 300,
        revocation_grace_period: float = 24,
    ) -> None:
        """Initialize security modules (no-op for community edition).
        
        This method is a no-op for the lightweight license manager.
        Security modules are only available in the enterprise package.
        
        Args:
            online_validation_url: URL for online validation (ignored)
            online_validation_interval: Check interval in hours (ignored)
            clock_grace_period: Clock grace period in seconds (ignored)
            revocation_grace_period: Revocation grace period in hours (ignored)
        """
        # No-op - security modules are only in enterprise package
        pass


# Global license manager instance
license_manager = LicenseManager()


# ═══════════════════════════════════════════════════════════
# Convenience Functions
# ═══════════════════════════════════════════════════════════


def has_feature(feature: str) -> bool:
    """Check if a feature is available."""
    return license_manager.has_feature(feature)


def is_enterprise() -> bool:
    """Check if running enterprise edition."""
    return license_manager.is_enterprise()


def get_tier() -> LicenseTier:
    """Get current license tier."""
    return license_manager.get_tier()
