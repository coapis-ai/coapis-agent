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

"""Dual Layer Evolution Engine.

This module implements the dual-layer evolution mechanism for scene agents:

Layer 1: Shared Evolution (Scene Agent)
    - Shared experiences across all users
    - Best practices and common patterns
    - Stored in agents/scene-{scene_id}/MEMORY.md

Layer 2: Personal Evolution (User Agent)
    - User-specific preferences and context
    - Personal memory and history
    - Stored in workspaces/{user_id}/MEMORY.md

Evolution Flow:
    User interacts with scene
        ↓
    Analyze interaction quality
        ↓
    Classify experience type:
        - Shared → Update scene agent MEMORY.md
        - Personal → Update user agent MEMORY.md
        ↓
    Dual-layer memory updated
"""

from __future__ import annotations

import asyncio
import json
import logging
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from ..models.scene import SceneAgentConfig, EvolutionConfig
from ..exceptions import SceneAgentError

logger = logging.getLogger(__name__)

# Token ceiling for a scene's shared MEMORY.md. Scene memory is shared by all
# users of that scene, so it needs its own ceiling independent of the global
# DEFAULT_MAX_TOKENS (10000) used for per-user memory.
SCENE_MEMORY_MAX_TOKENS = 4000


class EvolutionType:
    """Evolution type classification."""
    
    SHARED = "shared"       # Shared across all users
    PERSONAL = "personal"   # User-specific
    BOTH = "both"           # Both shared and personal


class EvolutionEntry:
    """Single evolution entry."""
    
    def __init__(
        self,
        content: str,
        evolution_type: str,
        confidence: float = 0.7,
        metadata: Optional[Dict[str, Any]] = None,
    ):
        self.timestamp = datetime.now(timezone.utc).isoformat()
        self.content = content
        self.evolution_type = evolution_type
        self.confidence = confidence
        self.metadata = metadata or {}
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "timestamp": self.timestamp,
            "content": self.content,
            "type": self.evolution_type,
            "confidence": self.confidence,
            "metadata": self.metadata,
        }


class DualLayerEvolutionEngine:
    """Engine for managing dual-layer evolution.
    
    This engine analyzes conversations and updates both:
    1. Scene agent memory (shared evolution)
    2. User agent memory (personal evolution)
    
    Usage:
        engine = DualLayerEvolutionEngine(data_dir)
        engine.evolve(
            scene_id="meeting-minutes",
            user_id="alice",
            conversation=[...],
            metadata={...}
        )
    """
    
    def __init__(self, data_dir: Path, model: Any = None):
        """Initialize dual-layer evolution engine.

        Args:
            data_dir: Data directory (e.g., server/data)
            model: Optional LLM model handle (from create_model_and_formatter).
                   When None, falls back to the global LLM client; when that
                   also fails, degrades to keyword heuristics.
        """
        self.data_dir = Path(data_dir)
        self.model = model
        self.agents_dir = self.data_dir / "agents"
        self.workspaces_dir = self.data_dir / "workspaces"

        # Ensure directories exist
        self.agents_dir.mkdir(parents=True, exist_ok=True)
        self.workspaces_dir.mkdir(parents=True, exist_ok=True)
    
    # -------------------------------------------------------------------------
    # Main Evolution API
    # -------------------------------------------------------------------------
    
    async def evolve(
        self,
        scene_id: str,
        user_id: str,
        conversation: List[Dict[str, Any]],
        metadata: Optional[Dict[str, Any]] = None,
    ) -> Tuple[Optional[str], Optional[str]]:
        """Evolve both scene agent and user agent based on conversation.

        This method:
        1. Analyzes conversation with the LLM to extract evolution entries
        2. Classifies entries (shared/personal)
        3. Updates scene agent memory (shared, deduped + capacity-checked)
        4. Updates user agent memory (personal)

        Args:
            scene_id: Scene ID (e.g., meeting-minutes)
            user_id: User ID
            conversation: Conversation messages
            metadata: Additional metadata

        Returns:
            Tuple of (shared_evolution, personal_evolution) or None if no evolution
        """
        # Analyze conversation for evolution opportunities
        evolution_entries = await self._analyze_conversation(conversation, metadata)

        if not evolution_entries:
            logger.debug(f"No evolution opportunities found for scene {scene_id}")
            return None, None

        # Separate shared and personal entries
        shared_entries = [e for e in evolution_entries if e.evolution_type in [EvolutionType.SHARED, EvolutionType.BOTH]]
        personal_entries = [e for e in evolution_entries if e.evolution_type in [EvolutionType.PERSONAL, EvolutionType.BOTH]]

        # Update scene agent memory (shared)
        shared_evolution = None
        if shared_entries:
            shared_evolution = self._update_scene_memory(scene_id, shared_entries)

        # Update user agent memory (personal)
        personal_evolution = None
        if personal_entries:
            personal_evolution = self._update_user_memory(user_id, scene_id, personal_entries)

        logger.info(
            f"Evolved scene {scene_id} for user {user_id}: "
            f"{len(shared_entries)} shared, {len(personal_entries)} personal"
        )

        return shared_evolution, personal_evolution
    
    # -------------------------------------------------------------------------
    # Conversation Analysis
    # -------------------------------------------------------------------------
    
    async def _analyze_conversation(
        self,
        conversation: List[Dict[str, Any]],
        metadata: Optional[Dict[str, Any]] = None,
    ) -> List[EvolutionEntry]:
        """Analyze conversation for evolution opportunities.

        Primary path is LLM extraction. The previous per-message keyword
        heuristic produced a constant junk string ("Best practice from
        assistant response") for every assistant message, so it is kept only
        as a degraded fallback when the LLM is unavailable.

        Args:
            conversation: Conversation messages
            metadata: Additional metadata

        Returns:
            List of EvolutionEntry
        """
        entries = await self._extract_with_llm(conversation, metadata)
        if entries:
            return entries

        # Degraded fallback: keyword heuristics (no LLM available).
        logger.info(
            "[DualLayerEvolution] LLM extraction unavailable, "
            "falling back to keyword heuristics"
        )
        return self._extract_with_heuristics(conversation)

    # ── LLM extraction ──

    def _build_transcript(self, conversation: List[Dict[str, Any]]) -> str:
        """Render conversation as a compact transcript for the LLM prompt."""
        lines = []
        for msg in conversation:
            role = msg.get("role", "")
            if role == "system":
                continue
            content = msg.get("content", "")
            if isinstance(content, list):
                content = " ".join(
                    b.get("text", "") for b in content
                    if isinstance(b, dict) and b.get("type") == "text"
                )
            content = str(content).strip()
            if not content:
                continue
            # Keep the prompt bounded; long tool output is not signal.
            if len(content) > 600:
                content = content[:600] + " …"
            lines.append(f"{role}: {content}")
        return "\n".join(lines)

    async def _extract_with_llm(
        self,
        conversation: List[Dict[str, Any]],
        metadata: Optional[Dict[str, Any]] = None,
    ) -> List[EvolutionEntry]:
        """Extract evolution entries with the LLM.

        Returns an empty list when no model is reachable, so the caller can
        fall back to heuristics.
        """
        transcript = self._build_transcript(conversation)
        if not transcript:
            return []

        scene_name = (metadata or {}).get("scene_name", "")
        prompt = (
            "You are a memory review assistant for a reusable business scene"
            + (f" named “{scene_name}”" if scene_name else "")
            + ". Read the transcript and extract ONLY durable, reusable knowledge.\n\n"
            "Rules:\n"
            "- shared: scene-level best practices useful to ANY user of this "
            "scene (workflow, format, pitfall, technique). Never mention a "
            "specific person, date, or confidential value.\n"
            "- personal: a preference/context specific to THIS user.\n"
            "- Output 0 to 5 entries. Output [] if nothing is durable. "
            "Do not invent content that is not in the transcript.\n"
            "- Each entry must be one short sentence (<= 40 words), "
            "actionable, and phrased generically.\n\n"
            "Output strict JSON: a JSON array of objects with keys "
            "\"type\" (\"shared\"|\"personal\") and \"content\". "
            "No prose, no markdown fences.\n\n"
            f"Transcript:\n{transcript}"
        )

        raw = await self._call_extraction_llm(prompt)
        if not raw:
            return []

        entries = self._parse_extraction(raw)
        if not entries:
            logger.info(
                "[DualLayerEvolution] LLM returned no parseable entries; "
                "skipping write (raw %d chars)", len(raw),
            )
        return entries

    @staticmethod
    def _text_of(content: Any) -> str:
        """Flatten a model response content into plain text.

        agentscope ChatResponse.content is a list of blocks; only ``text``
        blocks carry the answer (``thinking`` blocks must not leak into the
        extraction prompt).
        """
        if isinstance(content, str):
            return content
        if isinstance(content, list):
            return "".join(
                b.get("text", "")
                for b in content
                if isinstance(b, dict) and b.get("type") == "text"
            )
        return ""

    async def _call_model(self, prompt: str) -> str:
        """Call the model once. Returns "" if no usable calling path exists.

        Two shapes are supported:
        * OpenAI-style SDK client (``model.client.chat.completions``)
        * agentscope ChatModelBase (callable, streaming by default) — the
          shape used by local vLLM/Ollama providers, which expose no
          ``.client`` at all.
        """
        model = self.model
        if model is None:
            from ..agents.model_factory import create_model_and_formatter
            from ..config import load_config

            model, _ = create_model_and_formatter(load_config())

        if model is None:
            return ""

        messages = [
            {"role": "system", "content": "You output strict JSON only."},
            {"role": "user", "content": prompt},
        ]

        if hasattr(model, "client"):
            response = await asyncio.wait_for(
                model.client.chat.completions.create(
                    model=model.model_name,
                    messages=messages,
                    max_tokens=800,
                    temperature=0.2,
                ),
                timeout=30,
            )
            return response.choices[0].message.content or ""

        if callable(model):
            out = await model(messages)
            if hasattr(out, "content"):
                return self._text_of(out.content)
            # Streaming: the last cumulative chunk holds the full answer.
            last = None
            async for chunk in out:
                last = chunk
            return self._text_of(getattr(last, "content", None)) if last else ""

        logger.info(
            "[DualLayerEvolution] model %s has no usable calling path; "
            "skipping extraction",
            type(model).__name__,
        )
        return ""

    async def _call_extraction_llm(self, prompt: str) -> str:
        """Call the LLM for extraction. Returns "" on any failure."""
        max_retries = 2
        # Evolution runs as a detached background task, so it can afford a long
        # window: reasoning models (A3-class) routinely exceed 30s on an
        # extraction prompt, and a 30s ceiling made LLM extraction never run.
        timeout_seconds = 90

        for attempt in range(max_retries):
            try:
                text = await asyncio.wait_for(
                    self._call_model(prompt), timeout=timeout_seconds
                )
                if text:
                    return text
            except asyncio.TimeoutError:
                logger.warning(
                    "[DualLayerEvolution] extraction LLM timeout "
                    "(attempt %d/%d, %ds)",
                    attempt + 1, max_retries, timeout_seconds,
                )
            except Exception as e:
                logger.warning(
                    "[DualLayerEvolution] extraction LLM call failed "
                    "(attempt %d/%d): %s",
                    attempt + 1, max_retries, e,
                )

            if attempt < max_retries - 1:
                await asyncio.sleep(2 ** attempt)

        return ""

    def _parse_extraction(self, raw: str) -> List[EvolutionEntry]:
        """Parse the LLM JSON array into EvolutionEntry objects.

        Tolerates markdown fences (strips them) but rejects anything that is
        not a JSON array, so junk output never becomes a memory entry.
        """
        text = raw.strip()
        if text.startswith("```"):
            text = text.strip("`")
            # Drop a leading language tag line (e.g. "json")
            lines = text.split("\n")
            if lines and lines[0].strip().lower() in ("json", "javascript"):
                lines = lines[1:]
            text = "\n".join(lines).strip()

        try:
            data = json.loads(text)
        except json.JSONDecodeError:
            logger.info(
                "[DualLayerEvolution] extraction output is not JSON: %r",
                text[:120],
            )
            return []

        if not isinstance(data, list):
            return []

        valid_types = {EvolutionType.SHARED, EvolutionType.PERSONAL, EvolutionType.BOTH}
        entries: List[EvolutionEntry] = []
        for item in data[:5]:
            if not isinstance(item, dict):
                continue
            content = str(item.get("content", "")).strip()
            etype = str(item.get("type", "")).strip()
            if not content or etype not in valid_types:
                continue
            entries.append(EvolutionEntry(
                content=content,
                evolution_type=etype,
                confidence=0.7,
                metadata={"source": "llm_extraction"},
            ))
        return entries

    def _extract_with_heuristics(
        self,
        conversation: List[Dict[str, Any]],
    ) -> List[EvolutionEntry]:
        """Keyword-based fallback used only when the LLM is unavailable."""
        entries = []

        for msg in conversation:
            role = msg.get("role", "")
            content = msg.get("content", "")

            # Skip system messages
            if role == "system":
                continue

            # Analyze user messages for preferences
            if role == "user":
                preference = self._extract_user_preference(content)
                if preference:
                    entries.append(EvolutionEntry(
                        content=preference,
                        evolution_type=EvolutionType.PERSONAL,
                        confidence=0.8,
                        metadata={"source": "user_preference"},
                    ))

        return entries
    
    def _extract_user_preference(self, content: str) -> Optional[str]:
        """Extract user preference from message content.
        
        Simple heuristic: look for preference indicators.
        
        Args:
            content: Message content
        
        Returns:
            Extracted preference or None
        """
        # Simple heuristics
        preference_indicators = [
            "我喜欢", "我希望", "请记住", "下次",
            "我更喜欢", "我的习惯", "我通常",
        ]
        
        for indicator in preference_indicators:
            if indicator in content:
                # Extract sentence with preference
                sentences = content.split("。")
                for sentence in sentences:
                    if indicator in sentence:
                        return f"用户偏好: {sentence.strip()}"
        
        return None
    
    # -------------------------------------------------------------------------
    # Memory Updates
    # -------------------------------------------------------------------------
    
    # ── Desensitization (D1) ──

    # Scene memory is shared across every user of the scene, so anything
    # personally identifying must never reach it. Applied to shared entries
    # only; personal-layer entries stay verbatim because they are the user's
    # own memory and redacting them would destroy their value.
    # Name must be followed by a delimiter/verb. A bare greedy {2,3} swallowed
    # real content ("联系人王静负责" -> "联系人[人名]责").
    # A name is masked only when a role marker precedes it AND a delimiter
    # follows it. Without the trailing delimiter the pattern would swallow
    # ordinary words ("联系人负责对接" -> masking "负责对"). The PII-context
    # words below are the common case where a name sits directly against a
    # contact field, e.g. "联系人张三手机138...".
    _NAME_DELIM = r"(?:负责|提出|确认|参加|审核|跟进|对接|说|讲|是|为|在|与|和|，|。|、|：|；|手机|电话|邮箱|邮件|微信|身份证|联系方式|号码|地址|\s|$)"

    _PII_PATTERNS: List[tuple] = [
        # ID card: lookarounds, not \b — \b fails when the trailing X is
        # followed by a CJK character (CJK counts as a word char).
        (r"(?<!\d)\d{17}[\dXx](?!\d)", "[身份证]"),
        # Mainland mobile number
        (r"(?<!\d)1[3-9]\d{9}(?!\d)", "[手机号]"),
        # Email
        (r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}", "[邮箱]"),
        # Names after a role marker. Python lookbehind must be fixed-width, so
        # 3-char and 2-char markers are separate patterns — mixing them in one
        # alternation raises re.error and the pattern silently never fires.
        (r"(?<=(?:联系人|负责人|经办人|发言人|主持人))[\u4e00-\u9fa5]{2,3}(?=" + _NAME_DELIM + r")", "[人名]"),
        (r"(?<=(?:老师|经理|主任))[\u4e00-\u9fa5]{2,3}(?=" + _NAME_DELIM + r")", "[人名]"),
        # Name before an honorific (先生/女士 are post-positioned, so they are
        # NOT valid "name follows" markers).
        (r"[\u4e00-\u9fa5]{2,3}(?=(?:先生|女士|老师|经理|主任))", "[人名]"),
    ]

    @classmethod
    def _desensitize(cls, content: str) -> str:
        """Strip personally identifying information from a shared entry."""
        result = content
        for pattern, repl in cls._PII_PATTERNS:
            try:
                result = re.sub(pattern, repl, result)
            except re.error:
                # Never let a broken pattern silently disable PII masking.
                logger.error(
                    "[DualLayerEvolution] invalid PII pattern: %s", pattern
                )
        return result

    # ── Dedup & capacity helpers ──

    @staticmethod
    def _normalize(text: str) -> set[str]:
        """Normalize text into a token set for similarity comparison.

        Chinese has no word boundaries, so character bigrams are used as the
        token unit; ASCII words are kept as whole tokens.
        """
        cleaned = re.sub(r"[\s，。、；：！？,.;:!?\"'`（）()【】\[\]]+", "", text)
        tokens: set[str] = set()
        for m in re.finditer(r"[A-Za-z0-9_]+", cleaned):
            tokens.add(m.group().lower())
        zh = re.sub(r"[^一-鿿]", "", cleaned)
        for i in range(len(zh) - 1):
            tokens.add(zh[i:i + 2])
        return tokens

    @classmethod
    def _is_similar(cls, a: str, b: str) -> bool:
        """Semantic similarity, measured by containment (intersection / min size).

        Jaccard is too strict for Chinese paraphrases: two entries saying the
        same thing scored only 0.53, while unrelated pairs scored 0.00-0.17.
        Containment answers the dedup question directly — "is this new entry
        already covered by an existing one" — and separates cleanly
        (same-meaning >= 0.72, unrelated <= 0.17 on measured samples).
        """
        ta = cls._normalize(a)
        tb = cls._normalize(b)
        if not ta or not tb:
            return False
        return len(ta & tb) / min(len(ta), len(tb)) >= 0.6

    def _existing_entries(self, memory_file: Path) -> List[str]:
        """Collect existing entry lines (top-level "- " bullets)."""
        if not memory_file.exists():
            return []
        return [
            line[2:].strip()
            for line in memory_file.read_text(encoding="utf-8").splitlines()
            if line.startswith("- ")
        ]

    def _trim_to_capacity(self, memory_file: Path, scene_id: str) -> bool:
        """Enforce the scene MEMORY.md token ceiling by dropping oldest entries.

        Returns True if a trim happened.
        """
        from .memory_capacity import MemoryCapacityManager, estimate_tokens

        manager = MemoryCapacityManager(
            memory_file,
            max_tokens=SCENE_MEMORY_MAX_TOKENS,
            versions_dir=memory_file.parent / ".memory_versions",
        )
        status = manager.check_capacity()
        if not status["over_limit"]:
            return False

        # Snapshot before trimming — trimming is destructive.
        manager.backup_version(reason="capacity_trim")

        lines = memory_file.read_text(encoding="utf-8").splitlines()
        # Split into (header, entry blocks). Each entry block starts with a
        # "- " bullet and owns the indented lines that follow it.
        header: List[str] = []
        blocks: List[List[str]] = []
        for line in lines:
            if line.startswith("- "):
                blocks.append([line])
            elif blocks and line.startswith("  "):
                blocks[-1].append(line)
            elif not blocks:
                header.append(line)

        # Drop oldest blocks until under the ceiling.
        dropped = 0
        while blocks and estimate_tokens("\n".join(header + sum(blocks, []))) > SCENE_MEMORY_MAX_TOKENS:
            blocks.pop(0)
            dropped += 1

        memory_file.write_text("\n".join(header + sum(blocks, [])) + "\n", encoding="utf-8")
        logger.info(
            "[DualLayerEvolution] scene %s over capacity (%d tokens, limit %d); "
            "dropped %d oldest entries, backup saved",
            scene_id, status["current_tokens"], SCENE_MEMORY_MAX_TOKENS, dropped,
        )
        return True

    def _update_scene_memory(
        self,
        scene_id: str,
        entries: List[EvolutionEntry],
    ) -> Optional[str]:
        """Update scene agent shared memory.

        Applies semantic deduplication (C2) and capacity control (C3) before
        writing. Scene memory is user-independent, so duplicate detection runs
        against the whole shared file.

        Args:
            scene_id: Scene ID
            entries: Shared evolution entries

        Returns:
            Summary of evolution or None
        """
        scene_agent_dir = self.agents_dir / f"scene-{scene_id}"
        memory_file = scene_agent_dir / "MEMORY.md"

        if not scene_agent_dir.exists():
            logger.warning(f"Scene agent directory not found: {scene_agent_dir}")
            return None

        # Read existing memory
        existing_memory = ""
        if memory_file.exists():
            existing_memory = memory_file.read_text(encoding="utf-8")

        existing = self._existing_entries(memory_file)

        # Append new evolution entries (desensitize, then exact + semantic dedup)
        new_entries = []
        skipped = 0
        for entry in entries:
            cleaned = self._desensitize(entry.content)
            if cleaned != entry.content:
                logger.info(
                    "[DualLayerEvolution] scene %s: PII masked in shared "
                    "entry: %r -> %r",
                    scene_id, entry.content[:60], cleaned[:60],
                )
                entry.content = cleaned
            if not entry.content:
                skipped += 1
                continue
            if entry.content in existing_memory:
                skipped += 1
                continue
            if any(self._is_similar(entry.content, old) for old in existing):
                skipped += 1
                logger.debug(
                    "[DualLayerEvolution] dedup skip (semantic): %r",
                    entry.content[:60],
                )
                continue
            new_entries.append(entry)

        if not new_entries:
            logger.info(
                "[DualLayerEvolution] scene %s: all %d candidate entries "
                "already present, nothing written",
                scene_id, skipped,
            )
            return None

        # Build evolution content
        evolution_content = self._build_evolution_content(new_entries, "共享进化")

        # Append to memory file
        with open(memory_file, "a", encoding="utf-8") as f:
            f.write(evolution_content)

        # Capacity control (C3)
        self._trim_to_capacity(memory_file, scene_id)

        logger.info(f"Updated scene memory: {scene_id} with {len(new_entries)} entries")

        return f"新增 {len(new_entries)} 条共享进化"
    
    def _update_user_memory(
        self,
        user_id: str,
        scene_id: str,
        entries: List[EvolutionEntry],
    ) -> Optional[str]:
        """Update user agent personal memory.
        
        Args:
            user_id: User ID
            scene_id: Scene ID (for context)
            entries: Personal evolution entries
        
        Returns:
            Summary of evolution or None
        """
        user_workspace_dir = self.workspaces_dir / user_id
        memory_file = user_workspace_dir / "MEMORY.md"
        
        # Ensure user workspace exists
        user_workspace_dir.mkdir(parents=True, exist_ok=True)
        
        # Read existing memory
        existing_memory = ""
        if memory_file.exists():
            existing_memory = memory_file.read_text(encoding="utf-8")
        else:
            # Create initial memory file
            initial_content = f"# {user_id} 的个人记忆\n\n此文件记录用户在使用场景智能体时的个人偏好和上下文。\n\n---\n\n## 进化记录\n\n"
            memory_file.write_text(initial_content, encoding="utf-8")
        
        # Append new evolution entries
        new_entries = []
        for entry in entries:
            if entry.content not in existing_memory:
                new_entries.append(entry)
        
        if not new_entries:
            return None
        
        # Build evolution content
        evolution_content = self._build_evolution_content(
            new_entries,
            f"个人进化 (场景: {scene_id})"
        )
        
        # Append to memory file
        with open(memory_file, "a", encoding="utf-8") as f:
            f.write(evolution_content)
        
        logger.info(f"Updated user memory: {user_id} with {len(new_entries)} entries")
        
        return f"新增 {len(new_entries)} 条个人进化"
    
    def _build_evolution_content(
        self,
        entries: List[EvolutionEntry],
        section_title: str,
    ) -> str:
        """Build evolution content for memory file.
        
        Args:
            entries: Evolution entries
            section_title: Section title
        
        Returns:
            Formatted content
        """
        content_lines = [
            "",
            f"### {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M')}",
            "",
        ]
        
        for entry in entries:
            content_lines.append(f"- {entry.content}")
            if entry.metadata:
                content_lines.append(f"  - 来源: {entry.metadata.get('source', 'unknown')}")
            content_lines.append(f"  - 置信度: {entry.confidence:.2f}")
        
        content_lines.append("")
        
        return "\n".join(content_lines)
    
    # -------------------------------------------------------------------------
    # Utility Methods
    # -------------------------------------------------------------------------
    
    def get_scene_memory(self, scene_id: str) -> str:
        """Get scene agent shared memory content.
        
        Args:
            scene_id: Scene ID
        
        Returns:
            Memory content or empty string
        """
        memory_file = self.agents_dir / f"scene-{scene_id}" / "MEMORY.md"
        if not memory_file.exists():
            return ""
        return memory_file.read_text(encoding="utf-8")
    
    def get_user_memory(self, user_id: str) -> str:
        """Get user agent personal memory content.
        
        Args:
            user_id: User ID
        
        Returns:
            Memory content or empty string
        """
        memory_file = self.workspaces_dir / user_id / "MEMORY.md"
        if not memory_file.exists():
            return ""
        return memory_file.read_text(encoding="utf-8")
