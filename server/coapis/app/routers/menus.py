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
    """Get main menu configuration.
    
    Returns hardcoded core menu items plus dynamic workbench categories.
    
    Returns:
        {
            "items": [
                {
                    "key": "menu-chat",
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
                    "sortOrder": 100,
                    "isActive": true,
                    "childrenSource": "tag: nature"
                },
                ...
            ]
        }
    """
    # Core menu items (hardcoded for stability)
    menu_items = [
        {
            "key": "menu-chat",
            "label": "聊天",
            "labelKey": "nav.chat",
            "icon": "MessageOutlined",
            "path": "/chat",
            "permission": "chat",
            "sortOrder": 1,
            "isActive": True,
        },
        {
            "key": "nature",
            "label": "工作场景",
            "labelKey": "nav.workbench",
            "icon": "📁",
            "path": "/workbench",
            "permission": "scene",
            "sortOrder": 100,
            "isActive": True,
            "childrenSource": "tag: nature",
        },
        {
            "key": "menu-myspace",
            "label": "我的空间",
            "labelKey": "nav.myspace",
            "icon": "FolderOutlined",
            "path": "/workspace/myspace",
            "permission": "myspace",
            "sortOrder": 3,
            "isActive": True,
        },
        {
            "key": "menu-settings",
            "label": "设置",
            "labelKey": "nav.settings",
            "icon": "SettingOutlined",
            "path": "/settings",
            "permission": "settings",
            "sortOrder": 4,
            "isActive": True,
        },
    ]
    
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
