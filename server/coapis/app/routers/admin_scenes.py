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

"""Scene Admin API routes.

This module provides admin API endpoints for scene management:
- Create scene
- Update scene
- Delete scene
- Manage scene agent
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status

from ...models.scene import (
    SceneConfig,
    SceneConfigCreate,
    SceneConfigUpdate,
    SceneListResponse,
    SceneAgentConfig,
)
from ...services.scene_agent_service import SceneAgentService
from ...exceptions import SceneNotFoundError
from ..auth import get_current_user, require_permission

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/admin/scenes", tags=["admin-scenes"])


# ---------------------------------------------------------------------------
# Scene Service Dependency
# ---------------------------------------------------------------------------

def get_scene_service() -> SceneAgentService:
    """Get scene service instance."""
    data_dir = Path(__file__).parent.parent.parent / "data"
    return SceneAgentService(data_dir=data_dir)


# ---------------------------------------------------------------------------
# Admin API Endpoints
# ---------------------------------------------------------------------------

@router.get("", response_model=SceneListResponse)
@require_permission("scene:read")
async def admin_list_scenes(
    status: Optional[str] = Query(None, description="Filter by status"),
    category: Optional[str] = Query(None, description="Filter by category"),
    tag: Optional[str] = Query(None, description="Filter by tag"),
    current_user: dict = Depends(get_current_user),
    service: SceneAgentService = Depends(get_scene_service),
) -> SceneListResponse:
    """Admin: List all scenes (including disabled/deleted).
    
    Requires 'scene:read' permission.
    
    Args:
        status: Filter by status
        category: Filter by category
        tag: Filter by tag
    
    Returns:
        SceneListResponse with scene list
    """
    logger.info(f"Admin {current_user.get('username')} listing scenes")
    return service.list_scenes(status=status, category=category, tag=tag)


@router.post("", response_model=SceneConfig, status_code=status.HTTP_201_CREATED)
@require_permission("scene:create")
async def create_scene(
    request: SceneConfigCreate,
    current_user: dict = Depends(get_current_user),
    service: SceneAgentService = Depends(get_scene_service),
) -> SceneConfig:
    """Admin: Create a new scene.
    
    Requires 'scene:create' permission.
    
    This endpoint:
    1. Creates scene configuration in scenes.json
    2. Creates scene agent directory and configuration
    
    Args:
        request: Scene creation request
    
    Returns:
        Created SceneConfig
    
    Raises:
        HTTPException: 400 if scene ID already exists
    """
    username = current_user.get("username", "admin")
    
    try:
        result = service.create_scene(
            scene_create=request,
            created_by=username,
        )
        
        logger.info(f"Admin {username} created scene: {result.id}")
        return result
        
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e),
        )


@router.get("/{scene_id}", response_model=SceneConfig)
@require_permission("scene:read")
async def admin_get_scene(
    scene_id: str,
    current_user: dict = Depends(get_current_user),
    service: SceneAgentService = Depends(get_scene_service),
) -> SceneConfig:
    """Admin: Get scene details by ID.
    
    Requires 'scene:read' permission.
    
    Args:
        scene_id: Scene ID
    
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
    
    logger.info(f"Admin {current_user.get('username')} viewing scene: {scene_id}")
    return scene


@router.patch("/{scene_id}", response_model=SceneConfig)
@require_permission("scene:update")
async def update_scene(
    scene_id: str,
    request: SceneConfigUpdate,
    current_user: dict = Depends(get_current_user),
    service: SceneAgentService = Depends(get_scene_service),
) -> SceneConfig:
    """Admin: Update scene configuration.
    
    Requires 'scene:update' permission.
    
    Args:
        scene_id: Scene ID
        request: Scene update request
    
    Returns:
        Updated SceneConfig
    
    Raises:
        HTTPException: 404 if scene not found
    """
    result = service.update_scene(scene_id, request)
    if not result:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Scene not found: {scene_id}",
        )
    
    logger.info(f"Admin {current_user.get('username')} updated scene: {scene_id}")
    return result


@router.delete("/{scene_id}")
@require_permission("scene:delete")
async def delete_scene(
    scene_id: str,
    hard_delete: bool = Query(False, description="Permanently delete scene"),
    current_user: dict = Depends(get_current_user),
    service: SceneAgentService = Depends(get_scene_service),
) -> dict:
    """Admin: Delete scene (soft delete by default).
    
    Requires 'scene:delete' permission.
    
    Args:
        scene_id: Scene ID
        hard_delete: If True, permanently delete scene and agent
    
    Returns:
        Success message
    
    Raises:
        HTTPException: 404 if scene not found
    """
    success = service.delete_scene(scene_id, hard_delete=hard_delete)
    if not success:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Scene not found: {scene_id}",
        )
    
    action = "permanently deleted" if hard_delete else "deleted"
    logger.info(f"Admin {current_user.get('username')} {action} scene: {scene_id}")
    
    return {
        "success": True,
        "message": f"Scene {action}: {scene_id}",
    }


@router.get("/{scene_id}/agent", response_model=SceneAgentConfig)
@require_permission("scene:read")
async def get_scene_agent(
    scene_id: str,
    current_user: dict = Depends(get_current_user),
    service: SceneAgentService = Depends(get_scene_service),
) -> SceneAgentConfig:
    """Admin: Get scene agent configuration.
    
    Requires 'scene:read' permission.
    
    Args:
        scene_id: Scene ID
    
    Returns:
        SceneAgentConfig with scene agent details
    
    Raises:
        HTTPException: 404 if scene or agent not found
    """
    agent = service.get_scene_agent(scene_id)
    if not agent:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Scene agent not found: {scene_id}",
        )
    
    logger.info(f"Admin {current_user.get('username')} viewing scene agent: {scene_id}")
    return agent
