# -*- coding: utf-8 -*-
"""Session Execution Manager 会话状态单元测试"""

import time

import pytest

from server.coapis.agents.session_execution.state import (
    InterventionLevel,
    SessionState,
    ToolCallRecord,
)


class TestInterventionLevel:
    """测试 InterventionLevel"""

    def test_enum_values(self):
        """测试枚举值"""
        assert InterventionLevel.NONE.value == "none"
        assert InterventionLevel.WARNING.value == "warning"
        assert InterventionLevel.DEGRADATION.value == "degradation"
        assert InterventionLevel.BLOCKING.value == "blocking"
        assert InterventionLevel.FORCE_STOP.value == "force_stop"


class TestToolCallRecord:
    """测试 ToolCallRecord"""

    def test_creation(self):
        """测试创建"""
        record = ToolCallRecord(
            tool_name="tool1",
            tool_input={"arg": "value"},
            tool_output="result",
        )

        assert record.tool_name == "tool1"
        assert record.tool_input == {"arg": "value"}
        assert record.tool_output == "result"
        assert record.timestamp > 0


class TestSessionState:
    """测试 SessionState"""

    def test_creation(self):
        """测试创建"""
        state = SessionState(session_id="test-session")

        assert state.session_id == "test-session"
        assert state.current_iteration == 0
        assert state.llm_call_count == 0
        assert state.tool_call_count == 0
        assert state.prompt_tokens == 0
        assert state.completion_tokens == 0
        assert state.total_tokens == 0
        assert state.intervention_level == InterventionLevel.NONE
        assert state.warning_count == 0
        assert state.degradation_count == 0
        assert state.blocking_count == 0
        assert len(state.tool_call_history) == 0

    def test_record_iteration(self):
        """测试记录迭代"""
        state = SessionState(session_id="test-session")
        initial_time = state.last_activity_time

        time.sleep(0.1)
        state.record_iteration()

        assert state.current_iteration == 1
        assert state.last_activity_time > initial_time

    def test_record_llm_call(self):
        """测试记录 LLM 调用"""
        state = SessionState(session_id="test-session")

        state.record_llm_call(100, 50)
        assert state.llm_call_count == 1
        assert state.prompt_tokens == 100
        assert state.completion_tokens == 50
        assert state.total_tokens == 150

        state.record_llm_call(200, 100)
        assert state.llm_call_count == 2
        assert state.prompt_tokens == 300
        assert state.completion_tokens == 150
        assert state.total_tokens == 450

    def test_record_tool_call(self):
        """测试记录工具调用"""
        state = SessionState(session_id="test-session")

        state.record_tool_call("tool1", {"arg": "value"}, "result1")
        assert state.tool_call_count == 1
        assert len(state.tool_call_history) == 1
        assert state.tool_call_history[0].tool_name == "tool1"

        state.record_tool_call("tool2", {"arg": "value2"}, "result2")
        assert state.tool_call_count == 2
        assert len(state.tool_call_history) == 2

    def test_get_usage_ratio(self):
        """测试获取使用比例"""
        state = SessionState(session_id="test-session")

        # 没有 token
        assert state.get_usage_ratio(1000) == 0.0

        # 有一些 token
        state.record_llm_call(100, 50)
        assert state.get_usage_ratio(1000) == 0.15

        # max_tokens 为 0
        assert state.get_usage_ratio(0) == 0.0

        # max_tokens 为负数
        assert state.get_usage_ratio(-100) == 0.0
