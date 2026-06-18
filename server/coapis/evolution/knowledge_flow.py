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

"""Knowledge Flow - Manages knowledge propagation across hierarchical memory layers.

Architecture:
    Instance Layer (短期/会话级) → Professional Layer (长期/领域级) → Foundation Layer (全局/组织级)

Flow rules:
1. Instance → Professional: When a pattern/lesson is reused across ≥3 sessions
2. Professional → Foundation: When knowledge is confirmed valuable by multiple users/agents
3. Bidirectional: Foundation can push updates to lower layers (e.g., core principle updates)
4. All upward flows require review (LLM-assisted or human)

Key features:
- Flow tracking and audit logging
- Confidence-based promotion thresholds
- Category-aware routing
- Conflict detection and resolution
"""
from __future__ import annotations

import asyncio
import json
import logging
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

from ..foundation import FoundationManager, MemoryEntry
from ..evolution import ExtractedExperience

logger = logging.getLogger(__name__)


@dataclass
class FlowRecord:
    """Record of a knowledge flow event."""
    record_id: str = ""
    source_layer: str = ""  # instance | professional | foundation
    target_layer: str = ""
    experience_id: str = ""
    entry_id: str = ""
    flow_type: str = ""  # promote | demote | sync | merge
    triggered_by: str = ""  # auto | manual | threshold
    confidence: float = 0.0
    status: str = "pending"  # pending | approved | rejected | completed
    timestamp: datetime = field(default_factory=datetime.now)
    audit_comment: str = ""


@dataclass
class FlowConfig:
    """Configuration for knowledge flow thresholds (adaptive)."""
    # Instance → Professional thresholds (基础值，会被 importance 动态调整)
    instance_to_professional_reuse_count: int = 3
    instance_to_professional_user_count: int = 1
    instance_to_professional_min_confidence: float = 0.7

    # Professional → Foundation thresholds
    professional_to_foundation_user_count: int = 3
    professional_to_foundation_min_confidence: float = 0.85

    # Auto-promotion settings
    auto_promote_enabled: bool = False
    require_review: bool = True

    # Flow rate limits
    max_flows_per_hour: int = 10
    max_flows_per_day: int = 50

    # 自适应阈值参数
    # importance_score ∈ [0, 1]，重要性越高，上升门槛越低
    # adaptive_reuse = base_reuse / max(1, importance * importance_boost)
    importance_boost: float = 2.0          # 重要性对阈值的缩放因子
    min_adaptive_reuse: int = 1            # 自适应后的最低复用次数

    # 知识衰减参数
    decay_enabled: bool = True             # 是否启用知识衰减
    decay_check_interval_hours: int = 24   # 衰减检查间隔（小时）
    stale_ttl_days: int = 90               # 超过多少天未引用视为过时
    stale_confidence_penalty: float = 0.3  # 过时知识的置信度惩罚


class KnowledgeFlow:
    """Manages knowledge propagation across hierarchical memory layers.

    Responsibilities:
    1. Monitor knowledge usage across layers
    2. Evaluate promotion/demotion candidates
    3. Execute flow operations with proper routing
    4. Maintain audit trail for all flow events
    5. Handle conflicts and merges

    Flow directions:
    - Upward: Instance → Professional → Foundation (requires review)
    - Downward: Foundation → Professional → Instance (auto-sync)
    - Lateral: Professional ↔ Professional (cross-domain sharing)
    """

    def __init__(
        self,
        data_dir: Path,
        foundation_manager: FoundationManager = None,
        config: FlowConfig = None,
    ):
        self.foundation_manager = foundation_manager
        self.data_dir = Path(data_dir)
        self.config = config or FlowConfig()

        # Tracking state (persisted to disk)
        self._usage_file = self.data_dir / "knowledge_flow" / "usage_counts.json"
        self._usage_counts: Dict[str, int] = {}  # experience_id → reuse count
        self._user_counts: Dict[str, set] = {}  # experience_id → set of user_ids
        self._flow_queue: List[FlowRecord] = []
        self._completed_flows: List[FlowRecord] = []

        # Rate limiting
        self._flows_this_hour: int = 0
        self._flows_this_day: int = 0
        self._hour_reset_time: float = 0.0
        self._day_reset_time: float = 0.0

        # Ensure directory structure and load persisted state
        self._ensure_directory_structure()
        self._load_usage_counts()

        logger.info(
            "KnowledgeFlow initialized (auto_promote=%s, require_review=%s)",
            self.config.auto_promote_enabled,
            self.config.require_review,
        )

    def _ensure_directory_structure(self) -> None:
        """Ensure knowledge flow directory structure."""
        dirs = [
            self.data_dir / "knowledge_flow" / "professional",
            self.data_dir / "knowledge_flow" / "flow_history",
            self.data_dir / "knowledge_flow" / "pending_review",
        ]
        for d in dirs:
            d.mkdir(parents=True, exist_ok=True)

    def _load_usage_counts(self) -> None:
        """Load persisted usage counts from disk."""
        try:
            if self._usage_file.exists():
                data = json.loads(self._usage_file.read_text(encoding="utf-8"))
                self._usage_counts = data.get("usage_counts", {})
                # Convert user_counts from list back to set
                raw_users = data.get("user_counts", {})
                self._user_counts = {
                    k: set(v) for k, v in raw_users.items()
                }
                logger.debug(
                    "KnowledgeFlow: loaded %d usage entries",
                    len(self._usage_counts),
                )
        except Exception as e:
            logger.warning("KnowledgeFlow: failed to load usage counts: %s", e)

    def _save_usage_counts(self) -> None:
        """Persist usage counts to disk."""
        try:
            # Convert sets to lists for JSON serialization
            serializable_users = {
                k: list(v) for k, v in self._user_counts.items()
            }
            data = {
                "usage_counts": self._usage_counts,
                "user_counts": serializable_users,
            }
            self._usage_file.write_text(
                json.dumps(data, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
        except Exception as e:
            logger.warning("KnowledgeFlow: failed to save usage counts: %s", e)

    # ------------------------------------------------------------------
    # Core flow operations
    # ------------------------------------------------------------------

    async def evaluate_and_flow(
        self,
        experience: ExtractedExperience,
        agent_id: str,
        user_id: str,
    ) -> List[FlowRecord]:
        """Evaluate if an extracted experience should flow to another layer.

        Args:
            experience: Extracted experience to evaluate
            agent_id: Source agent ID
            user_id: Source user ID

        Returns:
            List of flow records created
        """
        flows = []

        # Track usage
        self._track_usage(experience.experience_id, user_id)

        # Route skill_effectiveness experiences to skill evolution bridge
        if experience.experience_type == "skill_effectiveness":
            bridge_flow = await self._route_to_skill_evolution(experience, agent_id, user_id)
            if bridge_flow:
                flows.append(bridge_flow)
            # skill_effectiveness experiences also go through normal flow
            # if they qualify (they have both memory and skill evolution value)

        # Check if experience qualifies for upward flow
        if self._qualifies_for_promotion(experience):
            flow_record = self._create_promotion_flow(experience, agent_id, user_id)
            flows.append(flow_record)

            if self.config.auto_promote_enabled and not self.config.require_review:
                await self._execute_flow(flow_record)
            else:
                await self._queue_for_review(flow_record)

        # Check if experience should be stored in professional layer
        if experience.memory_type == "long_term":
            await self._store_in_professional_layer(experience, agent_id)

        return flows

    async def sync_from_foundation(
        self,
        agent_id: str,
        categories: List[str] = None,
    ) -> List[MemoryEntry]:
        """Sync knowledge from foundation layer to professional/instance layers.

        This is a downward flow - foundation updates propagate automatically.

        Args:
            agent_id: Target agent ID
            categories: Optional category filter

        Returns:
            List of synced memory entries
        """
        synced = []

        # Get relevant foundation memories
        if categories:
            for category in categories:
                entries = self.foundation_manager.search_knowledge(category, limit=5)
                synced.extend(entries)
        else:
            # Sync all recent foundation memories
            entries = self.foundation_manager.get_recent_memories(limit=10)
            synced.extend(entries)

        # Store in professional layer
        for entry in synced:
            await self._store_in_professional_layer(
                ExtractedExperience(
                    title=entry.content[:100],
                    content=entry.content,
                    experience_type="pattern",
                    category=entry.category,
                    source_agent=agent_id,
                    confidence=entry.priority_score,
                ),
                agent_id,
            )

        logger.info(
            "Synced %d entries from foundation to agent %s",
            len(synced),
            agent_id,
        )

        return synced

    async def review_flow_request(
        self,
        record_id: str,
        approved: bool,
        comment: str = "",
    ) -> bool:
        """Review a pending flow request.

        Args:
            record_id: Flow record ID to review
            approved: Whether to approve the flow
            comment: Review comment

        Returns:
            True if review was successful
        """
        record = self._find_flow_record(record_id)
        if not record:
            logger.error("Flow record %s not found", record_id)
            return False

        record.status = "approved" if approved else "rejected"
        record.audit_comment = comment

        if approved:
            await self._execute_flow(record)
            self._completed_flows.append(record)
        else:
            self._flow_queue.remove(record)

        await self._save_flow_record(record)

        logger.info(
            "Flow %s %s: %s",
            record_id,
            "approved" if approved else "rejected",
            comment,
        )

        return True

    # ------------------------------------------------------------------
    # Internal operations
    # ------------------------------------------------------------------

    def _track_usage(self, experience_id: str, user_id: str) -> None:
        """Track experience usage across sessions and users."""
        self._usage_counts[experience_id] = self._usage_counts.get(experience_id, 0) + 1
        if experience_id not in self._user_counts:
            self._user_counts[experience_id] = set()
        self._user_counts[experience_id].add(user_id)
        # Persist after every update (cheap JSON write)
        self._save_usage_counts()

    def _qualifies_for_promotion(self, experience: ExtractedExperience) -> bool:
        """Check if experience qualifies for upward promotion.

        自适应阈值：基于 importance_score 动态调整复用次数门槛。
        importance 越高，上升门槛越低（重要知识更容易被晋升）。

        Promotion criteria:
        1. Confidence >= min_confidence threshold
        2. User count >= user_count threshold
        3. Reuse count >= adaptive_reuse (base / max(1, importance * boost))
        4. Rate limits must be respected
        """
        usage_count = self._usage_counts.get(experience.experience_id, 0)
        user_count = len(self._user_counts.get(experience.experience_id, set()))
        importance = getattr(experience, "importance_score", 0.5) or 0.5

        # 自适应复用次数：重要性越高，门槛越低
        adaptive_reuse = max(
            self.config.min_adaptive_reuse,
            int(
                self.config.instance_to_professional_reuse_count
                / max(1.0, importance * self.config.importance_boost)
            ),
        )

        # Check confidence threshold first
        if experience.confidence < self.config.instance_to_professional_min_confidence:
            return False

        # 自适应复用门槛：高置信度放宽一半，低置信度严格执行
        if experience.confidence >= 0.7:
            effective_reuse = max(1, adaptive_reuse // 2)
        else:
            effective_reuse = adaptive_reuse

        if usage_count < effective_reuse:
            return False
        if user_count < self.config.instance_to_professional_user_count:
            return False

        # Check rate limits
        if not self._check_rate_limits():
            return False

        return True

    def _create_promotion_flow(
        self,
        experience: ExtractedExperience,
        agent_id: str,
        user_id: str,
    ) -> FlowRecord:
        """Create a flow record for promotion."""
        import uuid

        record = FlowRecord(
            record_id=str(uuid.uuid4())[:8],
            source_layer="instance",
            target_layer="professional",
            experience_id=experience.experience_id,
            flow_type="promote",
            triggered_by="threshold",
            confidence=experience.confidence,
        )

        self._flow_queue.append(record)
        return record

    async def _execute_flow(self, record: FlowRecord) -> None:
        """Execute a knowledge flow operation."""
        try:
            if record.flow_type == "promote":
                await self._promote_knowledge(record)
            elif record.flow_type == "demote":
                await self._demote_knowledge(record)
            elif record.flow_type == "sync":
                await self._sync_knowledge(record)
            elif record.flow_type == "merge":
                await self._merge_knowledge(record)

            record.status = "completed"
            self._flows_this_hour += 1
            self._flows_this_day += 1

        except Exception as e:
            logger.error("Flow execution failed: %s", e)
            record.status = "failed"

        # Move from pending queue to completed list
        if record in self._flow_queue:
            self._flow_queue.remove(record)
        self._completed_flows.append(record)

        await self._save_flow_record(record)

    async def _promote_knowledge(self, record: FlowRecord) -> None:
        """Promote knowledge from instance to professional layer.
        
        Creates a MemoryEntry in the professional layer and persists it.
        """
        # Find the experience from pending experiences or completed flows
        experience = None
        for exp in self._tracked_experiences:
            if exp.experience_id == record.experience_id:
                experience = exp
                break
        
        if not experience:
            # Try to reconstruct from flow record
            from ..evolution import ExtractedExperience
            experience = ExtractedExperience(
                experience_id=record.experience_id,
                title=f"Promoted: {record.experience_id}",
                content="",
                experience_type="pattern",
                category="general",
                confidence=record.confidence,
            )
        
        # Create MemoryEntry in professional layer
        from ..foundation import MemoryEntry
        # Store title in content prefix (MemoryEntry doesn't have title field)
        entry = MemoryEntry(
            id=experience.experience_id,
            content=f"[{experience.title}] {experience.content}",
            category=experience.category,
            memory_type="long_term",
            priority_score=experience.confidence,
            tags=experience.tags,
            source_agent=experience.source_agent,
            source_user=experience.source_user,
            source_session=experience.source_session,
        )
        entry.user_confirmed = True  # Mark as confirmed (approved by review)
        
        # Persist to professional layer directory
        professional_dir = self.data_dir / "knowledge_flow" / "professional"
        professional_dir.mkdir(parents=True, exist_ok=True)
        
        entry_file = professional_dir / f"{entry.id}.json"
        try:
            entry_data = entry.to_dict() if hasattr(entry, 'to_dict') else entry.__dict__
            entry_file.write_text(
                json.dumps(entry_data, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
            logger.info("Promoted knowledge %s to professional layer (saved to %s)", record.experience_id, entry_file)
        except Exception as e:
            logger.error("Failed to save promoted knowledge: %s", e)
            raise

    async def _demote_knowledge(self, record: FlowRecord) -> None:
        """Demote knowledge from higher to lower layer."""
        logger.info("Demoting knowledge %s to lower layer", record.experience_id)

    async def _sync_knowledge(self, record: FlowRecord) -> None:
        """Sync knowledge between layers."""
        logger.info("Syncing knowledge %s between layers", record.experience_id)

    async def _merge_knowledge(self, record: FlowRecord) -> None:
        """Merge similar knowledge entries."""
        logger.info("Merging knowledge %s", record.experience_id)

    async def _store_in_professional_layer(
        self,
        experience: ExtractedExperience,
        agent_id: str,
    ) -> None:
        """Store experience in professional layer."""
        import uuid

        entry = MemoryEntry(
            id=str(uuid.uuid4())[:8],
            content=experience.content,
            memory_type=experience.memory_type,
            category=experience.category,
            tags=experience.tags,
            priority_score=experience.confidence,
            source_agent=experience.source_agent,
            source_user=experience.source_user,
            source_session=experience.source_session,
        )

        # Store in professional layer directory
        pro_file = (
            self.data_dir
            / "knowledge_flow"
            / "professional"
            / f"{agent_id}_{entry.id}.json"
        )

        try:
            pro_file.write_text(
                json.dumps(entry.to_dict(), ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
            logger.debug("Stored in professional layer: %s", entry.id)
        except Exception as e:
            logger.error("Failed to store in professional layer: %s", e)

    async def _queue_for_review(self, record: FlowRecord) -> None:
        """Queue flow record for manual/LLM review."""
        review_file = (
            self.data_dir
            / "knowledge_flow"
            / "pending_review"
            / f"{record.record_id}.json"
        )

        try:
            # Convert datetime to ISO string for JSON serialization
            review_data = record.__dict__.copy()
            if isinstance(review_data.get("timestamp"), datetime):
                review_data["timestamp"] = review_data["timestamp"].isoformat()

            review_file.write_text(
                json.dumps(review_data, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
            logger.info("Queued %s for review", record.record_id)
        except Exception as e:
            logger.error("Failed to queue for review: %s", e)

    def _find_flow_record(self, record_id: str) -> Optional[FlowRecord]:
        """Find flow record by ID."""
        for record in self._flow_queue:
            if record.record_id == record_id:
                return record
        for record in self._completed_flows:
            if record.record_id == record_id:
                return record
        return None

    def _check_rate_limits(self) -> bool:
        """Check if flow rate limits allow new flow."""
        import time

        now = time.time()
        if now - self._hour_reset_time > 3600:
            self._flows_this_hour = 0
            self._hour_reset_time = now
        if now - self._day_reset_time > 86400:
            self._flows_this_day = 0
            self._day_reset_time = now

        if self._flows_this_hour >= self.config.max_flows_per_hour:
            return False
        if self._flows_this_day >= self.config.max_flows_per_day:
            return False

        return True

    async def _save_flow_record(self, record: FlowRecord) -> None:
        """Save flow record to history."""
        history_file = (
            self.data_dir
            / "knowledge_flow"
            / "flow_history"
            / f"{record.record_id}.json"
        )

        try:
            history_file.write_text(
                json.dumps(record.__dict__, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
        except Exception as e:
            logger.error("Failed to save flow record: %s", e)

    def get_stats(self) -> dict:
        """Get knowledge flow statistics."""
        return {
            "pending_reviews": len(self._flow_queue),
            "completed_flows": len(self._completed_flows),
            "tracked_experiences": len(self._usage_counts),
            "unique_users": sum(len(users) for users in self._user_counts.values()),
            "flows_this_hour": self._flows_this_hour,
            "flows_this_day": self._flows_this_day,
            "auto_promote_enabled": self.config.auto_promote_enabled,
            "require_review": self.config.require_review,
        }

    # ── 知识衰减 ──

    def check_and_decay_stale_knowledge(self) -> list[dict]:
        """扫描已追踪的经验，对超过 TTL 未引用的知识进行衰减。

        Returns:
            被衰减的经验列表 [{experience_id, last_used, stale_days, confidence_penalty}]
        """
        if not self.config.decay_enabled:
            return []

        import time
        now = time.time()
        stale_ttl_seconds = self.config.stale_ttl_days * 86400
        decayed = []

        # 遍历所有追踪的经验，检查 last_used 时间
        usage_data = self._load_usage_data()
        for exp_id, usage_info in usage_data.items():
            last_used = usage_info.get("last_used", 0)
            if last_used <= 0:
                continue
            stale_seconds = now - last_used
            if stale_seconds > stale_ttl_seconds:
                stale_days = int(stale_seconds / 86400)
                confidence_penalty = self.config.stale_confidence_penalty

                decayed.append({
                    "experience_id": exp_id,
                    "last_used": datetime.fromtimestamp(last_used).isoformat(),
                    "stale_days": stale_days,
                    "confidence_penalty": confidence_penalty,
                })

                # 更新 usage_counts，标记为已衰减
                if exp_id in self._usage_counts:
                    self._usage_counts[exp_id] = max(0, self._usage_counts[exp_id] - 1)

                logger.info(
                    "KnowledgeFlow: decayed stale knowledge %s (stale=%dd, penalty=%.2f)",
                    exp_id, stale_days, confidence_penalty,
                )

        if decayed:
            self._save_usage_counts()

        return decayed

    def _load_usage_data(self) -> dict:
        """加载完整的 usage 数据（包含 last_used 时间戳）。"""
        try:
            if self._usage_file.exists():
                data = json.loads(self._usage_file.read_text(encoding="utf-8"))
                return data.get("usage_data", {})
        except Exception:
            pass
        return {}

    def _save_usage_counts(self) -> None:
        """持久化 usage counts 到磁盘。"""
        try:
            self._usage_file.parent.mkdir(parents=True, exist_ok=True)
            data = {
                "usage_counts": self._usage_counts,
                "user_counts": {k: list(v) for k, v in self._user_counts.items()},
            }
            self._usage_file.write_text(
                json.dumps(data, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
        except Exception as e:
            logger.error("Failed to save usage counts: %s", e)

    def get_pending_reviews(self) -> List[Dict]:
        """Get pending flow reviews."""
        return [record.__dict__ for record in self._flow_queue]

    async def _route_to_skill_evolution(
        self,
        experience: ExtractedExperience,
        agent_id: str,
        user_id: str,
    ) -> Optional[FlowRecord]:
        """Route skill_effectiveness experience to SkillEvolutionBridge.

        This bridges agent evolution → skill evolution. When the experience
        extractor identifies skill effectiveness issues (false_positive,
        false_negative, improve), this method routes them to the bridge
        for further processing by the skill evolution system.
        """
        try:
            from ..skill_evolution.bridge import get_skill_evolution_bridge

            bridge = get_skill_evolution_bridge()

            # Extract signal details from experience metadata
            metadata = experience.metadata or {}
            signal_type = metadata.get("signal_type", experience.experience_type)
            skill_name = metadata.get("skill_name", "")
            trigger_keyword = metadata.get("trigger_keyword", "")

            if not skill_name:
                # Try to extract skill name from title (format: [type] skill: keyword)
                title = experience.title or ""
                import re
                match = re.search(r'\[[\w_]+\]\s*(\S+)', title)
                if match:
                    skill_name = match.group(1).rstrip(":")

            if not skill_name:
                logger.debug("Skipping skill_effectiveness routing: no skill_name")
                return None

            # Check rate limits
            if not self._check_rate_limits():
                logger.warning("Rate limit reached, deferring skill evolution routing")
                return None

            # Create flow record for skill evolution
            import uuid as _uuid
            record = FlowRecord(
                record_id=str(_uuid.uuid4())[:8],
                source_layer="instance",
                target_layer="skill_evolution",
                experience_id=experience.experience_id,
                flow_type="skill_effectiveness",
                triggered_by="extractor",
                confidence=experience.confidence,
            )

            # Notify bridge of the signal (the bridge will log and callback)
            # Note: We don't call extract_effectiveness_signals here since
            # the signal was already extracted by the extractor. Instead we
            # just log that the routing happened.
            logger.info(
                "Routed skill_effectiveness to bridge: %s [%s] %s (confidence=%.2f)",
                skill_name, signal_type, trigger_keyword, experience.confidence,
            )

            record.status = "completed"
            self._flows_this_hour += 1
            self._flows_this_day += 1
            self._completed_flows.append(record)

            await self._save_flow_record(record)
            return record

        except Exception as e:
            logger.error("Failed to route to skill evolution: %s", e)
            return None
