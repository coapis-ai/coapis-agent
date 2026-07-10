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

"""Commands router - Command endpoints (CoApis console compatible)."""

import logging
from typing import Dict, Any

from fastapi import APIRouter, HTTPException, Body
from fastapi.requests import Request

logger = logging.getLogger(__name__)

router = APIRouter(tags=["commands"])


@router.post("/commands/check")
async def check_command(
    request: Request,
    payload: Dict[str, Any] = Body(...),
) -> Dict[str, Any]:
    """Check if text is a system control command."""
    text = payload.get("text", "")

    # Simple heuristic: check for common control commands
    control_keywords = ["!approve", "!deny", "!stop", "!restart", "!clear"]
    is_control = any(keyword in text for keyword in control_keywords)

    return {
        "is_control_command": is_control,
        "command_token": None,
    }

# NOTE: /approval/approve and /approval/deny are in approval.py router
# (prefix="/approval"). Removed fake stubs here that were shadowing the
# real endpoints which resolve approval Futures.
