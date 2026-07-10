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
from .audit_logger import AuditLogger, AuditEntry, get_audit_logger

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
    "AuditLogger",
    "AuditEntry",
    "get_audit_logger",
]
