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

"""Skill Evolution Bridge - 桥接智能体进化系统与技能进化系统。

Architecture:
┌─────────────────────┐     ┌──────────────────────┐     ┌─────────────────────┐
│  Agent Evolution    │     │  SkillEvolutionBridge │     │  Skill Evolution    │
│                     │────>│                      │────>│                     │
│  ExperienceExtractor│     │  信号路由 + 回调      │     │  Engine (效能评估)  │
│  KnowledgeFlow      │<────│                      │<────│  VersionManager     │
│                     │     │                      │     │  TriggerTracker     │
└─────────────────────┘     └──────────────────────┘     └─────────────────────┘

方向1: Agent Evolution → Skill Evolution
  experience_type=skill_effectiveness → 分析技能效能问题 → 生成改进建议

方向2: Skill Evolution → Agent Evolution
  on_skill_improved → 反馈给智能体进化系统 (memory + lesson)
  on_trigger_enhanced → 更新触发词配置

Data Sources:
  - trigger_log.jsonl: 触发事件 + 结果
  - tool_usage.jsonl: 工具使用记录
  - skill_metrics.json: 聚合指标
  - SKILL.md frontmatter: 版本 + 触发词
"""
from __future__ import annotations

import json
import logging
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, TYPE_CHECKING

if TYPE_CHECKING:
    from ..evolution.experience_extractor import ExtractedExperience
    from ..evolution.evolution_engine import TrajectoryEntry

logger = logging.getLogger(__name__)


# ── Data Models ──────────────────────────────────────────────────────────────


@dataclass
class SkillEffectivenessSignal:
    """从对话中提取的技能效能信号。"""
    signal_type: str           # "false_positive" | "false_negative" | "improve"
    skill_name: str
    trigger_keyword: str       # 触发词/关键词
    context: str               # 对话上下文摘要
    confidence: float          # 0.0-1.0
    turn_index: int = 0        # 对话轮次索引
    timestamp: float = field(default_factory=time.time)

    def to_dict(self) -> dict:
        return {
            "signal_type": self.signal_type,
            "skill_name": self.skill_name,
            "trigger_keyword": self.trigger_keyword,
            "context": self.context[:200],
            "confidence": self.confidence,
            "turn_index": self.turn_index,
            "timestamp": self.timestamp,
        }


@dataclass
class SkillImprovementFeedback:
    """技能改进后反馈给智能体进化系统的信息。"""
    skill_name: str
    improvement_type: str      # "trigger_enhanced" | "content_improved" | "version_bumped"
    description: str
    old_version: str = ""
    new_version: str = ""
    timestamp: float = field(default_factory=time.time)

    def to_dict(self) -> dict:
        return {
            "skill_name": self.skill_name,
            "improvement_type": self.improvement_type,
            "description": self.description,
            "old_version": self.old_version,
            "new_version": self.new_version,
            "timestamp": self.timestamp,
        }


# ── Bridge Class ─────────────────────────────────────────────────────────────


class SkillEvolutionBridge:
    """桥接智能体进化系统与技能进化系统。

    职责：
    1. 从对话轨迹中提取技能效能信号 (方向1)
    2. 将信号路由到技能进化引擎
    3. 接收技能改进反馈并注入智能体进化系统 (方向2)
    4. 管理回调注册
    """

    def __init__(
        self,
        system_dir: Optional[str] = None,
        on_skill_improved: Optional[Callable[[SkillImprovementFeedback], None]] = None,
        on_trigger_enhanced: Optional[Callable[[str, List[str]], None]] = None,
    ):
        if system_dir:
            self._system_dir = Path(system_dir)
        else:
            # 与 engine.py 中 _get_system_dir() 保持一致
            from .engine import _get_system_dir
            self._system_dir = _get_system_dir()
        self._signal_log_path = self._system_dir / "skill_evolution" / "effectiveness_signals.jsonl"
        self._feedback_log_path = self._system_dir / "skill_evolution" / "improvement_feedback.jsonl"

        # Ensure directory exists
        self._signal_log_path.parent.mkdir(parents=True, exist_ok=True)

        # Callbacks
        self._on_skill_improved = on_skill_improved
        self._on_trigger_enhanced = on_trigger_enhanced

        # Signal buffer (in-memory, flushed periodically)
        self._signal_buffer: List[SkillEffectivenessSignal] = []
        self._flush_threshold = 5

        logger.info("SkillEvolutionBridge initialized (system_dir=%s)", self._system_dir)

    # ── Direction 1: Agent Evolution → Skill Evolution ──

    async def extract_effectiveness_signals(
        self,
        trajectory: List[Any],
        session_id: str,
        agent_id: str,
        user_id: str,
        llm_client: Any = None,
    ) -> List[SkillEffectivenessSignal]:
        """从对话轨迹中提取技能效能信号。

        分析对话中技能/工具的使用情况，识别：
        - false_positive: 技能被触发但用户不想要
        - false_negative: 用户期望技能但未触发
        - improve: 技能触发了但效果不佳，需要改进

        Args:
            trajectory: 对话轨迹条目列表
            session_id: 会话 ID
            agent_id: 智能体 ID
            user_id: 用户 ID
            llm_client: 可选的 LLM 客户端，用于深度分析

        Returns:
            提取的技能效能信号列表
        """
        if not trajectory or len(trajectory) < 2:
            return []

        signals: List[SkillEffectivenessSignal] = []

        for i, entry in enumerate(trajectory):
            entry_signals = self._analyze_turn(entry, i, agent_id, user_id)
            signals.extend(entry_signals)

        # 如果有 LLM 客户端，用 LLM 做深度分析
        if llm_client and len(trajectory) >= 3:
            llm_signals = await self._llm_deep_analysis(
                trajectory, session_id, agent_id, user_id, llm_client
            )
            signals.extend(llm_signals)

        # 去重和置信度过滤
        signals = self._deduplicate_signals(signals)
        signals = [s for s in signals if s.confidence >= 0.5]

        # 持久化
        self._persist_signals(signals)

        logger.info(
            "Extracted %d effectiveness signals from session %s",
            len(signals), session_id,
        )
        return signals

    def _analyze_turn(
        self,
        entry: Any,
        turn_index: int,
        agent_id: str,
        user_id: str,
    ) -> List[SkillEffectivenessSignal]:
        """单轮启发式分析：识别技能效能信号。"""
        signals = []
        user_msg = getattr(entry, "user_message", "") or ""
        assistant_msg = getattr(entry, "assistant_response", "") or ""
        tool_calls = getattr(entry, "tool_calls", []) or []
        skill_ids = getattr(entry, "skill_ids", []) or []

        user_lower = user_msg.lower()

        # ── 信号1: false_positive（误触发）──
        # 用户消息中包含否定词 + 技能被触发
        negation_patterns = ["不要", "不用", "别", "不需要", "取消", "停止", "别管"]
        if skill_ids and any(neg in user_lower for neg in negation_patterns):
            for skill_name in skill_ids:
                signals.append(SkillEffectivenessSignal(
                    signal_type="false_positive",
                    skill_name=skill_name,
                    trigger_keyword=self._extract_trigger_from_msg(user_msg, skill_name),
                    context=user_msg[:150],
                    confidence=0.7,
                    turn_index=turn_index,
                ))

        # ── 信号2: false_negative（漏触发）──
        # 用户明确提到功能但没有技能被触发
        skill_hint_keywords = {
            "搜索": ["web-search", "web_search"],
            "邮件": ["himalaya", "email"],
            "文档": ["docx", "pdf", "pptx", "xlsx"],
            "浏览器": ["browser-use", "browser"],
            "定时": ["cron"],
            "报告": ["report-writing"],
            "润色": ["text-polishing", "humanizer"],
            "分析": ["data-analysis"],
        }
        if not skill_ids:
            for keyword, expected_skills in skill_hint_keywords.items():
                if keyword in user_lower:
                    # 检查 trajectory 中下一个 entry 是否用了相关工具
                    signals.append(SkillEffectivenessSignal(
                        signal_type="false_negative",
                        skill_name=expected_skills[0],
                        trigger_keyword=keyword,
                        context=user_msg[:150],
                        confidence=0.5,  # 启发式分析置信度较低
                        turn_index=turn_index,
                    ))

        # ── 信号3: improve（需要改进）──
        # 技能触发后用户追问/修正
        if tool_calls and turn_index > 0:
            # 检查下一轮是否有用户修正
            # 这需要在 trajectory 层面分析，这里做单轮启发式
            error_indicators = ["错误", "不对", "不对", "重新", "换一个", "换种方式"]
            if any(ind in user_lower for ind in error_indicators) and skill_ids:
                for skill_name in skill_ids:
                    signals.append(SkillEffectivenessSignal(
                        signal_type="improve",
                        skill_name=skill_name,
                        trigger_keyword="",
                        context=user_msg[:150],
                        confidence=0.6,
                        turn_index=turn_index,
                    ))

        return signals

    async def _llm_deep_analysis(
        self,
        trajectory: List[Any],
        session_id: str,
        agent_id: str,
        user_id: str,
        llm_client: Any,
    ) -> List[SkillEffectivenessSignal]:
        """使用 LLM 做深度技能效能分析。"""
        # 构建对话文本
        conversation_lines = []
        for i, entry in enumerate(trajectory):
            user_msg = getattr(entry, "user_message", "") or ""
            assistant_msg = getattr(entry, "assistant_response", "") or ""
            tool_calls = getattr(entry, "tool_calls", []) or []
            skill_ids = getattr(entry, "skill_ids", []) or []

            if user_msg:
                conversation_lines.append(f"[Turn {i}] User: {user_msg[:200]}")
            if skill_ids:
                conversation_lines.append(f"[Turn {i}] Skills triggered: {', '.join(skill_ids)}")
            if tool_calls:
                tool_names = [tc.get("name", "unknown") for tc in tool_calls]
                conversation_lines.append(f"[Turn {i}] Tools used: {', '.join(tool_names)}")
            if assistant_msg:
                conversation_lines.append(f"[Turn {i}] Assistant: {assistant_msg[:200]}")

        conversation_text = "\n".join(conversation_lines[-20:])  # 最近 20 轮

        prompt = """分析以下对话中技能/工具的使用效能。

识别以下三种信号：
1. false_positive: 技能被触发但用户不需要（用户否定、取消、或技能结果被忽略）
2. false_negative: 用户期望某个功能但没有对应技能被触发
3. improve: 技能被使用但效果不佳（用户追问、修正、或结果被拒绝）

对话记录：
{conversation}

输出 ONLY valid JSON array:
[{{"signal_type": "false_positive|false_negative|improve", "skill_name": "...", "trigger_keyword": "...", "context": "...", "confidence": 0.0-1.0}}]
如果无信号，输出: []
""".format(conversation=conversation_text)

        try:
            response = await llm_client.achat(prompt)
            return self._parse_llm_signals(response, trajectory)
        except Exception as e:
            logger.warning("LLM deep analysis failed: %s", e)
            return []

    def _parse_llm_signals(self, response: str, trajectory: List[Any]) -> List[SkillEffectivenessSignal]:
        """解析 LLM 返回的信号。"""
        signals = []
        try:
            # 提取 JSON 数组
            import re
            match = re.search(r'\[.*\]', response, re.DOTALL)
            if not match:
                return []
            items = json.loads(match.group())
            for item in items:
                if isinstance(item, dict) and "signal_type" in item and "skill_name" in item:
                    signals.append(SkillEffectivenessSignal(
                        signal_type=item["signal_type"],
                        skill_name=item["skill_name"],
                        trigger_keyword=item.get("trigger_keyword", ""),
                        context=item.get("context", ""),
                        confidence=float(item.get("confidence", 0.6)),
                    ))
        except (json.JSONDecodeError, ValueError) as e:
            logger.warning("Failed to parse LLM signals: %s", e)
        return signals

    def _extract_trigger_from_msg(self, message: str, skill_name: str) -> str:
        """从消息中提取可能的触发词。"""
        # 简单实现：返回消息中的关键词
        keywords = ["搜索", "查询", "找", "帮我", "请"]
        for kw in keywords:
            if kw in message:
                return kw
        return message[:20]

    def _deduplicate_signals(self, signals: List[SkillEffectivenessSignal]) -> List[SkillEffectivenessSignal]:
        """按 (signal_type, skill_name, trigger_keyword) 去重。"""
        seen = set()
        deduped = []
        for s in signals:
            key = (s.signal_type, s.skill_name, s.trigger_keyword)
            if key not in seen:
                seen.add(key)
                deduped.append(s)
        return deduped

    def _persist_signals(self, signals: List[SkillEffectivenessSignal]) -> None:
        """持久化信号到 JSONL。"""
        if not signals:
            return
        try:
            from coapis.utils.file_lock import safe_append_jsonl
            for s in signals:
                safe_append_jsonl(self._signal_log_path, s.to_dict())
        except Exception as e:
            logger.warning("Failed to persist effectiveness signals: %s", e)

    # ── Direction 2: Skill Evolution → Agent Evolution ──

    def register_on_skill_improved(
        self, callback: Callable[[SkillImprovementFeedback], None]
    ) -> None:
        """注册技能改进回调。"""
        self._on_skill_improved = callback
        logger.info("Registered on_skill_improved callback")

    def register_on_trigger_enhanced(
        self, callback: Callable[[str, List[str]], None]
    ) -> None:
        """注册触发词增强回调。"""
        self._on_trigger_enhanced = callback
        logger.info("Registered on_trigger_enhanced callback")

    def notify_skill_improved(
        self,
        skill_name: str,
        improvement_type: str,
        description: str,
        old_version: str = "",
        new_version: str = "",
    ) -> None:
        """技能改进后通知智能体进化系统。

        这会：
        1. 保存新版本的效能指标快照
        2. 对比新旧版本效能，生成变更报告
        3. 记录改进反馈到 JSONL
        4. 触发 on_skill_improved 回调（如果已注册）
        """
        feedback = SkillImprovementFeedback(
            skill_name=skill_name,
            improvement_type=improvement_type,
            description=description,
            old_version=old_version,
            new_version=new_version,
        )

        # ── 保存新版本效能快照 ──
        if new_version:
            try:
                from .engine import get_evolution_engine
                from .version_manager import save_metrics_snapshot
                engine = get_evolution_engine()
                metrics = engine.get_skill_metric(skill_name)
                if metrics:
                    save_metrics_snapshot(skill_name, new_version, metrics)
            except Exception as e:
                logger.warning("Failed to save metrics snapshot: %s", e)

        # ── 版本效能对比 ──
        if old_version and new_version:
            try:
                from .version_manager import compare_versions
                diff = compare_versions(skill_name, old_version, new_version)
                if diff:
                    feedback.description += f"\n[效能对比] {diff.get('overall', 'unknown')}"
                    if diff.get("alerts"):
                        feedback.description += f"\n⚠️ 告警: {'; '.join(diff['alerts'])}"
                    logger.info(
                        "Version comparison %s %s→%s: %s",
                        skill_name, old_version, new_version,
                        diff.get("overall", "unknown"),
                    )
            except Exception as e:
                logger.warning("Version comparison failed: %s", e)

        # 持久化反馈
        self._persist_feedback(feedback)

        # 触发回调
        if self._on_skill_improved:
            try:
                self._on_skill_improved(feedback)
            except Exception as e:
                logger.warning("on_skill_improved callback failed: %s", e)

        logger.info(
            "Notified skill improvement: %s (%s -> %s)",
            skill_name, old_version, new_version,
        )

    def notify_trigger_enhanced(
        self,
        skill_name: str,
        new_triggers: List[str],
    ) -> None:
        """触发词增强后通知智能体进化系统。

        这会：
        1. 触发 on_trigger_enhanced 回调（如果已注册）
        2. 更新智能体的触发词缓存
        """
        if self._on_trigger_enhanced:
            try:
                self._on_trigger_enhanced(skill_name, new_triggers)
            except Exception as e:
                logger.warning("on_trigger_enhanced callback failed: %s", e)

        logger.info("Notified trigger enhancement: %s → %s", skill_name, new_triggers)

    def _persist_feedback(self, feedback: SkillImprovementFeedback) -> None:
        """持久化改进反馈到 JSONL。"""
        try:
            from coapis.utils.file_lock import safe_append_jsonl
            safe_append_jsonl(self._feedback_log_path, feedback.to_dict())
        except Exception as e:
            logger.warning("Failed to persist improvement feedback: %s", e)

    # ── Signal Query API ──

    def get_recent_signals(
        self,
        skill_name: Optional[str] = None,
        signal_type: Optional[str] = None,
        limit: int = 50,
    ) -> List[dict]:
        """查询最近的效能信号。"""
        signals = []
        if not self._signal_log_path.exists():
            return signals
        try:
            with open(self._signal_log_path, "r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        entry = json.loads(line)
                        if skill_name and entry.get("skill_name") != skill_name:
                            continue
                        if signal_type and entry.get("signal_type") != signal_type:
                            continue
                        signals.append(entry)
                    except json.JSONDecodeError:
                        continue
        except Exception as e:
            logger.warning("Failed to read effectiveness signals: %s", e)

        return signals[-limit:]

    def get_recent_feedback(
        self,
        skill_name: Optional[str] = None,
        limit: int = 20,
    ) -> List[dict]:
        """查询最近的改进反馈。"""
        feedbacks = []
        if not self._feedback_log_path.exists():
            return feedbacks
        try:
            with open(self._feedback_log_path, "r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        entry = json.loads(line)
                        if skill_name and entry.get("skill_name") != skill_name:
                            continue
                        feedbacks.append(entry)
                    except json.JSONDecodeError:
                        continue
        except Exception as e:
            logger.warning("Failed to read improvement feedback: %s", e)

        return feedbacks[-limit:]


# ── Singleton ────────────────────────────────────────────────────────────────

_bridge_instance: Optional[SkillEvolutionBridge] = None


def get_skill_evolution_bridge() -> SkillEvolutionBridge:
    """获取全局桥接层单例。"""
    global _bridge_instance
    if _bridge_instance is None:
        _bridge_instance = SkillEvolutionBridge()
    return _bridge_instance
