# -*- coding: utf-8 -*-
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

"""Memory quota management for hierarchical agent architecture."""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

logger = logging.getLogger(__name__)


@dataclass
class RoleMemoryQuota:
    """单个角色的记忆配额。"""

    max_entries: int = 2_000
    max_tokens: int = 8_000

    injection_limits: dict[str, int] = field(
        default_factory=lambda: {
            "core": 2_000,
            "long_term": 2_000,
            "short_term": 4_000,
            "ephemeral": 1_000,
        }
    )

    def to_dict(self) -> dict[str, Any]:
        return {
            "max_entries": self.max_entries,
            "max_tokens": self.max_tokens,
            "injection_limits": self.injection_limits,
        }


# 各角色的默认配额
DEFAULT_ROLE_QUOTAS: dict[str, RoleMemoryQuota] = {
    "admin": RoleMemoryQuota(
        max_entries=10_000,
        max_tokens=16_000,
        injection_limits={
            "core": 2_000,
            "long_term": 4_000,
            "short_term": 8_000,
            "ephemeral": 2_000,
        },
    ),
    "advanced": RoleMemoryQuota(
        max_entries=5_000,
        max_tokens=12_000,
        injection_limits={
            "core": 2_000,
            "long_term": 3_000,
            "short_term": 6_000,
            "ephemeral": 1_000,
        },
    ),
    "user": RoleMemoryQuota(
        max_entries=2_000,
        max_tokens=8_000,
        injection_limits={
            "core": 2_000,
            "long_term": 2_000,
            "short_term": 3_000,
            "ephemeral": 1_000,
        },
    ),
}


@dataclass
class MemoryQuota:
    """记忆容量配额控制。

    全局上限 + 按角色分配的用户配额。
    全局配额为硬性上限，用户配额按角色分配。

    Attributes:
        max_entries: 全局最大条目数
        max_tokens: 全局最大注入 token 数
        max_total_size_mb: 全局最大存储大小（磁盘限制）
        injection_limits: 全局各记忆类型的注入限制（tokens）
        role_quotas: 按角色分配的配额
    """

    max_entries: int = 50_000
    max_tokens: int = 16_000
    max_total_size_mb: int = 100

    # 全局各记忆类型的注入限制
    injection_limits: dict[str, int] = field(
        default_factory=lambda: {
            "core": 2_000,
            "long_term": 4_000,
            "short_term": 8_000,
            "ephemeral": 2_000,
        }
    )

    # 按角色分配的配额
    role_quotas: dict[str, RoleMemoryQuota] = field(
        default_factory=lambda: dict(DEFAULT_ROLE_QUOTAS)
    )

    # ── 全局检查 ──

    def is_full(self, current_entries: int) -> bool:
        """检查全局是否达到条目数上限。"""
        return current_entries >= self.max_entries

    def get_injection_limit(self, memory_type: str) -> int:
        """根据记忆类型返回全局注入限制。"""
        return self.injection_limits.get(memory_type, 0)

    def can_inject(self, memory_type: str, tokens: int, current_injected: dict[str, int]) -> bool:
        """检查全局是否可以注入指定数量的 tokens。"""
        limit = self.get_injection_limit(memory_type)
        current = current_injected.get(memory_type, 0)
        return (current + tokens) <= limit

    def remaining_tokens(self, memory_type: str, current_injected: dict[str, int]) -> int:
        """计算全局某类型剩余的注入空间。"""
        limit = self.get_injection_limit(memory_type)
        current = current_injected.get(memory_type, 0)
        return max(0, limit - current)

    def total_injected(self, current_injected: dict[str, int]) -> int:
        """计算总已注入 token 数。"""
        return sum(current_injected.values())

    def has_space(self, current_injected: dict[str, int]) -> bool:
        """检查总注入量是否还有空间。"""
        return self.total_injected(current_injected) < self.max_tokens

    # ── 用户级检查 ──

    def get_role_quota(self, role: str) -> RoleMemoryQuota:
        """获取指定角色的配额。未定义的角色使用 user 级别。"""
        return self.role_quotas.get(role, self.role_quotas.get("user", RoleMemoryQuota()))

    def can_user_inject(
        self,
        role: str,
        memory_type: str,
        tokens: int,
        user_current_injected: dict[str, int],
    ) -> bool:
        """检查指定角色的用户是否可以注入指定数量的 tokens。

        Args:
            role: 用户角色
            memory_type: 记忆类型
            tokens: 要注入的 token 数
            user_current_injected: 用户当前已注入的 token 数（按类型）

        Returns:
            True 如果可以注入（同时满足用户级和全局限制），False 否则
        """
        # 用户级检查
        rq = self.get_role_quota(role)
        user_limit = rq.injection_limits.get(memory_type, 0)
        user_current = user_current_injected.get(memory_type, 0)
        if (user_current + tokens) > user_limit:
            return False
        # 全局检查
        return self.can_inject(memory_type, tokens, user_current_injected)

    def user_remaining_tokens(
        self,
        role: str,
        memory_type: str,
        user_current_injected: dict[str, int],
    ) -> int:
        """计算指定角色用户某类型剩余的注入空间（取用户级和全局级较小值）。"""
        rq = self.get_role_quota(role)
        user_limit = rq.injection_limits.get(memory_type, 0)
        user_current = user_current_injected.get(memory_type, 0)
        user_remaining = max(0, user_limit - user_current)
        global_remaining = self.remaining_tokens(memory_type, user_current_injected)
        return min(user_remaining, global_remaining)

    def is_user_entries_full(self, role: str, current_entries: int) -> bool:
        """检查指定角色的用户是否达到条目数上限。"""
        rq = self.get_role_quota(role)
        return current_entries >= rq.max_entries

    def to_dict(self) -> dict[str, Any]:
        """序列化为字典。"""
        return {
            "max_entries": self.max_entries,
            "max_tokens": self.max_tokens,
            "max_total_size_mb": self.max_total_size_mb,
            "injection_limits": self.injection_limits,
            "role_quotas": {
                role: rq.to_dict() for role, rq in self.role_quotas.items()
            },
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> MemoryQuota:
        """从字典反序列化。"""
        role_quotas = {}
        for role, rq_data in data.get("role_quotas", {}).items():
            role_quotas[role] = RoleMemoryQuota(
                max_entries=rq_data.get("max_entries", 2_000),
                max_tokens=rq_data.get("max_tokens", 8_000),
                injection_limits=rq_data.get("injection_limits", {
                    "core": 2_000,
                    "long_term": 2_000,
                    "short_term": 4_000,
                    "ephemeral": 1_000,
                }),
            )
        return cls(
            max_entries=data.get("max_entries", 50_000),
            max_tokens=data.get("max_tokens", 16_000),
            max_total_size_mb=data.get("max_total_size_mb", 100),
            injection_limits=data.get("injection_limits", {
                "core": 2_000,
                "long_term": 4_000,
                "short_term": 8_000,
                "ephemeral": 2_000,
            }),
            role_quotas=role_quotas if role_quotas else dict(DEFAULT_ROLE_QUOTAS),
        )

    def __str__(self) -> str:
        return (
            f"MemoryQuota(entries={self.max_entries}, "
            f"tokens={self.max_tokens}, "
            f"size={self.max_total_size_mb}MB, "
            f"roles={list(self.role_quotas.keys())})"
        )
