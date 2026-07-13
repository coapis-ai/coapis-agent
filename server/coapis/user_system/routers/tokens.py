# -*- coding: utf-8 -*-
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

"""Tokens router - endpoints for token usage tracking and quota management."""
from __future__ import annotations

import logging
from typing import Optional

from fastapi import APIRouter, HTTPException, Query

from ..models import (
    TokenUsageSummary, TokenUsageList, TokenRecordRequest,
)
from ..tokens import (
    record_token_usage, record_token_usage_simple,
    check_quota, is_quota_exceeded,
    get_usage_summary, get_usage_history,
    reset_monthly_quotas, get_model_pricing,
)
from ..config import get_config

logger = logging.getLogger(__name__)

router = APIRouter(tags=["user-system/tokens"])


@router.post("/tokens/record")
async def record_token_usage_endpoint(req: TokenRecordRequest):
    """Record token usage for a user."""
    try:
        record = record_token_usage(req)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))

    return {
        "success": True,
        "record": record.model_dump(),
    }


@router.get("/tokens/quota/{username}")
async def get_quota_status(username: str):
    """Get token quota status for a user."""
    status = check_quota(username)
    return status


@router.get("/tokens/summary/{username}", response_model=TokenUsageSummary)
async def get_token_summary(username: str):
    """Get token usage summary for a user."""
    return get_usage_summary(username)


@router.get("/tokens/summary")
async def get_global_token_summary():
    """Get global token usage summary (admin only)."""
    from ...token_usage import get_token_usage_manager
    from datetime import date, timedelta
    
    # Get last 30 days summary
    end = date.today()
    start = end - timedelta(days=30)
    
    manager = get_token_usage_manager()
    summary = await manager.get_summary(start_date=start, end_date=end)
    
    return {
        "total_prompt_tokens": summary.total_prompt_tokens,
        "total_completion_tokens": summary.total_completion_tokens,
        "total_calls": summary.total_calls,
        "by_model": {k: v.model_dump() for k, v in summary.by_model.items()},
        "by_provider": {k: v.model_dump() for k, v in summary.by_provider.items()},
        "by_date": {k: v.model_dump() for k, v in summary.by_date.items()},
    }


@router.get("/tokens/history", response_model=TokenUsageList)
async def get_token_history(
    username: str,
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=100),
    model: Optional[str] = Query(None),
    agent_id: Optional[str] = Query(None),
):
    """Get token usage history for a user."""
    return get_usage_history(username, page, page_size, model, agent_id)


@router.post("/tokens/reset-monthly")
async def reset_monthly_quotas_endpoint():
    """Reset monthly token usage for all users (admin action)."""
    count = reset_monthly_quotas()
    return {"success": True, "users_reset": count}


@router.get("/tokens/pricing")
async def get_model_pricing_endpoint():
    """Get model pricing information."""
    from ..tokens import MODEL_PRICING
    return {"pricing": MODEL_PRICING}


@router.get("/tokens/config")
async def get_token_config():
    """Get token system configuration (public endpoint)."""
    cfg = get_config()
    return {
        "enabled": cfg.enabled,
        "default_monthly_quota": cfg.token_quota_l0,
        "token_quotas": cfg.token_quotas,
        "token_quota_hard_limit": cfg.token_quota_hard_limit,
    }


@router.post("/tokens/check")
async def check_quota_endpoint(req: TokenRecordRequest):
    """Check if a user has quota for a requested tokens."""
    status = check_quota(req.username, req.input_tokens + req.output_tokens)
    return status
