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

"""Tag models for the tag system.

Tag types:
- dimension: 维度标签（一级菜单）
- category: 分类标签（二级菜单，需关联dimension）
- industry: 行业标签（场景属性）
- frequency: 频率标签（场景属性）
"""

from __future__ import annotations

from enum import Enum
from typing import Optional, List
from pydantic import BaseModel, Field
from datetime import datetime


class TagType(str, Enum):
    """Tag type enumeration."""
    DIMENSION = "dimension"   # 维度标签（一级菜单）
    CATEGORY = "category"     # 分类标签（二级菜单）
    INDUSTRY = "industry"     # 行业标签（场景属性）
    FREQUENCY = "frequency"   # 频率标签（场景属性）
    MENU = "menu"            # 菜单标签（主菜单配置）


class TagConfig(BaseModel):
    """Tag configuration model."""
    id: str = Field(..., description="Tag unique identifier")
    name: str = Field(..., description="Tag name")
    icon: str = Field(default="🏷️", description="Tag icon (emoji)")
    type: TagType = Field(..., description="Tag type")
    parent_id: Optional[str] = Field(default=None, description="Parent tag ID (only for category type)")
    description: Optional[str] = Field(default=None, description="Tag description")
    keywords: List[str] = Field(default_factory=list, description="Keywords for search")
    related_skills: List[str] = Field(default_factory=list, description="Related skill IDs")
    sort_order: int = Field(default=0, description="Sort order (higher = higher priority)")
    show_in_menu: bool = Field(default=True, description="Show in workbench menu")
    enabled: bool = Field(default=True, description="Tag enabled status")
    created_at: Optional[datetime] = Field(default=None, description="Creation timestamp")
    updated_at: Optional[datetime] = Field(default=None, description="Update timestamp")
    metadata: Optional[dict] = Field(default=None, description="Additional metadata (e.g., menu configuration)")
    category: Optional[str] = Field(default=None, description="Tag category (business, tech, system)")
    
    class Config:
        json_schema_extra = {
            "example": {
                "id": "office-common",
                "name": "办公通用",
                "icon": "📄",
                "type": "category",
                "parent_id": "nature",
                "description": "日常办公场景，所有领域通用",
                "keywords": ["会议", "报告", "邮件"],
                "related_skills": [],
                "sort_order": 1,
                "show_in_menu": True,
                "enabled": True
            }
        }


class TagCreateRequest(BaseModel):
    """Request model for creating a tag."""
    name: str = Field(..., description="Tag name", min_length=1, max_length=50)
    icon: str = Field(default="🏷️", description="Tag icon")
    type: TagType = Field(..., description="Tag type")
    parent_id: Optional[str] = Field(default=None, description="Parent tag ID")
    description: Optional[str] = Field(default=None, description="Tag description")
    keywords: List[str] = Field(default_factory=list, description="Keywords")
    related_skills: List[str] = Field(default_factory=list, description="Related skills")
    sort_order: int = Field(default=0, description="Sort order")
    show_in_menu: bool = Field(default=True, description="Show in menu")
    enabled: bool = Field(default=True, description="Enabled status")


class TagUpdateRequest(BaseModel):
    """Request model for updating a tag."""
    name: Optional[str] = Field(default=None, description="Tag name", min_length=1, max_length=50)
    icon: Optional[str] = Field(default=None, description="Tag icon")
    parent_id: Optional[str] = Field(default=None, description="Parent tag ID")
    description: Optional[str] = Field(default=None, description="Tag description")
    keywords: Optional[List[str]] = Field(default=None, description="Keywords")
    related_skills: Optional[List[str]] = Field(default=None, description="Related skills")
    sort_order: Optional[int] = Field(default=None, description="Sort order")
    show_in_menu: Optional[bool] = Field(default=None, description="Show in menu")
    enabled: Optional[bool] = Field(default=None, description="Enabled status")


class TagListResponse(BaseModel):
    """Response model for listing tags."""
    tags: List[TagConfig] = Field(default_factory=list, description="Tag list")
    total: int = Field(default=0, description="Total count")


class TagTreeItem(BaseModel):
    """Tree item for hierarchical display."""
    id: str = Field(..., description="Tag ID")
    name: str = Field(..., description="Tag name")
    icon: str = Field(..., description="Tag icon")
    type: TagType = Field(..., description="Tag type")
    children: List["TagTreeItem"] = Field(default_factory=list, description="Child tags")


# Update forward reference
TagTreeItem.model_rebuild()
