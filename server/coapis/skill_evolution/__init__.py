"""Skill Evolution — 进化系统的核心引擎与桥接模块。

职责：
- 从触发日志 + 工具日志聚合技能效能指标（SkillMetrics）
- 五维评估：precision / reliability / effectiveness / satisfaction / robustness
- 暴露 API 给前端效能看板
"""

from .engine import SkillEvolutionEngine, SkillMetrics, get_evolution_engine

__all__ = [
    "SkillEvolutionEngine",
    "SkillMetrics",
    "get_evolution_engine",
]
