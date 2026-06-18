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

"""Handler for /stop command.

The /stop command immediately terminates an ongoing agent task.
"""

from __future__ import annotations

import logging

from .base import BaseControlCommandHandler, ControlContext

logger = logging.getLogger(__name__)


class StopCommandHandler(BaseControlCommandHandler):
    """Handler for /stop command.

    Features:
    - Immediate response (priority level 0)
    - Stops task via TaskTracker.request_stop (native cancellation)
    - Default: stops current session
    - Optional: specify target session_id

    Usage:
        /stop                  # Stop current session
        /stop session=console:user1  # Stop specific session
    """

    command_name = "/stop"

    async def handle(self, context: ControlContext) -> str:
        """Handle /stop command.

        Args:
            context: Control command context

        Returns:
            Response text (success or error message)
        """
        target_session_id = context.args.get(
            "session",
            context.session_id,
        )

        # Cross-session stop requires advanced+ role
        if target_session_id != context.session_id:
            if context.role not in ("admin", "advanced"):
                return (
                    "❌ **权限不足**\n\n"
                    "停止其他会话的任务需要 advanced 或 admin 角色。\n"
                    f"- 当前角色: `{context.role}`\n"
                    f"- 目标会话: `{target_session_id[:30]}`\n"
                    "- 不带参数的 `/stop` 可停止当前会话。"
                )

        logger.info(
            f"/stop command: current_session={context.session_id[:30]} "
            f"target_session={target_session_id[:30]}",
        )

        workspace = context.workspace
        channel_id = context.channel.channel

        chat_id = await workspace.chat_manager.get_chat_id_by_session(
            target_session_id,
            channel_id,
        )

        if chat_id is None:
            logger.warning(
                f"/stop: No active chat found for "
                f"session={target_session_id[:30]} channel={channel_id}",
            )
            return (
                f"**No Active Task**\n\n"
                f"No running task found for session "
                f"`{target_session_id[:40]}`."
            )

        stopped = await workspace.task_tracker.request_stop(chat_id)

        cleared = await workspace.channel_manager.clear_queue(
            channel_id,
            target_session_id,
            20,
        )

        if stopped or cleared > 0:
            logger.info(
                f"/stop: stopped={stopped} cleared={cleared} "
                f"chat_id={chat_id} session={target_session_id[:30]}",
            )
            status_parts = []
            if stopped:
                status_parts.append("running task stopped")
            if cleared > 0:
                status_parts.append(f"{cleared} queued message(s) cleared")
            status_text = " and ".join(status_parts)
            return (
                f"**Task Stopped**\n\n"
                f"Session `{target_session_id[:40]}`: {status_text}."
            )
        else:
            logger.warning(
                f"/stop: Nothing to stop: "
                f"chat_id={chat_id} session={target_session_id[:30]}",
            )
            return (
                f"**Task Not Running**\n\n"
                f"No active task or queued messages for session "
                f"`{target_session_id[:40]}`."
            )
