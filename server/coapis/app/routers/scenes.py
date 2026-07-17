# -*- coding: utf-8 -*-
# Copyright 2026 蜜蜂 & CoApis Contributors
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU Affero General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU Affero General Public License for more details.
#
# You should have received a copy of the GNU Affero General Public License
# along with this program.  If not, see <https://www.gnu.org/licenses/>.

"""Scene API routes for users.

This module provides API endpoints for users to interact with scenes:
- List scenes
- Get scene details
- Enter a scene (create chat session)
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from fastapi.responses import JSONResponse

from ...models.scene import (
    SceneConfig,
    SceneListResponse,
    EnterSceneRequest,
    EnterSceneResponse,
)
from ...services.scene_agent_service import SceneAgentService
from ...exceptions import SceneNotFoundError, SceneAgentError
from ..auth import get_current_user

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/scenes", tags=["scenes"])


# ---------------------------------------------------------------------------
# Scene Service Dependency
# ---------------------------------------------------------------------------

def get_scene_service() -> SceneAgentService:
    """Get scene service instance.
    
    Uses data directory from environment or default.
    """
    # Default to server/data
    data_dir = Path(__file__).parent.parent.parent / "data"
    return SceneAgentService(data_dir=data_dir)


# ---------------------------------------------------------------------------
# User API Endpoints
# ---------------------------------------------------------------------------

@router.get("", response_model=SceneListResponse)
async def list_scenes(
    status: Optional[str] = Query(None, description="Filter by status"),
    category: Optional[str] = Query(None, description="Filter by category"),
    tag: Optional[str] = Query(None, description="Filter by tag"),
    current_user: dict = Depends(get_current_user),
    service: SceneAgentService = Depends(get_scene_service),
) -> SceneListResponse:
    """List all available scenes.
    
    Users can filter scenes by status, category, or tag.
    
    Args:
        status: Filter by status (active/disabled/deleted)
        category: Filter by category
        tag: Filter by tag
    
    Returns:
        SceneListResponse with scene list
    """
    logger.info(f"User {current_user.get('username')} listing scenes")
    return service.list_scenes(status=status or "active", category=category, tag=tag)


@router.get("/categories")
async def list_categories(
    current_user: dict = Depends(get_current_user),
    service: SceneAgentService = Depends(get_scene_service),
) -> list[str]:
    """List all unique scene categories.
    
    Returns:
        List of category names
    """
    return service.get_scene_categories()


@router.get("/tags")
async def list_tags(
    current_user: dict = Depends(get_current_user),
    service: SceneAgentService = Depends(get_scene_service),
) -> list[str]:
    """List all unique scene tags.
    
    Returns:
        List of tag names
    """
    return service.get_scene_tags()


@router.get("/{scene_id}", response_model=SceneConfig)
async def get_scene(
    scene_id: str,
    current_user: dict = Depends(get_current_user),
    service: SceneAgentService = Depends(get_scene_service),
) -> SceneConfig:
    """Get scene details by ID.
    
    Args:
        scene_id: Scene ID (e.g., meeting-minutes)
    
    Returns:
        SceneConfig with scene details
    
    Raises:
        HTTPException: 404 if scene not found
    """
    scene = service.get_scene(scene_id)
    if not scene:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Scene not found: {scene_id}",
        )
    
    # Only return active scenes to users
    if scene.status != "active":
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Scene not found: {scene_id}",
        )
    
    logger.info(f"User {current_user.get('username')} viewing scene: {scene_id}")
    return scene


@router.post("/{scene_id}/enter", response_model=EnterSceneResponse)
async def enter_scene(
    scene_id: str,
    request: Optional[EnterSceneRequest] = None,
    current_user: dict = Depends(get_current_user),
    service: SceneAgentService = Depends(get_scene_service),
) -> EnterSceneResponse:
    """Enter a scene - create chat session with scene agent.
    
    This endpoint:
    1. Validates scene exists and is active
    2. Creates or retrieves scene agent
    3. Creates chat session with scene context
    4. Returns scene info and welcome message
    
    Args:
        scene_id: Scene ID (e.g., meeting-minutes)
        request: Optional enter scene request
    
    Returns:
        EnterSceneResponse with chat session info
    
    Raises:
        HTTPException: 404 if scene not found
        HTTPException: 400 if scene is not active
    """
    user_id = current_user.get("username", "anonymous")
    
    try:
        result = service.enter_scene(
            scene_id=scene_id,
            user_id=user_id,
            request=request,
        )
        
        logger.info(f"User {user_id} entered scene: {scene_id}")
        return result
        
    except SceneNotFoundError as e:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(e),
        )
    except SceneAgentError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e),
        )
