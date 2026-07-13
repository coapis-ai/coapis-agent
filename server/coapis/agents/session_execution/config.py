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

"""Session Execution Manager 配置类。

所有配置都有合理默认值，默认关闭，不影响现有功能。
"""

from pydantic import BaseModel, Field


class LoopDetectionConfig(BaseModel):
    """循环检测配置"""

    enabled: bool = Field(
        default=False,
        description="是否启用循环检测",
    )
    exact_duplicate_threshold: int = Field(
        default=2,
        ge=1,
        description="精确重复检测阈值",
    )
    similar_duplicate_threshold: int = Field(
        default=3,
        ge=1,
        description="相似重复检测阈值",
    )
    similar_duplicate_similarity: float = Field(
        default=0.8,
        ge=0.0,
        le=1.0,
        description="相似重复相似度阈值",
    )
    detection_window: int = Field(
        default=10,
        ge=1,
        description="检测窗口大小（迭代次数）",
    )


class ResourceBudgetConfig(BaseModel):
    """资源预算配置"""

    token_budget_enabled: bool = Field(
        default=False,
        description="是否启用 token 预算",
    )
    max_total_tokens: int = Field(
        default=150000,
        ge=1000,
        description="单次会话最大总 tokens",
    )
    token_warning_threshold: float = Field(
        default=0.8,
        ge=0.0,
        le=1.0,
        description="token 预算警告阈值",
    )
    token_block_threshold: float = Field(
        default=0.95,
        ge=0.0,
        le=1.0,
        description="token 预算阻断阈值",
    )

    api_call_budget_enabled: bool = Field(
        default=False,
        description="是否启用 API 调用预算",
    )
    max_llm_calls: int = Field(
        default=50,
        ge=1,
        description="单次会话最大 LLM 调用次数",
    )
    max_tool_calls: int = Field(
        default=100,
        ge=1,
        description="单次会话最大工具调用次数",
    )

    time_budget_enabled: bool = Field(
        default=False,
        description="是否启用时间预算",
    )
    max_session_duration: int = Field(
        default=1800,
        ge=1,
        description="单次会话最大持续时间（秒）",
    )
    max_idle_duration: int = Field(
        default=300,
        ge=1,
        description="最大空闲时间（秒）",
    )


class InterventionConfig(BaseModel):
    """干预配置"""

    enabled: bool = Field(
        default=False,
        description="是否启用干预",
    )
    warning_to_degradation: int = Field(
        default=2,
        ge=1,
        description="警告升级到降级的阈值",
    )
    degradation_to_blocking: int = Field(
        default=2,
        ge=1,
        description="降级升级到阻断的阈值",
    )
    blocking_to_force_stop: int = Field(
        default=1,
        ge=1,
        description="阻断升级到强制停止的阈值",
    )


class ObservabilityConfig(BaseModel):
    """可观测性配置"""

    logging_enabled: bool = Field(
        default=True,
        description="是否启用日志",
    )
    logging_level: str = Field(
        default="INFO",
        description="日志级别",
    )
    metrics_enabled: bool = Field(
        default=False,
        description="是否启用指标收集",
    )
    metrics_collect_interval: int = Field(
        default=60,
        ge=1,
        description="指标收集间隔（秒）",
    )


class SessionExecutionConfig(BaseModel):
    """会话执行管理配置

    默认关闭，通过配置开关控制是否启用。不影响现有功能。
    """

    enabled: bool = Field(
        default=False,
        description="是否启用会话执行管理",
    )
    loop_detection: LoopDetectionConfig = Field(
        default_factory=LoopDetectionConfig,
        description="循环检测配置",
    )
    resource_budget: ResourceBudgetConfig = Field(
        default_factory=ResourceBudgetConfig,
        description="资源预算配置",
    )
    intervention: InterventionConfig = Field(
        default_factory=InterventionConfig,
        description="干预配置",
    )
    observability: ObservabilityConfig = Field(
        default_factory=ObservabilityConfig,
        description="可观测性配置",
    )
