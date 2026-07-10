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
