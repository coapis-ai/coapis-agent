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

"""Backend Review - Asynchronous background review system for agent evolution.

Performs periodic reviews without blocking the main conversation loop:
1. Memory Review: Evaluates stored memories for relevance, accuracy, and freshness
2. Skill Review: Evaluates tool usage patterns and skill effectiveness
3. Experience Review: Reviews pending experiences for promotion to higher layers
4. Knowledge Flow Review: Reviews flow requests and executes approved flows

Architecture:
- Scheduled tasks run asynchronously in background
- Review results are persisted and available via API
- Human-in-the-loop approval for critical changes
- LLM-assisted review with confidence scoring
"""
from __future__ import annotations

import asyncio
import json
import logging
import uuid
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

from ..foundation import FoundationManager, MemoryEntry
from ..evolution import EvolutionEngine, ExtractedExperience

logger = logging.getLogger(__name__)


@dataclass
class ReviewResult:
    """Result of a single review operation."""
    review_id: str = field(default_factory=lambda: str(uuid.uuid4())[:8])
    review_type: str = ""  # memory | skill | experience | knowledge_flow
    agent_id: str = ""
    user_id: str = ""
    timestamp: datetime = field(default_factory=datetime.now)
    status: str = "completed"  # pending | in_progress | completed | failed
    findings: List[Dict] = field(default_factory=list)
    actions_taken: List[str] = field(default_factory=list)
    confidence: float = 0.0
    summary: str = ""
    requires_human_review: bool = False


@dataclass
class ReviewSchedule:
    """Schedule configuration for background reviews."""
    memory_review_interval: int = 3600  # seconds (1 hour)
    skill_review_interval: int = 7200   # seconds (2 hours)
    experience_review_interval: int = 1800  # seconds (30 minutes)
    knowledge_flow_interval: int = 5400  # seconds (1.5 hours)
    max_concurrent_reviews: int = 2
    enabled: bool = True


class BackendReview:
    """Asynchronous background review system for agent evolution.

    Responsibilities:
    1. Schedule and execute periodic reviews
    2. Evaluate memory quality and relevance
    3. Assess skill effectiveness
    4. Review pending experiences for promotion
    5. Execute approved knowledge flows
    6. Maintain audit trail of all review actions
    """

    def __init__(
        self,
        evolution_engine: EvolutionEngine,
        foundation_manager: FoundationManager,
        data_dir: Path,
        schedule: ReviewSchedule = None,
        llm_review_callback: Callable = None,
    ):
        self.evolution_engine = evolution_engine
        self.foundation_manager = foundation_manager
        self.data_dir = Path(data_dir)
        self.schedule = schedule or ReviewSchedule()
        self.llm_review_callback = llm_review_callback

        # State
        self._running: bool = False
        self._tasks: Dict[str, asyncio.Task] = {}
        self._review_history: List[ReviewResult] = []
        self._pending_reviews: List[Dict] = []

        # Ensure directory structure
        self._ensure_directory_structure()

        logger.info(
            "BackendReview initialized (memory=%ds, skill=%ds, experience=%ds, flow=%ds)",
            self.schedule.memory_review_interval,
            self.schedule.skill_review_interval,
            self.schedule.experience_review_interval,
            self.schedule.knowledge_flow_interval,
        )

    def _ensure_directory_structure(self) -> None:
        """Ensure review directory structure.
        
        v0.5.1: Reviews centralized in system/reviews/ for all user agents.
        """
        from ..constant import SYSTEM_REVIEWS_DIR
        review_base = SYSTEM_REVIEWS_DIR
        dirs = [
            review_base / "memory",
            review_base / "skill",
            review_base / "experience",
            review_base / "knowledge_flow",
            review_base / "history",
        ]
        for d in dirs:
            d.mkdir(parents=True, exist_ok=True)

    # ------------------------------------------------------------------
    # Lifecycle management
    # ------------------------------------------------------------------

    async def start(self) -> None:
        """Start background review tasks."""
        if self._running or not self.schedule.enabled:
            return

        self._running = True
        logger.info("BackendReview started")

        # Schedule periodic reviews
        if self.schedule.memory_review_interval > 0:
            self._tasks["memory"] = asyncio.create_task(
                self._periodic_review("memory", self.schedule.memory_review_interval)
            )

        if self.schedule.skill_review_interval > 0:
            self._tasks["skill"] = asyncio.create_task(
                self._periodic_review("skill", self.schedule.skill_review_interval)
            )

        if self.schedule.experience_review_interval > 0:
            self._tasks["experience"] = asyncio.create_task(
                self._periodic_review("experience", self.schedule.experience_review_interval)
            )

        if self.schedule.knowledge_flow_interval > 0:
            self._tasks["knowledge_flow"] = asyncio.create_task(
                self._periodic_review("knowledge_flow", self.schedule.knowledge_flow_interval)
            )

    async def stop(self) -> None:
        """Stop all background review tasks."""
        if not self._running:
            return

        self._running = False
        logger.info("BackendReview stopping...")

        # Cancel all tasks
        for name, task in self._tasks.items():
            if not task.done():
                task.cancel()
                try:
                    await task
                except asyncio.CancelledError:
                    pass

        self._tasks.clear()
        logger.info("BackendReview stopped")

    # ------------------------------------------------------------------
    # Periodic review loop
    # ------------------------------------------------------------------

    async def _periodic_review(self, review_type: str, interval: int) -> None:
        """Run periodic review of specified type."""
        while self._running:
            try:
                await asyncio.sleep(interval)
                if not self._running:
                    break

                logger.debug("Running %s review", review_type)
                result = await self._execute_review(review_type)

                if result:
                    await self._save_review_result(result)
                    self._review_history.append(result)

                    # Check if human review is needed
                    if result.requires_human_review:
                        await self._notify_human_review(result)

            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error("Periodic %s review failed: %s", review_type, e)

    # ------------------------------------------------------------------
    # Review execution
    # ------------------------------------------------------------------

    async def _execute_review(self, review_type: str) -> Optional[ReviewResult]:
        """Execute a review of specified type."""
        if review_type == "memory":
            return await self._review_memory()
        elif review_type == "skill":
            return await self._review_skills()
        elif review_type == "experience":
            return await self._review_experiences()
        elif review_type == "knowledge_flow":
            return await self._review_knowledge_flow()
        else:
            logger.warning("Unknown review type: %s", review_type)
            return None

    async def _review_memory(self) -> ReviewResult:
        """Review stored memories for quality and relevance."""
        result = ReviewResult(
            review_type="memory",
            agent_id=self.evolution_engine._current_agent_id,
            user_id=self.evolution_engine._current_user_id,
        )

        # Get all stored memories
        memories = self._get_all_memories()

        findings = []
        actions = []

        for memory in memories:
            # Check if memory is still relevant
            relevance_score = self._assess_memory_relevance(memory)

            if relevance_score < 0.3:
                findings.append({
                    "memory_id": memory.id,
                    "issue": "low_relevance",
                    "score": relevance_score,
                    "suggestion": "consider_archiving",
                })
                actions.append(f"Archive memory {memory.id}")

            # Check if memory is outdated
            age_days = (datetime.now() - memory.created_at).days
            if age_days > 90 and not memory.user_confirmed:
                findings.append({
                    "memory_id": memory.id,
                    "issue": "outdated",
                    "age_days": age_days,
                    "suggestion": "review_or_delete",
                })
                actions.append(f"Review outdated memory {memory.id}")

            # Check for duplicates
            duplicates = self._find_duplicate_memories(memory, memories)
            if duplicates:
                findings.append({
                    "memory_id": memory.id,
                    "issue": "duplicate",
                    "duplicates": [d.id for d in duplicates],
                    "suggestion": "merge",
                })
                actions.append(f"Merge duplicate memories")

        result.findings = findings
        result.actions_taken = actions
        result.confidence = 0.8 if not findings else 0.6
        result.summary = f"Reviewed {len(memories)} memories, found {len(findings)} issues"

        # Determine if human review is needed
        result.requires_human_review = any(
            f.get("issue") == "low_relevance" for f in findings
        )

        return result

    async def _review_skills(self) -> ReviewResult:
        """Review tool usage patterns and skill effectiveness."""
        result = ReviewResult(
            review_type="skill",
            agent_id=self.evolution_engine._current_agent_id,
            user_id=self.evolution_engine._current_user_id,
        )

        # Analyze recent tool usage from trajectory
        trajectory = self.evolution_engine._current_trajectory
        tool_usage = self._analyze_tool_usage(trajectory)

        findings = []
        actions = []

        for tool_name, usage_stats in tool_usage.items():
            # Check for underutilized tools
            if usage_stats["success_rate"] < 0.5:
                findings.append({
                    "tool": tool_name,
                    "issue": "low_success_rate",
                    "success_rate": usage_stats["success_rate"],
                    "suggestion": "review_tool_usage",
                })
                actions.append(f"Review {tool_name} usage patterns")

            # Check for overused tools
            if usage_stats["call_count"] > 10:
                findings.append({
                    "tool": tool_name,
                    "issue": "overused",
                    "call_count": usage_stats["call_count"],
                    "suggestion": "consider_alternatives",
                })

        result.findings = findings
        result.actions_taken = actions
        result.confidence = 0.7
        result.summary = f"Reviewed {len(tool_usage)} tools, found {len(findings)} issues"

        result.requires_human_review = bool(findings)

        return result

    async def _review_experiences(self) -> ReviewResult:
        """Review pending experiences for promotion."""
        result = ReviewResult(
            review_type="experience",
            agent_id=self.evolution_engine._current_agent_id,
            user_id=self.evolution_engine._current_user_id,
        )

        pending = self.evolution_engine._pending_experiences
        findings = []
        actions = []

        for exp in pending:
            # Assess experience quality
            quality_score = self._assess_experience_quality(exp)

            if quality_score >= 0.8:
                findings.append({
                    "experience_id": exp.experience_id,
                    "title": exp.title,
                    "quality": quality_score,
                    "suggestion": "promote_to_professional",
                })
                actions.append(f"Promote {exp.title}")

            elif quality_score >= 0.6:
                findings.append({
                    "experience_id": exp.experience_id,
                    "title": exp.title,
                    "quality": quality_score,
                    "suggestion": "keep_in_instance",
                })

            else:
                findings.append({
                    "experience_id": exp.experience_id,
                    "title": exp.title,
                    "quality": quality_score,
                    "suggestion": "discard",
                })
                actions.append(f"Discard {exp.title}")

        result.findings = findings
        result.actions_taken = actions
        result.confidence = 0.75
        result.summary = f"Reviewed {len(pending)} pending experiences"

        result.requires_human_review = any(
            f.get("suggestion") == "promote_to_professional" for f in findings
        )

        return result

    async def _review_knowledge_flow(self) -> ReviewResult:
        """Review knowledge flow requests."""
        result = ReviewResult(
            review_type="knowledge_flow",
            agent_id=self.evolution_engine._current_agent_id,
            user_id=self.evolution_engine._current_user_id,
        )

        # Check for pending flow requests
        pending_dir = self.data_dir / "knowledge_flow" / "pending_review"
        if pending_dir.exists():
            pending_files = list(pending_dir.glob("*.json"))
            findings = []

            for pf in pending_files:
                try:
                    flow_data = json.loads(pf.read_text(encoding="utf-8"))
                    findings.append({
                        "flow_id": flow_data.get("record_id"),
                        "type": flow_data.get("type"),
                        "status": "pending_review",
                        "suggestion": "review_and_approve",
                    })
                except Exception as e:
                    logger.error("Failed to read flow request: %s", e)

            result.findings = findings
            result.actions_taken = [f"Review {len(findings)} flow requests"]
            result.confidence = 0.8
            result.summary = f"Found {len(findings)} pending flow requests"
            result.requires_human_review = bool(findings)

        return result

    # ------------------------------------------------------------------
    # Assessment helpers
    # ------------------------------------------------------------------

    def _get_all_memories(self) -> List[MemoryEntry]:
        """Get all stored memories from foundation manager."""
        # TODO: Implement actual retrieval from foundation manager
        return []

    def _assess_memory_relevance(self, memory: MemoryEntry) -> float:
        """Assess relevance of a memory entry."""
        # Simple heuristic: access_count and recency
        recency = max(0, 1.0 - (datetime.now() - memory.last_accessed_at).days / 30)
        frequency = min(memory.access_count / 10, 1.0)
        return (recency * 0.6 + frequency * 0.4)

    def _find_duplicate_memories(
        self,
        memory: MemoryEntry,
        all_memories: List[MemoryEntry],
    ) -> List[MemoryEntry]:
        """Find duplicate memories based on content similarity."""
        duplicates = []
        for other in all_memories:
            if other.id == memory.id:
                continue
            # Simple text similarity check
            if self._text_similarity(memory.content, other.content) > 0.8:
                duplicates.append(other)
        return duplicates

    def _text_similarity(self, text1: str, text2: str) -> float:
        """Calculate simple text similarity (Jaccard-like)."""
        if not text1 or not text2:
            return 0.0
        words1 = set(text1.lower().split())
        words2 = set(text2.lower().split())
        if not words1 or not words2:
            return 0.0
        intersection = words1 & words2
        union = words1 | words2
        return len(intersection) / len(union)

    def _analyze_tool_usage(self, trajectory) -> Dict[str, Dict]:
        """Analyze tool usage patterns from trajectory."""
        tool_stats = {}
        for entry in trajectory:
            for tc in entry.tool_calls:
                tool_name = tc.get("name", "unknown")
                if tool_name not in tool_stats:
                    tool_stats[tool_name] = {
                        "call_count": 0,
                        "success_count": 0,
                        "success_rate": 0.0,
                    }
                tool_stats[tool_name]["call_count"] += 1
                # Assume success if no error in tool result
                tool_stats[tool_name]["success_count"] += 1

        # Calculate success rates
        for stats in tool_stats.values():
            if stats["call_count"] > 0:
                stats["success_rate"] = stats["success_count"] / stats["call_count"]

        return tool_stats

    def _assess_experience_quality(self, exp: ExtractedExperience) -> float:
        """Assess quality of an extracted experience."""
        # Factors: confidence, content length, specificity
        score = exp.confidence * 0.5

        # Longer content is generally better (up to a point)
        content_length = len(exp.content)
        if content_length > 100:
            score += 0.2
        elif content_length > 50:
            score += 0.1

        # Specificity bonus (has tags, category)
        if exp.tags:
            score += 0.1
        if exp.category != "general":
            score += 0.1

        # Generalizability bonus
        if exp.is_generalizable:
            score += 0.1

        return min(score, 1.0)

    # ------------------------------------------------------------------
    # Persistence and notification
    # ------------------------------------------------------------------

    async def _save_review_result(self, result: ReviewResult) -> None:
        """Save review result to history."""
        from ..constant import SYSTEM_REVIEWS_DIR
        result_file = (
            SYSTEM_REVIEWS_DIR
            / "history"
            / f"{result.review_type}_{result.review_id}.json"
        )

        try:
            result_dict = result.__dict__.copy()
            # Convert datetime to string for JSON serialization
            result_dict["timestamp"] = result.timestamp.isoformat()

            result_file.write_text(
                json.dumps(result_dict, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
        except Exception as e:
            logger.error("Failed to save review result: %s", e)

    async def _notify_human_review(self, result: ReviewResult) -> None:
        """Notify that human review is needed."""
        # TODO: Implement actual notification mechanism
        # For now, just log
        logger.warning(
            "Human review needed for %s review %s: %s",
            result.review_type,
            result.review_id,
            result.summary,
        )

    # ------------------------------------------------------------------
    # Query interface
    # ------------------------------------------------------------------

    def get_review_history(self, limit: int = 50) -> List[Dict]:
        """Get recent review history."""
        recent = self._review_history[-limit:]
        return [r.__dict__.copy() for r in recent]

    def get_pending_reviews(self) -> List[Dict]:
        """Get reviews requiring human attention."""
        return [r for r in self._review_history if r.requires_human_review]

    def get_stats(self) -> dict:
        """Get review statistics."""
        return {
            "running": self._running,
            "active_tasks": len(self._tasks),
            "total_reviews": len(self._review_history),
            "pending_human_review": len(self.get_pending_reviews()),
            "schedule": self.schedule.__dict__.copy(),
        }
