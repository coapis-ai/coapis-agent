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

"""Trigger logic for proactive conversation feature."""

import asyncio
import logging
import time
from collections import defaultdict
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Dict, Optional, Any, List

from .proactive_types import (
    ProactiveConfig,
    ProactiveEvent,
    ProactiveEventType,
    ProactiveTask,
)
from .proactive_responder import generate_proactive_response
from .proactive_utils import (
    get_last_message_ts,
    ensure_tz_aware,
    is_agent_busy,
)

if TYPE_CHECKING:
    from ....app.workspace import Workspace

logger = logging.getLogger(__name__)

# Global storage for proactive configurations per session
proactive_configs: Dict[str, ProactiveConfig] = {}
proactive_tasks: Dict[str, asyncio.Task] = {}


def enable_proactive_for_session(
    session_id: str,
    idle_minutes: int = 30,
) -> str:
    """Enable proactive for the given session and start monitoring."""
    config = ProactiveConfig(
        enabled=True,
        idle_minutes=idle_minutes,
        last_user_interaction=datetime.now(timezone.utc),
        mode_enabled_time=datetime.now(timezone.utc),
    )
    proactive_configs[session_id] = config

    # Start the proactive trigger loop if not already running
    if session_id not in proactive_tasks or proactive_tasks[session_id].done():
        task = asyncio.create_task(_run_trigger_loop(session_id))
        proactive_tasks[session_id] = task

    return f"Proactive mode enabled with {idle_minutes} minute idle threshold."


async def _run_trigger_loop(
    session_id: str,
) -> None:
    """Internal function to run the trigger loop."""
    try:
        await proactive_trigger_loop(session_id)
    except Exception as e:
        logger.error(f"Error in proactive trigger: {e}")


async def is_last_message_proactive(workspace: Any) -> bool:
    """Check if the last message in session was a proactive message."""
    from agentscope.memory import InMemoryMemory
    from ....app.runner.utils import agentscope_msg_to_message

    try:
        chats = await workspace.chat_manager.list_chats()

        sessions_with_ts = [(ensure_tz_aware(s.updated_at), s) for s in chats]
        _, latest_session = max(sessions_with_ts)

        session_id = latest_session.session_id
        user_id = latest_session.user_id

        state = await workspace.runner.session.get_session_state_dict(
            session_id,
            user_id,
        )

        memories_data = state.get("agent", {}).get("memory", [])

        memory = InMemoryMemory()
        memory.load_state_dict(memories_data)
        messages = await memory.get_memory()

        serializable_messages = agentscope_msg_to_message(messages)

        latest_msg = serializable_messages[-1]
        contents = getattr(latest_msg, "contents", [])

        if not contents or not isinstance(contents, list):
            return "[PROACTIVE]" in str(latest_msg)

        for content_item in contents:
            text_content = ""
            if hasattr(content_item, "text"):
                text_content = content_item.text

            if "[PROACTIVE]" in text_content:
                return True

        return False

    except Exception as e:
        logger.warning(f"Could not check if last message was proactive: {e}")
        return False


def _should_trigger_proactive(
    config: ProactiveConfig,
    last_interaction_tz_aware: datetime,
    current_time: datetime,
) -> bool:
    """Determine if proactive trigger conditions are met."""
    elapsed_time = current_time - last_interaction_tz_aware
    elapsed_minutes = elapsed_time.total_seconds() / 60.0

    if elapsed_minutes < config.idle_minutes:
        return False

    if not config.mode_enabled_time:
        return True

    mode_enabled_time_tz_aware = ensure_tz_aware(config.mode_enabled_time)
    time_since_mode_enabled = (
        current_time - mode_enabled_time_tz_aware
    ).total_seconds() / 60.0

    return time_since_mode_enabled >= config.idle_minutes


async def _handle_proactive_trigger(
    session_id: str,
    config: ProactiveConfig,
    last_trigger_attempt: Optional[datetime],
    workspace: "Workspace",
) -> Optional[datetime]:
    """Handle the logic when a proactive trigger is attempted."""
    now_utc = datetime.now(timezone.utc)

    if config.running_task_id is not None:
        return last_trigger_attempt

    if last_trigger_attempt is not None:
        time_since_last_attempt = (
            now_utc - ensure_tz_aware(last_trigger_attempt)
        ).total_seconds()
        if time_since_last_attempt <= 60:
            return last_trigger_attempt

    if config.last_user_interaction is None:
        return last_trigger_attempt

    last_interaction_tz_aware = ensure_tz_aware(config.last_user_interaction)

    if config.mode_enabled_time is None:
        return last_trigger_attempt

    mode_enabled_time_tz_aware = ensure_tz_aware(config.mode_enabled_time)

    last_interaction_was_before_mode_enabled = (
        last_interaction_tz_aware <= mode_enabled_time_tz_aware
    )

    if not last_interaction_was_before_mode_enabled:
        if await is_last_message_proactive(workspace):
            logger.info("Last Proactive Message Unresponded, skipping")
            return now_utc

    logger.info("Triggering proactive response now")

    new_attempt_time = now_utc
    config.running_task_id = f"proactive_{now_utc.timestamp()}"

    try:
        responder_task = asyncio.create_task(
            generate_proactive_response(workspace),
        )

        proactive_msg = await responder_task

        if proactive_msg:
            msg_preview = str(proactive_msg)[:100]
            logger.info(
                f"Proactive message generated for session {session_id}: "
                f"{msg_preview}...",
            )

    except Exception as e:
        logger.error(f"Error in proactive responder: {e}")
    finally:
        if session_id in proactive_configs:
            proactive_configs[session_id].running_task_id = None

    return new_attempt_time


async def proactive_trigger_loop(
    session_id: str,
) -> None:
    """Background loop that polls every 30s to detect idle periods."""
    last_trigger_attempt: Optional[datetime] = None

    try:
        from ....app.agent_context import get_current_agent_id
        from ....app.multi_agent_manager import MultiAgentManager

        active_agent_id = get_current_agent_id()
        multi_agent_manager = MultiAgentManager()
        workspace = await multi_agent_manager.get_agent(active_agent_id)
    except Exception as e:
        logger.error(f"Failed to initialize workspace for proactive loop: {e}")
        return

    while True:
        try:
            await asyncio.sleep(30)

            if session_id not in proactive_configs:
                continue

            config = proactive_configs[session_id]
            if not config.enabled:
                continue

            if await is_agent_busy(workspace):
                continue

            actual_last_user_time = await get_last_message_ts(
                workspace=workspace,
            )

            if actual_last_user_time is not None:
                last_interaction_dt = datetime.fromtimestamp(
                    actual_last_user_time,
                    tz=timezone.utc,
                )
            else:
                last_interaction_dt = config.last_user_interaction

            if last_interaction_dt is None:
                continue

            last_interaction_tz_aware = ensure_tz_aware(last_interaction_dt)
            current_time = datetime.now(timezone.utc)

            if not _should_trigger_proactive(
                config,
                last_interaction_tz_aware,
                current_time,
            ):
                continue

            config.last_user_interaction = last_interaction_tz_aware

            last_trigger_attempt = await _handle_proactive_trigger(
                session_id,
                config,
                last_trigger_attempt,
                workspace,
            )

        except asyncio.CancelledError:
            logger.info("Proactive trigger loop cancelled")
            break
        except Exception as e:
            logger.error(f"Error in proactive trigger loop: {e}")


# =========================================================================
# 事件驱动主动性 — 扩展空闲触发为多事件触发
# =========================================================================

# 全局事件队列（进程内）
_event_queue: asyncio.Queue = asyncio.Queue()
_event_history: List[ProactiveEvent] = []
_event_cooldowns: Dict[str, datetime] = {}
_event_counts_this_hour: int = 0
_event_hour_reset: float = 0.0


def emit_proactive_event(
    event_type: ProactiveEventType,
    session_id: str,
    payload: Optional[Dict[str, Any]] = None,
    priority: int = 5,
    source: str = "",
) -> bool:
    """发射一个主动对话事件到队列。

    各模块（ToolMonitor、CronManager 等）调用此函数触发事件。
    返回 True 表示事件已入队。
    """
    config = proactive_configs.get(session_id)
    if not config or not config.enabled or not config.event_driven_enabled:
        return False

    # 优先级过滤
    if priority > config.event_priority_threshold:
        return False

    # 冷却检查
    now = datetime.now(timezone.utc)
    cooldown_key = f"{session_id}:{event_type.value}"
    last_event = _event_cooldowns.get(cooldown_key)
    if last_event and (now - last_event).total_seconds() < config.event_cooldown_seconds:
        return False

    # 速率限制
    now_ts = time.time()
    global _event_counts_this_hour, _event_hour_reset
    if now_ts - _event_hour_reset > 3600:
        _event_counts_this_hour = 0
        _event_hour_reset = now_ts
    if _event_counts_this_hour >= config.max_events_per_hour:
        return False

    event = ProactiveEvent(
        event_type=event_type,
        session_id=session_id,
        payload=payload or {},
        priority=priority,
        created_at=now,
        source=source,
    )
    _event_queue.put_nowait(event)
    _event_cooldowns[cooldown_key] = now
    _event_counts_this_hour += 1
    _event_history.append(event)

    logger.info(
        "ProactiveEvent emitted: type=%s session=%s priority=%d source=%s",
        event_type.value, session_id[:8], priority, source,
    )
    return True


def get_event_history(limit: int = 20) -> List[Dict]:
    """获取最近的事件历史。"""
    recent = _event_history[-limit:]
    return [
        {
            "event_type": e.event_type.value,
            "session_id": e.session_id[:8],
            "priority": e.priority,
            "source": e.source,
            "created_at": e.created_at.isoformat(),
        }
        for e in recent
    ]


def _event_to_proactive_task(event: ProactiveEvent) -> Optional[ProactiveTask]:
    """将事件转换为主动对话任务。"""
    type_to_task = {
        ProactiveEventType.SECURITY_ALERT: ProactiveTask(
            task="security_check",
            query="检测到安全告警，请检查当前环境状态并提供处置建议",
            priority=2,
            reason=f"安全事件触发: {event.payload.get('description', '未知')}",
        ),
        ProactiveEventType.TASK_COMPLETED: ProactiveTask(
            task="task_followup",
            query=f"后台任务已完成，请总结结果: {event.payload.get('task_name', '未知任务')}",
            priority=4,
            reason="后台任务完成通知",
        ),
        ProactiveEventType.DAILY_SUMMARY: ProactiveTask(
            task="daily_summary",
            query="请生成今日工作摘要，包括完成的任务、待办事项和关键发现",
            priority=5,
            reason="定时摘要触发",
        ),
        ProactiveEventType.SKILL_EVOLVED: ProactiveTask(
            task="skill_update",
            query=f"技能已完成进化: {event.payload.get('skill_name', '未知')}，请评估改进效果",
            priority=6,
            reason="技能进化完成",
        ),
        ProactiveEventType.MEMORY_FULL: ProactiveTask(
            task="memory_cleanup",
            query="记忆容量接近上限，请整理记忆并归档过时内容",
            priority=3,
            reason="记忆容量告警",
        ),
        ProactiveEventType.FILE_CHANGED: ProactiveTask(
            task="file_review",
            query=f"关键文件已变更: {event.payload.get('file_path', '未知')}，请检查变更内容",
            priority=5,
            reason="文件变更通知",
        ),
    }
    return type_to_task.get(event.event_type)


async def _process_event_queue(
    session_id: str,
    workspace: "Workspace",
) -> None:
    """处理事件队列中的事件。"""
    while not _event_queue.empty():
        event = _event_queue.get_nowait()
        if event.session_id != session_id:
            continue

        task = _event_to_proactive_task(event)
        if task is None:
            continue

        logger.info(
            "ProactiveEvent processing: %s -> task=%s",
            event.event_type.value, task.task,
        )

        try:
            responder_task = generate_proactive_response(
                workspace=workspace,
                task=task,
            )
            proactive_msg = await responder_task
            if proactive_msg:
                logger.info(
                    "ProactiveEvent response generated for %s: %s",
                    event.event_type.value, str(proactive_msg)[:100],
                )
        except Exception as e:
            logger.error("ProactiveEvent handling failed: %s", e)


async def start_event_driven_loop(session_id: str) -> None:
    """启动事件驱动的主动对话循环（独立于空闲触发）。"""
    try:
        from ....app.agent_context import get_current_agent_id
        from ....app.multi_agent_manager import MultiAgentManager

        active_agent_id = get_current_agent_id()
        multi_agent_manager = MultiAgentManager()
        workspace = await multi_agent_manager.get_agent(active_agent_id)
    except Exception as e:
        logger.error("Failed to init workspace for event loop: %s", e)
        return

    while True:
        try:
            await asyncio.sleep(10)  # 每 10 秒检查一次事件队列

            if session_id not in proactive_configs:
                continue
            config = proactive_configs[session_id]
            if not config.enabled or not config.event_driven_enabled:
                continue

            await _process_event_queue(session_id, workspace)

        except asyncio.CancelledError:
            logger.info("Event-driven proactive loop cancelled")
            break
        except Exception as e:
            logger.error("Event-driven proactive loop error: %s", e)
