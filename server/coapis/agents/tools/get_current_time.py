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

"""Tools for getting and setting the user timezone."""

import logging
from .registry import register_tool
from datetime import datetime, timezone
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from agentscope.message import TextBlock
from agentscope.tool import ToolResponse

from ...config import load_config, save_config

logger = logging.getLogger(__name__)


@register_tool(
    name="get_current_time",
    description="获取当前时间",
    category="builtin",
    tags=['time'],
    scene="system",
)
async def get_current_time() -> ToolResponse:
    """Get the current time in format `%Y-%m-%d %H:%M:%S TZ (Day)`,
    e.g. "2026-02-13 19:30:45 Asia/Shanghai (Friday)".

    Call this tool when the user asks for the current time or when
    the current time is needed for other operations.

    Returns:
        `ToolResponse`:
            The current time string,
            e.g. "2026-02-13 19:30:45 Asia/Shanghai (Friday)".
    """
    user_tz = load_config().user_timezone or "UTC"
    try:
        now = datetime.now(ZoneInfo(user_tz))
    except (ZoneInfoNotFoundError, KeyError):
        logger.warning("Invalid timezone %r, falling back to UTC", user_tz)
        now = datetime.now(timezone.utc)
        user_tz = "UTC"

    time_str = (
        f"{now.strftime('%Y-%m-%d %H:%M:%S')} "
        f"{user_tz} ({now.strftime('%A')})"
    )

    return ToolResponse(
        content=[
            TextBlock(
                type="text",
                text=time_str,
            ),
        ],
    )


@register_tool(
    name="set_user_timezone",
    description="设置用户时区",
    category="builtin",
    tags=['time', 'config'],
    scene="system",
)
async def set_user_timezone(timezone_name: str) -> ToolResponse:
    """Set the user timezone.
    Only call this tool when the user explicitly asks to change their timezone.

    Args:
        timezone_name: IANA timezone name (e.g. "Asia/Shanghai",
            "America/New_York", "Europe/London", "UTC").

    Returns:
        `ToolResponse`: Confirmation with the new timezone and current time.
    """
    tz_name = timezone_name.strip()
    if not tz_name:
        return ToolResponse(
            content=[TextBlock(type="text", text="Error: timezone is empty.")],
        )

    try:
        now = datetime.now(ZoneInfo(tz_name))
    except (ZoneInfoNotFoundError, KeyError):
        return ToolResponse(
            content=[
                TextBlock(
                    type="text",
                    text=f"Error: invalid timezone '{tz_name}'.",
                ),
            ],
        )

    config = load_config()
    config.user_timezone = tz_name
    save_config(config)

    time_str = (
        f"{now.strftime('%Y-%m-%d %H:%M:%S')} "
        f"{tz_name} ({now.strftime('%A')})"
    )
    return ToolResponse(
        content=[
            TextBlock(
                type="text",
                text=f"Timezone set to {tz_name}. Current time: {time_str}",
            ),
        ],
    )
