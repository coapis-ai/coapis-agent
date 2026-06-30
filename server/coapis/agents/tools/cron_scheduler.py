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

"""Cron scheduler — manage CoApis internal cron jobs.

Uses the internal APScheduler-based CronManager instead of system crontab.
This ensures compatibility with containerized environments and provides
unified management with the Web UI cron jobs.
"""

from __future__ import annotations

import logging
import uuid
from typing import Any, Optional

from .registry import register_tool

logger = logging.getLogger(__name__)


def _get_cron_manager():
    """Get the CronManager for the current user from the request context.

    This is a helper that tries to get the CronManager from the
    multi_agent_manager's cron_registry.
    """
    # Import here to avoid circular imports
    from ..app.crons.registry import get_registry

    registry = get_registry()
    if registry is None:
        return None

    # Get the first available manager (for the current user context)
    # In practice, the workspace's CronManager should be registered
    if registry._managers:
        # Return the first available manager
        for username, mgr in registry._managers.items():
            return mgr
    return None


@register_tool(
    name="cron_scheduler",
    description="定时任务管理：创建/列表/暂停/恢复/删除定时任务。基于内部调度系统，无需系统 cron 服务。",
    category="builtin",
    tags=["cron", "scheduling", "automation"],
    scene="ops"
)
async def cron_scheduler(
    action: str = "list",
    name: str = "",
    schedule: str = "",
    prompt: str = "",
    task_type: str = "agent",
    agent_id: str = "",
    channel: str = "console",
    session_id: str = "",
    user_id: str = "",
    timezone: str = "Asia/Shanghai",
    timeout_seconds: int = 120,
    job_id: str = "",
    enabled: bool = True,
) -> dict[str, Any]:
    """定时任务管理。

    基于 CoApis 内部调度系统管理定时任务，支持 AI 对话和文本消息两种任务类型。

    Args:
        action: 操作类型 (list/add/remove/enable/disable/show/run)
        name: 任务名称（add 时必填，用于标识任务）
        schedule: cron 调度表达式（add 时必填，如 "*/5 * * * *" 每5分钟，"0 9 * * *" 每天9点）
        prompt: 任务提示词/消息内容（add 时必填）
        task_type: 任务类型，"agent"（AI对话）或 "text"（文本消息），默认 "agent"
        agent_id: 目标智能体ID，默认为空使用默认智能体
        channel: 消息通道，默认 "console"
        session_id: 会话ID，默认自动生成
        user_id: 用户ID，默认使用当前用户
        timezone: 时区，默认 "Asia/Shanghai"
        timeout_seconds: 任务超时时间（秒），默认 120
        job_id: 任务ID（remove/enable/disable/show/run 时使用，或通过 name 查找）
        enabled: 是否启用（add 时），默认 True

    Returns:
        操作结果
    """
    # Get the CronManager from the registry
    mgr = _get_cron_manager()
    if mgr is None:
        return {
            "error": "CronManager 未初始化，请确保系统已启动",
            "hint": "如果是首次使用，请等待系统初始化完成后再试"
        }

    # Get owner user_id from the manager
    owner_user_id = mgr._owner_user_id or user_id or "default"

    if action == "list":
        try:
            jobs = await mgr.list_jobs()
            entries = []
            for job in jobs:
                state = mgr.get_state(job.id)
                entries.append({
                    "id": job.id,
                    "name": job.name,
                    "schedule": job.schedule.cron if job.schedule else "",
                    "task_type": job.task_type,
                    "prompt": job.text or (job.request.input if job.request else ""),
                    "enabled": job.enabled,
                    "channel": job.dispatch.channel if job.dispatch else "",
                    "agent_id": job.agent_id,
                    "next_run_at": state.next_run_at.isoformat() if state and state.next_run_at else None,
                    "last_run_at": state.last_run_at.isoformat() if state and state.last_run_at else None,
                    "last_status": state.last_status if state else None,
                })
            return {
                "action": "list",
                "entries": entries,
                "count": len(entries),
                "success": True,
            }
        except Exception as e:
            logger.error(f"Failed to list cron jobs: {e}")
            return {"error": f"获取任务列表失败: {str(e)}"}

    elif action == "add":
        if not name.strip():
            return {"error": "name 不能为空"}
        if not schedule.strip():
            return {"error": "schedule 不能为空（如 */5 * * * * 或 0 9 * * *）"}
        if not prompt.strip():
            return {"error": "prompt 不能为空（任务提示词/消息内容）"}

        # Check for duplicate name
        existing_jobs = await mgr.list_jobs()
        for job in existing_jobs:
            if job.name == name.strip():
                return {"error": f"任务 '{name}' 已存在，请先 remove 再重新添加，或使用不同的名称"}

        # Generate IDs
        new_job_id = job_id or str(uuid.uuid4())
        target_session_id = session_id or f"{channel}:{owner_user_id}"

        # Build the CronJobSpec
        from ..app.crons.models import (
            CronJobSpec,
            CronJobRequest,
            DispatchSpec,
            DispatchTarget,
            ScheduleSpec,
            JobRuntimeSpec,
        )

        try:
            # Build dispatch target
            dispatch_target = DispatchTarget(
                user_id=owner_user_id,
                session_id=target_session_id,
            )
            dispatch = DispatchSpec(
                channel=channel,
                target=dispatch_target,
            )

            # Build schedule
            schedule_spec = ScheduleSpec(
                cron=schedule.strip(),
                timezone=timezone,
            )

            # Build runtime spec
            runtime = JobRuntimeSpec(
                timeout_seconds=timeout_seconds,
            )

            # Build the job spec
            if task_type == "text":
                spec = CronJobSpec(
                    id=new_job_id,
                    name=name.strip(),
                    enabled=enabled,
                    schedule=schedule_spec,
                    task_type="text",
                    text=prompt.strip(),
                    dispatch=dispatch,
                    agent_id=agent_id or None,
                    runtime=runtime,
                )
            else:  # agent
                request = CronJobRequest(
                    input=prompt.strip(),
                    user_id=owner_user_id,
                    session_id=target_session_id,
                )
                spec = CronJobSpec(
                    id=new_job_id,
                    name=name.strip(),
                    enabled=enabled,
                    schedule=schedule_spec,
                    task_type="agent",
                    request=request,
                    dispatch=dispatch,
                    agent_id=agent_id or None,
                    runtime=runtime,
                )

            # Create the job
            await mgr.create_or_replace_job(spec)

            return {
                "action": "add",
                "success": True,
                "job_id": new_job_id,
                "name": name.strip(),
                "schedule": schedule.strip(),
                "task_type": task_type,
                "prompt": prompt.strip()[:100] + ("..." if len(prompt.strip()) > 100 else ""),
                "enabled": enabled,
                "channel": channel,
                "message": f"定时任务 '{name}' 创建成功"
            }

        except Exception as e:
            logger.error(f"Failed to create cron job: {e}")
            return {"error": f"创建任务失败: {str(e)}"}

    elif action == "remove":
        if not job_id.strip() and not name.strip():
            return {"error": "需要提供 job_id 或 name"}

        # Find job by name if job_id not provided
        if not job_id.strip():
            jobs = await mgr.list_jobs()
            for job in jobs:
                if job.name == name.strip():
                    job_id = job.id
                    break
            if not job_id.strip():
                return {"error": f"未找到任务 '{name}'"}

        try:
            success = await mgr.delete_job(job_id)
            if success:
                return {
                    "action": "remove",
                    "success": True,
                    "job_id": job_id,
                    "message": f"任务已删除"
                }
            else:
                return {"error": f"未找到任务 ID '{job_id}'"}
        except Exception as e:
            logger.error(f"Failed to delete cron job: {e}")
            return {"error": f"删除任务失败: {str(e)}"}

    elif action in ("enable", "disable"):
        if not job_id.strip() and not name.strip():
            return {"error": "需要提供 job_id 或 name"}

        # Find job by name if job_id not provided
        if not job_id.strip():
            jobs = await mgr.list_jobs()
            for job in jobs:
                if job.name == name.strip():
                    job_id = job.id
                    break
            if not job_id.strip():
                return {"error": f"未找到任务 '{name}'"}

        try:
            if action == "enable":
                await mgr.resume_job(job_id)
            else:
                await mgr.pause_job(job_id)

            return {
                "action": action,
                "success": True,
                "job_id": job_id,
                "enabled": (action == "enable"),
                "message": f"任务已{'启用' if action == 'enable' else '暂停'}"
            }
        except Exception as e:
            logger.error(f"Failed to {action} cron job: {e}")
            return {"error": f"{'启用' if action == 'enable' else '暂停'}任务失败: {str(e)}"}

    elif action == "show":
        if not job_id.strip() and not name.strip():
            return {"error": "需要提供 job_id 或 name"}

        # Find job by name if job_id not provided
        if not job_id.strip():
            jobs = await mgr.list_jobs()
            for job in jobs:
                if job.name == name.strip():
                    job_id = job.id
                    break
            if not job_id.strip():
                return {"error": f"未找到任务 '{name}'"}

        try:
            job = await mgr.get_job(job_id)
            if not job:
                return {"error": f"未找到任务 ID '{job_id}'"}

            state = mgr.get_state(job_id)
            return {
                "action": "show",
                "success": True,
                "job": {
                    "id": job.id,
                    "name": job.name,
                    "schedule": job.schedule.cron if job.schedule else "",
                    "timezone": job.schedule.timezone if job.schedule else "",
                    "task_type": job.task_type,
                    "prompt": job.text or (job.request.input if job.request else ""),
                    "enabled": job.enabled,
                    "channel": job.dispatch.channel if job.dispatch else "",
                    "session_id": job.dispatch.target.session_id if job.dispatch and job.dispatch.target else "",
                    "agent_id": job.agent_id,
                    "timeout_seconds": job.runtime.timeout_seconds if job.runtime else 120,
                    "next_run_at": state.next_run_at.isoformat() if state and state.next_run_at else None,
                    "last_run_at": state.last_run_at.isoformat() if state and state.last_run_at else None,
                    "last_status": state.last_status if state else None,
                    "last_error": state.last_error if state else None,
                }
            }
        except Exception as e:
            logger.error(f"Failed to get cron job: {e}")
            return {"error": f"获取任务详情失败: {str(e)}"}

    elif action == "run":
        if not job_id.strip() and not name.strip():
            return {"error": "需要提供 job_id 或 name"}

        # Find job by name if job_id not provided
        if not job_id.strip():
            jobs = await mgr.list_jobs()
            for job in jobs:
                if job.name == name.strip():
                    job_id = job.id
                    break
            if not job_id.strip():
                return {"error": f"未找到任务 '{name}'"}

        try:
            result = await mgr.run_job_once(job_id)
            return {
                "action": "run",
                "success": True,
                "job_id": job_id,
                "result": result,
                "message": "任务已触发执行"
            }
        except Exception as e:
            logger.error(f"Failed to run cron job: {e}")
            return {"error": f"执行任务失败: {str(e)}"}

    else:
        return {"error": f"未知操作: {action}，支持 list/add/remove/enable/disable/show/run"}
