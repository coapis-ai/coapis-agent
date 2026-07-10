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

"""Points router — STUB (removed in simplification).

All points-related endpoints return 404 to indicate the feature has been removed.
"""
from __future__ import annotations

from fastapi import APIRouter, HTTPException

router = APIRouter(tags=["user-system/points"])


@router.get("/points/config")
async def get_points_config():
    raise HTTPException(status_code=404, detail="Points system has been removed")


@router.post("/points/add")
async def add_points_endpoint():
    raise HTTPException(status_code=404, detail="Points system has been removed")


@router.post("/points/spend")
async def spend_points_endpoint():
    raise HTTPException(status_code=404, detail="Points system has been removed")


@router.get("/points/transactions")
async def get_transactions():
    raise HTTPException(status_code=404, detail="Points system has been removed")


@router.get("/points/levels")
async def get_level_info():
    raise HTTPException(status_code=404, detail="Points/level system has been removed")
