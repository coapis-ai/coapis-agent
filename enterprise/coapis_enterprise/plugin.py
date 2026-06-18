# -*- coding: utf-8 -*-
"""Enterprise Plugin Implementation

This module provides the actual implementation of enterprise features.
It auto-registers with the CoApis server at import time.
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

from coapis.enterprise_plugin import (
    EnterpriseFeature,
    EnterprisePlugin,
    register_enterprise_plugin,
    is_enterprise_installed,
)

logger = logging.getLogger(__name__)


class EnterprisePluginImpl(EnterprisePlugin):
    """Enterprise plugin implementation for CoApis.
    
    Provides actual implementations for all enterprise features:
    - Monitoring: System metrics, Prometheus integration, alerting
    - SSO: OIDC/SAML integration with auto-provisioning
    - Skill Market: Curated marketplace with review and ratings
    - Clustering: Multi-node coordination and load balancing
    - Audit: Activity logging and compliance reporting
    """
    
    def __init__(self):
        self._license_manager = None
        self._feature_routers = {}
        self._available_features = self._detect_available_features()
        logger.info(f"CoApis Enterprise plugin initialized with features: {[f.value for f in self._available_features]}")
    
    def _detect_available_features(self) -> List[EnterpriseFeature]:
        """Detect which features are available based on installed dependencies."""
        available = []
        
        # Monitoring is always available in enterprise
        available.append(EnterpriseFeature.MONITORING)
        
        # SSO is always available in enterprise
        available.append(EnterpriseFeature.SSO)
        
        # Skill market is always available in enterprise
        available.append(EnterpriseFeature.SKILL_MARKET)
        
        # Clustering requires additional dependencies
        try:
            import redis  # noqa: F401
            available.append(EnterpriseFeature.CLUSTERING)
        except ImportError:
            logger.info("Clustering feature disabled: redis not installed")
        
        # Audit is always available in enterprise
        available.append(EnterpriseFeature.AUDIT)
        
        return available
    
    def get_available_features(self) -> List[EnterpriseFeature]:
        """Return list of available enterprise features."""
        return self._available_features.copy()
    
    def is_feature_available(self, feature: EnterpriseFeature) -> bool:
        """Check if a specific feature is available."""
        return feature in self._available_features
    
    def get_feature_router(self, feature: EnterpriseFeature) -> Optional[Any]:
        """Get FastAPI router for a feature (None if not available)."""
        if feature not in self._available_features:
            return None
        
        if feature not in self._feature_routers:
            self._feature_routers[feature] = self._load_feature_router(feature)
        
        return self._feature_routers[feature]
    
    def _load_feature_router(self, feature: EnterpriseFeature) -> Optional[Any]:
        """Load router for a specific feature."""
        try:
            if feature == EnterpriseFeature.MONITORING:
                from .monitoring.router import router
                return router
            
            elif feature == EnterpriseFeature.SSO:
                from .sso.router import router
                return router
            
            elif feature == EnterpriseFeature.SKILL_MARKET:
                from .skill_market.router import router
                return router
            
            elif feature == EnterpriseFeature.CLUSTERING:
                from .clustering.router import router
                return router
            
            elif feature == EnterpriseFeature.AUDIT:
                from .audit.router import router
                return router
            
        except ImportError as e:
            logger.warning(f"Failed to load router for {feature.value}: {e}")
            return None
        
        return None
    
    def get_license_manager(self) -> Optional[Any]:
        """Get license manager instance."""
        if self._license_manager is None:
            try:
                from .license_manager import LicenseManager
                self._license_manager = LicenseManager()
            except ImportError as e:
                logger.warning(f"Failed to initialize license manager: {e}")
                return None
        return self._license_manager
    
    def get_upgrade_prompt(self, feature: EnterpriseFeature) -> Dict[str, Any]:
        """Get upgrade prompt for a feature (should not reach here in enterprise)."""
        # In enterprise package, all features should be available
        # This is a fallback in case of licensing issues
        return {
            "feature": feature.value,
            "available": False,
            "message": f"Enterprise feature '{feature.value}' requires valid license",
            "upgrade_url": "https://coapis.dev/enterprise",
            "contact": "sales@coapis.dev",
        }


# Auto-register when enterprise package is imported
_plugin_instance = None


def get_enterprise_plugin() -> EnterprisePluginImpl:
    """Get or create enterprise plugin instance."""
    global _plugin_instance
    if _plugin_instance is None:
        _plugin_instance = EnterprisePluginImpl()
        register_enterprise_plugin(_plugin_instance)
        logger.info("CoApis Enterprise plugin registered successfully")
    return _plugin_instance


# Initialize on import
get_enterprise_plugin()
