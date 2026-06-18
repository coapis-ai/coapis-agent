# -*- coding: utf-8 -*-
"""Stub endpoints for enterprise features (shown when enterprise not installed).

These endpoints provide upgrade prompts and feature previews.
They are replaced by actual implementations when coapis-enterprise is installed.

This module is part of the open-source package and is safe to distribute.
The actual enterprise feature implementations are in the commercial package.

License:
    Apache-2.0 (open source)
"""

from __future__ import annotations

import logging
from typing import Any, Dict

from fastapi import APIRouter, HTTPException

logger = logging.getLogger(__name__)

router = APIRouter(tags=["enterprise-stubs"])


# ═══════════════════════════════════════════════════════════
# Feature Previews (safe to expose in open source)
# ═══════════════════════════════════════════════════════════

FEATURE_PREVIEWS: Dict[str, Dict[str, Any]] = {
    "clustering": {
        "name": "Clustering",
        "description": "Run CoApis across multiple nodes for high availability and horizontal scaling",
        "category": "enterprise_basic",
        "benefits": [
            "High availability with automatic failover",
            "Horizontal scaling to handle more users",
            "Load balancing across nodes",
        ],
        "min_tier": "starter",
    },
    "monitoring": {
        "name": "Monitoring Dashboard",
        "description": "Real-time system monitoring, metrics collection, and alerting",
        "category": "enterprise_basic",
        "benefits": [
            "System health metrics and dashboards",
            "Error tracking and alerting",
            "Performance insights and bottleneck detection",
        ],
        "min_tier": "starter",
    },
    "sso": {
        "name": "SSO Integration",
        "description": "Single Sign-On support for enterprise identity providers (SAML/OIDC)",
        "category": "enterprise_advanced",
        "benefits": [
            "Centralized user management",
            "SAML 2.0 and OIDC support",
            "Seamless enterprise integration",
        ],
        "min_tier": "professional",
    },
    "audit": {
        "name": "Audit Reports",
        "description": "Comprehensive audit logging and compliance reporting",
        "category": "enterprise_advanced",
        "benefits": [
            "Detailed activity audit logs",
            "Compliance reporting (SOC2, GDPR)",
            "Tamper-proof log storage",
        ],
        "min_tier": "professional",
    },
}


# ═══════════════════════════════════════════════════════════
# Stub Endpoints
# ═══════════════════════════════════════════════════════════


@router.get("/enterprise/overview")
async def enterprise_overview() -> Dict[str, Any]:
    """Get enterprise features overview (always available).
    
    This endpoint is always available, even in Community edition.
    It shows what enterprise features exist and how to unlock them.
    """
    from ..enterprise_plugin import is_enterprise_installed
    
    return {
        "current_tier": "community",
        "enterprise_installed": is_enterprise_installed(),
        "features": [
            {
                "id": feature_id,
                "name": preview["name"],
                "description": preview["description"],
                "category": preview["category"],
                "available": False,
                "preview": True,
                "min_tier": preview["min_tier"],
            }
            for feature_id, preview in FEATURE_PREVIEWS.items()
        ],
        "upgrade_url": "https://coapis.dev/enterprise",
        "trial_available": True,
        "trial_url": "/api/license/trial/start",
    }


@router.get("/enterprise/{feature}/preview")
async def feature_preview(feature: str) -> Dict[str, Any]:
    """Get feature preview (always available).
    
    Provides a glimpse of what the feature does without exposing
    implementation details. Safe to expose in open source.
    
    Args:
        feature: Feature ID (e.g., "clustering", "monitoring")
    """
    preview = FEATURE_PREVIEWS.get(feature)
    if not preview:
        raise HTTPException(status_code=404, detail=f"Feature '{feature}' not found")
    
    return {
        "feature": feature,
        "name": preview["name"],
        "description": preview["description"],
        "category": preview["category"],
        "benefits": preview["benefits"],
        "min_tier": preview["min_tier"],
        "upgrade_url": "https://coapis.dev/enterprise",
        "trial_available": True,
    }


@router.get("/enterprise/{feature}/status")
async def feature_status(feature: str) -> Dict[str, Any]:
    """Get feature status (stub - returns upgrade prompt).
    
    When coapis-enterprise is installed, this endpoint is replaced
    by the actual implementation. Otherwise, it returns an upgrade prompt.
    
    Args:
        feature: Feature ID (e.g., "clustering", "monitoring")
    """
    from ..enterprise_plugin import check_enterprise_feature
    
    result = check_enterprise_feature(feature)
    
    if result["available"]:
        # Enterprise plugin is available - this shouldn't happen with stub
        # (the real router should handle this)
        return {"status": "available", "feature": feature}
    
    # Return upgrade prompt
    raise HTTPException(status_code=402, detail=result)
