# -*- coding: utf-8 -*-
# -*- coding: utf-8 -*-
# Copyright 2026 以太吃虾 & CoApis Contributors
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

"""CoApis 进化引擎模块。

核心组件:
- EvolutionEngine: 进化引擎主类（轨迹记录、Nudge 系统、生命周期钩子）
- ExperienceExtractor: LLM 驱动的经验提取器
- KnowledgeFlow: 知识在三层间的流动机制
- BackendReview: 异步后台审查系统
- CrossAgentEvolution: 跨 Agent 进化引擎（AB 桶管理 + AI 评审晋升）
"""
from .evolution_engine import EvolutionEngine, TrajectoryEntry, ExtractedExperience, EvolutionConfig
from .experience_extractor import ExperienceExtractor, ExtractionResult
from .knowledge_flow import KnowledgeFlow, FlowConfig, FlowRecord
from .backend_review import BackendReview, ReviewSchedule, ReviewResult
from .cross_agent_evolution import CrossAgentEvolution, CrossAgentEvolutionConfig
from .memory_capacity import MemoryCapacityManager

__all__ = [
    "EvolutionEngine",
    "TrajectoryEntry",
    "ExtractedExperience",
    "EvolutionConfig",
    "ExperienceExtractor",
    "ExtractionResult",
    "KnowledgeFlow",
    "FlowConfig",
    "FlowRecord",
    "BackendReview",
    "ReviewSchedule",
    "ReviewResult",
    "CrossAgentEvolution",
    "CrossAgentEvolutionConfig",
    "MemoryCapacityManager",
    "SkillEvolutionEngine",
    "SkillMetrics",
    "SkillMetricsSnapshot",
    "get_skill_evolution_engine",
]
