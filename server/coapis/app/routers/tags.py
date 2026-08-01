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

"""Tag API routes for administrators.

This module provides API endpoints for managing tags:
- List tags
- Create tag
- Update tag
- Delete tag
- Get tag tree (for menu rendering)
"""

from __future__ import annotations

import logging
from typing import Optional

from fastapi import APIRouter, HTTPException, Query, Depends
from pydantic import BaseModel

from ...models.tag import (
    TagType,
    TagConfig,
    TagCreateRequest,
    TagUpdateRequest,
    TagListResponse,
    TagTreeItem,
)
from ..services.tag_service import TagService
from ..auth import get_current_user
from ..permissions.decorators import require_permission

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/admin/tags", tags=["tags"])


# Singleton service instance
_tag_service: Optional[TagService] = None


def get_tag_service() -> TagService:
    """Get or create the TagService singleton."""
    global _tag_service
    if _tag_service is None:
        from ...constant import WORKING_DIR
        from pathlib import Path
        _tag_service = TagService(data_dir=Path(WORKING_DIR))
    return _tag_service


@router.get("", response_model=TagListResponse)
@require_permission("tag:read")
async def list_tags(
    tag_type: Optional[TagType] = Query(None, description="Filter by tag type"),
    parent_id: Optional[str] = Query(None, description="Filter by parent tag ID"),
    show_in_menu: Optional[bool] = Query(None, description="Filter by show_in_menu"),
    enabled: Optional[bool] = Query(None, description="Filter by enabled status"),
    current_user: dict = Depends(get_current_user),
):
    """
    List all tags with optional filtering.
    
    Args:
        tag_type: Filter by tag type (dimension/category/industry/frequency)
        parent_id: Filter by parent tag ID (for category tags)
        show_in_menu: Filter by show_in_menu
        enabled: Filter by enabled status
    
    Returns:
        List of tags
    """
    try:
        service = get_tag_service()
        return service.list_tags(
            tag_type=tag_type,
            parent_id=parent_id,
            show_in_menu=show_in_menu,
            enabled=enabled,
        )
    except Exception as e:
        logger.error(f"Failed to list tags: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/tree", response_model=list[TagTreeItem])
async def get_tag_tree(
    current_user: dict = Depends(get_current_user),
):
    """
    Get tag tree for menu rendering.
    
    Returns a hierarchical structure:
    - dimension tags at top level
    - category tags as children (linked by parent_id)
    
    Returns:
        List of tag tree items
    """
    try:
        service = get_tag_service()
        tree = service.get_tag_tree()
        return tree
    except Exception as e:
        logger.error(f"Failed to get tag tree: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/menu", response_model=list[TagTreeItem])
async def get_menu_tags(
    current_user: dict = Depends(get_current_user),
):
    """
    Get tags for workbench menu.
    
    Only returns tags with show_in_menu=True.
    
    Returns:
        List of TagTreeItem
    """
    try:
        service = get_tag_service()
        menu = service.get_menu_tags()
        return menu
    except Exception as e:
        logger.error(f"Failed to get menu tags: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/{tag_id}", response_model=TagConfig)
async def get_tag(
    tag_id: str,
    current_user: dict = Depends(get_current_user),
):
    """
    Get a single tag by ID.
    
    Args:
        tag_id: Tag ID
    
    Returns:
        Tag configuration
    """
    try:
        service = get_tag_service()
        tag = service.get_tag(tag_id)
        if not tag:
            raise HTTPException(status_code=404, detail=f"Tag not found: {tag_id}")
        return tag
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to get tag {tag_id}: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("", response_model=TagConfig)
@require_permission("tag:create")
async def create_tag(
    request: TagCreateRequest,
    current_user: dict = Depends(get_current_user),
):
    """
    Create a new tag.
    
    Args:
        request: Tag creation request
    
    Returns:
        Created tag configuration
    """
    try:
        service = get_tag_service()
        tag = service.create_tag(request)
        logger.info(f"Admin {current_user.get('username')} created tag: {tag.id} ({tag.name})")
        return tag
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.error(f"Failed to create tag: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.put("/{tag_id}", response_model=TagConfig)
@require_permission("tag:update")
async def update_tag(
    tag_id: str,
    request: TagUpdateRequest,
    current_user: dict = Depends(get_current_user),
):
    """
    Update an existing tag.
    
    Args:
        tag_id: Tag ID
        request: Tag update request
    
    Returns:
        Updated tag configuration
    """
    try:
        service = get_tag_service()
        tag = service.update_tag(tag_id, request)
        if not tag:
            raise HTTPException(status_code=404, detail=f"Tag not found: {tag_id}")
        logger.info(f"Admin {current_user.get('username')} updated tag: {tag_id}")
        return tag
    except HTTPException:
        raise
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.error(f"Failed to update tag {tag_id}: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.delete("/{tag_id}")
@require_permission("tag:delete")
async def delete_tag(
    tag_id: str,
    current_user: dict = Depends(get_current_user),
):
    """
    Delete a tag.
    
    Args:
        tag_id: Tag ID
    
    Returns:
        Success status
    """
    try:
        service = get_tag_service()
        success = service.delete_tag(tag_id)
        if not success:
            raise HTTPException(status_code=404, detail=f"Tag not found: {tag_id}")
        logger.info(f"Admin {current_user.get('username')} deleted tag: {tag_id}")
        return {"success": True, "message": f"Tag {tag_id} deleted"}
    except HTTPException:
        raise
    except ValueError as e:
        # E.g., cannot delete tag with scenes
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.error(f"Failed to delete tag {tag_id}: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/migrate")
async def migrate_from_categories():
    """
    Migrate existing categories to tags.
    
    This is a one-time migration endpoint that:
    1. Reads /apps/ai/coapis/categories.json
    2. Creates dimension tags from dimensions
    3. Creates category tags from categories
    4. Links category tags to dimension tags
    
    Returns:
        Migration result
    """
    try:
        service = get_tag_service()
        result = service.migrate_from_categories()
        logger.info(f"Migration completed: {result}")
        return {
            "success": True,
            "message": "Migration completed",
            "details": result,
        }
    except Exception as e:
        logger.error(f"Failed to migrate categories: {e}")
        raise HTTPException(status_code=500, detail=str(e))
