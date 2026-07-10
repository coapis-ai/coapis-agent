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

"""Type definitions for proactive conversation feature."""

from dataclasses import dataclass, field
from typing import Optional, List, Dict, Any
from datetime import datetime
from enum import Enum


class ProactiveEventType(str, Enum):
    """主动对话事件类型。"""
    IDLE = "idle"                        # 空闲超时（原有）
    FILE_CHANGED = "file_changed"        # 关键文件变更
    SECURITY_ALERT = "security_alert"    # 安全告警（ToolMonitor 触发）
    TASK_COMPLETED = "task_completed"    # 后台任务完成
    DAILY_SUMMARY = "daily_summary"      # 定时摘要（CronManager 触发）
    SKILL_EVOLVED = "skill_evolved"      # 技能进化完成
    MEMORY_FULL = "memory_full"          # 记忆容量告警


@dataclass
class ProactiveEvent:
    """一个主动对话事件。"""
    event_type: ProactiveEventType
    session_id: str
    payload: Dict[str, Any] = field(default_factory=dict)
    priority: int = 5                    # 1=最高, 10=最低
    created_at: datetime = field(default_factory=lambda: datetime.now())
    source: str = ""                     # 事件来源模块


@dataclass
class ProactiveConfig:
    """Configuration for proactive feature."""

    enabled: bool = False
    idle_minutes: int = 30
    last_user_interaction: Optional[datetime] = None
    running_task_id: Optional[str] = None
    mode_enabled_time: Optional[datetime] = None

    # 事件驱动配置
    event_driven_enabled: bool = True
    event_cooldown_seconds: int = 300     # 同类事件冷却（秒）
    max_events_per_hour: int = 10         # 每小时最大事件数
    event_priority_threshold: int = 7     # 低于此优先级的事件不触发


@dataclass
class ProactiveTask:
    """Represents a task extracted from memory context."""

    task: str
    query: str
    priority: int  # Lower number means higher priority
    reason: str


@dataclass
class ProactiveQueryResult:
    """Result from executing a proactive query."""

    query: str
    success: bool
    data: Optional[str] = None
    error: Optional[str] = None
