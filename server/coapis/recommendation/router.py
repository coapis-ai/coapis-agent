# -*- coding: utf-8 -*-
# Copyright 2026 蜜蜂 & CoApis Contributors
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

"""Recommendation API router.

Endpoints:
- GET  /api/recommendations           - Get recommendations
- POST /api/recommendations/feedback  - Record user feedback
- GET  /api/recommendations/scenes    - List available scenes
"""

from __future__ import annotations

import logging
from typing import Any, Dict, Optional

from fastapi import APIRouter, HTTPException, Query, Request
from pydantic import BaseModel

from .engine import get_recommendations, get_engine
from .models import SceneConfig
from .store import get_store

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/recommendations", tags=["recommendations"])


# ---------------------------------------------------------------------------
# Request/Response models
# ---------------------------------------------------------------------------

class FeedbackRequest(BaseModel):
    """User feedback on a recommendation."""
    recommendation_id: str
    action: str  # click, dismiss, hide
    scene: Optional[str] = None


class SceneConfigResponse(BaseModel):
    """Scene configuration."""
    scene: str
    max_items: int
    strategies: list[str]
    layout: str


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------

@router.get("")
async def get_recommendations_endpoint(
    request: Request,
    scene: str = Query("chat_welcome", description="Scene identifier"),
    limit: Optional[int] = Query(None, ge=1, le=20, description="Max items"),
    category: Optional[str] = Query(None, description="Filter by category"),
):
    """Get recommendations for the current user.
    
    Args:
        scene: Scene identifier (chat_welcome, sidebar, skill_market, dashboard)
        limit: Maximum number of recommendations
        category: Filter by category (skill, history, context, popularity)
    
    Returns:
        RecommendationResponse with ranked items
    """
    # Get user ID from request
    user_info = getattr(request.state, "user_info", None)
    user_id = "anonymous"
    if user_info:
        user_id = user_info.get("username") or user_info.get("sub", "anonymous")
    
    # Build context
    context = {
        "scene": scene,
        "category": category,
    }
    
    # Check if new user (for context strategy)
    try:
        from ..user_store import get_user
        user = get_user(user_id)
        if user and user.get("last_login") is None:
            context["is_new_user"] = True
    except Exception:
        pass
    
    try:
        response = get_recommendations(
            user_id=user_id,
            scene=scene,
            limit=limit,
            context=context,
        )
        return response.to_dict()
    except Exception as e:
        logger.error(f"Failed to get recommendations: {e}")
        raise HTTPException(status_code=500, detail="Failed to get recommendations")


@router.post("/feedback")
async def record_feedback(
    request: Request,
    req: FeedbackRequest,
):
    """Record user feedback on a recommendation.
    
    Args:
        recommendation_id: ID of the recommendation
        action: User action (click, dismiss, hide)
        scene: Scene where the action occurred
    """
    user_info = getattr(request.state, "user_info", None)
    user_id = "anonymous"
    if user_info:
        user_id = user_info.get("username") or user_info.get("sub", "anonymous")
    
    # Store feedback
    store = get_store()
    store.record_feedback(
        user_id=user_id,
        recommendation_id=req.recommendation_id,
        action=req.action,
        scene=req.scene,
    )
    
    # Update user preferences if needed
    if req.action == "dismiss":
        store.dismiss_recommendation(user_id, req.recommendation_id)
    
    # Log feedback
    logger.info(
        f"Recommendation feedback: user={user_id}, "
        f"rec={req.recommendation_id}, action={req.action}, scene={req.scene}"
    )
    
    return {"ok": True, "message": "Feedback recorded"}


@router.get("/scenes")
async def list_scenes():
    """List available recommendation scenes and their configurations."""
    engine = get_engine()
    
    scenes = []
    for scene_name, config in engine.scene_configs.items():
        scenes.append({
            "scene": scene_name,
            "max_items": config.max_items,
            "strategies": config.strategies,
            "layout": config.layout,
        })
    
    return {"scenes": scenes}


# ──────────────────────────────────────────────
# Admin Endpoints
# ──────────────────────────────────────────────

class SceneConfigUpdate(BaseModel):
    """Scene configuration update request."""
    max_items: Optional[int] = None
    strategies: Optional[List[str]] = None
    layout: Optional[str] = None


@router.put("/admin/scenes/{scene}")
async def update_scene_config(
    request: Request,
    scene: str,
    update: SceneConfigUpdate,
):
    """Update scene configuration (admin only)."""
    user_info = getattr(request.state, "user_info", None)
    role = user_info.get("role", "user") if user_info else "user"
    
    if role not in ["admin", "superadmin"]:
        raise HTTPException(status_code=403, detail="Admin access required")
    
    engine = get_engine()
    
    # Get current config
    current_config = engine.scene_configs.get(scene)
    if not current_config:
        raise HTTPException(status_code=404, detail=f"Scene '{scene}' not found")
    
    # Update fields
    if update.max_items is not None:
        current_config.max_items = update.max_items
    if update.strategies is not None:
        current_config.strategies = update.strategies
    if update.layout is not None:
        current_config.layout = update.layout
    
    # Save updated config
    engine.scene_configs[scene] = current_config
    
    return {
        "ok": True,
        "scene": scene,
        "config": {
            "max_items": current_config.max_items,
            "strategies": current_config.strategies,
            "layout": current_config.layout,
        },
    }

@router.get("/admin/stats")
async def get_admin_stats(request: Request):
    """Get recommendation statistics (admin only)."""
    user_info = getattr(request.state, "user_info", None)
    role = user_info.get("role", "user") if user_info else "user"
    
    if role not in ["admin", "superadmin"]:
        raise HTTPException(status_code=403, detail="Admin access required")
    
    store = get_store()
    stats = store.get_global_stats()
    
    return stats


@router.get("/admin/user/{user_id}")
async def get_user_stats(
    request: Request,
    user_id: str,
):
    """Get user recommendation statistics (admin only)."""
    user_info = getattr(request.state, "user_info", None)
    role = user_info.get("role", "user") if user_info else "user"
    
    if role not in ["admin", "superadmin"]:
        raise HTTPException(status_code=403, detail="Admin access required")
    
    store = get_store()
    stats = store.get_user_activity_summary(user_id)
    prefs = store.get_user_preferences(user_id)
    
    return {
        "user_id": user_id,
        "activity": stats,
        "preferences": prefs,
    }



