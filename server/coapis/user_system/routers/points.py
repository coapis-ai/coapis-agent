# -*- coding: utf-8 -*-
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

"""Points router - endpoints for point management."""
from __future__ import annotations

import logging
from typing import Optional

from fastapi import APIRouter, HTTPException, Query

from ..models import (
    PointTransactionList, PointAddRequest,
    PointsConfigResponse,
    LEVEL_THRESHOLDS, LEVEL_NAMES, LEVEL_NAMES_ZH,
)
from ..points import (
    add_points, spend_points, manual_add_points,
    get_point_transactions,
)
from ..config import get_config

logger = logging.getLogger(__name__)

router = APIRouter(tags=["user-system/points"])


@router.get("/points/config", response_model=PointsConfigResponse)
async def get_points_config():
    """Get current points configuration."""
    cfg = get_config()
    return PointsConfigResponse(point_rules=cfg.point_rules)


@router.post("/points/add")
async def add_points_endpoint(req: PointAddRequest):
    """Manually add points to a user (admin action)."""
    cfg = get_config()
    if not cfg.enabled:
        raise HTTPException(status_code=403, detail="User system is disabled")

    try:
        actual = manual_add_points(req)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))

    return {
        "success": True,
        "requested": req.amount,
        "actual_added": actual,
        "username": req.username,
    }


@router.post("/points/spend")
async def spend_points_endpoint(req: PointAddRequest):
    """Spend points from a user account."""
    cfg = get_config()
    if not cfg.enabled:
        raise HTTPException(status_code=403, detail="User system is disabled")

    try:
        success = spend_points(req.username, req.amount, req.source, req.description)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))

    if not success:
        raise HTTPException(status_code=400, detail="Insufficient points")

    return {
        "success": True,
        "amount": req.amount,
        "username": req.username,
    }


@router.get("/points/transactions", response_model=PointTransactionList)
async def get_transactions(
    username: str,
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=100),
    source: Optional[str] = Query(None),
):
    """Get point transaction history for a user."""
    return get_point_transactions(username, page, page_size, source)


@router.get("/points/levels")
@router.get("/level-info")  # Alias for frontend compatibility
async def get_level_info():
    """Get level threshold information."""
    return {
        "thresholds": LEVEL_THRESHOLDS,
        "names": LEVEL_NAMES,
        "names_zh": LEVEL_NAMES_ZH,
    }
