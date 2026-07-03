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

"""Session Execution Manager API endpoints.

Provides endpoints to query session execution statistics and token budgets.
All endpoints are read-only and do not modify any state.
"""

from fastapi import APIRouter, HTTPException
from typing import Dict, Any

router = APIRouter(
    prefix="/sessions",
    tags=["session-execution"],
)


@router.get("/{session_id}/stats")
async def get_session_stats(session_id: str) -> Dict[str, Any]:
    """Get session execution statistics.

    Returns:
        Session statistics including iteration count, LLM call count,
        tool call count, token usage, and intervention level.
    """
    from ...agents.session_execution import SessionExecutionManager
    from ...config.config import AgentsRunningConfig

    try:
        # This is a placeholder - in production, the SEM instance
        # would be stored in a registry or accessed via the agent
        return {
            "session_id": session_id,
            "status": "SEM not initialized",
            "message": "Session Execution Manager is not initialized for this session",
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/{session_id}/token-budget")
async def get_token_budget(session_id: str) -> Dict[str, Any]:
    """Get token budget information for a session.

    Returns:
        Token budget details including current usage, limits, and thresholds.
    """
    from ...agents.session_execution import SessionExecutionManager

    try:
        return {
            "session_id": session_id,
            "status": "SEM not initialized",
            "message": "Session Execution Manager is not initialized for this session",
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
