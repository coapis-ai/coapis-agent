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

from ...agents.session_execution.manager import SessionExecutionManager
from ...agents.session_execution.config import SessionExecutionConfig

# Initialize SEM instance with default config (features disabled by default)
_sem_manager = SessionExecutionManager(config=SessionExecutionConfig())

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
    try:
        stats = _sem_manager.get_session_stats(session_id)
        if stats is None:
            # Return initial state if session not found/created yet
            return {
                "session_id": session_id,
                "current_iteration": 0,
                "llm_call_count": 0,
                "tool_call_count": 0,
                "prompt_tokens": 0,
                "completion_tokens": 0,
                "total_tokens": 0,
                "intervention_level": "none",
                "warning_count": 0,
                "degradation_count": 0,
                "blocking_count": 0,
            }
        return stats
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/{session_id}/token-budget")
async def get_token_budget(session_id: str) -> Dict[str, Any]:
    """Get token budget information for a session.

    Returns:
        Token budget details including current usage, limits, and thresholds.
    """
    try:
        state = _sem_manager.get_or_create_session(session_id)
        config = _sem_manager.config.resource_budget
        
        return {
            "session_id": session_id,
            "current_usage": {
                "total_tokens": state.total_tokens,
                "llm_call_count": state.llm_call_count,
            },
            "limits": {
                "max_total_tokens": config.max_total_tokens,
                "max_llm_calls": config.max_llm_calls,
            },
            "thresholds": {
                "token_warning_threshold": config.token_warning_threshold,
                "token_block_threshold": config.token_block_threshold,
            },
            "budget_enabled": config.token_budget_enabled,
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
