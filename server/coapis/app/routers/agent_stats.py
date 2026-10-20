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


@router.get("/agent-stats/context-overhead")
@require_permission("admin:admin")
async def get_context_overhead(
    request: Request,
) -> Dict[str, Any]:
    """What the fixed part of a request costs, per agent (last reading).

    The numbers behind the context budget: system prompt, tool schemas (with
    the per-group cost table, so "which group is worth unloading" is
    answerable), the share of the window they take, which levers the
    fixed-overhead guard had to pull, and the windows the providers reported
    by refusing a request.  In-memory, so it reports the live sessions and
    nothing historical.
    """
    from ...agents.context.fixed_overhead import latest_reports
    from ...agents.context.window_source import feedback_report

    return {"agents": latest_reports(), "window_feedback": feedback_report()}
