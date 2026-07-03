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

"""Session Execution Manager 会话状态类。

追踪会话执行的全生命周期状态。
"""

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List
import time


class InterventionLevel(Enum):
    """干预级别"""

    NONE = "none"
    WARNING = "warning"
    DEGRADATION = "degradation"
    BLOCKING = "blocking"
    FORCE_STOP = "force_stop"


@dataclass
class ToolCallRecord:
    """工具调用记录"""

    tool_name: str
    tool_input: Dict[str, Any]
    tool_output: Any
    timestamp: float = field(default_factory=time.time)


@dataclass
class SessionState:
    """会话执行状态

    追踪会话的迭代次数、token 消耗、工具调用历史等。
    """

    session_id: str
    start_time: float = field(default_factory=time.time)
    current_iteration: int = 0
    llm_call_count: int = 0
    tool_call_count: int = 0
    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0
    intervention_level: InterventionLevel = InterventionLevel.NONE
    warning_count: int = 0
    degradation_count: int = 0
    blocking_count: int = 0
    tool_call_history: List[ToolCallRecord] = field(default_factory=list)
    last_activity_time: float = field(default_factory=time.time)

    def record_iteration(self) -> None:
        """记录迭代"""
        self.current_iteration += 1
        self.last_activity_time = time.time()

    def record_llm_call(
        self,
        prompt_tokens: int,
        completion_tokens: int,
    ) -> None:
        """记录 LLM 调用"""
        self.llm_call_count += 1
        self.prompt_tokens += prompt_tokens
        self.completion_tokens += completion_tokens
        self.total_tokens = self.prompt_tokens + self.completion_tokens
        self.last_activity_time = time.time()

    def record_tool_call(
        self,
        tool_name: str,
        tool_input: Dict[str, Any],
        tool_output: Any,
    ) -> None:
        """记录工具调用"""
        self.tool_call_count += 1
        self.tool_call_history.append(
            ToolCallRecord(
                tool_name=tool_name,
                tool_input=tool_input,
                tool_output=tool_output,
            )
        )
        self.last_activity_time = time.time()

    def get_usage_ratio(self, max_tokens: int) -> float:
        """获取 token 使用比例"""
        if max_tokens <= 0:
            return 0.0
        return self.total_tokens / max_tokens
