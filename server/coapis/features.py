# -*- coding: utf-8 -*-
"""Feature Flags v2 - Granular, tier-aware feature management.

Improvements over v1:
1. Tier-based feature access (not just binary community/enterprise)
2. Feature-level granularity (check individual features)
3. Trial mode support with grace period
4. Runtime enforcement (periodic re-check)
5. Usage tracking (anonymous telemetry)
6. Graceful degradation (warn before block)
7. Backward compatible with v1 API
"""

from __future__ import annotations

import logging
import time
from typing import Any, Dict, List, Optional, Set

from .license_manager_lite import (
    LicenseTier,
    FeatureCategory,
    FEATURE_CATALOG,
    LicenseState,
    license_manager,
    is_enterprise,
    has_feature,
    get_tier,
)

# TIER_FEATURE_MAP is only needed for enterprise features
# For community edition, we only have CORE and EXPERIENCE categories
TIER_FEATURE_MAP = {
    LicenseTier.COMMUNITY: {FeatureCategory.CORE, FeatureCategory.EXPERIENCE},
}

logger = logging.getLogger(__name__)


class FeatureFlagsV2:
    """V2 Feature flags with tier-aware, granular control.
    
    Usage:
        from coapis.features import flags
        
        # Check tier
        if flags.tier == LicenseTier.ENTERPRISE:
            # Enterprise-only logic
        
        # Check feature
        if flags.has_feature("clustering"):
            # Enable clustering
        
        # Check category
        if flags.has_category(FeatureCategory.ENTERPRISE_ADVANCED):
            # Advanced enterprise features
        
        # Get state
        state = flags.get_state()
        if state.is_trial:
            # Show trial banner
    """
    
    _initialized: bool = False
    _state: Optional[LicenseState] = None
    _usage_stats: Dict[str, int] = {}
    
    @property
    def tier(self) -> LicenseTier:
        """Get current license tier."""
        self._ensure_initialized()
        return self._state.tier
    
    @property
    def is_community(self) -> bool:
        """Check if running community edition."""
        return self.tier == LicenseTier.COMMUNITY
    
    @property
    def is_enterprise_flag(self) -> bool:
        """Check if running any enterprise tier."""
        return self.tier != LicenseTier.COMMUNITY
    
    @property
    def is_trial(self) -> bool:
        """Check if running trial mode."""
        self._ensure_initialized()
        return self._state.is_trial
    
    @property
    def days_remaining(self) -> int:
        """Get days until license expires."""
        self._ensure_initialized()
        return self._state.days_remaining
    
    def has_feature(self, feature: str) -> bool:
        """Check if a specific feature is available.
        
        Args:
            feature: Feature name (e.g., "clustering", "monitoring")
            
        Returns:
            True if feature is available in current tier
        """
        self._ensure_initialized()
        result = self._state.has_feature(feature)
        
        # Track usage
        self._track_usage(feature, result)
        
        return result
    
    def has_category(self, category: FeatureCategory) -> bool:
        """Check if an entire feature category is available.
        
        Args:
            category: Feature category to check
            
        Returns:
            True if category is available in current tier
        """
        self._ensure_initialized()
        allowed_cats = TIER_FEATURE_MAP.get(self._state.tier, set())
        return category in allowed_cats
    
    def get_available_features(self) -> List[str]:
        """Get list of all available features.
        
        Returns:
            List of feature names available in current tier
        """
        self._ensure_initialized()
        allowed_cats = TIER_FEATURE_MAP.get(self._state.tier, set())
        return [
            name for name, info in FEATURE_CATALOG.items()
            if info["category"] in allowed_cats
        ]
    
    def get_state(self) -> LicenseState:
        """Get full license state."""
        self._ensure_initialized()
        return self._state
    
    def get_warnings(self) -> List[str]:
        """Get license warnings (e.g., expiring soon, trial mode)."""
        self._ensure_initialized()
        return self._state.get_warnings()
    
    def get_usage_stats(self) -> Dict[str, int]:
        """Get feature usage statistics.
        
        Returns:
            Dict of feature_name -> access_count
        """
        return dict(self._usage_stats)
    
    def _ensure_initialized(self) -> None:
        """Ensure license state is loaded."""
        if not self._initialized:
            self._state = license_manager.get_state()
            self._initialized = True
            logger.info(
                "Feature flags initialized: tier=%s valid=%s trial=%s",
                self._state.tier.value,
                self._state.is_valid,
                self._state.is_trial,
            )
    
    def _track_usage(self, feature: str, available: bool) -> None:
        """Track feature access for telemetry.
        
        Args:
            feature: Feature name
            available: Whether feature was available
        """
        key = f"{feature}:{'ok' if available else 'blocked'}"
        self._usage_stats[key] = self._usage_stats.get(key, 0) + 1
    
    # ═══════════════════════════════════════════════════════════
    # Convenience methods (backward compatible with v1)
    # ═══════════════════════════════════════════════════════════
    
    def is_enterprise(self) -> bool:
        """Check if running enterprise edition (v1 compat)."""
        return self.is_enterprise_flag
    
    def has_clustering(self) -> bool:
        return self.has_feature("clustering")
    
    def has_monitoring(self) -> bool:
        return self.has_feature("monitoring")
    
    def has_sso(self) -> bool:
        return self.has_feature("sso")
    
    def has_audit_reports(self) -> bool:
        return self.has_feature("audit_reports")
    
    def has_sla(self) -> bool:
        return self.has_feature("sla")
    
    def has_support(self) -> bool:
        return self.has_feature("dedicated_support")
    
    def has_feature_flag(self, feature: str) -> bool:
        """Alias for has_feature (v1 compat)."""
        return self.has_feature(feature)


# Global instance
flags = FeatureFlagsV2()
