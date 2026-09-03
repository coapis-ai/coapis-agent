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

try:
    from ...enterprise_plugin import is_enterprise_installed, get_enterprise_plugin
except ImportError:
    is_enterprise_installed = lambda: False
    get_enterprise_plugin = lambda: None

logger = logging.getLogger(__name__)


class TagService:
    """Service for managing tags.
    
    In community edition: Tags are stored in a JSON file: {data_dir}/tags.json
    In enterprise edition: Tags are stored in PostgreSQL database via RepositoryFactory.
    """
    
    def __init__(self, data_dir: Path):
        """Initialize tag service.
        
        Args:
            data_dir: Data directory path
        """
        self.data_dir = data_dir
        self.tags_file = data_dir / "tags.json"
        self._enterprise_repo = None
        
        # Check if enterprise repository is available
        if is_enterprise_installed():
            try:
                from ...foundation.repository_factory import RepositoryFactory
                if RepositoryFactory.is_initialized():
                    self._enterprise_repo = RepositoryFactory.get_tag_repository()
                    logger.info("TagService using Enterprise PostgreSQL tag repository")
            except Exception as e:
                logger.warning(f"Failed to get enterprise tag repository: {e}, falling back to JSON")
    
    def _load_tags(self) -> List[TagConfig]:
        """Load tags from file or enterprise repository.
        
        Returns:
            List of tag configurations
        """
        if self._enterprise_repo:
            return self._load_tags_from_repository()
        
        if not self.tags_file.exists():
            logger.warning(f"Tags file not found: {self.tags_file}")
            return []
        
        try:
            with open(self.tags_file, 'r', encoding='utf-8') as f:
                data = json.load(f)
            
            tags = []
            for tag_data in data.get("tags", []):
                tags.append(TagConfig(**tag_data))
            
            return tags
        except Exception as e:
            logger.error(f"Failed to load tags: {e}")
            return []

    def _load_tags_from_repository(self) -> List[TagConfig]:
        """Load tags from enterprise PostgreSQL repository.
        
        Returns:
            List of TagConfig objects
        """
        try:
            db_tags = self._enterprise_repo.list_tags()
            tags = []
            for db_tag in db_tags:
                # Convert SQLAlchemy model to Pydantic TagConfig
                tag_config = TagConfig(
                    id=db_tag.id,
                    name=db_tag.name,
                    icon=getattr(db_tag, 'icon', None),
                    type=TagType(db_tag.type) if hasattr(db_tag, 'type') and db_tag.type else TagType.DIMENSION,
                    parent_id=getattr(db_tag, 'parent_id', None),
                    description=getattr(db_tag, 'description', None),
                    keywords=getattr(db_tag, 'keywords', []),
                    related_skills=getattr(db_tag, 'related_skills', []),
                    sort_order=getattr(db_tag, 'sort_order', 0),
                    show_in_menu=getattr(db_tag, 'show_in_menu', False),
                    enabled=getattr(db_tag, 'enabled', True),
                    metadata=getattr(db_tag, 'extra_metadata', None),
                    created_at=datetime.fromisoformat(getattr(db_tag, 'created_at', datetime.now().isoformat())) if getattr(db_tag, 'created_at', None) else datetime.now(),
                    updated_at=datetime.fromisoformat(getattr(db_tag, 'updated_at', datetime.now().isoformat())) if getattr(db_tag, 'updated_at', None) else datetime.now(),
                )
                tags.append(tag_config)
            return tags
        except Exception as e:
            logger.error(f"Failed to load tags from repository: {e}")
            return []
    
    def _save_tags(self, tags: List[TagConfig]) -> None:
        """Save tags to file or enterprise repository.
        
        Args:
            tags: List of tag configurations
        """
        if self._enterprise_repo:
            self._save_tags_to_repository(tags)
            return
        
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
        
        logger.info(f"Saved {len(tags)} tags to {self.tags_file}")

    def _save_tags_to_repository(self, tags: List[TagConfig]) -> None:
        """Save tags to enterprise PostgreSQL repository.
        
        Args:
            tags: List of TagConfig objects
        """
        try:
            for tag_config in tags:
                # Convert Pydantic TagConfig to SQLAlchemy model
                from ...enterprise.database.models import tag as tag_model
                
                db_tag = self._enterprise_repo.get_tag(tag_config.id)
                if not db_tag:
                    db_tag = tag_model.Tag(
                        id=tag_config.id,
                        name=tag_config.name,
                        icon=tag_config.icon,
                        type=str(tag_config.type.value) if hasattr(tag_config.type, 'value') else str(tag_config.type),
                        parent_id=tag_config.parent_id,
                        description=tag_config.description,
                        keywords=tag_config.keywords or [],
                        related_skills=tag_config.related_skills or [],
                        sort_order=tag_config.sort_order,
                        show_in_menu=tag_config.show_in_menu,
                        enabled=tag_config.enabled,
                        extra_metadata=getattr(tag_config, 'metadata', None),
                    )
                
                # Update fields
                db_tag.name = tag_config.name
                db_tag.icon = tag_config.icon
                db_tag.type = str(tag_config.type.value) if hasattr(tag_config.type, 'value') else str(tag_config.type)
                db_tag.parent_id = tag_config.parent_id
                db_tag.description = tag_config.description
                db_tag.keywords = tag_config.keywords or []
                db_tag.related_skills = tag_config.related_skills or []
                db_tag.sort_order = tag_config.sort_order
                db_tag.show_in_menu = tag_config.show_in_menu
                db_tag.enabled = tag_config.enabled
                db_tag.extra_metadata = getattr(tag_config, 'metadata', None)
                
                self._enterprise_repo.save_tag(db_tag)
            
            logger.info(f"Saved {len(tags)} tags to PostgreSQL repository")
        except Exception as e:
            logger.error(f"Failed to save tags to repository: {e}")
    
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
            TagType.MENU: "-menu",
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
        if self._enterprise_repo:
            # Use enterprise repository
            db_tags = self._enterprise_repo.list_tags(
                tag_type=str(tag_type.value) if tag_type and hasattr(tag_type, 'value') else str(tag_type),
                parent_id=parent_id,
                enabled=enabled,
                show_in_menu=show_in_menu,
            )
            tags = []
            for db_tag in db_tags:
                tag_config = TagConfig(
                    id=db_tag.id,
                    name=db_tag.name,
                    icon=getattr(db_tag, 'icon', None),
                    type=TagType(db_tag.type) if hasattr(db_tag, 'type') and db_tag.type else TagType.DIMENSION,
                    parent_id=getattr(db_tag, 'parent_id', None),
                    description=getattr(db_tag, 'description', None),
                    keywords=getattr(db_tag, 'keywords', []),
                    related_skills=getattr(db_tag, 'related_skills', []),
                    sort_order=getattr(db_tag, 'sort_order', 0),
                    show_in_menu=getattr(db_tag, 'show_in_menu', False),
                    enabled=getattr(db_tag, 'enabled', True),
                    metadata=getattr(db_tag, 'extra_metadata', None),
                    created_at=datetime.fromisoformat(getattr(db_tag, 'created_at', datetime.now().isoformat())) if getattr(db_tag, 'created_at', None) else datetime.now(),
                    updated_at=datetime.fromisoformat(getattr(db_tag, 'updated_at', datetime.now().isoformat())) if getattr(db_tag, 'updated_at', None) else datetime.now(),
                )
                tags.append(tag_config)
            return TagListResponse(tags=tags, total=len(tags))
        
        # Fallback to JSON storage
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
        if self._enterprise_repo:
            db_tag = self._enterprise_repo.get_tag(tag_id)
            if not db_tag:
                return None
            tag_config = TagConfig(
                id=db_tag.id,
                name=db_tag.name,
                icon=getattr(db_tag, 'icon', None),
                type=TagType(db_tag.type) if hasattr(db_tag, 'type') and db_tag.type else TagType.DIMENSION,
                parent_id=getattr(db_tag, 'parent_id', None),
                description=getattr(db_tag, 'description', None),
                keywords=getattr(db_tag, 'keywords', []),
                related_skills=getattr(db_tag, 'related_skills', []),
                sort_order=getattr(db_tag, 'sort_order', 0),
                show_in_menu=getattr(db_tag, 'show_in_menu', False),
                enabled=getattr(db_tag, 'enabled', True),
                metadata=getattr(db_tag, 'extra_metadata', None),
                created_at=datetime.fromisoformat(getattr(db_tag, 'created_at', datetime.now().isoformat())) if getattr(db_tag, 'created_at', None) else datetime.now(),
                updated_at=datetime.fromisoformat(getattr(db_tag, 'updated_at', datetime.now().isoformat())) if getattr(db_tag, 'updated_at', None) else datetime.now(),
            )
            return tag_config
        
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
        if self._enterprise_repo:
            return self._create_tag_in_repository(request)
        
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
        
        # Validate that dimension and menu tags don't have parent_id
        if request.type in (TagType.DIMENSION, TagType.MENU) and request.parent_id:
            raise ValueError(f"{request.type} tag cannot have a parent_id")
        
        # Validate that menu tags must have metadata.path for routing
        if request.type == TagType.MENU:
            metadata = request.metadata or {}
            if not metadata.get("path"):
                raise ValueError("Menu tag must have metadata.path for navigation")
        
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
            metadata=getattr(request, 'metadata', None),
            created_at=now,
            updated_at=now,
        )
        
        # Add to list
        tags.append(tag)
        self._save_tags(tags)
        
        logger.info(f"Created tag: {tag_id} ({tag.name})")
        return tag

    def _create_tag_in_repository(self, request: TagCreateRequest) -> TagConfig:
        """Create a new tag in PostgreSQL repository.
        
        Args:
            request: Tag creation request
            
        Returns:
            Created TagConfig
            
        Raises:
            ValueError: If validation fails
        """
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
        
        # Validate that dimension and menu tags don't have parent_id
        if request.type in (TagType.DIMENSION, TagType.MENU) and request.parent_id:
            raise ValueError(f"{request.type} tag cannot have a parent_id")
        
        # Validate that menu tags must have metadata.path for routing
        if request.type == TagType.MENU:
            metadata = request.metadata or {}
            if not metadata.get("path"):
                raise ValueError("Menu tag must have metadata.path for navigation")
        
        # Generate ID
        tag_id = self._generate_id(request.name, request.type)
        
        from ...enterprise.database.models import tag as tag_model
        
        now = datetime.now()
        db_tag = tag_model.Tag(
            id=tag_id,
            name=request.name,
            icon=request.icon,
            type=str(request.type.value) if hasattr(request.type, 'value') else str(request.type),
            parent_id=request.parent_id,
            description=request.description,
            keywords=request.keywords or [],
            related_skills=request.related_skills or [],
            sort_order=request.sort_order,
            show_in_menu=request.show_in_menu,
            enabled=request.enabled,
            extra_metadata=getattr(request, 'metadata', None),
            created_at=now,
            updated_at=now,
        )
        
        saved_tag = self._enterprise_repo.save_tag(db_tag)
        
        tag_config = TagConfig(
            id=saved_tag.id,
            name=saved_tag.name,
            icon=getattr(saved_tag, 'icon', None),
            type=TagType(saved_tag.type) if hasattr(saved_tag, 'type') and saved_tag.type else TagType.DIMENSION,
            parent_id=getattr(saved_tag, 'parent_id', None),
            description=getattr(saved_tag, 'description', None),
            keywords=getattr(saved_tag, 'keywords', []),
            related_skills=getattr(saved_tag, 'related_skills', []),
            sort_order=getattr(saved_tag, 'sort_order', 0),
            show_in_menu=getattr(saved_tag, 'show_in_menu', False),
            enabled=getattr(saved_tag, 'enabled', True),
            metadata=getattr(saved_tag, 'extra_metadata', None),
            created_at=datetime.fromisoformat(getattr(saved_tag, 'created_at', datetime.now().isoformat())) if getattr(saved_tag, 'created_at', None) else datetime.now(),
            updated_at=datetime.fromisoformat(getattr(saved_tag, 'updated_at', datetime.now().isoformat())) if getattr(saved_tag, 'updated_at', None) else datetime.now(),
        )
        
        logger.info(f"Created tag in repository: {tag_id} ({saved_tag.name})")
        return tag_config
    
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
        if self._enterprise_repo:
            return self._update_tag_in_repository(tag_id, request)
        
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
            elif tag.type in (TagType.DIMENSION, TagType.MENU):
                raise ValueError(f"{tag.type} tag cannot have a parent_id")
        
        # Validate that menu tags still have metadata.path after update
        if tag.type == TagType.MENU and request.metadata is not None:
            if not request.metadata.get("path"):
                raise ValueError("Menu tag must have metadata.path for navigation")
        
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

    def _update_tag_in_repository(self, tag_id: str, request: TagUpdateRequest) -> TagConfig:
        """Update a tag in PostgreSQL repository.
        
        Args:
            tag_id: Tag ID to update
            request: Tag update request
            
        Returns:
            Updated TagConfig
            
        Raises:
            ValueError: If tag not found or validation fails
        """
        db_tag = self._enterprise_repo.get_tag(tag_id)
        if not db_tag:
            raise ValueError(f"Tag not found: {tag_id}")
        
        # Validate parent_id if being updated
        if request.parent_id is not None:
            if db_tag.type == TagType.CATEGORY.value:
                if request.parent_id:  # Not empty
                    parent = self.get_tag(request.parent_id)
                    if not parent:
                        raise ValueError(f"Parent tag not found: {request.parent_id}")
                    if parent.type != TagType.DIMENSION:
                        raise ValueError(f"Parent must be a dimension tag, got: {parent.type}")
            elif db_tag.type in (TagType.DIMENSION.value, TagType.MENU.value):
                raise ValueError(f"{db_tag.type} tag cannot have a parent_id")
        
        # Validate that menu tags still have metadata.path after update
        if db_tag.type == TagType.MENU.value and request.metadata is not None:
            if not request.metadata.get("path"):
                raise ValueError("Menu tag must have metadata.path for navigation")
        
        # Update fields
        update_data = request.model_dump(exclude_unset=True)
        for key, value in update_data.items():
            if key == 'metadata':
                # Map 'metadata' field to 'extra_metadata' attribute in SQLAlchemy model
                setattr(db_tag, 'extra_metadata', value)
            elif hasattr(db_tag, key) and key != 'type':
                setattr(db_tag, key, value)
        
        if request.type is not None:
            db_tag.type = str(request.type.value) if hasattr(request.type, 'value') else str(request.type)
        
        if request.icon is not None:
            db_tag.icon = request.icon
        if request.description is not None:
            db_tag.description = request.description
        if request.keywords is not None:
            db_tag.keywords = request.keywords
        if request.related_skills is not None:
            db_tag.related_skills = request.related_skills
        if request.sort_order is not None:
            db_tag.sort_order = request.sort_order
        if request.show_in_menu is not None:
            db_tag.show_in_menu = request.show_in_menu
        if request.enabled is not None:
            db_tag.enabled = request.enabled
        
        db_tag.updated_at = datetime.now()
        
        saved_tag = self._enterprise_repo.save_tag(db_tag)
        
        tag_config = TagConfig(
            id=saved_tag.id,
            name=saved_tag.name,
            icon=getattr(saved_tag, 'icon', None),
            type=TagType(saved_tag.type) if hasattr(saved_tag, 'type') and saved_tag.type else TagType.DIMENSION,
            parent_id=getattr(saved_tag, 'parent_id', None),
            description=getattr(saved_tag, 'description', None),
            keywords=getattr(saved_tag, 'keywords', []),
            related_skills=getattr(saved_tag, 'related_skills', []),
            sort_order=getattr(saved_tag, 'sort_order', 0),
            show_in_menu=getattr(saved_tag, 'show_in_menu', False),
            enabled=getattr(saved_tag, 'enabled', True),
            metadata=getattr(saved_tag, 'extra_metadata', None),
            created_at=datetime.fromisoformat(getattr(saved_tag, 'created_at', datetime.now().isoformat())) if getattr(saved_tag, 'created_at', None) else datetime.now(),
            updated_at=datetime.fromisoformat(getattr(saved_tag, 'updated_at', datetime.now().isoformat())) if getattr(saved_tag, 'updated_at', None) else datetime.now(),
        )
        
        logger.info(f"Updated tag in repository: {tag_id}")
        return tag_config
    
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
        if self._enterprise_repo:
            return self._delete_tag_in_repository(tag_id)
        
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

    def _delete_tag_in_repository(self, tag_id: str) -> bool:
        """Delete a tag in PostgreSQL repository.
        
        Args:
            tag_id: Tag ID to delete
            
        Returns:
            True if deleted
            
        Raises:
            ValueError: If tag not found or in use
        """
        db_tag = self._enterprise_repo.get_tag(tag_id)
        if not db_tag:
            raise ValueError(f"Tag not found: {tag_id}")
        
        # Check if tag has children (for dimension tags)
        if db_tag.type == TagType.DIMENSION.value:
            children = [t for t in self._enterprise_repo.list_tags() if getattr(t, 'parent_id', None) == tag_id]
            if children:
                raise ValueError(
                    f"Cannot delete dimension tag with {len(children)} category tags. "
                    "Delete or reassign category tags first."
                )
        
        success = self._enterprise_repo.delete_tag(tag_id)
        logger.info(f"Deleted tag in repository: {tag_id}")
        return success
    
    def get_tag_tree(self) -> List[TagTreeItem]:
        """Get tag tree for hierarchical display.
        
        Returns:
            List of TagTreeItem (dimension tags with children)
        """
        if self._enterprise_repo:
            return self._get_tag_tree_from_repository()
        
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

    def _get_tag_tree_from_repository(self) -> List[TagTreeItem]:
        """Get tag tree from PostgreSQL repository.
        
        Returns:
            List of TagTreeItem (dimension tags with children)
        """
        db_tags = self._enterprise_repo.list_tags()
        
        # Get dimension tags
        dimensions = [t for t in db_tags if str(t.type) == TagType.DIMENSION.value and getattr(t, 'enabled', True)]
        dimensions.sort(key=lambda t: (-getattr(t, 'sort_order', 0), t.name))
        
        # Build tree
        tree = []
        for dim in dimensions:
            # Get category tags under this dimension
            categories = [
                t for t in db_tags 
                if str(t.type) == TagType.CATEGORY.value and getattr(t, 'parent_id', None) == dim.id and getattr(t, 'enabled', True)
            ]
            categories.sort(key=lambda t: (-getattr(t, 'sort_order', 0), t.name))
            
            tree_item = TagTreeItem(
                id=dim.id,
                name=dim.name,
                icon=getattr(dim, 'icon', None),
                type=TagType(dim.type) if hasattr(dim, 'type') and dim.type else TagType.DIMENSION,
                children=[
                    TagTreeItem(
                        id=cat.id,
                        name=cat.name,
                        icon=getattr(cat, 'icon', None),
                        type=TagType(cat.type) if hasattr(cat, 'type') and cat.type else TagType.CATEGORY,
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
        if self._enterprise_repo:
            return self._get_menu_tags_from_repository()
        
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

    def _get_menu_tags_from_repository(self) -> List[TagTreeItem]:
        """Get menu tags from PostgreSQL repository.
        
        Only returns tags with show_in_menu=True.
        
        Returns:
            List of TagTreeItem
        """
        db_tags = self._enterprise_repo.list_tags()
        
        # Get dimension tags with show_in_menu=True
        dimensions = [
            t for t in db_tags 
            if str(t.type) == TagType.DIMENSION.value and getattr(t, 'show_in_menu', False) and getattr(t, 'enabled', True)
        ]
        dimensions.sort(key=lambda t: (-getattr(t, 'sort_order', 0), t.name))
        
        # Build tree
        tree = []
        for dim in dimensions:
            # Get category tags under this dimension
            categories = [
                t for t in db_tags 
                if (str(t.type) == TagType.CATEGORY.value and 
                    getattr(t, 'parent_id', None) == dim.id and 
                    getattr(t, 'show_in_menu', False) and 
                    getattr(t, 'enabled', True))
            ]
            categories.sort(key=lambda t: (-getattr(t, 'sort_order', 0), t.name))
            
            tree_item = TagTreeItem(
                id=dim.id,
                name=dim.name,
                icon=getattr(dim, 'icon', None),
                type=TagType(dim.type) if hasattr(dim, 'type') and dim.type else TagType.DIMENSION,
                children=[
                    TagTreeItem(
                        id=cat.id,
                        name=cat.name,
                        icon=getattr(cat, 'icon', None),
                        type=TagType(cat.type) if hasattr(cat, 'type') and cat.type else TagType.CATEGORY,
                        children=[],
                    )
                    for cat in categories
                ],
            )
            tree.append(tree_item)
        
        return tree

    def get_workbench_categories(self) -> List[dict]:
        """Get workbench category tags for second-level menu.
        
        Returns tags with type='category' and show_in_menu=True, enabled=True.
        
        Returns:
            List of category item dictionaries
        """
        tags = self._load_tags()
        
        # Get category tags with show_in_menu=True and enabled
        categories = [
            t for t in tags 
            if t.type == TagType.CATEGORY and t.show_in_menu and t.enabled
        ]
        
        # Sort by sort_order
        def _get_sort_order(tag) -> int:
            if isinstance(tag, dict):
                return tag.get('sort_order', 0) or tag.get('sortOrder', 0) or 0
            return getattr(tag, 'sort_order', 0) or 0
        
        categories.sort(key=_get_sort_order)
        
        # Convert to menu items
        category_items = []
        for cat in categories:
            if isinstance(cat, dict):
                cat_id = cat.get('id', '')
                name = cat.get('name', '')
                icon = cat.get('icon', '🏷️')
            else:
                cat_id = cat.id
                name = cat.name
                icon = cat.icon or '🏷️'
            
            category_items.append({
                "id": cat_id,
                "name": name,
                "icon": icon,
            })
        
        return category_items
    

