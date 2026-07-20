# -*- coding: utf-8 -*-
"""Enterprise Plugin Interface - Abstract layer for enterprise features.

This module defines the interface that enterprise plugins must implement.
When coapis-enterprise is installed, it registers itself as a plugin
and provides the actual implementation.

When NOT installed, this module provides stub implementations with
upgrade prompts (graceful degradation).

Usage:
    # Check if enterprise is installed
    from coapis.enterprise_plugin import is_enterprise_installed
    if is_enterprise_installed():
        # Enterprise features available
    
    # Check feature availability
    from coapis.enterprise_plugin import check_enterprise_feature
    result = check_enterprise_feature("clustering")
    if not result["available"]:
        # Show upgrade prompt
        print(result["message"])

License:
    Apache-2.0 (open source)
"""

from __future__ import annotations

import logging
from enum import Enum
from typing import Any, Dict, List, Optional, Protocol

logger = logging.getLogger(__name__)


# ═══════════════════════════════════════════════════════════
# Enterprise Feature Identifiers
# ═══════════════════════════════════════════════════════════


class EnterpriseFeature(str, Enum):
    """Enterprise feature identifiers.
    
    These features are only available when coapis-enterprise is installed.
    """
    CLUSTERING = "clustering"
    MONITORING = "monitoring"
    SSO = "sso"
    AUDIT = "audit"


# ═══════════════════════════════════════════════════════════
# Enterprise Plugin Protocol
# ═══════════════════════════════════════════════════════════


class EnterprisePlugin(Protocol):
    """Protocol that enterprise plugins must implement.
    
    The coapis-enterprise package provides an implementation of this
    protocol. When installed, it registers itself via register_enterprise_plugin().
    """
    
    def get_available_features(self) -> List[EnterpriseFeature]:
        """Return list of available enterprise features."""
        ...
    
    def is_feature_available(self, feature: EnterpriseFeature) -> bool:
        """Check if a specific feature is available."""
        ...
    
    def get_feature_router(self, feature: EnterpriseFeature) -> Optional[Any]:
        """Get FastAPI router for a feature (None if not available)."""
        ...
    
    def get_license_manager(self) -> Optional[Any]:
        """Get license manager instance."""
        ...
    
    def get_upgrade_prompt(self, feature: EnterpriseFeature) -> Dict[str, Any]:
        """Get upgrade prompt for a blocked feature."""
        ...


# ═══════════════════════════════════════════════════════════
# Plugin Registry
# ═══════════════════════════════════════════════════════════

_enterprise_plugin: Optional[EnterprisePlugin] = None


def register_enterprise_plugin(plugin: EnterprisePlugin) -> None:
    """Register an enterprise plugin.
    
    Called by coapis-enterprise package on import.
    
    Args:
        plugin: Enterprise plugin implementation
    """
    global _enterprise_plugin
    _enterprise_plugin = plugin
    logger.info("Enterprise plugin registered: %s", plugin.__class__.__name__)


def get_enterprise_plugin() -> Optional[EnterprisePlugin]:
    """Get the registered enterprise plugin (if any).
    
    Returns:
        Enterprise plugin instance, or None if not installed
    """
    return _enterprise_plugin


def is_enterprise_installed() -> bool:
    """Check if enterprise package is installed.
    
    Returns:
        True if coapis-enterprise is installed and registered
    """
    # First check if package is importable
    try:
        import coapis.enterprise
        has_package = True
    except ImportError:
        has_package = False
    
    # Also check if plugin is registered
    has_plugin = _enterprise_plugin is not None
    
    return has_package or has_plugin


# ═══════════════════════════════════════════════════════════
# Graceful Degradation
# ═══════════════════════════════════════════════════════════


def check_enterprise_feature(feature: str) -> Dict[str, Any]:
    """Check if enterprise feature is available.
    
    Returns upgrade prompt if not available.
    
    Args:
        feature: Feature name (e.g., "clustering", "monitoring")
    
    Returns:
        Dict with "available" flag and upgrade prompt if blocked
    """
    plugin = get_enterprise_plugin()
    
    # Check if plugin has the feature
    if plugin:
        try:
            feature_enum = EnterpriseFeature(feature)
            if plugin.is_feature_available(feature_enum):
                return {"available": True, "feature": feature}
        except ValueError:
            # Not an enterprise feature
            pass
    
    # Feature not available - return upgrade prompt
    return {
        "available": False,
        "blocked": True,
        "feature": feature,
        "current_tier": "community",
        "message": f"'{feature}' requires CoApis Enterprise edition",
        "upgrade_url": "https://coapis.dev/enterprise",
        "trial_available": True,
        "trial_url": "/api/license/trial/start",
    }


def get_enterprise_routers() -> List[Any]:
    """Get enterprise routers (if available).
    
    Returns:
        List of FastAPI routers from enterprise plugin
    """
    plugin = get_enterprise_plugin()
    if not plugin:
        return []
    
    routers = []
    for feature in EnterpriseFeature:
        router = plugin.get_feature_router(feature)
        if router:
            routers.append(router)
    
    return routers
