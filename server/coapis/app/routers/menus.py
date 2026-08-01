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
        working_dir = os.getenv("WORKING_DIR", "/apps/ai/coapis")
        _tag_service = TagService(data_dir=Path(working_dir))
    return _tag_service


@router.get("")
async def get_menus(
    tag_service: TagService = Depends(get_tag_service)
) -> Dict[str, Any]:
    """Get main menu configuration.
    
    Returns menu items from tags with type='menu'.
    
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
                ...
            ]
        }
    """
    menu_items = tag_service.get_main_menu()
    
    return {
        "items": menu_items
    }
