# -*- coding: utf-8 -*-
"""CoApis Enterprise - Commercial features with graceful upgrade prompts.

This module provides enterprise-grade features with:
- Graceful degradation (upgrade prompts instead of 402 errors)
- Trial mode support
- Feature preview for unlicensed features
- Tier-based access control

Features:
    - Clustering (P2-1)
    - Monitoring (P2-2)
    - SSO Integration (P2-3)
    - Audit Reports (P2-4)
    - Skill Market (P3-1)

License Required:
    Set COAPIS_EDITION=enterprise and COAPIS_LICENSE_KEY
    to enable these features.

Note:
    The actual implementation is in the coapis-enterprise package.
    This module provides stub implementations with upgrade prompts.
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, HTTPException

from ...features import flags, LicenseTier, FeatureCategory
from ...license_manager import license_manager

logger = logging.getLogger(__name__)


# ═══════════════════════════════════════════════════════════
# Enterprise Feature Check with Graceful Degradation
# ═══════════════════════════════════════════════════════════

def _check_enterprise(
    feature_name: str,
    raise_error: bool = True,
) -> Optional[Dict[str, Any]]:
    """Check if enterprise feature is available.
    
    Args:
        feature_name: Name of the enterprise feature
        raise_error: If True, raise HTTPException when blocked
        
    Returns:
        None if feature is available, or upgrade prompt dict if blocked
    """
    state = flags.get_state()
    
    if state.has_feature(feature_name):
        return None  # Feature is available
    
    # Build upgrade prompt
    upgrade_prompt = {
        "blocked": True,
        "feature": feature_name,
        "current_tier": state.tier.value,
        "message": f"'{feature_name}' requires a higher license tier",
        "upgrade_url": "https://coapis.dev/enterprise",
    }
    
    # Add trial info if available
    if state.tier == LicenseTier.COMMUNITY and not state.is_trial:
        upgrade_prompt["trial_available"] = True
        upgrade_prompt["trial_url"] = "/api/license/trial/start"
        upgrade_prompt["message"] = f"'{feature_name}' is available in our trial. Start a 30-day free trial!"
    
    # Add feature preview
    upgrade_prompt["preview"] = _get_feature_preview(feature_name)
    
    if raise_error:
        raise HTTPException(
            status_code=402,
            detail=upgrade_prompt,
        )
    
    return upgrade_prompt


def _get_feature_preview(feature_name: str) -> Dict[str, Any]:
    """Get feature preview information.
    
    Provides a glimpse of what the feature does without exposing implementation.
    """
    previews = {
        "clustering": {
            "description": "Deploy CoApis across multiple nodes for high availability",
            "benefits": [
                "Horizontal scaling",
                "Fault tolerance",
                "Load balancing",
                "Zero-downtime updates",
            ],
            "demo_available": True,
        },
        "monitoring": {
            "description": "Real-time monitoring dashboard with Grafana integration",
            "benefits": [
                "System metrics (CPU, memory, disk)",
                "Business metrics (QPS, latency, errors)",
                "Agent health monitoring",
                "Custom alerting rules",
            ],
            "demo_available": True,
        },
        "sso": {
            "description": "Enterprise SSO integration (LDAP, AD, OAuth2, SAML)",
            "benefits": [
                "Centralized user management",
                "Reduced admin overhead",
                "Compliance with security policies",
                "Seamless user experience",
            ],
            "demo_available": False,
        },
        "audit_reports": {
            "description": "Compliance audit reports for SOC2, GDPR, HIPAA",
            "benefits": [
                "Automated report generation",
                "Audit trail retention",
                "Compliance dashboards",
                "Export to PDF/CSV",
            ],
            "demo_available": True,
        },
        "skill_market": {
            "description": "Official skill marketplace with curated skills",
            "benefits": [
                "Browse and install skills",
                "Skill ratings and reviews",
                "Automated updates",
                "Skill certification",
            ],
            "demo_available": True,
        },
        "sla": {
            "description": "Service Level Agreement guarantees",
            "benefits": [
                "99.9% uptime guarantee",
                "Performance SLAs",
                "Credit compensation",
                "Dedicated support",
            ],
            "demo_available": False,
        },
        "dedicated_support": {
            "description": "24/7 dedicated support team",
            "benefits": [
                "Priority response",
                "Dedicated account manager",
                "Custom integrations",
                "Training sessions",
            ],
            "demo_available": False,
        },
    }
    
    return previews.get(feature_name, {
        "description": f"Enterprise feature: {feature_name}",
        "benefits": ["Contact sales for details"],
        "demo_available": False,
    })


# ═══════════════════════════════════════════════════════════
# Enterprise Feature Routers with Upgrade Prompts
# ═══════════════════════════════════════════════════════════

# P2-1 Clustering
clustering_router = APIRouter(tags=["enterprise/clustering"], prefix="/enterprise")


@clustering_router.get("/cluster/status")
async def get_cluster_status() -> Dict[str, Any]:
    """Get cluster status.
    
    Returns upgrade prompt if not licensed.
    """
    prompt = _check_enterprise("clustering", raise_error=False)
    
    if prompt:
        return {
            "status": "unavailable",
            "upgrade_prompt": prompt,
        }
    
    return {
        "status": "standalone",
        "nodes": 1,
        "message": "Clustering feature stub - requires enterprise license",
    }


@clustering_router.get("/cluster/preview")
async def get_cluster_preview() -> Dict[str, Any]:
    """Get clustering feature preview (available in all editions)."""
    return {
        "feature": "clustering",
        "preview": _get_feature_preview("clustering"),
        "upgrade_url": "https://coapis.dev/enterprise",
        "trial_available": flags.tier == LicenseTier.COMMUNITY and not flags.is_trial,
    }


# P2-2 Monitoring
monitoring_router = APIRouter(tags=["enterprise/monitoring"], prefix="/enterprise")


@monitoring_router.get("/monitoring/dashboard")
async def get_monitoring_dashboard() -> Dict[str, Any]:
    """Get monitoring dashboard data.
    
    Returns upgrade prompt if not licensed.
    """
    prompt = _check_enterprise("monitoring", raise_error=False)
    
    if prompt:
        return {
            "status": "unavailable",
            "upgrade_prompt": prompt,
        }
    
    return {
        "metrics": {},
        "message": "Monitoring feature stub - requires enterprise license",
    }


@monitoring_router.get("/monitoring/preview")
async def get_monitoring_preview() -> Dict[str, Any]:
    """Get monitoring feature preview (available in all editions)."""
    return {
        "feature": "monitoring",
        "preview": _get_feature_preview("monitoring"),
        "upgrade_url": "https://coapis.dev/enterprise",
        "trial_available": flags.tier == LicenseTier.COMMUNITY and not flags.is_trial,
    }


# P2-3 SSO
sso_router = APIRouter(tags=["enterprise/sso"], prefix="/enterprise")


@sso_router.get("/sso/config")
async def get_sso_config() -> Dict[str, Any]:
    """Get SSO configuration.
    
    Returns upgrade prompt if not licensed.
    """
    prompt = _check_enterprise("sso", raise_error=False)
    
    if prompt:
        return {
            "status": "unavailable",
            "upgrade_prompt": prompt,
        }
    
    return {
        "providers": [],
        "message": "SSO feature stub - requires enterprise license",
    }


@sso_router.get("/sso/preview")
async def get_sso_preview() -> Dict[str, Any]:
    """Get SSO feature preview (available in all editions)."""
    return {
        "feature": "sso",
        "preview": _get_feature_preview("sso"),
        "upgrade_url": "https://coapis.dev/enterprise",
        "trial_available": flags.tier == LicenseTier.COMMUNITY and not flags.is_trial,
    }


# P2-4 Audit Reports
audit_router = APIRouter(tags=["enterprise/audit"], prefix="/enterprise")


@audit_router.get("/audit/reports")
async def get_audit_reports() -> Dict[str, Any]:
    """Get audit reports.
    
    Returns upgrade prompt if not licensed.
    """
    prompt = _check_enterprise("audit_reports", raise_error=False)
    
    if prompt:
        return {
            "status": "unavailable",
            "upgrade_prompt": prompt,
        }
    
    return {
        "reports": [],
        "message": "Audit reports feature stub - requires enterprise license",
    }


@audit_router.get("/audit/preview")
async def get_audit_preview() -> Dict[str, Any]:
    """Get audit reports feature preview (available in all editions)."""
    return {
        "feature": "audit_reports",
        "preview": _get_feature_preview("audit_reports"),
        "upgrade_url": "https://coapis.dev/enterprise",
        "trial_available": flags.tier == LicenseTier.COMMUNITY and not flags.is_trial,
    }


# P3-1 Skill Market
skill_market_router = APIRouter(tags=["enterprise/skill-market"], prefix="/enterprise")


@skill_market_router.get("/market/skills")
async def get_market_skills() -> Dict[str, Any]:
    """Get skills from the marketplace.
    
    Returns upgrade prompt if not licensed.
    """
    prompt = _check_enterprise("skill_market", raise_error=False)
    
    if prompt:
        return {
            "status": "unavailable",
            "upgrade_prompt": prompt,
        }
    
    return {
        "skills": [],
        "message": "Skill market feature stub - requires enterprise license",
    }


@skill_market_router.get("/market/preview")
async def get_market_preview() -> Dict[str, Any]:
    """Get skill market feature preview (available in all editions)."""
    return {
        "feature": "skill_market",
        "preview": _get_feature_preview("skill_market"),
        "upgrade_url": "https://coapis.dev/enterprise",
        "trial_available": flags.tier == LicenseTier.COMMUNITY and not flags.is_trial,
    }


# ═══════════════════════════════════════════════════════════
# Enterprise Overview Endpoint
# ═══════════════════════════════════════════════════════════

enterprise_router = APIRouter(tags=["enterprise"], prefix="/enterprise")


@enterprise_router.get("/overview")
async def get_enterprise_overview() -> Dict[str, Any]:
    """Get enterprise features overview.
    
    Available in all editions. Shows what's available and what requires upgrade.
    """
    state = flags.get_state()
    
    # Get all enterprise features with status
    enterprise_features = []
    for name, info in {
        "clustering": {"category": FeatureCategory.ENTERPRISE_ADVANCED, "description": "Multi-node clustering"},
        "monitoring": {"category": FeatureCategory.ENTERPRISE_BASIC, "description": "Monitoring dashboard"},
        "sso": {"category": FeatureCategory.ENTERPRISE_ADVANCED, "description": "SSO integration"},
        "audit_reports": {"category": FeatureCategory.ENTERPRISE_ADVANCED, "description": "Compliance reports"},
        "skill_market": {"category": FeatureCategory.ENTERPRISE_PREMIUM, "description": "Skill marketplace"},
        "sla": {"category": FeatureCategory.ENTERPRISE_PREMIUM, "description": "SLA guarantees"},
        "dedicated_support": {"category": FeatureCategory.ENTERPRISE_PREMIUM, "description": "24/7 support"},
    }.items():
        available = state.has_feature(name)
        enterprise_features.append({
            "name": name,
            "description": info["description"],
            "available": available,
            "preview_available": True,
            "preview_url": f"/api/enterprise/{name}/preview",
        })
    
    return {
        "current_tier": state.tier.value,
        "is_enterprise": state.tier != LicenseTier.COMMUNITY,
        "is_trial": state.is_trial,
        "days_remaining": state.days_remaining,
        "features": enterprise_features,
        "available_count": sum(1 for f in enterprise_features if f["available"]),
        "total_count": len(enterprise_features),
        "upgrade_url": "https://coapis.dev/enterprise",
        "trial_available": state.tier == LicenseTier.COMMUNITY and not state.is_trial,
        "trial_url": "/api/license/trial/start" if (state.tier == LicenseTier.COMMUNITY and not state.is_trial) else None,
    }
