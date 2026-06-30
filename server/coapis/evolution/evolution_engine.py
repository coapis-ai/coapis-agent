# -*- coding: utf-8 -*-
# -*- coding: utf-8 -*-
# Copyright 2026 蜜蜂 & CoApis Contributors
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

"""CoApis 进化引擎 - 从经验中自动学习，持续进化。

借鉴 CoApis 的自我进化机制，但针对 CoApis 的多层架构优化。

核心能力:
1. **轨迹记录**: 记录每次对话的完整轨迹（用户输入+Agent输出+工具调用）
2. **Nudge 系统**: 周期性触发审查（记忆审查 + 技能审查）
3. **经验提取**: 使用 LLM 从对话中自动提取有价值经验
4. **知识流动**: 实例层经验 → 专业层 → 基础层（需审核）
5. **后台审查**: 不阻塞主对话，异步执行

生命周期:
    on_turn_start()   → 每轮对话开始: 记录轨迹、检查 Nudge
    on_turn_end()     → 每轮对话结束: 保存轨迹、更新计数器
    on_session_end()  → 会话结束: 触发经验提取、同步记忆
    on_nudge_trigger()→ Nudge 触发: 后台审查、更新记忆/技能

与 CoApis 的差异:
- CoApis: 单 Agent + 外部 MemoryProvider
- CoApis: 多层架构（基础层/专业层/实例层）+ 内置 FoundationManager
"""
from __future__ import annotations

import asyncio
import json
import logging
import uuid
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Optional

from ..utils.file_lock import safe_read_json, safe_write_json, safe_append_jsonl

logger = logging.getLogger(__name__)


# =========================================================================
# 配置
# =========================================================================

@dataclass
class EvolutionConfig:
    """进化引擎配置（全部可配置）。"""
    enabled: bool = True
    memory_nudge_interval: int = 10          # 记忆审查间隔（对话轮数）
    skill_nudge_interval: int = 8            # 技能审查间隔（工具调用次数）
    experience_extraction_min_turns: int = 2  # 最少对话轮数才触发经验提取
    min_confidence: float = 0.6              # 经验上报最低置信度
    trajectory_retention_days: int = 30      # 轨迹保留天数
    max_trajectory_per_session: int = 50     # 每会话最大轨迹数
    # 采样策略：避免每个会话都调用 LLM 提取
    extraction_cooldown_seconds: int = 300   # 两次提取最短间隔（秒）
    extraction_min_total_chars: int = 200    # 对话总字符数低于此跳过提取
    # 梦境优化：定期整理 MEMORY.md
    dream_interval_sessions: int = 5         # 每 N 次会话触发一次梦境优化

    @classmethod
    def from_dict(cls, data: dict) -> "EvolutionConfig":
        return cls(**{k: v for k, v in data.items() if k in cls.__dataclass_fields__})


# =========================================================================
# 数据模型
# =========================================================================

@dataclass
class TrajectoryEntry:
    """单次对话轨迹。"""
    turn_id: str = field(default_factory=lambda: str(uuid.uuid4())[:8])
    timestamp: datetime = field(default_factory=datetime.now)
    user_message: str = ""
    assistant_message: str = ""
    tool_calls: list[dict] = field(default_factory=list)
    tool_results: list[dict] = field(default_factory=list)
    tokens_used: int = 0
    session_id: str = ""
    agent_id: str = ""
    user_id: str = ""
    trigger_events: list[dict] = field(default_factory=list)
    trigger_outcomes: list[dict] = field(default_factory=list)
    
    def to_dict(self) -> dict:
        return {
            "turn_id": self.turn_id,
            "timestamp": self.timestamp.isoformat(),
            "user_message": self.user_message,
            "assistant_message": self.assistant_message,
            "tool_calls": self.tool_calls,
            "tool_results": self.tool_results,
            "tokens_used": self.tokens_used,
            "session_id": self.session_id,
            "agent_id": self.agent_id,
            "user_id": self.user_id,
            "trigger_events": self.trigger_events,
            "trigger_outcomes": self.trigger_outcomes,
        }


@dataclass
class ExtractedExperience:
    """提取的经验。"""
    experience_id: str = field(default_factory=lambda: str(uuid.uuid4())[:8])
    title: str = ""
    content: str = ""
    experience_type: str = "lesson"  # lesson | pattern | preference | skill
    category: str = "general"
    tags: list[str] = field(default_factory=list)
    source_session: str = ""
    source_user: str = ""
    source_agent: str = ""
    confidence: float = 0.5  # LLM 提取的置信度
    is_generalizable: bool = False  # 是否可泛化到所有 Agent
    memory_type: str = "long_term"  # 目标记忆类型
    importance_score: float = 0.5  # 重要性评分 [0, 1]，用于自适应知识流动阈值
    status: str = "pending"  # pending | approved | reviewed | rejected | promoted
    
    def to_dict(self) -> dict:
        return {
            "experience_id": self.experience_id,
            "title": self.title,
            "content": self.content,
            "experience_type": self.experience_type,
            "category": self.category,
            "tags": self.tags,
            "source_session": self.source_session,
            "source_user": self.source_user,
            "source_agent": self.source_agent,
            "confidence": self.confidence,
            "is_generalizable": self.is_generalizable,
            "memory_type": self.memory_type,
            "importance_score": self.importance_score,
        }


# =========================================================================
# 进化引擎
# =========================================================================

class EvolutionEngine:
    """
    进化引擎主类。

    职责:
    1. 管理对话轨迹记录
    2. 管理 Nudge 计数器
    3. 触发后台审查
    4. 协调经验提取
    5. 管理知识流动

    Attributes:
        data_dir: 数据存储目录
        foundation_manager: 基础层管理器
        enabled: 是否启用进化
        memory_nudge_interval: 记忆审查间隔（对话轮数）
        skill_nudge_interval: 技能审查间隔（工具调用次数）
    """

    def __init__(
        self,
        data_dir: str | Path,
        foundation_manager: Any = None,
        config: EvolutionConfig | None = None,
        agent_core: Any = None,  # For ExperienceExtractor
        knowledge_flow: Any = None,  # For KnowledgeFlow
        backend_review: Any = None,  # For BackendReview
        workspace_dir: str | Path | None = None,  # Explicit workspace dir for MEMORY.md
        # Legacy params for backward compatibility
        enabled: bool | None = None,
        memory_nudge_interval: int | None = None,
        skill_nudge_interval: int | None = None,
    ):
        self.data_dir = Path(data_dir)
        # workspace_dir: explicit path to user workspace (where MEMORY.md lives).
        # Falls back to data_dir.parent for backward compatibility.
        self.workspace_dir = Path(workspace_dir) if workspace_dir else self.data_dir.parent
        self.foundation_manager = foundation_manager
        self.agent_core = agent_core  # LLM client for experience extraction
        
        # 配置（支持直接传 config 或 legacy 参数）
        if config:
            self.config = config
        else:
            self.config = EvolutionConfig(
                enabled=enabled if enabled is not None else True,
                memory_nudge_interval=memory_nudge_interval if memory_nudge_interval is not None else 10,
                skill_nudge_interval=skill_nudge_interval if skill_nudge_interval is not None else 8,
            )
        
        # 从 config 读取参数
        self.enabled = self.config.enabled
        self.memory_nudge_interval = self.config.memory_nudge_interval
        self.skill_nudge_interval = self.config.skill_nudge_interval
        
        # 计数器
        self._turns_since_memory_review: int = 0
        self._tools_since_skill_review: int = 0
        
        # 当前会话状态
        self._current_session_id: str = ""
        self._current_agent_id: str = ""
        self._current_user_id: str = ""
        self._current_trajectory: list[TrajectoryEntry] = []
        
        # 经验队列（待审核）
        self._pending_experiences: list[ExtractedExperience] = []
        
        # 采样控制
        self._last_extraction_time: float = 0.0
        # 梦境优化计数
        self._sessions_since_dream: int = 0

        # LLM 调用统计
        self._llm_stats: dict[str, int] = {"success": 0, "failure": 0, "timeout": 0}

        # 采样统计
        self._sampling_stats: dict[str, int] = {
            "total_sessions": 0,
            "skipped_cooldown": 0,
            "skipped_quality": 0,
            "extracted": 0,
        }
        
        # 异步锁（防止并发任务交错执行导致数据不一致）
        self._lock: asyncio.Lock = asyncio.Lock()
        
        # 子模块
        self.knowledge_flow = knowledge_flow
        self.backend_review = backend_review
        
        # 跨 Agent 进化引擎（可选）
        self.cross_agent_evolution: Any = None
        
        # 确保目录结构
        self._ensure_directory_structure()
        
        logger.info(
            "EvolutionEngine initialized (enabled=%s, memory_nudge=%d, skill_nudge=%d, "
            "knowledge_flow=%s, backend_review=%s, cross_agent=%s)",
            self.enabled, self.memory_nudge_interval, self.skill_nudge_interval,
            knowledge_flow is not None,
            backend_review is not None,
            self.cross_agent_evolution is not None,
        )

    def _ensure_directory_structure(self) -> None:
        """确保进化引擎的目录结构。"""
        dirs = [
            self.data_dir / "evolution" / "trajectories",
            self.data_dir / "evolution" / "experiences",
            self.data_dir / "evolution" / "reviews",
        ]
        for d in dirs:
            d.mkdir(parents=True, exist_ok=True)

    # ------------------------------------------------------------------
    # 会话生命周期
    # ------------------------------------------------------------------

    def on_session_start(
        self,
        session_id: str,
        agent_id: str,
        user_id: str,
    ) -> None:
        """会话开始时调用。"""
        if not self.enabled:
            return
        
        self._current_session_id = session_id
        self._current_agent_id = agent_id
        self._current_user_id = user_id
        self._current_trajectory = []
        
        logger.info(
            "EvolutionEngine: session started (session=%s, agent=%s, user=%s)",
            session_id, agent_id, user_id,
        )

    def on_turn_start(self, user_message: str) -> None:
        """每轮对话开始时调用。"""
        if not self.enabled:
            return
        
        # 创建轨迹条目
        entry = TrajectoryEntry(
            user_message=user_message,
            session_id=self._current_session_id,
            agent_id=self._current_agent_id,
            user_id=self._current_user_id,
        )
        self._current_trajectory.append(entry)
        
        # 更新计数器
        self._turns_since_memory_review += 1
        
        # 检查 Nudge
        self._check_nudges()

    def on_turn_end(
        self,
        assistant_message: str,
        tool_calls: list[dict] | None = None,
        tool_results: list[dict] | None = None,
        tokens_used: int = 0,
        trigger_events: list[dict] | None = None,
        trigger_outcomes: list[dict] | None = None,
    ) -> None:
        """每轮对话结束时调用。"""
        if not self.enabled:
            return

        # Auto-pull trigger data from TriggerTracker if not explicitly passed
        if trigger_events is None and trigger_outcomes is None:
            try:
                from ..agents.utils.trigger_tracker import get_trigger_tracker
                tracker = get_trigger_tracker()
                active = tracker.get_active_events()
                if active:
                    trigger_events = [e.to_dict() for e in active]
                outcomes = tracker.get_session_outcomes()
                if outcomes:
                    trigger_outcomes = [o.to_dict() for o in outcomes[-len(tool_calls or []):]]
            except Exception:
                pass
        
        if self._current_trajectory:
            entry = self._current_trajectory[-1]
            entry.assistant_message = assistant_message
            entry.tool_calls = tool_calls or []
            entry.tool_results = tool_results or []
            entry.tokens_used = tokens_used
            if trigger_events:
                entry.trigger_events.extend(trigger_events)
            if trigger_outcomes:
                entry.trigger_outcomes.extend(trigger_outcomes)
            
            # Save trajectory immediately after each turn (not just on session end)
            self._save_trajectory()
            
            # 更新技能审查计数器
            if tool_calls:
                self._tools_since_skill_review += len(tool_calls)
                
                # 检查技能 Nudge
                self._check_skill_nudge()

    async def on_session_end(self) -> list[ExtractedExperience]:
        """
        会话结束时调用。

        1. 保存轨迹
        2. 采样检查（冷却时间 + 对话质量）
        3. 触发经验提取
        4. 返回提取的经验（待审核）
        """
        if not self.enabled:
            return []
        
        async with self._lock:
            self._sampling_stats["total_sessions"] += 1
            # 1. 保存轨迹
            self._save_trajectory()
            
            # 2. 采样策略：冷却时间检查
            import time
            now = time.time()
            cooldown = self.config.extraction_cooldown_seconds
            if (now - self._last_extraction_time) < cooldown:
                self._sampling_stats["skipped_cooldown"] += 1
                logger.debug(
                    "EvolutionEngine: extraction skipped (cooldown %ds)",
                    cooldown,
                )
                self._turns_since_memory_review = 0
                self._tools_since_skill_review = 0
                return []
            
            # 3. 采样策略：对话质量检查
            total_chars = sum(
                len(e.user_message) + len(e.assistant_message)
                for e in self._current_trajectory
            )
            min_chars = self.config.extraction_min_total_chars
            if total_chars < min_chars:
                self._sampling_stats["skipped_quality"] += 1
                logger.debug(
                    "EvolutionEngine: extraction skipped (only %d chars, need %d)",
                    total_chars, min_chars,
                )
                self._turns_since_memory_review = 0
                self._tools_since_skill_review = 0
                return []
            
            # 4. 提取经验
            experiences = []
            if len(self._current_trajectory) >= self.config.experience_extraction_min_turns:
                experiences = await self._extract_experiences()
                self._last_extraction_time = now
                self._sampling_stats["extracted"] += len(experiences)
            
            # 5. 重置计数器
            self._turns_since_memory_review = 0
            self._tools_since_skill_review = 0
        
        logger.info(
            "EvolutionEngine: session ended, extracted %d experiences",
            len(experiences),
        )

        # 6. 梦境优化触发：每 N 次会话整理一次 MEMORY.md
        self._sessions_since_dream += 1
        if self._sessions_since_dream >= self.config.dream_interval_sessions:
            self._sessions_since_dream = 0
            asyncio.create_task(self._trigger_dream_optimization())

        return experiences

    # ------------------------------------------------------------------
    # 经验提取
    # ------------------------------------------------------------------

    async def _extract_experiences(self) -> list[ExtractedExperience]:
        """使用 ExperienceExtractor 从当前轨迹中提取经验。"""
        from .experience_extractor import ExperienceExtractor

        if not self.agent_core or not self._current_trajectory:
            return []

        # Load existing MEMORY.md content for content-based dedup
        existing_memory = ""
        try:
            mem_file = self.workspace_dir / "MEMORY.md"
            if mem_file.exists():
                existing_memory = mem_file.read_text(encoding="utf-8").strip()
        except Exception:
            pass

        extractor = ExperienceExtractor(
            agent_core=self.agent_core,
            existing_memory_content=existing_memory,
        )
        experiences = await extractor.extract_from_trajectory(
            trajectory=self._current_trajectory,
            session_id=self._current_session_id,
            agent_id=self._current_agent_id,
            user_id=self._current_user_id,
        )
        
        # ── P0: 按置信度自动分级处理 ──
        auto_approved = 0
        auto_discarded = 0
        pending_count = 0
        for exp in experiences:
            if exp.confidence >= 0.8:
                # 高置信度 → 自动通过，直接写入经验库
                exp.status = "approved"
                exp.approved_by = "auto_high_confidence"
                await self._save_experience(exp)
                auto_approved += 1
            elif exp.confidence < 0.5:
                # 低置信度 → 自动丢弃
                auto_discarded += 1
            else:
                # 中间地带 → 进入待审核队列
                self._pending_experiences.append(exp)
                pending_count += 1

        # 如果有 knowledge_flow，提交自动通过的经验进行知识流动
        if self.knowledge_flow:
            for exp in experiences:
                if exp.status == "approved":
                    await self.knowledge_flow.evaluate_and_flow(
                        experience=exp,
                        agent_id=self._current_agent_id,
                        user_id=self._current_user_id,
                    )

        logger.info(
            "EvolutionEngine: extracted %d experiences (auto_approved=%d, pending=%d, discarded=%d)",
            len(experiences), auto_approved, pending_count, auto_discarded,
        )
        
        logger.info(
            "EvolutionEngine: extracted %d experiences from trajectory (%d total pending)",
            len(experiences), len(self._pending_experiences),
        )
        
        return experiences

    # ------------------------------------------------------------------
    # 轨迹记录
    # ------------------------------------------------------------------

    def _save_trajectory(self) -> None:
        """保存当前会话的轨迹到 JSONL 文件。"""
        if not self._current_trajectory:
            return
        
        trajectory_file = (
            self.data_dir
            / "evolution"
            / "trajectories"
            / f"{self._current_session_id}.jsonl"
        )
        
        try:
            for entry in self._current_trajectory:
                safe_append_jsonl(trajectory_file, entry.to_dict())
            
            logger.debug("Trajectory saved to %s (%d entries)", trajectory_file, len(self._current_trajectory))
        except Exception as e:
            logger.error("Failed to save trajectory: %s", e)

    # ------------------------------------------------------------------
    # Nudge 系统
    # ------------------------------------------------------------------

    def _check_nudges(self) -> None:
        """检查是否触发 Nudge。"""
        # 记忆审查
        if self._turns_since_memory_review >= self.memory_nudge_interval:
            logger.info(
                "EvolutionEngine: memory nudge triggered (turns=%d)",
                self._turns_since_memory_review,
            )
            asyncio.create_task(self._spawn_memory_review())
            self._turns_since_memory_review = 0

    def _check_skill_nudge(self) -> None:
        """检查技能 Nudge。"""
        if self._tools_since_skill_review >= self.skill_nudge_interval:
            logger.info(
                "EvolutionEngine: skill nudge triggered (tools=%d)",
                self._tools_since_skill_review,
            )
            asyncio.create_task(self._spawn_skill_review())
            self._tools_since_skill_review = 0

    async def _spawn_memory_review(self) -> None:
        """
        后台记忆审查。

        使用辅助 LLM 回顾最近的对话，提取值得记忆的信息。
        提取结果自动追加到 MEMORY.md。
        """
        if not self._current_trajectory:
            return

        recent = self._current_trajectory[-self.memory_nudge_interval:]
        review_prompt = self._build_memory_review_prompt(recent)

        try:
            result = await self._call_review_llm(review_prompt)
            if result and "nothing to save" not in result.lower():
                # Parse and write to MEMORY.md
                self._append_to_memory(result)
                logger.info(
                    "Memory nudge: extracted and saved to MEMORY.md (%d chars)",
                    len(result),
                )
            else:
                logger.debug("Memory nudge: nothing worth saving")
        except Exception as e:
            logger.warning("Memory nudge LLM call failed: %s", e)
            # Fallback: save review request for later processing
            self._save_review_request("memory", review_prompt)

    async def _trigger_dream_optimization(self) -> None:
        """
        梦境优化：定期整理 MEMORY.md，去重、精简、合并。

        每 N 次会话触发一次，使用 LLM 对 MEMORY.md 进行优化。
        不阻塞主流程。集成容量管理：备份版本、容量检查、自动淘汰。
        """
        try:
            memory_file = self.workspace_dir / "MEMORY.md"
            if not memory_file.exists():
                return

            existing = memory_file.read_text(encoding="utf-8").strip()
            if len(existing) < 100:
                return  # 内容太少，不需要优化

            # ── 容量管理：备份 + 淘汰检查 ──
            try:
                from .memory_capacity import MemoryCapacityManager
                cap_mgr = MemoryCapacityManager(memory_file)
                cap_mgr.backup_version(reason="pre_dream")

                # 自动淘汰过时条目
                archive_result = cap_mgr.auto_archive_stale()
                if archive_result["archived_count"] > 0:
                    logger.info(
                        "Memory capacity: auto-archived %d stale entries",
                        archive_result["archived_count"],
                    )

                # 容量检查：如果超限，在 dream prompt 中提示 LLM 精简
                capacity = cap_mgr.check_capacity()
                over_limit = capacity["over_limit"]
                current_tokens = capacity["current_tokens"]
            except Exception as cap_err:
                logger.debug("Memory capacity check failed: %s", cap_err)
                over_limit = False
                current_tokens = 0

            # 读取最近的 daily logs 作为增量信息
            daily_dir = workspace_dir / "memory"
            today_logs = ""
            if daily_dir.exists():
                from datetime import datetime
                today = datetime.now().strftime("%Y-%m-%d")
                today_file = daily_dir / f"{today}.md"
                if today_file.exists():
                    today_logs = today_file.read_text(encoding="utf-8").strip()

            from ..agents.memory.prompts import DREAM_OPTIMIZATION_ZH
            dream_prompt = (
                f"{DREAM_OPTIMIZATION_ZH}\n\n"
                f"--- 当前长期记忆 ---\n{existing}\n--- 结束 ---\n\n"
            )
            if today_logs:
                dream_prompt += f"--- 今日日志 ---\n{today_logs[:3000]}\n--- 结束 ---\n"

            # 容量超限时提醒 LLM 精简
            if over_limit:
                dream_prompt += (
                    f"\n⚠️ 当前记忆约 {current_tokens} tokens，超过 10K 上限。"
                    f"请重点精简：去除重复、合并相似条目、删除过时信息。"
                    f"保留锁定条目和高置信度条目。\n"
                )

            result = await self._call_review_llm(dream_prompt)
            if result and len(result) > 50:
                # 生成对比报告
                old_lines = existing.splitlines()
                new_lines = result.strip().splitlines()
                old_tokens = len(existing)
                new_tokens = len(result.strip())
                diff_summary = (
                    f"优化前: {old_tokens} 字符, {len(old_lines)} 行\n"
                    f"优化后: {new_tokens} 字符, {len(new_lines)} 行\n"
                    f"精简: {old_tokens - new_tokens} 字符 ({(old_tokens - new_tokens) / max(old_tokens, 1) * 100:.0f}%)"
                )

                # 保存为待确认草稿（而非直接覆写）
                from datetime import datetime
                timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
                draft_dir = workspace_dir / ".dream_drafts"
                draft_dir.mkdir(parents=True, exist_ok=True)
                draft_file = draft_dir / f"draft_{timestamp}.md"
                draft_meta = draft_dir / f"draft_{timestamp}.json"

                import json as _json
                draft_file.write_text(result.strip(), encoding="utf-8")
                draft_meta.write_text(
                    _json.dumps({
                        "created_at": timestamp,
                        "old_chars": old_tokens,
                        "new_chars": new_tokens,
                        "diff_summary": diff_summary,
                        "approved": False,
                        "approved_by": None,
                        "approved_at": None,
                    }, ensure_ascii=False, indent=2),
                    encoding="utf-8",
                )

                logger.info(
                    "Dream optimization: draft saved (pending admin approval)\n%s",
                    diff_summary,
                )

                # P1: 所有智能体自动通过梦境优化（已有备份可回滚）
                memory_file.write_text(
                    f"{result.strip()}\n\n<!-- 梦境优化于 {timestamp} (auto-approved) -->\n",
                    encoding="utf-8",
                )
                logger.info("Dream optimization auto-approved for %s", workspace_dir.name)
            else:
                logger.debug("Dream optimization: LLM returned empty/negligible result")
        except Exception as e:
            logger.warning("Dream optimization failed: %s", e)

    async def _spawn_skill_review(self) -> None:
        """
        后台技能审查。

        使用辅助 LLM 回顾最近的工具调用，判断是否需要创建/更新技能。
        审查结果保存到 evolution/reviews/ 待处理，同时自动创建技能草稿。
        """
        recent_tool_calls = []
        for entry in self._current_trajectory[-self.skill_nudge_interval:]:
            recent_tool_calls.extend(entry.tool_calls)

        if not recent_tool_calls:
            return

        review_prompt = self._build_skill_review_prompt(recent_tool_calls)

        try:
            result = await self._call_review_llm(review_prompt)
            if result and "no skill" not in result.lower():
                # Save skill suggestion for admin review
                self._save_review_request("skill", review_prompt, result)

                # Auto-create skill draft
                draft_path = self._create_skill_draft(result)
                if draft_path:
                    logger.info(
                        "Skill nudge: draft created at %s",
                        draft_path,
                    )
                else:
                    logger.info(
                        "Skill nudge: suggestion saved (%d chars), no draft created",
                        len(result),
                    )
            else:
                logger.debug("Skill nudge: no skill suggestions")
        except Exception as e:
            logger.warning("Skill nudge LLM call failed: %s", e)
            self._save_review_request("skill", review_prompt)

    async def _call_review_llm(self, prompt: str) -> str:
        """调用辅助 LLM 进行审查。

        优先使用 agent_core.client，fallback 到全局 LLM client。
        内置重试机制（最多 3 次）和超时控制（30 秒）。
        """
        max_retries = 3
        timeout_seconds = 30

        for attempt in range(max_retries):
            try:
                # Try agent_core (ExperienceExtractor pattern)
                if self.agent_core and hasattr(self.agent_core, "client"):
                    response = await asyncio.wait_for(
                        self.agent_core.client.chat.completions.create(
                            model=self.agent_core.model,
                            messages=[
                                {
                                    "role": "system",
                                    "content": (
                                        "You are a memory review assistant. "
                                        "Analyze conversations and extract valuable insights. "
                                        "Output concise, actionable items."
                                    ),
                                },
                                {"role": "user", "content": prompt},
                            ],
                            max_tokens=1000,
                            temperature=0.3,
                        ),
                        timeout=timeout_seconds,
                    )
                    self._llm_stats["success"] += 1
                    return response.choices[0].message.content or ""

                # Fallback: try to create a lightweight LLM client
                from ..agents.model_factory import create_model_and_formatter
                from ..config import load_config
                config = load_config()
                model, _ = create_model_and_formatter(config)
                if model and hasattr(model, "client"):
                    response = await asyncio.wait_for(
                        model.client.chat.completions.create(
                            model=model.model_name,
                            messages=[
                                {"role": "system", "content": "You are a review assistant."},
                                {"role": "user", "content": prompt},
                            ],
                            max_tokens=1000,
                            temperature=0.3,
                        ),
                        timeout=timeout_seconds,
                    )
                    self._llm_stats["success"] += 1
                    return response.choices[0].message.content or ""

            except asyncio.TimeoutError:
                self._llm_stats["timeout"] += 1
                logger.warning(
                    "LLM call timeout (attempt %d/%d, %ds)",
                    attempt + 1, max_retries, timeout_seconds,
                )
            except Exception as e:
                self._llm_stats["failure"] += 1
                logger.warning(
                    "LLM call failed (attempt %d/%d): %s",
                    attempt + 1, max_retries, e,
                )

            # Wait before retry (exponential backoff)
            if attempt < max_retries - 1:
                await asyncio.sleep(2 ** attempt)

        return ""

    def _append_to_memory(self, content: str) -> None:
        """将审查结果追加到 MEMORY.md。"""
        try:
            memory_file = self.workspace_dir / "MEMORY.md"

            if not memory_file.exists():
                return

            existing = memory_file.read_text(encoding="utf-8").strip()
            timestamp = datetime.now().strftime("%Y-%m-%d %H:%M")
            new_section = (
                f"\n\n## 自动提取 ({timestamp})\n\n{content}"
            )
            memory_file.write_text(
                existing + new_section,
                encoding="utf-8",
            )
            # 审计日志
            try:
                from .audit_logger import get_audit_logger, AuditEntry
                get_audit_logger().log(AuditEntry(
                    change_type="add", target_type="memory",
                    target_id=str(memory_file),
                    risk_level="L0", review_method="auto", decision="approved",
                    reason="经验自动提取写入 MEMORY.md",
                    content_before="", content_after=content[:500],
                    source_user=self._current_user_id,
                    source_agent=self._current_agent_id,
                ))
            except Exception:
                pass
        except Exception as e:
            logger.warning("Failed to append to MEMORY.md: %s", e)

    async def _save_experience(self, exp: "ExtractedExperience") -> None:
        """保存已通过的经验到经验库（JSONL 文件）。"""
        exp_dir = self.data_dir / "evolution" / "experiences"
        exp_dir.mkdir(parents=True, exist_ok=True)
        exp_file = exp_dir / "approved.jsonl"
        try:
            record = exp.to_dict() if hasattr(exp, "to_dict") else {
                "experience_id": exp.experience_id,
                "title": exp.title,
                "content": exp.content,
                "experience_type": exp.experience_type,
                "category": exp.category,
                "tags": exp.tags,
                "confidence": exp.confidence,
                "status": exp.status,
                "approved_by": getattr(exp, "approved_by", ""),
                "source_session": exp.source_session,
                "source_agent": exp.source_agent,
                "source_user": exp.source_user,
            }
            safe_append_jsonl(exp_file, record)
            logger.info(
                "Experience auto-approved: id=%s, confidence=%.2f, title=%s",
                exp.experience_id[:8], exp.confidence, exp.title[:30],
            )
        except Exception as e:
            logger.warning("Failed to save experience: %s", e)

    def _save_review_request(
        self, review_type: str, prompt: str, result: str = "",
    ) -> None:
        """保存审查请求（待 LLM 处理）。"""
        review_file = (
            self.data_dir
            / "evolution"
            / "reviews"
            / f"{self._current_session_id}_{review_type}.json"
        )

        review_data = {
            "type": review_type,
            "session_id": self._current_session_id,
            "timestamp": datetime.now().isoformat(),
            "prompt": prompt,
            "result": result,
            "status": "pending",
        }

        try:
            review_file.write_text(
                json.dumps(review_data, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
        except Exception as e:
            logger.error("Failed to save review request: %s", e)

    def _create_skill_draft(self, llm_result: str) -> str | None:
        """从 LLM 审查结果中解析技能信息并自动创建生效。

        P2: 自动写入 skills/ 目录，标记 source: auto_generated。
        用户可在技能页面查看和删除。

        Args:
            llm_result: LLM 返回的技能建议 JSON 字符串

        Returns:
            技能路径，失败返回 None
        """
        try:
            # Parse JSON from LLM result
            start = llm_result.find("{")
            end = llm_result.rfind("}") + 1
            if start < 0 or end <= start:
                logger.debug("No JSON found in skill suggestion")
                return None

            data = json.loads(llm_result[start:end])
            skill_name = data.get("skill_name", "").strip()
            description = data.get("description", "").strip()
            action = data.get("action", "create").strip()

            if not skill_name or not description:
                logger.debug("Incomplete skill suggestion: name=%s, desc=%s", skill_name, description[:50] if description else "")
                return None

            # Sanitize skill name
            skill_name = skill_name.lower().replace(" ", "_").replace("-", "_")
            skill_name = "".join(c for c in skill_name if c.isalnum() or c == "_")
            if not skill_name:
                return None

            # P2: 直接写入 skills/ 目录（自动生效）
            skills_dir = self.workspace_dir / "skills"
            skills_dir.mkdir(parents=True, exist_ok=True)

            skill_dir = skills_dir / skill_name
            if skill_dir.exists():
                logger.info("Skill already exists, skipping: %s", skill_name)
                return str(skill_dir)

            skill_dir.mkdir(parents=True, exist_ok=True)

            # Generate SKILL.md with auto_generated marker
            timestamp = datetime.now().strftime("%Y-%m-%d %H:%M")
            skill_md = (
                f"---\n"
                f"name: {skill_name}\n"
                f"description: \"{description}\"\n"
                f"metadata:\n"
                f"  coapis:\n"
                f"    priority: on-demand\n"
                f"    source: auto_generated\n"
                f"    created_by: evolution_nudge\n"
                f"    created_at: \"{timestamp}\"\n"
                f"    action: {action}\n"
                f"---\n\n"
                f"# {skill_name}\n\n"
                f"{description}\n\n"
                f"<!-- 由进化系统 Nudge 自动生成，可在技能页面删除 -->\n"
            )
            (skill_dir / "SKILL.md").write_text(skill_md, encoding="utf-8")

            # Save metadata
            meta = {
                "skill_name": skill_name,
                "description": description,
                "action": action,
                "created_at": timestamp,
                "session_id": self._current_session_id,
                "status": "auto_active",
                "source": "auto_generated",
                "version": 1,
            }
            (skill_dir / "meta.json").write_text(
                json.dumps(meta, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )

            logger.info("Auto-created skill: %s at %s", skill_name, skill_dir)
            return str(skill_dir)

        except Exception as e:
            logger.warning("Failed to create skill draft: %s", e)
            return None

    @staticmethod
    def approve_skill_draft(
        workspace_dir: str | Path,
        skill_name: str,
        approved_by: str = "admin",
    ) -> bool:
        """管理员确认技能草稿，将其激活。

        将草稿从 .skill_drafts/ 移动到 skills/ 目录。

        Args:
            workspace_dir: 工作目录路径
            skill_name: 技能名称
            approved_by: 审批人

        Returns:
            是否成功
        """
        workspace_dir = Path(workspace_dir)
        # Normalize skill name (same as _create_skill_draft)
        skill_name = skill_name.lower().replace(" ", "_").replace("-", "_")
        skill_name = "".join(c for c in skill_name if c.isalnum() or c == "_")
        draft_dir = workspace_dir / ".skill_drafts" / skill_name
        if not draft_dir.exists():
            logger.warning("Skill draft not found: %s", skill_name)
            return False

        skills_dir = workspace_dir / "skills" / skill_name
        try:
            import shutil
            # Backup existing skill if updating
            if skills_dir.exists():
                backup_dir = workspace_dir / ".skill_backups" / f"{skill_name}_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
                backup_dir.parent.mkdir(parents=True, exist_ok=True)
                shutil.copytree(skills_dir, backup_dir)
                logger.info("Backed up existing skill to %s", backup_dir)
                shutil.rmtree(skills_dir)

            # Move draft to active skills
            shutil.copytree(draft_dir, skills_dir)

            # Update metadata
            meta_file = skills_dir / "draft_meta.json"
            if meta_file.exists():
                meta = json.loads(meta_file.read_text(encoding="utf-8"))
                meta["status"] = "approved"
                meta["approved_by"] = approved_by
                meta["approved_at"] = datetime.now().isoformat()
                meta_file.write_text(
                    json.dumps(meta, ensure_ascii=False, indent=2),
                    encoding="utf-8",
                )

            # Remove draft flag from SKILL.md
            skill_md = skills_dir / "SKILL.md"
            if skill_md.exists():
                content = skill_md.read_text(encoding="utf-8")
                content = content.replace("    draft: true", "    draft: false")
                skill_md.write_text(content, encoding="utf-8")

            # Clean up draft
            shutil.rmtree(draft_dir)
            logger.info("Approved skill draft: %s by %s", skill_name, approved_by)
            return True

        except Exception as e:
            logger.warning("Failed to approve skill draft %s: %s", skill_name, e)
            return False

    @staticmethod
    def list_skill_drafts(workspace_dir: str | Path) -> list[dict]:
        """列出待审批的技能草稿。"""
        workspace_dir = Path(workspace_dir)
        drafts_dir = workspace_dir / ".skill_drafts"
        if not drafts_dir.exists():
            return []

        drafts = []
        for d in sorted(drafts_dir.iterdir()):
            if not d.is_dir():
                continue
            meta_file = d / "draft_meta.json"
            if meta_file.exists():
                try:
                    meta = json.loads(meta_file.read_text(encoding="utf-8"))
                    meta["path"] = str(d)
                    drafts.append(meta)
                except Exception:
                    pass
        return drafts

    # ------------------------------------------------------------------
    # 提示词构建
    # ------------------------------------------------------------------

    def _build_memory_review_prompt(self, trajectory: list[TrajectoryEntry]) -> str:
        """构建记忆审查提示词。"""
        conversation = "\n".join(
            f"User: {e.user_message}\nAssistant: {e.assistant_message}"
            for e in trajectory
        )
        
        return f"""Review the conversation below and consider saving to memory.

Focus on:
1. User preferences, persona, or details worth remembering
2. User expectations about how you should behave
3. Important decisions or conclusions

Conversation:
{conversation}

If something stands out, output JSON:
{{"title": "...", "content": "...", "type": "preference|lesson|pattern"}}

If nothing worth saving, say "Nothing to save." and stop.
"""

    def _build_skill_review_prompt(self, tool_calls: list[dict]) -> str:
        """构建技能审查提示词。"""
        tools = "\n".join(f"- {tc.get('name', 'unknown')}" for tc in tool_calls)
        
        return f"""Review the tool calls below and consider creating or updating a skill.

Recent tool calls:
{tools}

Focus on:
1. Was a non-trivial approach used that required trial and error?
2. Is there a reusable pattern that should be captured as a skill?
3. Does an existing skill need updating?

If a skill should be created/updated, output JSON:
{{"skill_name": "...", "description": "...", "action": "create|update"}}

If nothing worth saving, say "Nothing to save." and stop.
"""

    def _build_extraction_prompt(self) -> str:
        """构建经验提取提示词。"""
        conversation = "\n".join(
            f"User: {e.user_message}\nAssistant: {e.assistant_message}"
            for e in self._current_trajectory
        )
        
        return f"""Analyze the conversation below and extract valuable experiences.

Conversation:
{conversation}

Extract:
1. Lessons learned (what worked, what didn't)
2. User preferences (explicitly stated)
3. Reusable patterns (complex workflows)

Output JSON array:
[
  {{"title": "...", "content": "...", "type": "lesson|preference|pattern", "confidence": 0.8}}
]

If nothing valuable, return empty array [].
"""

    # ------------------------------------------------------------------
    # 查询接口
    # ------------------------------------------------------------------

    def get_pending_experiences(self) -> list[ExtractedExperience]:
        """获取待审核的经验列表。"""
        return self._pending_experiences.copy()

    def get_trajectory(self, session_id: str) -> list[dict]:
        """获取指定会话的轨迹。"""
        trajectory_file = (
            self.data_dir
            / "evolution"
            / "trajectories"
            / f"{session_id}.jsonl"
        )
        
        if not trajectory_file.exists():
            return []
        
        entries = []
        try:
            with open(trajectory_file, "r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if line:
                        entries.append(json.loads(line))
        except Exception as e:
            logger.error("Failed to load trajectory: %s", e)
        
        return entries

    def get_stats(self) -> dict:
        """获取进化引擎统计信息。"""
        # Count trajectory files on disk (persisted across sessions)
        trajectory_dir = self.data_dir / "evolution" / "trajectories"
        trajectory_count = 0
        if trajectory_dir.exists():
            trajectory_count = len(list(trajectory_dir.glob("*.jsonl")))
        
        return {
            "enabled": self.enabled,
            "memory_nudge_interval": self.memory_nudge_interval,
            "skill_nudge_interval": self.skill_nudge_interval,
            "turns_since_memory_review": self._turns_since_memory_review,
            "tools_since_skill_review": self._tools_since_skill_review,
            "trajectory_count": trajectory_count,
            "current_trajectory_len": len(self._current_trajectory),
            "pending_experiences": len(self._pending_experiences),
            "current_session": self._current_session_id,
        }
