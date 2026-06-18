# -*- coding: utf-8 -*-
"""Enterprise License Management API.

Provides REST endpoints for:
- License status checking
- License activation
- License renewal
- Trial mode management
- Usage statistics
- Upgrade prompts

These endpoints are available in ALL editions (to allow upgrade flow).
"""

from __future__ import annotations

import json
import logging
import os
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, HTTPException, Depends

from ...features import flags, LicenseTier, FeatureCategory, FEATURE_CATALOG, TIER_FEATURE_MAP
from ...license_manager import license_manager, generate_license_key, LicenseState
from ...license_crypto import LicenseSigner, LicenseVerifier, generate_keypair

logger = logging.getLogger(__name__)

router = APIRouter(tags=["license"])


# ═══════════════════════════════════════════════════════════
# License Status Endpoints
# ═══════════════════════════════════════════════════════════

@router.get("/license/status")
async def get_license_status() -> Dict[str, Any]:
    """Get current license status.
    
    Available in all editions.
    """
    state = flags.get_state()
    
    return {
        "valid": state.is_valid,
        "tier": state.tier.value,
        "customer": state.customer,
        "issued": state.issued.isoformat() if state.issued else None,
        "expires": state.expires.isoformat() if state.expires else None,
        "days_remaining": state.days_remaining,
        "is_trial": state.is_trial,
        "features": sorted(state.features) if state.features else [],
        "max_nodes": state.max_nodes,
        "max_users": state.max_users,
        "max_agents": state.max_agents,
        "warnings": state.get_warnings(),
        "error": state.error,
    }


@router.get("/license/tier")
async def get_license_tier() -> Dict[str, Any]:
    """Get current license tier and available features.
    
    Available in all editions.
    """
    state = flags.get_state()
    
    # Get available categories for this tier
    allowed_cats = TIER_FEATURE_MAP.get(state.tier, set())
    
    # Build feature list by category
    features_by_category = {}
    for name, info in FEATURE_CATALOG.items():
        cat = info["category"].value
        available = info["category"] in allowed_cats
        if cat not in features_by_category:
            features_by_category[cat] = []
        features_by_category[cat].append({
            "name": name,
            "description": info["description"],
            "available": available,
        })
    
    return {
        "tier": state.tier.value,
        "is_enterprise": state.tier != LicenseTier.COMMUNITY,
        "is_trial": state.is_trial,
        "days_remaining": state.days_remaining,
        "features_by_category": features_by_category,
        "available_features_count": len(flags.get_available_features()),
        "total_features_count": len(FEATURE_CATALOG),
    }


@router.get("/license/features")
async def get_available_features() -> Dict[str, Any]:
    """Get list of available features.
    
    Available in all editions.
    """
    available = flags.get_available_features()
    
    # Get all features with availability status
    all_features = []
    for name, info in FEATURE_CATALOG.items():
        all_features.append({
            "name": name,
            "description": info["description"],
            "category": info["category"].value,
            "available": name in available,
        })
    
    return {
        "available": available,
        "available_count": len(available),
        "total_count": len(FEATURE_CATALOG),
        "features": all_features,
    }


# ═══════════════════════════════════════════════════════════
# License Activation
# ═══════════════════════════════════════════════════════════

@router.post("/license/activate")
async def activate_license(license_key: str) -> Dict[str, Any]:
    """Activate a license key.
    
    Saves the license key to file for persistence.
    Available in all editions.
    
    Args:
        license_key: The license key to activate
        
    Returns:
        Activation result with new license state
    """
    if not license_key:
        raise HTTPException(status_code=400, detail="License key is required")
    
    # Save license
    saved = license_manager.save_license(license_key)
    if not saved:
        raise HTTPException(status_code=500, detail="Failed to save license")
    
    # Reload state
    state = license_manager.get_state()
    
    if not state.is_valid:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid license key: {state.error}",
        )
    
    return {
        "activated": True,
        "tier": state.tier.value,
        "customer": state.customer,
        "expires": state.expires.isoformat() if state.expires else None,
        "days_remaining": state.days_remaining,
        "features": sorted(state.features) if state.features else [],
    }


@router.post("/license/deactivate")
async def deactivate_license() -> Dict[str, Any]:
    """Deactivate current license (revert to community).
    
    Available in all editions.
    """
    try:
        # Remove license file
        if license_manager.LICENSE_FILE.exists():
            license_manager.LICENSE_FILE.unlink()
        
        # Reset state
        license_manager._state = None
        
        # Reload (will get community default)
        state = license_manager.get_state()
        
        return {
            "deactivated": True,
            "tier": state.tier.value,
            "message": "License deactivated. Reverted to Community edition.",
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to deactivate: {e}")


# ═══════════════════════════════════════════════════════════
# Trial Mode
# ═══════════════════════════════════════════════════════════

@router.post("/license/trial/start")
async def start_trial(
    tier: str = LicenseTier.PROFESSIONAL.value,
    duration_days: int = 30,
) -> Dict[str, Any]:
    """Start a trial license.
    
    Generates a trial license key and activates it.
    Available in all editions.
    
    Args:
        tier: Tier to trial (default: Professional)
        duration_days: Trial duration (default: 30 days)
    """
    # Check if already in trial or has enterprise license
    state = flags.get_state()
    if state.is_trial or state.tier != LicenseTier.COMMUNITY:
        raise HTTPException(
            status_code=400,
            detail="Trial already active or enterprise license exists",
        )
    
    # Generate trial license
    try:
        license_key = generate_license_key(
            customer="Trial User",
            tier=LicenseTier(tier),
            duration_days=duration_days,
            trial=True,
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to generate trial: {e}")
    
    # Activate trial
    saved = license_manager.save_license(license_key)
    if not saved:
        raise HTTPException(status_code=500, detail="Failed to save trial license")
    
    # Reload state
    state = license_manager.get_state()
    
    return {
        "trial_started": True,
        "tier": state.tier.value,
        "expires": state.expires.isoformat() if state.expires else None,
        "days_remaining": state.days_remaining,
        "message": f"Trial started for {duration_days} days",
    }


# ═══════════════════════════════════════════════════════════
# Usage Statistics
# ═══════════════════════════════════════════════════════════

@router.get("/license/usage")
async def get_usage_stats() -> Dict[str, Any]:
    """Get feature usage statistics.
    
    Available in all editions.
    """
    stats = flags.get_usage_stats()
    
    # Parse stats
    accessed = 0
    blocked = 0
    feature_stats = {}
    
    for key, count in stats.items():
        parts = key.rsplit(":", 1)
        if len(parts) == 2:
            feature, status = parts
            if feature not in feature_stats:
                feature_stats[feature] = {"accessed": 0, "blocked": 0}
            if status == "ok":
                feature_stats[feature]["accessed"] = count
                accessed += count
            else:
                feature_stats[feature]["blocked"] = count
                blocked += count
    
    return {
        "total_accesses": accessed + blocked,
        "total_blocked": blocked,
        "block_rate": blocked / (accessed + blocked) if (accessed + blocked) > 0 else 0,
        "features": feature_stats,
    }


# ═══════════════════════════════════════════════════════════
# Upgrade Prompts
# ═══════════════════════════════════════════════════════════

@router.get("/license/upgrade-prompt")
async def get_upgrade_prompt(feature: Optional[str] = None) -> Dict[str, Any]:
    """Get upgrade prompt for a blocked feature.
    
    Returns user-friendly upgrade message and options.
    Available in all editions.
    
    Args:
        feature: The blocked feature (optional)
    """
    current_state = flags.get_state()
    current_tier = current_state.tier
    
    # Determine what's needed
    if feature:
        feature_info = FEATURE_CATALOG.get(feature, {})
        required_cat = feature_info.get("category")
        
        # Find minimum tier that has this feature
        required_tier = None
        for tier in LicenseTier:
            if tier == LicenseTier.COMMUNITY:
                continue
            allowed = TIER_FEATURE_MAP.get(tier, set())
            if required_cat and required_cat in allowed:
                required_tier = tier
                break
    else:
        required_tier = None
    
    # Check if feature is blocked
    is_blocked = False
    if feature:
        feature_info = FEATURE_CATALOG.get(feature, {})
        allowed_cats = TIER_FEATURE_MAP.get(current_tier, set())
        is_blocked = feature_info.get("category") not in allowed_cats
    
    # Build prompt
    prompt = {
        "current_tier": current_tier.value,
        "blocked": is_blocked,
        "is_trial": current_state.is_trial,
        "upgrade_available": current_tier != LicenseTier.ENTERPRISE,
        "trial_available": current_tier == LicenseTier.COMMUNITY and not current_state.is_trial,
        "features": {},
    }
    
    if feature and required_tier:
        prompt["upgrade_to"] = required_tier.value
        prompt["message"] = f"'{feature}' requires {required_tier.value} edition or higher"
    
    # Add tier comparison
    prompt["tiers"] = []
    for tier in LicenseTier:
        if tier == LicenseTier.COMMUNITY:
            continue
        allowed_cats = TIER_FEATURE_MAP.get(tier, set())
        tier_features = [
            name for name, info in FEATURE_CATALOG.items()
            if info["category"] in allowed_cats
        ]
        prompt["tiers"].append({
            "tier": tier.value,
            "features_count": len(tier_features),
            "has_requested_feature": feature in tier_features if feature else False,
        })
    
    return prompt


# ═══════════════════════════════════════════════════════════
# License Key Generation (Admin Only)
# ═══════════════════════════════════════════════════════════

@router.post("/license/generate")
async def generate_license(
    customer: str,
    tier: str = LicenseTier.STARTER.value,
    duration_days: int = 365,
    max_nodes: int = 1,
    max_users: int = 10,
    max_agents: int = 5,
) -> Dict[str, Any]:
    """Generate a new license key.
    
    ⚠️ ADMIN ONLY - Requires admin role.
    
    In production, this should be on a separate license server.
    """
    # TODO: Add admin auth check
    
    try:
        license_key = generate_license_key(
            customer=customer,
            tier=LicenseTier(tier),
            duration_days=duration_days,
            max_nodes=max_nodes,
            max_users=max_users,
            max_agents=max_agents,
        )
        
        return {
            "license_key": license_key,
            "customer": customer,
            "tier": tier,
            "duration_days": duration_days,
            "max_nodes": max_nodes,
            "max_users": max_users,
            "max_agents": max_agents,
            "warning": "This is a DEV license. In production, use the license server.",
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to generate license: {e}")


@router.post("/license/keys/generate")
async def generate_license_keys() -> Dict[str, Any]:
    """Generate RSA key pair for license signing.
    
    ⚠️ ADMIN ONLY - Requires admin role.
    
    This generates the private/public key pair used for license signing.
    The private key should be kept secure and never exposed.
    The public key should be embedded in the product.
    """
    # TODO: Add admin auth check
    
    try:
        # Generate keys in /tmp (in production, use secure storage)
        private_path, public_path = generate_keypair("/tmp/coapis-license-keys")
        
        # Read public key content
        with open(public_path, "r") as f:
            public_key_content = f.read()
        
        return {
            "generated": True,
            "private_key_path": private_path,
            "public_key_path": public_path,
            "public_key": public_key_content,
            "instructions": {
                "private_key": "Keep this secure! Set COAPIS_LICENSE_PRIVATE_KEY env var",
                "public_key": "Embed this in license_manager.py or set COAPIS_LICENSE_PUBLIC_KEY env var",
            },
            "warning": "⚠️ PRIVATE KEY MUST BE KEPT SECRET! Never commit to version control.",
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to generate keys: {e}")


@router.post("/license/verify")
async def verify_license_key(body: Dict[str, Any]) -> Dict[str, Any]:
    """Verify a license key without activating it.
    
    Available in all editions.
    
    Expects JSON body: {"license_key": "..."}
    """
    license_key = body.get("license_key", "")
    if not license_key:
        raise HTTPException(status_code=400, detail="license_key is required")
    
    from ...license_crypto import LicenseInfo as CryptoLicenseInfo
    
    # Try RSA verification
    public_key_path = os.environ.get("COAPIS_LICENSE_PUBLIC_KEY")
    if public_key_path and os.path.exists(public_key_path):
        try:
            verifier = LicenseVerifier.load(public_key_path)
            info = verifier.verify(license_key)
            
            return {
                "valid": info.is_valid,
                "error": info.error,
                "customer": info.customer,
                "tier": info.tier,
                "expires": info.expires.isoformat() if info.expires else None,
                "days_remaining": info.days_remaining,
                "is_trial": info.is_trial,
                "features": info.features,
                "verification_method": "RSA",
            }
        except Exception as e:
            raise HTTPException(status_code=400, detail=f"Verification failed: {e}")
    else:
        # Fallback: simple validation
        try:
            import base64
            parts = license_key.split(".")
            if len(parts) != 2:
                return {"valid": False, "error": "Invalid format"}
            
            payload = base64.b64decode(parts[0]).decode()
            data = json.loads(payload)
            
            return {
                "valid": True,
                "customer": data.get("customer", ""),
                "tier": data.get("tier", "community"),
                "expires": data.get("expires"),
                "is_trial": data.get("trial", False),
                "features": data.get("features", []),
                "verification_method": "fallback",
                "warning": "RSA verification not available (no public key configured)",
            }
        except Exception as e:
            return {"valid": False, "error": str(e)}


# ═══════════════════════════════════════════════════════════
# Commercial Security Module Endpoints
# ═══════════════════════════════════════════════════════════

@router.get("/license/security/status")
async def get_security_modules_status() -> Dict[str, Any]:
    """Get status of all commercial security modules.
    
    Available in all editions.
    """
    online_status = license_manager.get_online_validation_status()
    clock_status = license_manager.get_clock_protection_status()
    revocation_status = license_manager.get_revocation_status()
    renewal_status = license_manager.get_renewal_reminders_status()
    
    return {
        "online_validation": {**online_status, "initialized": True},
        "clock_protection": {**clock_status, "initialized": True},
        "revocation": {**revocation_status, "initialized": True},
        "renewal_reminders": {**renewal_status, "initialized": True},
    }


@router.post("/license/security/clock/check")
async def check_clock_status() -> Dict[str, Any]:
    """Check current clock status for rollback detection.
    
    Available in all editions.
    """
    return license_manager.check_clock()


@router.post("/license/security/revoke")
async def revoke_license(body: Dict[str, Any]) -> Dict[str, Any]:
    """Revoke a license.
    
    Admin only.
    
    Expects JSON body: {"license_id": "...", "reason": "..."}
    """
    license_id = body.get("license_id", "")
    reason = body.get("reason", "")
    if not license_id:
        raise HTTPException(status_code=400, detail="license_id is required")
    
    success = license_manager.revoke_license(license_id, reason=reason)
    return {
        "success": success,
        "license_id": license_id,
        "message": f"License {license_id} has been revoked" if success else "Failed to revoke license",
    }


@router.post("/license/security/unrevoke")
async def unrevoke_license(body: Dict[str, Any]) -> Dict[str, Any]:
    """Restore a revoked license.
    
    Admin only.
    
    Expects JSON body: {"license_id": "...", "reason": "..."}
    """
    license_id = body.get("license_id", "")
    reason = body.get("reason", "")
    if not license_id:
        raise HTTPException(status_code=400, detail="license_id is required")
    
    success = license_manager.unrevoke_license(license_id, reason=reason)
    return {
        "success": success,
        "license_id": license_id,
        "message": f"License {license_id} has been restored" if success else "Failed to restore license",
    }


@router.get("/license/security/revocation/check")
async def check_license_revocation(license_id: str) -> Dict[str, Any]:
    """Check if a license has been revoked.
    
    Available in all editions.
    """
    is_revoked = license_manager.check_license_revocation(license_id)
    return {
        "license_id": license_id,
        "is_revoked": is_revoked,
    }


@router.get("/license/renewal/history")
async def get_renewal_history(
    license_id: str = "",
    limit: int = 50,
) -> Dict[str, Any]:
    """Get renewal reminder history.
    
    Available in all editions.
    """
    records = license_manager.get_renewal_history(
        license_id=license_id,
        limit=limit,
    )
    return {
        "records": records,
        "count": len(records),
    }
