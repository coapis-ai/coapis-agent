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
