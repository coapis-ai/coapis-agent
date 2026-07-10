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

"""Settings router - Settings endpoints (CoApis console compatible)."""

import logging
from typing import Dict, Any

from fastapi import APIRouter, HTTPException, Body
from fastapi.requests import Request

from ..permissions.decorators import require_permission

logger = logging.getLogger(__name__)

router = APIRouter(tags=["settings"])


@router.get("/settings")
@require_permission("profile:read")
async def get_settings_info(request: Request) -> Dict[str, Any]:
    """Get settings information."""
    return {
        "language": "zh",
        "theme": "coapis",
    }


@router.get("/settings/language")
async def get_language(request: Request) -> Dict[str, Any]:
    """Get language setting. (Public — needed on login page.)"""
    return {"language": "zh"}


@router.put("/settings/language")
@require_permission("profile:write")
async def update_language(
    request: Request,
    payload: Dict[str, Any] = Body(...),
) -> Dict[str, Any]:
    """Update language setting."""
    return {"language": payload.get("language", "zh")}
