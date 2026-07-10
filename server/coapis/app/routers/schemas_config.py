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

"""Request/response schemas for config API endpoints."""

from typing import Literal, Optional

from pydantic import BaseModel, Field

from ...config.config import ActiveHoursConfig


class HeartbeatBody(BaseModel):
    """Request body for PUT /config/heartbeat."""

    enabled: bool = False
    every: str = "6h"
    target: str = "main"
    active_hours: Optional[ActiveHoursConfig] = Field(
        default=None,
        alias="activeHours",
    )

    model_config = {"populate_by_name": True, "extra": "allow"}


class ChannelHealthResponse(BaseModel):
    """Response model for GET /config/channels/{channel_name}/health."""

    channel: str
    status: Literal["healthy", "unhealthy", "disabled"]
    detail: str = ""


class ChannelRestartResponse(BaseModel):
    """Response model for POST /config/channels/{channel_name}/restart."""

    channel: str
    status: Literal["restarted"]
    detail: str = ""
