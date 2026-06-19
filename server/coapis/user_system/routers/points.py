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
