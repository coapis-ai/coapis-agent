# -*- coding: utf-8 -*-
# Copyright 2026 蜜蜂 & CoApis Contributors
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

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
