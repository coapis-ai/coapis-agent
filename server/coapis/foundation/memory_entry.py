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

"""Memory entry model with priority scoring."""
from __future__ import annotations

import math
import uuid
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any


@dataclass
class MemoryEntry:
    """记忆条目。

    每个记忆条目都有类型、分类、标签和优先级分数，
    支持动态计算优先级以决定淘汰顺序。

    Attributes:
        id: 唯一标识符
        content: 记忆内容
        memory_type: 记忆类型 (core | long_term | short_term | ephemeral)
        category: 分类 (coding | research | design | ...)
        tags: 标签列表
        priority_score: 优先级分数 (0.0 - 1.0)
        created_at: 创建时间
        last_accessed_at: 最后访问时间
        access_count: 访问次数
        user_confirmed: 用户是否确认过
        source_agent: 来源 Agent
        source_user: 来源用户
        source_session: 来源会话
    """

    id: str = field(default_factory=lambda: str(uuid.uuid4())[:8])
    content: str = ""
    memory_type: str = "short_term"
    category: str = "general"
    tags: list[str] = field(default_factory=list)
    priority_score: float = 0.5

    # 生命周期
    created_at: datetime = field(default_factory=datetime.now)
    last_accessed_at: datetime = field(default_factory=datetime.now)
    access_count: int = 0
    user_confirmed: bool = False

    # 来源
    source_agent: str = ""
    source_user: str = ""
    source_session: str = ""

    def compute_priority(self) -> float:
        """
        动态计算优先级分数（0.0 - 1.0）。

        评分因素:
        - 访问频率 (30%): log 缩放，避免极端值
        - 用户确认 (25%): 强信号
        - 时效性 (20%): 越新越高
        - 跨会话复用 (15%): 被多个会话引用
        - 记忆类型权重 (10%): core > long_term > short_term > ephemeral
        """
        # 访问频率 (log 缩放)
        freq_score = min(math.log2(1 + self.access_count) / 10, 1.0) * 0.3

        # 用户确认（强信号）
        confirm_score = 0.25 if self.user_confirmed else 0.0

        # 时效性（越新越高，365天衰减到0）
        age_days = (datetime.now() - self.created_at).days
        freshness = max(0, 1.0 - age_days / 365) * 0.2

        # 跨会话复用
        cross_session = min(self.access_count / 10, 1.0) * 0.15

        # 记忆类型权重
        type_weights = {
            "core": 1.0,
            "long_term": 0.8,
            "short_term": 0.5,
            "ephemeral": 0.2,
        }
        type_score = type_weights.get(self.memory_type, 0.1) * 0.1

        self.priority_score = min(
            freq_score + confirm_score + freshness + cross_session + type_score,
            1.0,
        )
        return self.priority_score

    def access(self) -> None:
        """记录一次访问。"""
        self.access_count += 1
        self.last_accessed_at = datetime.now()
        self.compute_priority()

    def confirm(self) -> None:
        """用户确认此记忆重要。"""
        self.user_confirmed = True
        self.compute_priority()

    def to_dict(self) -> dict[str, Any]:
        """序列化为字典。"""
        return {
            "id": self.id,
            "content": self.content,
            "memory_type": self.memory_type,
            "category": self.category,
            "tags": self.tags,
            "priority_score": self.priority_score,
            "created_at": self.created_at.isoformat(),
            "last_accessed_at": self.last_accessed_at.isoformat(),
            "access_count": self.access_count,
            "user_confirmed": self.user_confirmed,
            "source_agent": self.source_agent,
            "source_user": self.source_user,
            "source_session": self.source_session,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> MemoryEntry:
        """从字典反序列化。"""
        return cls(
            id=data.get("id", str(uuid.uuid4())[:8]),
            content=data.get("content", ""),
            memory_type=data.get("memory_type", "short_term"),
            category=data.get("category", "general"),
            tags=data.get("tags", []),
            priority_score=data.get("priority_score", 0.5),
            created_at=datetime.fromisoformat(data["created_at"])
            if data.get("created_at")
            else datetime.now(),
            last_accessed_at=datetime.fromisoformat(data["last_accessed_at"])
            if data.get("last_accessed_at")
            else datetime.now(),
            access_count=data.get("access_count", 0),
            user_confirmed=data.get("user_confirmed", False),
            source_agent=data.get("source_agent", ""),
            source_user=data.get("source_user", ""),
            source_session=data.get("source_session", ""),
        )

    def __lt__(self, other: "MemoryEntry") -> bool:
        """支持排序（优先级从高到低）。"""
        return self.priority_score > other.priority_score
