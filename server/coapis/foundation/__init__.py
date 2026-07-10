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

"""Foundation layer for hierarchical agent architecture.

基础层提供全局共享的核心价值观、通用思考模式和组织级记忆，
始终注入到 Agent 上下文中，不受思路改变或会话重启影响。

核心组件:
- FoundationManager: 基础层管理器
- MemoryInjector: 智能记忆注入器
- MemoryQuota: 容量配额控制
- MemoryEntry: 记忆条目模型
"""
from .memory_quota import MemoryQuota
from .memory_entry import MemoryEntry
from .memory_injector import MemoryInjector, InjectionResult
from .foundation_manager import FoundationManager, PendingMemory

__all__ = [
    "FoundationManager",
    "MemoryInjector",
    "MemoryQuota",
    "MemoryEntry",
    "InjectionResult",
    "PendingMemory",
]
