# -*- coding: utf-8 -*-
# Copyright 2026 以太吃虾 & CoApis Contributors
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

"""Plan router - Plan endpoints (CoApis console compatible)."""

import logging
from typing import Dict, Any, Optional

from fastapi import APIRouter, HTTPException, Query, Body
from fastapi.requests import Request

logger = logging.getLogger(__name__)

router = APIRouter(tags=["plan"])


@router.get("/plan/current")
async def get_current_plan(
    request: Request,
    session_id: str = Query(None),
) -> Dict[str, Any]:
    """Get current plan."""
    # CoApis doesn't have plans - return empty plan
    return {
        "plan": None,
        "session_id": session_id,
        "usage": {
            "sessions_used": 0,
            "sessions_limit": 0,
            "messages_used": 0,
            "messages_limit": 0,
        },
    }


@router.get("/plan/config")
async def get_plan_config(request: Request) -> Dict[str, Any]:
    """Get plan configuration."""
    return {"enabled": False}


@router.put("/plan/config")
async def update_plan_config(
    request: Request,
    payload: Dict[str, Any] = Body(...),
) -> Dict[str, Any]:
    """Update plan configuration."""
    return {"enabled": payload.get("enabled", False)}


@router.get("/plan/stream")
async def stream_plan_updates(request: Request):
    """Stream plan updates via SSE."""
    # For now, return empty stream
    from fastapi.responses import StreamingResponse

    async def event_generator():
        yield "data: {\"type\": \"plan_update\", \"plan\": null, \"session_id\": null}\n\n"

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
    )
