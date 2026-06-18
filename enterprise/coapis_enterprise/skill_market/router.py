# -*- coding: utf-8 -*-
"""Enterprise Skill Market API Router.

Provides enhanced skill marketplace endpoints with curation features.
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, HTTPException, Query, Request

from coapis.app.auth import require_admin, require_role

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/skill-market", tags=["enterprise-skill-market"])

# Import registry
from .registry import EnterpriseSkillRegistry

_registry = EnterpriseSkillRegistry()


@router.get("/admin/pending")
async def list_pending_skills(request: Request) -> List[Dict[str, Any]]:
    """List skills pending review.
    
    Enterprise feature: Skill curation workflow.
    """
    require_admin(request)
    
    pending = [
        s.model_dump() 
        for s in _registry._skills.values() 
        if s.review_status == "pending"
    ]
    
    return pending


@router.post("/admin/skills/{name}/approve")
async def approve_skill(request: Request, name: str, notes: str = "") -> Dict[str, Any]:
    """Approve a skill for public listing.
    
    Enterprise feature: Skill curation workflow.
    """
    require_admin(request)
    
    if not _registry.approve_skill(name, notes):
        raise HTTPException(status_code=404, detail=f"Skill '{name}' not found")
    
    return {
        "success": True,
        "message": f"Skill '{name}' approved for public listing",
    }


@router.post("/admin/skills/{name}/reject")
async def reject_skill(request: Request, name: str, reason: str = "") -> Dict[str, Any]:
    """Reject a skill submission.
    
    Enterprise feature: Skill curation workflow.
    """
    require_admin(request)
    
    if not _registry.reject_skill(name, reason):
        raise HTTPException(status_code=404, detail=f"Skill '{name}' not found")
    
    return {
        "success": True,
        "message": f"Skill '{name}' rejected",
    }


@router.get("/admin/stats")
async def get_marketplace_stats(request: Request) -> Dict[str, Any]:
    """Get marketplace statistics.
    
    Enterprise feature: Analytics and reporting.
    """
    require_admin(request)
    
    return _registry.get_stats()


@router.post("/skills/{name}/reviews")
async def add_skill_review(
    request: Request,
    name: str,
    rating: float = Query(..., ge=1.0, le=5.0),
    comment: str = "",
) -> Dict[str, Any]:
    """Add review for a skill.
    
    Enterprise feature: Review and rating system.
    """
    require_role(request, "user")
    
    user = request.state.username if hasattr(request.state, "username") else "anonymous"
    
    if not _registry.add_review(name, rating, comment, user):
        raise HTTPException(status_code=404, detail=f"Skill '{name}' not found")
    
    return {
        "success": True,
        "message": f"Review added for '{name}'",
    }


@router.get("/skills/{name}/reviews")
async def get_skill_reviews(name: str) -> List[Dict[str, Any]]:
    """Get reviews for a skill."""
    return _registry.get_reviews(name)


@router.get("/enterprise-only")
async def list_enterprise_skills(
    request: Request,
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
) -> Dict[str, Any]:
    """List enterprise-only skills.
    
    Enterprise feature: Enterprise skill marketplace.
    """
    require_role(request, "user")
    
    return _registry.list_skills(
        enterprise_only=True,
        page=page,
        page_size=page_size,
    )
