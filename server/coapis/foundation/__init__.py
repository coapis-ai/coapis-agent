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
