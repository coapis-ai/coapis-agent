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

"""Session Execution Manager 核心类。

会话执行全生命周期管理，包括：
1. 追踪会话执行状态
2. 检测异常模式（循环、资源超限）
3. 执行干预策略
4. 记录可观测性数据

注意：
- 所有方法都是纯函数，不修改外部状态
- 不与任何现有系统集成
- 通过配置开关控制是否启用
"""

from __future__ import annotations

import logging
import time
from typing import Dict, Optional

from .config import SessionExecutionConfig
from .state import InterventionLevel, SessionState

logger = logging.getLogger(__name__)


class SessionExecutionManager:
    """会话执行管理器

    职责：
    1. 追踪会话执行状态
    2. 检测异常模式（循环、资源超限）
    3. 执行干预策略
    4. 记录可观测性数据

    注意：
    - 默认关闭，通过配置开关控制是否启用
    - 不与任何现有系统集成
    - 所有操作都有 try-except 保护
    """

    def __init__(self, config: SessionExecutionConfig):
        self.config = config
        self._sessions: Dict[str, SessionState] = {}

        # 初始化日志
        if config.observability.logging_enabled:
            logger.info(
                f"SessionExecutionManager initialized: "
                f"enabled={config.enabled}, "
                f"loop_detection={config.loop_detection.enabled}, "
                f"token_budget={config.resource_budget.token_budget_enabled}"
            )

    def get_or_create_session(self, session_id: str) -> SessionState:
        """获取或创建会话状态"""
        if session_id not in self._sessions:
            self._sessions[session_id] = SessionState(session_id=session_id)
            if self.config.observability.logging_enabled:
                logger.info(f"Created session: {session_id}")
        return self._sessions[session_id]

    def record_iteration(self, session_id: str) -> None:
        """记录迭代"""
        if not self.config.enabled:
            return

        try:
            state = self.get_or_create_session(session_id)
            state.record_iteration()

            if self.config.observability.logging_enabled:
                logger.debug(
                    f"Session {session_id}: "
                    f"iteration={state.current_iteration}"
                )
        except Exception as e:
            logger.error(f"record_iteration error: {e}")

    def record_llm_call(
        self,
        session_id: str,
        prompt_tokens: int,
        completion_tokens: int,
    ) -> None:
        """记录 LLM 调用"""
        if not self.config.enabled:
            return

        try:
            state = self.get_or_create_session(session_id)
            state.record_llm_call(prompt_tokens, completion_tokens)

            if self.config.observability.logging_enabled:
                logger.debug(
                    f"Session {session_id}: "
                    f"llm_call={state.llm_call_count}, "
                    f"tokens={state.total_tokens}"
                )
        except Exception as e:
            logger.error(f"record_llm_call error: {e}")

    def record_tool_call(
        self,
        session_id: str,
        tool_name: str,
        tool_input: dict,
        tool_output: any,
    ) -> None:
        """记录工具调用"""
        if not self.config.enabled:
            return

        try:
            state = self.get_or_create_session(session_id)
            state.record_tool_call(tool_name, tool_input, tool_output)

            if self.config.observability.logging_enabled:
                logger.debug(
                    f"Session {session_id}: "
                    f"tool_call={state.tool_call_count}, "
                    f"tool={tool_name}"
                )
        except Exception as e:
            logger.error(f"record_tool_call error: {e}")

    def check_and_intervene(
        self,
        session_id: str,
    ) -> Optional[InterventionLevel]:
        """检查并干预

        Returns:
            如果需要干预，返回干预级别；否则返回 None
        """
        if not self.config.enabled:
            return None

        try:
            state = self.get_or_create_session(session_id)

            # 检查时间预算
            if self.config.resource_budget.time_budget_enabled:
                if self._check_time_budget(state):
                    return self._escalate_intervention(
                        state, "time_budget_exceeded"
                    )

            # 检查空闲时间
            if self.config.resource_budget.time_budget_enabled:
                if self._check_idle_time(state):
                    return self._escalate_intervention(
                        state, "idle_time_exceeded"
                    )

            # 检查 token 预算
            if self.config.resource_budget.token_budget_enabled:
                if self._check_token_budget(state):
                    return self._escalate_intervention(
                        state, "token_budget_exceeded"
                    )

            # 检查 API 调用预算
            if self.config.resource_budget.api_call_budget_enabled:
                if self._check_api_call_budget(state):
                    return self._escalate_intervention(
                        state, "api_call_budget_exceeded"
                    )

            # 检查循环
            if self.config.loop_detection.enabled:
                loop_result = self._detect_loop(state)
                if loop_result:
                    return self._escalate_intervention(
                        state, f"loop_detected:{loop_result}"
                    )

            return None
        except Exception as e:
            logger.error(f"check_and_intervene error: {e}")
            return None

    def _check_time_budget(self, state: SessionState) -> bool:
        """检查时间预算"""
        elapsed = time.time() - state.start_time
        max_duration = self.config.resource_budget.max_session_duration
        return elapsed > max_duration

    def _check_idle_time(self, state: SessionState) -> bool:
        """检查空闲时间"""
        idle = time.time() - state.last_activity_time
        max_idle = self.config.resource_budget.max_idle_duration
        return idle > max_idle

    def _check_token_budget(self, state: SessionState) -> bool:
        """检查 token 预算"""
        max_tokens = self.config.resource_budget.max_total_tokens
        return state.total_tokens > max_tokens

    def _check_api_call_budget(self, state: SessionState) -> bool:
        """检查 API 调用预算"""
        max_calls = self.config.resource_budget.max_llm_calls
        return state.llm_call_count > max_calls

    def _detect_loop(self, state: SessionState) -> Optional[str]:
        """检测循环"""
        # 检测精确重复
        if self._detect_exact_duplicate(state):
            return "exact_duplicate"

        # 检测相似重复
        if self._detect_similar_duplicate(state):
            return "similar_duplicate"

        return None

    def _detect_exact_duplicate(self, state: SessionState) -> bool:
        """检测精确重复"""
        threshold = self.config.loop_detection.exact_duplicate_threshold
        window = self.config.loop_detection.detection_window
        history = state.tool_call_history[-window:]

        if len(history) < threshold:
            return False

        # 检查最近的调用是否有精确重复
        last_call = history[-1]
        duplicate_count = sum(
            1
            for call in history[:-1]
            if call.tool_name == last_call.tool_name
            and call.tool_input == last_call.tool_input
        )

        return duplicate_count >= threshold - 1

    def _detect_similar_duplicate(self, state: SessionState) -> bool:
        """检测相似重复"""
        threshold = self.config.loop_detection.similar_duplicate_threshold
        similarity_threshold = (
            self.config.loop_detection.similar_duplicate_similarity
        )
        window = self.config.loop_detection.detection_window
        history = state.tool_call_history[-window:]

        if len(history) < threshold:
            return False

        # 检查最近的调用是否有相似重复
        last_call = history[-1]
        similar_count = 0

        for call in history[:-1]:
            if call.tool_name == last_call.tool_name:
                similarity = self._calculate_similarity(
                    call.tool_input,
                    last_call.tool_input,
                )
                if similarity >= similarity_threshold:
                    similar_count += 1

        return similar_count >= threshold - 1

    def _calculate_similarity(
        self,
        dict1: dict,
        dict2: dict,
    ) -> float:
        """计算两个字典的相似度"""
        if not dict1 and not dict2:
            return 1.0
        if not dict1 or not dict2:
            return 0.0

        all_keys = set(dict1.keys()) | set(dict2.keys())
        matching_keys = set(dict1.keys()) & set(dict2.keys())

        if not all_keys:
            return 1.0

        key_similarity = len(matching_keys) / len(all_keys)

        # 计算值的相似度
        value_similarity = 0.0
        for key in matching_keys:
            if dict1[key] == dict2[key]:
                value_similarity += 1.0

        if matching_keys:
            value_similarity /= len(matching_keys)

        return (key_similarity + value_similarity) / 2

    def _escalate_intervention(
        self,
        state: SessionState,
        reason: str,
    ) -> InterventionLevel:
        """升级干预级别"""
        if not self.config.intervention.enabled:
            return InterventionLevel.NONE

        current_level = state.intervention_level

        # 根据原因和当前级别，决定是否升级
        if current_level == InterventionLevel.NONE:
            state.intervention_level = InterventionLevel.WARNING
            state.warning_count = 1
        elif current_level == InterventionLevel.WARNING:
            state.warning_count += 1
            if (
                state.warning_count
                >= self.config.intervention.warning_to_degradation
            ):
                state.intervention_level = InterventionLevel.DEGRADATION
                state.degradation_count = 0
        elif current_level == InterventionLevel.DEGRADATION:
            state.degradation_count += 1
            if (
                state.degradation_count
                >= self.config.intervention.degradation_to_blocking
            ):
                state.intervention_level = InterventionLevel.BLOCKING
                state.blocking_count = 0
        elif current_level == InterventionLevel.BLOCKING:
            state.blocking_count += 1
            if (
                state.blocking_count
                >= self.config.intervention.blocking_to_force_stop
            ):
                state.intervention_level = InterventionLevel.FORCE_STOP

        # 记录日志
        if self.config.observability.logging_enabled:
            logger.warning(
                f"Session {state.session_id}: "
                f"Intervention escalated to {state.intervention_level.value} "
                f"due to {reason}"
            )

        return state.intervention_level

    def cleanup_session(self, session_id: str) -> None:
        """清理会话状态"""
        if session_id in self._sessions:
            del self._sessions[session_id]
            if self.config.observability.logging_enabled:
                logger.info(f"Cleaned up session: {session_id}")

    def get_session_stats(self, session_id: str) -> Optional[dict]:
        """获取会话统计信息"""
        if session_id not in self._sessions:
            return None

        state = self._sessions[session_id]
        return {
            "session_id": state.session_id,
            "current_iteration": state.current_iteration,
            "llm_call_count": state.llm_call_count,
            "tool_call_count": state.tool_call_count,
            "prompt_tokens": state.prompt_tokens,
            "completion_tokens": state.completion_tokens,
            "total_tokens": state.total_tokens,
            "intervention_level": state.intervention_level.value,
            "warning_count": state.warning_count,
            "degradation_count": state.degradation_count,
            "blocking_count": state.blocking_count,
        }
