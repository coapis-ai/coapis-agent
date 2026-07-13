# -*- coding: utf-8 -*-
"""Session Execution Manager 核心类单元测试"""

import time
from unittest.mock import patch

import pytest

from server.coapis.agents.session_execution.config import SessionExecutionConfig
from server.coapis.agents.session_execution.manager import SessionExecutionManager
from server.coapis.agents.session_execution.state import InterventionLevel


class TestSessionExecutionManager:
    """测试 SessionExecutionManager"""

    def _create_manager(self, **config_kwargs) -> SessionExecutionManager:
        """创建测试用管理器"""
        config = SessionExecutionConfig(**config_kwargs)
        return SessionExecutionManager(config)

    def test_disabled_manager(self):
        """测试禁用的管理器"""
        manager = self._create_manager(enabled=False)

        # 所有操作都应该被跳过
        manager.record_iteration("test")
        manager.record_llm_call("test", 100, 50)
        manager.record_tool_call("test", "tool", {}, "result")

        result = manager.check_and_intervene("test")
        assert result is None

        stats = manager.get_session_stats("test")
        assert stats is None

    def test_record_iteration(self):
        """测试记录迭代"""
        manager = self._create_manager(enabled=True)
        session_id = "test-session"

        manager.record_iteration(session_id)
        stats = manager.get_session_stats(session_id)
        assert stats is not None
        assert stats["current_iteration"] == 1

        manager.record_iteration(session_id)
        stats = manager.get_session_stats(session_id)
        assert stats["current_iteration"] == 2

    def test_record_llm_call(self):
        """测试记录 LLM 调用"""
        manager = self._create_manager(enabled=True)
        session_id = "test-session"

        manager.record_llm_call(session_id, 100, 50)
        stats = manager.get_session_stats(session_id)
        assert stats is not None
        assert stats["llm_call_count"] == 1
        assert stats["prompt_tokens"] == 100
        assert stats["completion_tokens"] == 50
        assert stats["total_tokens"] == 150

        manager.record_llm_call(session_id, 200, 100)
        stats = manager.get_session_stats(session_id)
        assert stats["llm_call_count"] == 2
        assert stats["prompt_tokens"] == 300
        assert stats["completion_tokens"] == 150
        assert stats["total_tokens"] == 450

    def test_record_tool_call(self):
        """测试记录工具调用"""
        manager = self._create_manager(enabled=True)
        session_id = "test-session"

        manager.record_tool_call(session_id, "tool1", {"arg": "value"}, "result1")
        stats = manager.get_session_stats(session_id)
        assert stats is not None
        assert stats["tool_call_count"] == 1

        manager.record_tool_call(session_id, "tool2", {"arg": "value2"}, "result2")
        stats = manager.get_session_stats(session_id)
        assert stats["tool_call_count"] == 2

    def test_cleanup_session(self):
        """测试清理会话"""
        manager = self._create_manager(enabled=True)
        session_id = "test-session"

        manager.record_iteration(session_id)
        assert manager.get_session_stats(session_id) is not None

        manager.cleanup_session(session_id)
        assert manager.get_session_stats(session_id) is None

    def test_check_and_intervene_disabled(self):
        """测试禁用干预时的检查"""
        manager = self._create_manager(enabled=True, intervention={"enabled": False})
        session_id = "test-session"

        result = manager.check_and_intervene(session_id)
        assert result is None

    def test_check_and_intervene_token_budget(self):
        """测试 token 预算检查"""
        manager = self._create_manager(
            enabled=True,
            resource_budget={
                "token_budget_enabled": True,
                "max_total_tokens": 1000,
                "token_warning_threshold": 0.8,
                "token_block_threshold": 0.95,
            },
            intervention={"enabled": True},
        )
        session_id = "test-session"

        # 初始状态，没有超过阈值
        result = manager.check_and_intervene(session_id)
        assert result is None

        # 记录 token，超过警告阈值
        manager.record_llm_call(session_id, 1001, 0)
        result = manager.check_and_intervene(session_id)
        assert result == InterventionLevel.WARNING

    def test_check_and_intervene_time_budget(self):
        """测试时间预算检查"""
        manager = self._create_manager(
            enabled=True,
            resource_budget={
                "time_budget_enabled": True,
                "max_session_duration": 1,  # 1秒
            },
            intervention={"enabled": True},
        )
        session_id = "test-session"

        # 初始状态，没有超过阈值
        result = manager.check_and_intervene(session_id)
        assert result is None

        # 模拟时间流逝
        time.sleep(1.1)

        result = manager.check_and_intervene(session_id)
        assert result == InterventionLevel.WARNING

    def test_escalate_intervention(self):
        """测试干预升级"""
        manager = self._create_manager(
            enabled=True,
            intervention={
                "enabled": True,
                "warning_to_degradation": 2,
                "degradation_to_blocking": 2,
                "blocking_to_force_stop": 1,
            },
            resource_budget={
                "token_budget_enabled": True,
                "max_total_tokens": 1000,
            },
        )
        session_id = "test-session"

        # 第一次触发警告
        manager.record_llm_call(session_id, 1001, 0)
        result = manager.check_and_intervene(session_id)
        assert result == InterventionLevel.WARNING

        # 第二次触发，升级到降级
        manager.record_llm_call(session_id, 1001, 0)
        result = manager.check_and_intervene(session_id)
        assert result == InterventionLevel.DEGRADATION

        # 第三次触发，仍然降级
        manager.record_llm_call(session_id, 1001, 0)
        result = manager.check_and_intervene(session_id)
        assert result == InterventionLevel.DEGRADATION

        # 第四次触发，升级到阻断
        manager.record_llm_call(session_id, 1001, 0)
        result = manager.check_and_intervene(session_id)
        assert result == InterventionLevel.BLOCKING

        # 第五次触发，升级到强制停止
        manager.record_llm_call(session_id, 1001, 0)
        result = manager.check_and_intervene(session_id)
        assert result == InterventionLevel.FORCE_STOP

    def test_detect_exact_duplicate(self):
        """测试精确重复检测"""
        manager = self._create_manager(
            enabled=True,
            loop_detection={
                "enabled": True,
                "exact_duplicate_threshold": 2,
                "detection_window": 10,
            },
            intervention={"enabled": True},
        )
        session_id = "test-session"

        # 记录不同的工具调用
        manager.record_tool_call(session_id, "tool1", {"arg": "value1"}, "result1")
        manager.record_tool_call(session_id, "tool2", {"arg": "value2"}, "result2")

        # 记录重复的工具调用
        manager.record_tool_call(session_id, "tool1", {"arg": "value1"}, "result3")

        # 检查是否检测到循环
        result = manager.check_and_intervene(session_id)
        assert result == InterventionLevel.WARNING

    def test_detect_similar_duplicate(self):
        """测试相似重复检测"""
        manager = self._create_manager(
            enabled=True,
            loop_detection={
                "enabled": True,
                "similar_duplicate_threshold": 2,
                "similar_duplicate_similarity": 0.8,
                "detection_window": 10,
            },
            intervention={"enabled": True},
        )
        session_id = "test-session"

        # 记录相似的工具调用
        manager.record_tool_call(session_id, "tool1", {"arg": "value1"}, "result1")
        manager.record_tool_call(session_id, "tool1", {"arg": "value2"}, "result2")

        # 检查是否检测到循环
        result = manager.check_and_intervene(session_id)
        # 相似度不够高，不应该检测到
        assert result is None

    def test_error_handling(self):
        """测试错误处理"""
        manager = self._create_manager(enabled=True)
        session_id = "test-session"

        # 模拟异常情况
        with patch.object(manager, "get_or_create_session", side_effect=Exception("Test error")):
            # 所有操作都应该被捕获异常
            manager.record_iteration(session_id)
            manager.record_llm_call(session_id, 100, 50)
            manager.record_tool_call(session_id, "tool", {}, "result")
            result = manager.check_and_intervene(session_id)
            assert result is None

    def test_multiple_sessions(self):
        """测试多会话"""
        manager = self._create_manager(enabled=True)

        # 创建多个会话
        manager.record_iteration("session1")
        manager.record_iteration("session2")
        manager.record_iteration("session3")

        # 验证每个会话独立
        stats1 = manager.get_session_stats("session1")
        stats2 = manager.get_session_stats("session2")
        stats3 = manager.get_session_stats("session3")

        assert stats1["current_iteration"] == 1
        assert stats2["current_iteration"] == 1
        assert stats3["current_iteration"] == 1

        # 清理一个会话
        manager.cleanup_session("session2")
        assert manager.get_session_stats("session2") is None
        assert manager.get_session_stats("session1") is not None
        assert manager.get_session_stats("session3") is not None

    def test_concurrent_access(self):
        """测试并发访问"""
        import threading

        manager = self._create_manager(enabled=True)
        session_id = "test-session"
        errors = []

        def worker():
            try:
                for _ in range(100):
                    manager.record_iteration(session_id)
                    manager.record_llm_call(session_id, 10, 5)
                    manager.record_tool_call(session_id, "tool", {}, "result")
            except Exception as e:
                errors.append(e)

        # 启动多个线程
        threads = [threading.Thread(target=worker) for _ in range(10)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        # 验证没有错误
        assert len(errors) == 0

        # 验证最终状态
        stats = manager.get_session_stats(session_id)
        assert stats["current_iteration"] == 1000
        assert stats["llm_call_count"] == 1000
        assert stats["tool_call_count"] == 1000
