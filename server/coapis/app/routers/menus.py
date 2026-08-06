# -*- coding: utf-8 -*-
# Copyright 2026 蜜蜂 & CoApis Contributors
#
# This program is free software: you are free to redistribute and/or modify
# it under the terms of the GNU Affero General Public License as published
# by the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU Affero General Public License for more details.
#
# You should have received a copy of the GNU Affero General Public License
# along with this program.  If not, see <https://www.gnu.org/licenses/>.

"""Menu API router - provides dynamic menu configuration."""

from fastapi import APIRouter, Depends
from typing import List, Dict, Any
from pathlib import Path
import os

from ..services.tag_service import TagService
from ...models.tag import TagType

router = APIRouter(prefix="/menus", tags=["menus"])

# Global tag service instance
_tag_service: TagService = None

def get_tag_service() -> TagService:
    """Get tag service instance."""
    global _tag_service
    if _tag_service is None:
        working_dir = os.getenv("COAPIS_WORKING_DIR") or os.getenv("WORKING_DIR", "/apps/ai/coapis")
        _tag_service = TagService(data_dir=Path(working_dir))
    return _tag_service


@router.get("")
async def get_menus(
    tag_service: TagService = Depends(get_tag_service)
) -> Dict[str, Any]:
    """Get main menu configuration from tags.
    
    Returns:
      - menu tags as top-level menu items (e.g., chat, workspace, knowledge, settings)
      - dimension tags as top-level menu items with category children
      
    All items are sorted by sort_order (ascending).
    
    Returns:
        {
            "items": [
                {
                    "key": "chat-menu",
                    "label": "聊天",
                    "labelKey": "nav.chat",
                    "icon": "MessageOutlined",
                    "path": "/chat",
                    "permission": "chat",
                    "sortOrder": 1,
                    "isActive": true
                },
                {
                    "key": "nature",
                    "label": "工作场景",
                    "labelKey": "nav.workbench",
                    "icon": "📁",
                    "path": "/workbench",
                    "permission": "scene",
                    "sortOrder": 50,
                    "isActive": true,
                    "children": [
                        {
                            "key": "office-common",
                            "label": "办公通用",
                            "path": "/workbench/office-common",
                            "icon": "📄"
                        },
                        ...
                    ]
                },
                ...
            ]
        }
    """
    tags = tag_service._load_tags()
    
    # 1. Menu tags: leaf top-level navigation items
    menu_tags = [t for t in tags if t.type == TagType.MENU and t.enabled]
    menu_tags.sort(key=lambda t: (t.sort_order, t.name))
    
    # 2. Dimension tags: group menu items with category children
    dimension_tags = [t for t in tags if t.type == TagType.DIMENSION and t.show_in_menu and t.enabled]
    dimension_tags.sort(key=lambda t: (t.sort_order, t.name))
    
    menu_items = []
    
    # Add menu tags first
    for menu_tag in menu_tags:
        metadata = menu_tag.metadata or {}
        menu_item: Dict[str, Any] = {
            "key": menu_tag.id,
            "label": menu_tag.name,
            "labelKey": metadata.get("labelKey", f"nav.{menu_tag.id}"),
            "icon": menu_tag.icon or "📁",
            "path": metadata.get("path", f"/{menu_tag.id}"),
            "permission": metadata.get("permission"),
            "sortOrder": menu_tag.sort_order,
            "isActive": metadata.get("isActive", True),
        }
        menu_items.append(menu_item)
    
    # Add dimension tags with children
    for dim in dimension_tags:
        # Get category children for this dimension
        children = [t for t in tags if t.type == TagType.CATEGORY and t.parent_id == dim.id and t.enabled]
        children.sort(key=lambda t: (t.sort_order, t.name))
        
        metadata = dim.metadata or {}
        menu_item: Dict[str, Any] = {
            "key": dim.id,
            "label": dim.name,
            "labelKey": metadata.get("labelKey", f"nav.{dim.id}"),
            "icon": dim.icon or "📁",
            "path": metadata.get("path", f"/{dim.id}"),
            "permission": metadata.get("permission"),
            "sortOrder": dim.sort_order,
            "isActive": metadata.get("isActive", True),
        }
        
        # Add children if any
        if children:
            menu_item["children"] = [
                {
                    "key": cat.id,
                    "label": cat.name,
                    "path": f"{metadata.get('path', f'/{dim.id}')}/{cat.id}",
                    "icon": cat.icon or "📄",
                    "labelKey": f"nav.{cat.id}",
                }
                for cat in children
            ]
        
        menu_items.append(menu_item)
    
    # Final sort by sort_order ascending, then by label
    menu_items.sort(key=lambda item: (item.get("sortOrder", 0), item.get("label", "")))
    
    return {
        "items": menu_items
    }


@router.get("/workbench-categories")
async def get_workbench_categories(
    tag_service: TagService = Depends(get_tag_service)
) -> List[dict]:
    """Get workbench category tags for second-level menu.
    
    Returns tags with type='category' and show_in_menu=True, enabled=True.
    
    Returns:
        [
            {
                "id": "office-common",
                "name": "办公通用",
                "icon": "📄"
            },
            ...
        ]
    """
    return tag_service.get_workbench_categories()
