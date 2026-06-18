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

"""Root router - Root and version endpoints (CoApis console compatible)."""

import logging
from typing import Dict, Any

from fastapi import APIRouter, Request

logger = logging.getLogger(__name__)

router = APIRouter(tags=["root"])


@router.get("/")
async def root(request: Request) -> Dict[str, Any]:
    """Root endpoint."""
    return {
        "name": "coapis",
        "version": "0.1.0",
        "status": "running",
    }


@router.get("/version")
async def get_version(request: Request) -> Dict[str, Any]:
    """Get version information."""
    return {"version": "0.1.0"}
