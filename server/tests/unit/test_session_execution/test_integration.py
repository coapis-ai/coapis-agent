# -*- coding: utf-8 -*-
"""Session Execution Manager 集成测试"""

import pytest

from server.coapis.agents.session_execution.config import SessionExecutionConfig
from server.coapis.agents.session_execution.manager import SessionExecutionManager
from server.coapis.agents.session_execution.state import InterventionLevel


class TestSEMIntegration:
    """测试 SEM 集成"""

    def test_full_lifecycle(self):
        """测试完整生命周期"""
        # 创建启用所有功能的配置
        config = SessionExecutionConfig(
            enabled=True,
            loop_detection={
                "enabled": True,
                "exact_duplicate_threshold": 2,
                "similar_duplicate_threshold": 3,
                "detection_window": 10,
            },
            resource_budget={
                "token_budget_enabled": True,
                "max_total_tokens": 10000,
                "token_warning_threshold": 0.8,
                "token_block_threshold": 0.95,
                "api_call_budget_enabled": True,
                "max_llm_calls": 50,
                "time_budget_enabled": True,
                "max_session_duration": 3600,
                "max_idle_duration": 300,
            },
            intervention={
                "enabled": True,
                "warning_to_degradation": 2,
                "degradation_to_blocking": 2,
                "blocking_to_force_stop": 1,
            },
        )
        manager = SessionExecutionManager(config)
        session_id = "test-session"

        # 1. 记录迭代
        for i in range(5):
            manager.record_iteration(session_id)
        stats = manager.get_session_stats(session_id)
        assert stats["current_iteration"] == 5

        # 2. 记录 LLM 调用
        for i in range(10):
            manager.record_llm_call(session_id, 100, 50)
        stats = manager.get_session_stats(session_id)
        assert stats["llm_call_count"] == 10
        assert stats["total_tokens"] == 1500

        # 3. 记录工具调用
        for i in range(20):
            manager.record_tool_call(
                session_id,
                f"tool_{i}",
                {"arg": f"value_{i}"},
                f"result_{i}",
            )
        stats = manager.get_session_stats(session_id)
        assert stats["tool_call_count"] == 20

        # 4. 检查干预 - 不应该触发
        result = manager.check_and_intervene(session_id)
        assert result is None

        # 5. 清理会话
        manager.cleanup_session(session_id)
        stats = manager.get_session_stats(session_id)
        assert stats is None

    def test_token_budget_intervention(self):
        """测试 token 预算干预"""
        config = SessionExecutionConfig(
            enabled=True,
            resource_budget={
                "token_budget_enabled": True,
                "max_total_tokens": 1000,
                "token_warning_threshold": 0.8,
                "token_block_threshold": 0.95,
            },
            intervention={"enabled": True},
        )
        manager = SessionExecutionManager(config)
        session_id = "test-session"

        # 记录 token，接近警告阈值
        manager.record_llm_call(session_id, 800, 0)
        result = manager.check_and_intervene(session_id)
        assert result == InterventionLevel.WARNING

        # 继续记录，升级到降级
        manager.record_llm_call(session_id, 200, 0)
        result = manager.check_and_intervene(session_id)
        assert result == InterventionLevel.DEGRADATION

    def test_loop_detection(self):
        """测试循环检测"""
        config = SessionExecutionConfig(
            enabled=True,
            loop_detection={
                "enabled": True,
                "exact_duplicate_threshold": 2,
                "detection_window": 10,
            },
            intervention={"enabled": True},
        )
        manager = SessionExecutionManager(config)
        session_id = "test-session"

        # 记录重复的工具调用
        manager.record_tool_call(session_id, "tool1", {"arg": "value"}, "result1")
        manager.record_tool_call(session_id, "tool1", {"arg": "value"}, "result2")

        # 检查是否检测到循环
        result = manager.check_and_intervene(session_id)
        assert result == InterventionLevel.WARNING

    def test_disabled_sem(self):
        """测试禁用的 SEM"""
        config = SessionExecutionConfig(enabled=False)
        manager = SessionExecutionManager(config)
        session_id = "test-session"

        # 所有操作都应该被跳过
        manager.record_iteration(session_id)
        manager.record_llm_call(session_id, 100, 50)
        manager.record_tool_call(session_id, "tool", {}, "result")

        result = manager.check_and_intervene(session_id)
        assert result is None

        stats = manager.get_session_stats(session_id)
        assert stats is None

    def test_error_handling(self):
        """测试错误处理"""
        config = SessionExecutionConfig(enabled=True)
        manager = SessionExecutionManager(config)
        session_id = "test-session"

        # 模拟异常情况
        with pytest.raises(Exception):
            with pytest.MonkeyPatch.context() as m:
                m.setattr(
                    manager,
                    "get_or_create_session",
                    lambda _: (_ for _ in ()).throw(Exception("Test error")),
                )
                manager.record_iteration(session_id)
