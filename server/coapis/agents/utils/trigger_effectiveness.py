"""Trigger Effectiveness Tracker — 追踪每个触发词的命中率和满意度，自动调整权重。

数据流：
  TriggerTracker 的 TriggerOutcome → 按 skill_name + keyword 分组统计
      ↓ 定期聚合
  trigger_effectiveness.json 缓存
      ↓ 暴露
  get_effective_triggers(skill_name) → 过滤后的有效触发词

核心逻辑：
  1. 每次触发后，记录 matched_keywords 的命中情况
  2. 根据工具成功率和用户满意度（无 follow-up）计算关键词满意度
  3. 定期根据满意度调整权重：高满意度 → 保持/提升，低满意度 → 降级/移除
  4. 权重 < 0.2 的触发词自动降级（不推荐但仍保留）
"""

from __future__ import annotations

import json
import logging
import os
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

logger = logging.getLogger(__name__)


def _get_effectiveness_path() -> Path:
    """获取 trigger_effectiveness.json 路径。"""
    wd = os.environ.get("COAPIS_WORKING_DIR")
    if wd:
        base = Path(wd) / "system" / "skill_evolution"
    else:
        base = Path(__file__).resolve().parent.parent.parent.parent / "system" / "skill_evolution"
    base.mkdir(parents=True, exist_ok=True)
    return base / "trigger_effectiveness.json"


@dataclass
class KeywordStats:
    """单个关键词的统计信息。"""

    keyword: str = ""
    hits: int = 0               # 命中次数
    successes: int = 0          # 成功次数（工具执行成功）
    satisfied: int = 0          # 满意次数（无 follow-up）
    total: int = 0              # 总触发次数
    weight: float = 1.0         # 当前权重（0.0 ~ 1.5）
    last_hit_at: str = ""
    created_at: str = ""

    @property
    def hit_rate(self) -> float:
        """命中率 = hits / total。"""
        return self.hits / self.total if self.total > 0 else 0.0

    @property
    def success_rate(self) -> float:
        """成功率 = successes / hits。"""
        return self.successes / self.hits if self.hits > 0 else 0.0

    @property
    def satisfaction_rate(self) -> float:
        """满意度 = satisfied / total。"""
        return self.satisfied / self.total if self.total > 0 else 0.0

    def to_dict(self) -> dict:
        return {
            "keyword": self.keyword,
            "hits": self.hits,
            "successes": self.successes,
            "satisfied": self.satisfied,
            "total": self.total,
            "weight": round(self.weight, 3),
            "hit_rate": round(self.hit_rate, 4),
            "success_rate": round(self.success_rate, 4),
            "satisfaction_rate": round(self.satisfaction_rate, 4),
            "last_hit_at": self.last_hit_at,
            "created_at": self.created_at,
        }


@dataclass
class SkillKeywordStats:
    """单个技能的所有关键词统计。"""

    skill_name: str = ""
    keywords: dict[str, KeywordStats] = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {
            "skill_name": self.skill_name,
            "keywords": {k: v.to_dict() for k, v in self.keywords.items()},
        }


class TriggerEffectivenessTracker:
    """触发词效能追踪器。

    职责：
    1. 记录每次触发的关键词命中和执行结果
    2. 定期聚合统计，计算每个关键词的满意度
    3. 根据满意度调整权重，低权重关键词自动降级
    4. 提供过滤后的有效触发词列表
    """

    # 配置
    MIN_SAMPLES_FOR_ADJUSTMENT = 5   # 至少 N 次触发才调整权重
    SATISFACTION_THRESHOLD = 0.6     # 满意度阈值
    WEIGHT_DECAY = 0.85              # 低满意度时权重衰减系数
    WEIGHT_BOOST = 1.1               # 高满意度时权重提升系数
    MIN_WEIGHT = 0.1                 # 最低权重（低于此值自动降级）
    MAX_WEIGHT = 1.5                 # 最高权重
    DEMOTION_THRESHOLD = 0.2         # 降级阈值

    def __init__(self):
        self._stats: dict[str, SkillKeywordStats] = {}  # skill_name → SkillKeywordStats
        self._last_adjustment: float = 0
        self._adjustment_interval: float = 3600  # 每小时调整一次
        self._dirty: bool = False

        # 加载缓存
        self._load()

    # ── 记录触发结果 ──

    def record_outcome(
        self,
        skill_name: str,
        matched_keywords: list[str],
        tool_success: bool,
        user_followed_up: bool,
    ) -> None:
        """记录一次触发的结果，更新关键词统计。

        Args:
            skill_name: 技能名称
            matched_keywords: 本次触发匹配到的关键词列表
            tool_success: 工具执行是否成功
            user_followed_up: 用户是否 follow-up（重复提问 = 不满意）
        """
        if not matched_keywords:
            return

        now_iso = datetime.now(timezone.utc).isoformat()
        skill_stats = self._stats.setdefault(skill_name, SkillKeywordStats(skill_name=skill_name))

        for kw in matched_keywords:
            kw_lower = kw.lower().strip()
            if not kw_lower:
                continue

            ks = skill_stats.keywords.setdefault(kw_lower, KeywordStats(
                keyword=kw_lower,
                created_at=now_iso,
            ))

            ks.total += 1
            ks.hits += 1
            if tool_success:
                ks.successes += 1
            if not user_followed_up:
                ks.satisfied += 1
            ks.last_hit_at = now_iso

        self._dirty = True

        # 检查是否需要调整权重
        self._maybe_adjust_weights()

    # ── 权重调整 ──

    def _maybe_adjust_weights(self) -> None:
        """定期调整权重。"""
        now = time.time()
        if (now - self._last_adjustment) < self._adjustment_interval:
            return
        self._adjust_weights()
        self._last_adjustment = now

    def _adjust_weights(self) -> None:
        """根据满意度调整所有关键词的权重。"""
        adjusted_count = 0
        for skill_name, skill_stats in self._stats.items():
            for kw, ks in skill_stats.keywords.items():
                if ks.total < self.MIN_SAMPLES_FOR_ADJUSTMENT:
                    continue

                if ks.satisfaction_rate >= self.SATISFACTION_THRESHOLD:
                    # 高满意度 → 提升权重
                    ks.weight = min(self.MAX_WEIGHT, ks.weight * self.WEIGHT_BOOST)
                else:
                    # 低满意度 → 衰减权重
                    ks.weight = max(self.MIN_WEIGHT, ks.weight * self.WEIGHT_DECAY)

                adjusted_count += 1

        if adjusted_count > 0:
            logger.info(
                "TriggerEffectiveness: adjusted weights for %d keywords",
                adjusted_count,
            )
            self._dirty = True
            self._save()

    # ── 查询接口 ──

    def get_effective_triggers(
        self,
        skill_name: str,
        base_triggers: list[str],
        min_weight: float = 0.2,
    ) -> list[str]:
        """根据权重过滤触发词，返回有效的触发词列表。

        Args:
            skill_name: 技能名称
            base_triggers: 基础触发词列表（来自 SKILL.md）
            min_weight: 最低权重阈值，低于此值的触发词被降级

        Returns:
            过滤后的有效触发词列表
        """
        skill_stats = self._stats.get(skill_name)
        if not skill_stats:
            return base_triggers

        now = time.time()
        effective = []
        for trigger in base_triggers:
            kw_lower = trigger.lower().strip()
            ks = skill_stats.keywords.get(kw_lower)
            if ks is None:
                # 新触发词（无统计记录）默认通过
                effective.append(trigger)
                continue

            # 时间衰减：超过 7 天未命中的触发词，权重按天衰减 5%
            # 但最低不低于 0.5（保留基础权重，避免完全失效）
            effective_weight = ks.weight
            if ks.last_hit_at:
                try:
                    last_hit_ts = datetime.fromisoformat(ks.last_hit_at).timestamp()
                    days_since = (now - last_hit_ts) / 86400
                    if days_since > 7:
                        decay = max(0.5, 1.0 - (days_since - 7) * 0.05)
                        effective_weight = ks.weight * decay
                except Exception:
                    pass

            if effective_weight >= min_weight:
                effective.append(trigger)
            else:
                logger.debug(
                    "TriggerEffectiveness: demoted trigger '%s' for skill '%s' "
                    "(effective_weight=%.3f < %.3f, raw_weight=%.3f, days_decay=%.2f)",
                    trigger, skill_name, effective_weight, min_weight, ks.weight,
                    effective_weight / ks.weight if ks.weight > 0 else 0,
                )

        return effective

    def get_keyword_stats(self, skill_name: str) -> dict[str, dict]:
        """获取指定技能的关键词统计。"""
        skill_stats = self._stats.get(skill_name)
        if not skill_stats:
            return {}
        return {k: v.to_dict() for k, v in skill_stats.keywords.items()}

    def get_all_stats(self) -> dict[str, dict]:
        """获取所有技能的关键词统计概览。"""
        return {name: ss.to_dict() for name, ss in self._stats.items()}

    def get_demoted_triggers(self, skill_name: str) -> list[dict]:
        """获取指定技能中被降级的触发词。"""
        skill_stats = self._stats.get(skill_name)
        if not skill_stats:
            return []
        result = []
        for kw, ks in skill_stats.keywords.items():
            if ks.weight < self.DEMOTION_THRESHOLD and ks.total >= self.MIN_SAMPLES_FOR_ADJUSTMENT:
                result.append(ks.to_dict())
        result.sort(key=lambda x: x.get("weight", 0))
        return result

    # ── 持久化 ──

    def _save(self) -> None:
        """保存到 trigger_effectiveness.json。"""
        if not self._dirty:
            return
        try:
            path = _get_effectiveness_path()
            data = {
                "version": 1,
                "updated_at": datetime.now(timezone.utc).isoformat(),
                "skills_count": len(self._stats),
                "skills": {name: ss.to_dict() for name, ss in self._stats.items()},
            }
            with open(path, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
            self._dirty = False
        except Exception as exc:
            logger.warning("TriggerEffectiveness: failed to save: %s", exc)

    def _load(self) -> None:
        """从 trigger_effectiveness.json 加载。"""
        path = _get_effectiveness_path()
        if not path.exists():
            return
        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
            for name, ss_data in data.get("skills", {}).items():
                ss = SkillKeywordStats(skill_name=name)
                for kw, kw_data in ss_data.get("keywords", {}).items():
                    ss.keywords[kw] = KeywordStats(
                        keyword=kw_data.get("keyword", kw),
                        hits=kw_data.get("hits", 0),
                        successes=kw_data.get("successes", 0),
                        satisfied=kw_data.get("satisfied", 0),
                        total=kw_data.get("total", 0),
                        weight=kw_data.get("weight", 1.0),
                        last_hit_at=kw_data.get("last_hit_at", ""),
                        created_at=kw_data.get("created_at", ""),
                    )
                self._stats[name] = ss
            logger.info(
                "TriggerEffectiveness: loaded %d skills from cache",
                len(self._stats),
            )
        except Exception as exc:
            logger.warning("TriggerEffectiveness: failed to load: %s", exc)

    def save(self) -> None:
        """公共保存接口（session 结束时调用）。"""
        self._save()


# ── Module-level singleton ──
_global_effectiveness: Optional[TriggerEffectivenessTracker] = None


def get_trigger_effectiveness() -> TriggerEffectivenessTracker:
    """获取全局 TriggerEffectivenessTracker 单例。"""
    global _global_effectiveness
    if _global_effectiveness is None:
        _global_effectiveness = TriggerEffectivenessTracker()
    return _global_effectiveness
