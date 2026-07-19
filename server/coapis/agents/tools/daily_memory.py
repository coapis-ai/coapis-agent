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

"""Tool for recording events to daily memory notes."""

import logging
from datetime import datetime
from pathlib import Path
from typing import Optional

from .registry import register_tool
from agentscope.message import TextBlock
from agentscope.tool import ToolResponse

from ...config.context import get_current_workspace_dir

logger = logging.getLogger(__name__)


@register_tool(
    name="record_daily_memory",
    description=(
        "记录重要事件到每日笔记。"
        "参数：event（事件描述）、category（可选分类：决策/偏好/任务/问题/其他）。"
        "当用户说"记住这个"、做出重要决策、发现有价值的信息时调用此工具。"
    ),
    category="builtin",
    tags=['memory', 'daily'],
    scene="chat",
)
async def record_daily_memory(
    event: str,
    category: Optional[str] = None,
) -> ToolResponse:
    """Record an event to the daily memory note.

    This tool is automatically called by the AI when:
    - User says "remember this" or similar phrases
    - Important decisions are made during conversation
    - Valuable information is discovered
    - User mentions personal preferences or important details

    Args:
        event: Description of the event to record (required).
        category: Optional category for the event. 
            Values: "决策" (decision), "偏好" (preference), 
            "任务" (task), "问题" (issue), "其他" (other).
            Default is "其他".

    Returns:
        ToolResponse: Confirmation with the recorded event and file path.

    Example:
        >>> await record_daily_memory(
        ...     event="用户偏好使用深色主题",
        ...     category="偏好"
        ... )
    """
    # Get workspace directory
    workspace_dir = get_current_workspace_dir()
    if not workspace_dir:
        return ToolResponse(
            content=[
                TextBlock(
                    type="text",
                    text="❌ 无法获取工作目录，记录失败。",
                ),
            ],
        )

    # Create memory directory if not exists
    memory_dir = workspace_dir / "memory"
    memory_dir.mkdir(parents=True, exist_ok=True)

    # Get today's date
    today = datetime.now().strftime("%Y-%m-%d")
    memory_file = memory_dir / f"{today}.md"

    # Format the event with timestamp and category
    timestamp = datetime.now().strftime("%H:%M")
    category_str = f"[{category}]" if category else ""
    formatted_event = f"- {timestamp} {category_str} {event}\n"

    # Append to file
    try:
        # Check if file exists and has content
        if memory_file.exists():
            existing_content = memory_file.read_text(encoding="utf-8")
            # Append to existing file
            with open(memory_file, "a", encoding="utf-8") as f:
                f.write(formatted_event)
        else:
            # Create new file with header
            header = f"# {today} 日记\n\n## 事件记录\n\n"
            content = header + formatted_event
            memory_file.write_text(content, encoding="utf-8")

        logger.info(
            f"Recorded daily memory: {event[:50]}... -> {memory_file}"
        )

        return ToolResponse(
            content=[
                TextBlock(
                    type="text",
                    text=f"✅ 已记录到每日笔记：{memory_file.name}\n"
                    f"📝 {formatted_event.strip()}",
                ),
            ],
        )

    except Exception as e:
        logger.error(f"Failed to record daily memory: {e}")
        return ToolResponse(
            content=[
                TextBlock(
                    type="text",
                    text=f"❌ 记录失败：{str(e)}",
                ),
            ],
        )
