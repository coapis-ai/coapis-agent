# -*- coding: utf-8 -*-
"""Session Execution Manager 单元测试"""

import pytest

from server.coapis.agents.session_execution.config import SessionExecutionConfig


class TestSessionExecutionConfig:
    """测试 SessionExecutionConfig"""

    def test_default_config(self):
        """测试默认配置"""
        config = SessionExecutionConfig()

        # 默认关闭
        assert config.enabled is False

        # 循环检测默认关闭
        assert config.loop_detection.enabled is False
        assert config.loop_detection.exact_duplicate_threshold == 2
        assert config.loop_detection.similar_duplicate_threshold == 3
        assert config.loop_detection.similar_duplicate_similarity == 0.8
        assert config.loop_detection.detection_window == 10

        # 资源预算默认关闭
        assert config.resource_budget.token_budget_enabled is False
        assert config.resource_budget.max_total_tokens == 150000
        assert config.resource_budget.token_warning_threshold == 0.8
        assert config.resource_budget.token_block_threshold == 0.95
        assert config.resource_budget.api_call_budget_enabled is False
        assert config.resource_budget.max_llm_calls == 50
        assert config.resource_budget.max_tool_calls == 100
        assert config.resource_budget.time_budget_enabled is False
        assert config.resource_budget.max_session_duration == 1800
        assert config.resource_budget.max_idle_duration == 300

        # 干预默认关闭
        assert config.intervention.enabled is False
        assert config.intervention.warning_to_degradation == 2
        assert config.intervention.degradation_to_blocking == 2
        assert config.intervention.blocking_to_force_stop == 1

        # 可观测性默认日志开启
        assert config.observability.logging_enabled is True
        assert config.observability.logging_level == "INFO"
        assert config.observability.metrics_enabled is False

    def test_custom_config(self):
        """测试自定义配置"""
        config = SessionExecutionConfig(
            enabled=True,
            loop_detection={"enabled": True, "exact_duplicate_threshold": 3},
            resource_budget={"token_budget_enabled": True, "max_total_tokens": 100000},
            intervention={"enabled": True},
        )

        assert config.enabled is True
        assert config.loop_detection.enabled is True
        assert config.loop_detection.exact_duplicate_threshold == 3
        assert config.resource_budget.token_budget_enabled is True
        assert config.resource_budget.max_total_tokens == 100000
        assert config.intervention.enabled is True

    def test_backward_compatibility(self):
        """测试向后兼容性"""
        # 空配置使用默认值
        config = SessionExecutionConfig(**{})
        assert config.enabled is False

        # 只配置部分字段
        config = SessionExecutionConfig(enabled=True)
        assert config.enabled is True
        assert config.loop_detection.enabled is False  # 保持默认

    def test_config_validation(self):
        """测试配置验证"""
        # 测试无效的阈值
        with pytest.raises(Exception):
            SessionExecutionConfig(
                loop_detection={"exact_duplicate_threshold": -1}
            )

        # 测试无效的相似度
        with pytest.raises(Exception):
            SessionExecutionConfig(
                loop_detection={"similar_duplicate_similarity": 2.0}
            )

    def test_config_serialization(self):
        """测试配置序列化"""
        config = SessionExecutionConfig(
            enabled=True,
            loop_detection={"enabled": True},
            resource_budget={"token_budget_enabled": True},
        )

        # 测试序列化
        data = config.model_dump()
        assert data["enabled"] is True
        assert data["loop_detection"]["enabled"] is True
        assert data["resource_budget"]["token_budget_enabled"] is True

        # 测试反序列化
        config2 = SessionExecutionConfig(**data)
        assert config2.enabled is True
        assert config2.loop_detection.enabled is True
        assert config2.resource_budget.token_budget_enabled is True
