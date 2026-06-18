# -*- coding: utf-8 -*-
"""Lightweight License API for Community Edition.

Provides basic license status, tier, features, and upgrade prompt endpoints.
Full license management is available in the enterprise package.
"""

import logging
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field

from ..license_manager_lite import license_manager, LicenseTier
from .auth import get_current_user
from .routers.user.user_me import UserInfoResponse as UserInfo

logger = logging.getLogger(__name__)

router = APIRouter(tags=["license"])


# ═══════════════════════════════════════════════════════════
# Response Models
# ═══════════════════════════════════════════════════════════


class LicenseStatusResponse(BaseModel):
    tier: str = Field(..., description="Current license tier")
    is_enterprise: bool = Field(..., description="Whether enterprise edition is active")
    enterprise_installed: bool = Field(..., description="Whether enterprise package is installed")
    expires_at: str | None = Field(None, description="License expiration time")
    features_count: int = Field(..., description="Number of available features")


class LicenseTierResponse(BaseModel):
    tier: str = Field(..., description="Current license tier")
    label: str = Field(..., description="Human-readable tier label")
    can_upgrade: bool = Field(..., description="Whether upgrade is available")


class LicenseFeaturesResponse(BaseModel):
    tier: str = Field(..., description="Current license tier")
    features: list[str] = Field(..., description="List of available feature IDs")
    total: int = Field(..., description="Total number of available features")


class UpgradePromptResponse(BaseModel):
    feature: str = Field(..., description="Feature ID")
    feature_name: str = Field(..., description="Human-readable feature name")
    current_tier: str = Field(..., description="Current license tier")
    required_tier: str = Field(..., description="Minimum tier required for this feature")
    message: str = Field(..., description="Upgrade prompt message")
    upgrade_url: str = Field(..., description="URL to upgrade")
    trial_available: bool = Field(..., description="Whether trial is available")
    trial_url: str = Field(..., description="URL to start trial")


# ═══════════════════════════════════════════════════════════
# Feature Catalog
# ═══════════════════════════════════════════════════════════

FEATURE_CATALOG = {
    "clustering": {
        "name": "Clustering",
        "description": "Run CoApis across multiple nodes for high availability and horizontal scaling",
        "min_tier": LicenseTier.STARTER,
    },
    "monitoring": {
        "name": "Monitoring Dashboard",
        "description": "Real-time system monitoring, metrics collection, and alerting",
        "min_tier": LicenseTier.STARTER,
    },
    "sso": {
        "name": "SSO Integration",
        "description": "Single Sign-On support for enterprise identity providers (SAML/OIDC)",
        "min_tier": LicenseTier.PROFESSIONAL,
    },
    "audit": {
        "name": "Audit Reports",
        "description": "Comprehensive audit logging and compliance reporting",
        "min_tier": LicenseTier.PROFESSIONAL,
    },
}

TIER_LABELS = {
    LicenseTier.COMMUNITY: "Community",
    LicenseTier.STARTER: "Starter",
    LicenseTier.PROFESSIONAL: "Professional",
    LicenseTier.ENTERPRISE: "Enterprise",
}


# ═══════════════════════════════════════════════════════════
# Endpoints
# ═══════════════════════════════════════════════════════════


@router.get("/license/status", response_model=LicenseStatusResponse)
async def get_license_status(_: UserInfo = Depends(get_current_user)):
    """Get current license status."""
    state = license_manager.get_state()
    return LicenseStatusResponse(
        tier=state.tier.value,
        is_enterprise=state.tier != LicenseTier.COMMUNITY,
        enterprise_installed=license_manager.is_enterprise_package_installed(),
        expires_at=state.expires.isoformat() if state.expires else None,
        features_count=len(state.features),
    )


@router.get("/license/tier", response_model=LicenseTierResponse)
async def get_license_tier(_: UserInfo = Depends(get_current_user)):
    """Get current license tier."""
    tier = license_manager.get_tier()
    return LicenseTierResponse(
        tier=tier.value,
        label=TIER_LABELS.get(tier, tier.value),
        can_upgrade=True,
    )


@router.get("/license/features", response_model=LicenseFeaturesResponse)
async def get_license_features(_: UserInfo = Depends(get_current_user)):
    """Get available features based on current license tier."""
    state = license_manager.get_state()
    return LicenseFeaturesResponse(
        tier=state.tier.value,
        features=list(state.features),
        total=len(state.features),
    )


@router.get("/license/upgrade-prompt", response_model=UpgradePromptResponse)
async def get_upgrade_prompt(
    feature: str,
    _: UserInfo = Depends(get_current_user),
):
    """Get upgrade prompt for a specific feature."""
    feat = FEATURE_CATALOG.get(feature)
    if not feat:
        raise HTTPException(status_code=404, detail=f"Unknown feature: {feature}")

    current_tier = license_manager.get_tier()
    return UpgradePromptResponse(
        feature=feature,
        feature_name=feat["name"],
        current_tier=current_tier.value,
        required_tier=feat["min_tier"].value,
        message=f"Upgrade to {TIER_LABELS[feat['min_tier']]} edition to unlock {feat['name']}",
        upgrade_url="https://coapis.dev/enterprise",
        trial_available=True,
        trial_url="/api/license/trial/start",
    )


@router.get("/license/enterprise-features")
async def get_enterprise_features(_: UserInfo = Depends(get_current_user)):
    """Get list of all enterprise features with details."""
    features = []
    for feat_id, feat_info in FEATURE_CATALOG.items():
        features.append(
            {
                "id": feat_id,
                "name": feat_info["name"],
                "description": feat_info["description"],
                "available": license_manager.has_feature(feat_id),
                "min_tier": feat_info["min_tier"].value,
            }
        )

    return {
        "current_tier": license_manager.get_tier().value,
        "enterprise_installed": license_manager.is_enterprise_package_installed(),
        "features": features,
        "upgrade_url": "https://coapis.dev/enterprise",
    }
