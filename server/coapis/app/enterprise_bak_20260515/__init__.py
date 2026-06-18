# -*- coding: utf-8 -*-
"""CoApis Enterprise - Commercial features module.

This module provides enterprise-grade features with graceful upgrade prompts
instead of blocking 402 errors.

Features:
    - Clustering (P2-1)
    - Monitoring (P2-2)
    - SSO Integration (P2-3)
    - Audit Reports (P2-4)
    - Skill Market (P3-1)

License Required:
    Set COAPIS_EDITION=enterprise and COAPIS_LICENSE_KEY
    to enable these features.

Graceful Degradation:
    When a feature is not licensed, the system returns:
    - Feature preview information
    - Upgrade prompts with pricing
    - Trial mode availability
    - Clear upgrade paths

This approach improves conversion rates by showing value before asking for payment.
"""

from __future__ import annotations

from .features import (
    clustering_router,
    monitoring_router,
    sso_router,
    audit_router,
    skill_market_router,
    enterprise_router,
    _check_enterprise,
    _get_feature_preview,
)

from .license_api import router as license_router

__all__ = [
    "clustering_router",
    "monitoring_router",
    "sso_router",
    "audit_router",
    "skill_market_router",
    "enterprise_router",
    "license_router",
    "_check_enterprise",
    "_get_feature_preview",
]
