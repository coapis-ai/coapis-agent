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

"""Agent stats router - Agent statistics endpoints (CoApis console compatible)."""

import logging
from typing import Dict, Any

from ..permissions.decorators import require_permission
from fastapi import APIRouter, Query
from fastapi.requests import Request

logger = logging.getLogger(__name__)

router = APIRouter(tags=["agent-stats"])


@router.get("/agent-stats")
@require_permission("admin:admin")
async def get_agent_stats(
    request: Request,
    start_date: str = Query("2026-01-01"),
    end_date: str = Query("2026-12-31"),
) -> Dict[str, Any]:
    """Get agent statistics summary."""
    return {
        "start_date": start_date,
        "end_date": end_date,
        "total_sessions": 0,
        "total_messages": 0,
        "by_agent": {},
    }
