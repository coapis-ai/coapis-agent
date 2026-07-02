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
