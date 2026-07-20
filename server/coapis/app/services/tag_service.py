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

"""Tag service for managing tags.

This service provides CRUD operations for tags.
"""

from __future__ import annotations

import json
import logging
from datetime import datetime
from pathlib import Path
from typing import Optional, List

from ...models.tag import (
    TagType,
    TagConfig,
    TagCreateRequest,
    TagUpdateRequest,
    TagListResponse,
    TagTreeItem,
)

logger = logging.getLogger(__name__)


class TagService:
    """Service for managing tags.
    
    Tags are stored in a JSON file: {data_dir}/tags.json
    """
    
    def __init__(self, data_dir: Path):
        """Initialize tag service.
        
        Args:
            data_dir: Data directory path
        """
        self.data_dir = data_dir
        self.tags_file = data_dir / "tags.json"
        self._tags: Optional[List[TagConfig]] = None
    
    def _load_tags(self) -> List[TagConfig]:
        """Load tags from file.
        
        Returns:
            List of tag configurations
        """
        if self._tags is not None:
            return self._tags
        
        if not self.tags_file.exists():
            logger.warning(f"Tags file not found: {self.tags_file}")
            return []
        
        try:
            with open(self.tags_file, 'r', encoding='utf-8') as f:
                data = json.load(f)
            
            tags = []
            for tag_data in data.get("tags", []):
                tags.append(TagConfig(**tag_data))
            
            self._tags = tags
            return tags
        except Exception as e:
            logger.error(f"Failed to load tags: {e}")
            return []
    
    def _save_tags(self, tags: List[TagConfig]) -> None:
        """Save tags to file.
        
        Args:
            tags: List of tag configurations
        """
        # Create data directory if not exists
        self.data_dir.mkdir(parents=True, exist_ok=True)
        
        # Convert to dict (use mode='json' to serialize datetime to ISO string)
        tags_data = {
            "version": "3.0",
            "description": "标签配置文件 - 统一标签系统",
            "tags": [tag.model_dump(mode='json', exclude_none=True) for tag in tags]
        }
        
        # Write to file
        with open(self.tags_file, 'w', encoding='utf-8') as f:
            json.dump(tags_data, f, ensure_ascii=False, indent=2)
        
        # Update cache
        self._tags = tags
        logger.info(f"Saved {len(tags)} tags to {self.tags_file}")
    
    def _generate_id(self, name: str, tag_type: TagType) -> str:
        """Generate tag ID from name.
        
        Args:
            name: Tag name
            tag_type: Tag type
            
        Returns:
            Generated tag ID
        """
        # Convert to lowercase and replace spaces with hyphens
        import re
        base_id = re.sub(r'[^\w\u4e00-\u9fff]+', '-', name.lower()).strip('-')
        
        # Add type suffix
        type_suffix = {
            TagType.DIMENSION: "",
            TagType.CATEGORY: "",
            TagType.INDUSTRY: "-industry",
            TagType.FREQUENCY: "-frequency",
        }
        
        tag_id = f"{base_id}{type_suffix[tag_type]}"
        
        # Check for duplicates
        tags = self._load_tags()
        existing_ids = {t.id for t in tags}
        
        if tag_id not in existing_ids:
            return tag_id
        
        # Add number suffix if duplicate
        counter = 1
        while f"{tag_id}-{counter}" in existing_ids:
            counter += 1
        
        return f"{tag_id}-{counter}"
    
    def list_tags(
        self,
        tag_type: Optional[TagType] = None,
        parent_id: Optional[str] = None,
        show_in_menu: Optional[bool] = None,
        enabled: Optional[bool] = None,
    ) -> TagListResponse:
        """List tags with optional filters.
        
        Args:
            tag_type: Filter by tag type
            parent_id: Filter by parent ID (only for category type)
            show_in_menu: Filter by show_in_menu
            enabled: Filter by enabled status
            
        Returns:
            TagListResponse with filtered tags
        """
        tags = self._load_tags()
        
        # Apply filters
        if tag_type is not None:
            tags = [t for t in tags if t.type == tag_type]
        
        if parent_id is not None:
            tags = [t for t in tags if t.parent_id == parent_id]
        
        if show_in_menu is not None:
            tags = [t for t in tags if t.show_in_menu == show_in_menu]
        
        if enabled is not None:
            tags = [t for t in tags if t.enabled == enabled]
        
        # Sort by sort_order (descending) then by name
        tags.sort(key=lambda t: (-t.sort_order, t.name))
        
        return TagListResponse(tags=tags, total=len(tags))
    
    def get_tag(self, tag_id: str) -> Optional[TagConfig]:
        """Get a tag by ID.
        
        Args:
            tag_id: Tag ID
            
        Returns:
            TagConfig if found, None otherwise
        """
        tags = self._load_tags()
        for tag in tags:
            if tag.id == tag_id:
                return tag
        return None
    
    def create_tag(self, request: TagCreateRequest) -> TagConfig:
        """Create a new tag.
        
        Args:
            request: Tag creation request
            
        Returns:
            Created TagConfig
            
        Raises:
            ValueError: If validation fails
        """
        tags = self._load_tags()
        
        # Validate parent_id for category type
        if request.type == TagType.CATEGORY:
            if not request.parent_id:
                raise ValueError("Category tag must have a parent_id")
            
            # Check if parent exists and is a dimension
            parent = self.get_tag(request.parent_id)
            if not parent:
                raise ValueError(f"Parent tag not found: {request.parent_id}")
            if parent.type != TagType.DIMENSION:
                raise ValueError(f"Parent must be a dimension tag, got: {parent.type}")
        
        # Validate that dimension tags don't have parent_id
        if request.type == TagType.DIMENSION and request.parent_id:
            raise ValueError("Dimension tag cannot have a parent_id")
        
        # Generate ID
        tag_id = self._generate_id(request.name, request.type)
        
        # Check for duplicate ID
        if any(t.id == tag_id for t in tags):
            raise ValueError(f"Tag with ID '{tag_id}' already exists")
        
        # Create tag
        now = datetime.now()
        tag = TagConfig(
            id=tag_id,
            name=request.name,
            icon=request.icon,
            type=request.type,
            parent_id=request.parent_id,
            description=request.description,
            keywords=request.keywords,
            related_skills=request.related_skills,
            sort_order=request.sort_order,
            show_in_menu=request.show_in_menu,
            enabled=request.enabled,
            created_at=now,
            updated_at=now,
        )
        
        # Add to list
        tags.append(tag)
        self._save_tags(tags)
        
        logger.info(f"Created tag: {tag_id} ({tag.name})")
        return tag
    
    def update_tag(self, tag_id: str, request: TagUpdateRequest) -> TagConfig:
        """Update a tag.
        
        Args:
            tag_id: Tag ID to update
            request: Tag update request
            
        Returns:
            Updated TagConfig
            
        Raises:
            ValueError: If tag not found or validation fails
        """
        tags = self._load_tags()
        
        # Find tag
        tag_index = None
        for i, tag in enumerate(tags):
            if tag.id == tag_id:
                tag_index = i
                break
        
        if tag_index is None:
            raise ValueError(f"Tag not found: {tag_id}")
        
        tag = tags[tag_index]
        
        # Validate parent_id if being updated
        if request.parent_id is not None:
            if tag.type == TagType.CATEGORY:
                if request.parent_id:  # Not empty
                    parent = self.get_tag(request.parent_id)
                    if not parent:
                        raise ValueError(f"Parent tag not found: {request.parent_id}")
                    if parent.type != TagType.DIMENSION:
                        raise ValueError(f"Parent must be a dimension tag, got: {parent.type}")
            elif tag.type == TagType.DIMENSION:
                raise ValueError("Dimension tag cannot have a parent_id")
        
        # Update fields
        update_data = request.model_dump(exclude_unset=True)
        for key, value in update_data.items():
            if hasattr(tag, key):
                setattr(tag, key, value)
        
        tag.updated_at = datetime.now()
        
        # Save
        tags[tag_index] = tag
        self._save_tags(tags)
        
        logger.info(f"Updated tag: {tag_id}")
        return tag
    
    def delete_tag(self, tag_id: str, check_usage: bool = True) -> bool:
        """Delete a tag.
        
        Args:
            tag_id: Tag ID to delete
            check_usage: Check if tag is in use
            
        Returns:
            True if deleted
            
        Raises:
            ValueError: If tag not found or in use
        """
        tags = self._load_tags()
        
        # Find tag
        tag_index = None
        tag_to_delete = None
        for i, tag in enumerate(tags):
            if tag.id == tag_id:
                tag_index = i
                tag_to_delete = tag
                break
        
        if tag_index is None:
            raise ValueError(f"Tag not found: {tag_id}")
        
        # Check if tag has children (for dimension tags)
        if tag_to_delete.type == TagType.DIMENSION:
            children = [t for t in tags if t.parent_id == tag_id]
            if children:
                raise ValueError(
                    f"Cannot delete dimension tag with {len(children)} category tags. "
                    "Delete or reassign category tags first."
                )
        
        # TODO: Check if tag is used by scenes (when scene-tag relationship is implemented)
        
        # Remove tag
        tags.pop(tag_index)
        self._save_tags(tags)
        
        logger.info(f"Deleted tag: {tag_id}")
        return True
    
    def get_tag_tree(self) -> List[TagTreeItem]:
        """Get tag tree for hierarchical display.
        
        Returns:
            List of TagTreeItem (dimension tags with children)
        """
        tags = self._load_tags()
        
        # Get dimension tags
        dimensions = [t for t in tags if t.type == TagType.DIMENSION and t.enabled]
        dimensions.sort(key=lambda t: (-t.sort_order, t.name))
        
        # Build tree
        tree = []
        for dim in dimensions:
            # Get category tags under this dimension
            categories = [
                t for t in tags 
                if t.type == TagType.CATEGORY and t.parent_id == dim.id and t.enabled
            ]
            categories.sort(key=lambda t: (-t.sort_order, t.name))
            
            tree_item = TagTreeItem(
                id=dim.id,
                name=dim.name,
                icon=dim.icon,
                type=dim.type,
                children=[
                    TagTreeItem(
                        id=cat.id,
                        name=cat.name,
                        icon=cat.icon,
                        type=cat.type,
                        children=[],
                    )
                    for cat in categories
                ],
            )
            tree.append(tree_item)
        
        return tree
    
    def get_menu_tags(self) -> List[TagTreeItem]:
        """Get tags for workbench menu.
        
        Only returns tags with show_in_menu=True.
        
        Returns:
            List of TagTreeItem
        """
        tags = self._load_tags()
        
        # Get dimension tags with show_in_menu=True
        dimensions = [
            t for t in tags 
            if t.type == TagType.DIMENSION and t.show_in_menu and t.enabled
        ]
        dimensions.sort(key=lambda t: (-t.sort_order, t.name))
        
        # Build tree
        tree = []
        for dim in dimensions:
            # Get category tags under this dimension
            categories = [
                t for t in tags 
                if (t.type == TagType.CATEGORY and 
                    t.parent_id == dim.id and 
                    t.show_in_menu and 
                    t.enabled)
            ]
            categories.sort(key=lambda t: (-t.sort_order, t.name))
            
            tree_item = TagTreeItem(
                id=dim.id,
                name=dim.name,
                icon=dim.icon,
                type=dim.type,
                children=[
                    TagTreeItem(
                        id=cat.id,
                        name=cat.name,
                        icon=cat.icon,
                        type=cat.type,
                        children=[],
                    )
                    for cat in categories
                ],
            )
            tree.append(tree_item)
        
        return tree
