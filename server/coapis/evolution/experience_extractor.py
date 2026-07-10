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

"""Experience Extractor - LLM-driven experience mining from conversation trajectories.

Uses auxiliary LLM to analyze conversation trajectories and extract:
1. Lessons learned (trial-and-error successes)
2. User preferences (explicitly stated or inferred)
3. Reusable patterns (complex workflows abstracted)
4. Skill improvements (new tool usage patterns)

Architecture:
- Pluggable extraction strategies (LLM-based or heuristic)
- Confidence scoring for each extracted experience
- Deduplication against existing memory
- Category classification for knowledge flow routing
"""
from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass
from typing import Any, List, Optional

from ..agents.core import AgentCore
from .evolution_engine import TrajectoryEntry, ExtractedExperience

logger = logging.getLogger(__name__)


@dataclass
class ExtractionResult:
    """Result from a single extraction pass."""
    experiences: List[ExtractedExperience]
    duplicates_removed: int
    total_analyzed: int
    extraction_time_ms: float


class ExperienceExtractor:
    """LLM-driven experience extraction from conversation trajectories.

    Uses the agent's LLM client to analyze trajectories and extract valuable
    experiences that should be persisted to memory layers.

    Extraction strategies:
    1. **Pattern Detection**: Identifies repeated workflows or problem-solving patterns
    2. **Lesson Mining**: Finds trial-and-error sequences that led to success
    3. **Preference Extraction**: Captures user preferences and behavioral patterns
    4. **Skill Discovery**: Identifies new tool usage patterns or capabilities
    """

    # Extraction prompt templates
    LESSON_PROMPT = """Analyze the conversation below and extract lessons learned.
Focus on:
1. Problems encountered and how they were solved
2. Mistakes made and corrections applied
3. Insights gained during the process

Output ONLY valid JSON array:
[{"title": "...", "content": "...", "confidence": 0.0-1.0}]
If no lessons found, output: []
"""

    PATTERN_PROMPT = """Analyze the conversation below and identify reusable patterns.
Focus on:
1. Repeated workflows or procedures
2. Problem-solving strategies that worked
3. Template patterns for similar tasks

Output ONLY valid JSON array:
[{"title": "...", "content": "...", "confidence": 0.0-1.0}]
If no patterns found, output: []
"""

    PREFERENCE_PROMPT = """Analyze the conversation below and extract user preferences.
Focus on:
1. Explicitly stated preferences ("I prefer...", "I like...")
2. Implicit preferences (repeated choices, corrections)
3. Style and format preferences
4. Domain-specific requirements

Output ONLY valid JSON array:
[{"title": "...", "content": "...", "confidence": 0.0-1.0}]
If no preferences found, output: []
"""

    SKILL_PROMPT = """Analyze the conversation below and identify new skills or tool usage patterns.
Focus on:
1. New tools discovered or learned
2. Improved tool usage techniques
3. Workarounds for tool limitations
4. New capabilities unlocked

Output ONLY valid JSON array:
[{"title": "...", "content": "...", "confidence": 0.0-1.0}]
If no new skills found, output: []
"""

    # ── 5th strategy: Skill Effectiveness Analysis ──
    SKILL_EFFECTIVENESS_PROMPT = """Analyze the conversation below and identify skill/tool effectiveness issues.

Focus on three types of problems:
1. **false_positive**: A skill was triggered but the user didn't want it (user negated, cancelled, or ignored the result)
2. **false_negative**: The user expected a capability but no skill was triggered (user asked for something a skill could handle)
3. **improve**: A skill was used but performed poorly (user asked to retry, corrected the result, or expressed dissatisfaction)

For each issue found, output a JSON object with:
- "signal_type": "false_positive" | "false_negative" | "improve"
- "skill_name": the skill name or expected skill name
- "trigger_keyword": the keyword/pattern that caused or should have caused triggering
- "context": brief description of what happened
- "confidence": 0.0-1.0

Output ONLY valid JSON array:
[{"signal_type": "...", "skill_name": "...", "trigger_keyword": "...", "context": "...", "confidence": 0.0-1.0}]
If no issues found, output: []
"""

    def __init__(
        self,
        agent_core: AgentCore,
        min_confidence: float = 0.6,
        max_extraction_per_session: int = 5,
        enable_deduplication: bool = True,
        existing_memory_content: str = "",
    ):
        self.agent_core = agent_core
        self.min_confidence = min_confidence
        self.max_extraction_per_session = max_extraction_per_session
        self.enable_deduplication = enable_deduplication

        # Cache for deduplication
        self._known_titles: set[str] = set()

        # Pre-index existing memory for content-based dedup
        self._memory_keywords: set[str] = set()
        if existing_memory_content:
            import re as _re
            words = _re.findall(r'[\u4e00-\u9fff]{2,}|[a-zA-Z]{3,}', existing_memory_content.lower())
            self._memory_keywords = set(words)

    async def extract_from_trajectory(
        self,
        trajectory: List[TrajectoryEntry],
        session_id: str,
        agent_id: str,
        user_id: str,
    ) -> List[ExtractedExperience]:
        """Extract experiences from a complete conversation trajectory.

        Args:
            trajectory: List of trajectory entries from a session
            session_id: Session identifier
            agent_id: Agent identifier
            user_id: User identifier

        Returns:
            List of extracted experiences (filtered by confidence)
        """
        if len(trajectory) < 2:
            logger.debug("Trajectory too short for extraction (%d entries)", len(trajectory))
            return []

        logger.info(
            "Starting experience extraction for session %s (%d turns)",
            session_id,
            len(trajectory),
        )

        all_experiences: List[ExtractedExperience] = []

        # Run all extraction strategies in parallel
        import asyncio

        tasks = [
            self._extract_lessons(trajectory, session_id, agent_id, user_id),
            self._extract_patterns(trajectory, session_id, agent_id, user_id),
            self._extract_preferences(trajectory, session_id, agent_id, user_id),
            self._extract_skills(trajectory, session_id, agent_id, user_id),
            self._extract_skill_effectiveness(trajectory, session_id, agent_id, user_id),
        ]

        results = await asyncio.gather(*tasks, return_exceptions=True)

        for result in results:
            if isinstance(result, Exception):
                logger.error("Extraction strategy failed: %s", result)
                continue
            all_experiences.extend(result)

        # Filter by confidence threshold
        filtered = [exp for exp in all_experiences if exp.confidence >= self.min_confidence]

        # Deduplication
        if self.enable_deduplication:
            filtered = self._deduplicate(filtered)

        # Limit total extraction per session
        if len(filtered) > self.max_extraction_per_session:
            # Sort by confidence and take top N
            filtered.sort(key=lambda x: x.confidence, reverse=True)
            filtered = filtered[: self.max_extraction_per_session]

        logger.info(
            "Extracted %d experiences from session %s (filtered from %d)",
            len(filtered),
            session_id,
            len(all_experiences),
        )

        return filtered

    async def _extract_lessons(
        self,
        trajectory: List[TrajectoryEntry],
        session_id: str,
        agent_id: str,
        user_id: str,
    ) -> List[ExtractedExperience]:
        """Extract lessons learned from conversation."""
        return await self._run_extraction(
            trajectory,
            self.LESSON_PROMPT,
            "lesson",
            session_id,
            agent_id,
            user_id,
        )

    async def _extract_patterns(
        self,
        trajectory: List[TrajectoryEntry],
        session_id: str,
        agent_id: str,
        user_id: str,
    ) -> List[ExtractedExperience]:
        """Extract reusable patterns from conversation."""
        return await self._run_extraction(
            trajectory,
            self.PATTERN_PROMPT,
            "pattern",
            session_id,
            agent_id,
            user_id,
        )

    async def _extract_preferences(
        self,
        trajectory: List[TrajectoryEntry],
        session_id: str,
        agent_id: str,
        user_id: str,
    ) -> List[ExtractedExperience]:
        """Extract user preferences from conversation."""
        return await self._run_extraction(
            trajectory,
            self.PREFERENCE_PROMPT,
            "preference",
            session_id,
            agent_id,
            user_id,
        )

    async def _extract_skills(
        self,
        trajectory: List[TrajectoryEntry],
        session_id: str,
        agent_id: str,
        user_id: str,
    ) -> List[ExtractedExperience]:
        """Extract new skills from conversation."""
        return await self._run_extraction(
            trajectory,
            self.SKILL_PROMPT,
            "skill",
            session_id,
            agent_id,
            user_id,
        )

    async def _extract_skill_effectiveness(
        self,
        trajectory: List[TrajectoryEntry],
        session_id: str,
        agent_id: str,
        user_id: str,
    ) -> List[ExtractedExperience]:
        """Extract skill effectiveness signals from conversation.

        The 5th extraction strategy: analyzes skill/tool usage patterns to find
        false positives, false negatives, and improvement opportunities.
        Results are also routed to SkillEvolutionBridge for skill evolution.
        """
        raw_experiences = await self._run_extraction(
            trajectory,
            self.SKILL_EFFECTIVENESS_PROMPT,
            "skill_effectiveness",
            session_id,
            agent_id,
            user_id,
        )

        # Also run bridge's heuristic extraction for non-LLM signals
        try:
            from ..skill_evolution.bridge import get_skill_evolution_bridge
            bridge = get_skill_evolution_bridge()
            bridge_signals = await bridge.extract_effectiveness_signals(
                trajectory, session_id, agent_id, user_id,
            )
            # Convert bridge signals to ExtractedExperience format
            for signal in bridge_signals:
                raw_experiences.append(ExtractedExperience(
                    title=f"[{signal.signal_type}] {signal.skill_name}: {signal.trigger_keyword}",
                    content=signal.context,
                    experience_type="skill_effectiveness",
                    category="skill_effectiveness",
                    source_agent=agent_id,
                    source_session=session_id,
                    source_user=user_id,
                    confidence=signal.confidence,
                    metadata={
                        "signal_type": signal.signal_type,
                        "skill_name": signal.skill_name,
                        "trigger_keyword": signal.trigger_keyword,
                    },
                ))
        except Exception as e:
            logger.warning("Bridge extraction failed: %s", e)

        return raw_experiences

    async def _run_extraction(
        self,
        trajectory: List[TrajectoryEntry],
        prompt_template: str,
        exp_type: str,
        session_id: str,
        agent_id: str,
        user_id: str,
    ) -> List[ExtractedExperience]:
        """Run a single extraction strategy using LLM."""
        # Build conversation text
        conversation = self._build_conversation_text(trajectory)

        if not conversation.strip():
            return []

        prompt = prompt_template + "\n\n--- Conversation ---\n" + conversation + "\n--- End ---"

        try:
            # Call LLM for extraction
            result = await self._call_llm(prompt)

            # Parse JSON response
            experiences = self._parse_extraction_result(result, exp_type, session_id, agent_id, user_id)
            return experiences

        except Exception as e:
            logger.error("LLM extraction failed for %s: %s", exp_type, e)
            # Fallback to heuristic extraction
            return self._heuristic_extract(trajectory, exp_type, session_id, agent_id, user_id)

    def _build_conversation_text(self, trajectory: List[TrajectoryEntry]) -> str:
        """Build formatted conversation text from trajectory entries."""
        lines = []
        for entry in trajectory:
            lines.append(f"User: {entry.user_message}")
            if entry.tool_calls:
                tool_names = [tc.get("name", "unknown") for tc in entry.tool_calls]
                lines.append(f"Tools used: {', '.join(tool_names)}")
            if entry.assistant_message:
                lines.append(f"Assistant: {entry.assistant_message}")
            lines.append("")
        return "\n".join(lines)

    async def _call_llm(self, prompt: str) -> str:
        """Call LLM for experience extraction."""
        response = await self.agent_core.client.chat.completions.create(
            model=self.agent_core.model,
            messages=[
                {
                    "role": "system",
                    "content": (
                        "You are an experience extraction assistant. "
                        "Analyze conversations and extract valuable insights. "
                        "Output ONLY valid JSON arrays."
                    ),
                },
                {"role": "user", "content": prompt},
            ],
            max_tokens=min(2000, self.agent_core.max_tokens),
            temperature=0.5,
        )
        return response.choices[0].message.content or ""

    def _parse_extraction_result(
        self,
        llm_response: str,
        exp_type: str,
        session_id: str,
        agent_id: str,
        user_id: str,
    ) -> List[ExtractedExperience]:
        """Parse LLM JSON response into ExtractedExperience objects."""
        experiences = []

        # Try to extract JSON from response
        json_match = re.search(r'\[.*\]', llm_response, re.DOTALL)
        if not json_match:
            logger.warning("No JSON found in extraction response: %s", llm_response[:100])
            return experiences

        try:
            items = json.loads(json_match.group())
        except json.JSONDecodeError as e:
            logger.warning("Failed to parse extraction JSON: %s", e)
            return experiences

        for item in items:
            if not isinstance(item, dict):
                continue

            title = item.get("title", "").strip()
            content = item.get("content", "").strip()
            confidence = float(item.get("confidence", 0.5))

            if not title or not content:
                continue

            exp = ExtractedExperience(
                title=title,
                content=content,
                experience_type=exp_type,
                category=self._classify_category(exp_type, content),
                source_session=session_id,
                source_agent=agent_id,
                source_user=user_id,
                confidence=confidence,
                is_generalizable=confidence >= 0.8,
                memory_type=self._determine_memory_type(exp_type, confidence),
            )
            experiences.append(exp)

        return experiences

    def _classify_category(self, exp_type: str, content: str) -> str:
        """Classify experience into a category based on type and content."""
        # Keyword-based classification
        content_lower = content.lower()

        if exp_type == "lesson":
            if any(kw in content_lower for kw in ["code", "bug", "error", "debug", "fix"]):
                return "coding"
            if any(kw in content_lower for kw in ["design", "architecture", "structure"]):
                return "design"
            return "general"

        if exp_type == "pattern":
            if any(kw in content_lower for kw in ["workflow", "process", "procedure"]):
                return "workflow"
            if any(kw in content_lower for kw in ["template", "format", "structure"]):
                return "template"
            return "general"

        if exp_type == "preference":
            if any(kw in content_lower for kw in ["style", "format", "tone", "language"]):
                return "style"
            if any(kw in content_lower for kw in ["domain", "industry", "field"]):
                return "domain"
            return "preference"

        if exp_type == "skill":
            if any(kw in content_lower for kw in ["tool", "command", "api", "function"]):
                return "tool_usage"
            return "skill"

        return "general"

    def _determine_memory_type(self, exp_type: str, confidence: float) -> str:
        """Determine target memory type based on experience type and confidence."""
        if exp_type == "preference" and confidence >= 0.7:
            return "long_term"
        if exp_type == "pattern" and confidence >= 0.8:
            return "long_term"
        if exp_type == "lesson" and confidence >= 0.9:
            return "long_term"
        return "short_term"

    def _heuristic_extract(
        self,
        trajectory: List[TrajectoryEntry],
        exp_type: str,
        session_id: str,
        agent_id: str,
        user_id: str,
    ) -> List[ExtractedExperience]:
        """Fallback heuristic extraction when LLM fails."""
        experiences = []

        for entry in trajectory:
            if exp_type == "lesson" and entry.tool_calls:
                # Extract tool usage as a lesson
                tool_names = [tc.get("name", "unknown") for tc in entry.tool_calls]
                experiences.append(ExtractedExperience(
                    title=f"Used {tool_names[0]} tool",
                    content=f"Tool {tool_names[0]} was used to address: {entry.user_message[:100]}",
                    experience_type="lesson",
                    category="tool_usage",
                    source_session=session_id,
                    source_agent=agent_id,
                    source_user=user_id,
                    confidence=0.4,  # Low confidence for heuristic
                ))

        return experiences

    def _deduplicate(self, experiences: List[ExtractedExperience]) -> List[ExtractedExperience]:
        """Remove duplicate experiences based on title similarity + memory content overlap."""
        import re as _re
        unique = []
        for exp in experiences:
            title_lower = exp.title.lower()
            if title_lower in self._known_titles:
                continue

            # Content-based dedup against existing MEMORY.md
            if self._memory_keywords:
                exp_words = set(_re.findall(r'[\u4e00-\u9fff]{2,}|[a-zA-Z]{3,}', exp.content.lower()))
                if exp_words:
                    overlap = len(exp_words & self._memory_keywords) / len(exp_words)
                    if overlap > 0.6:
                        logger.debug(
                            "Dedup: skipping '%s' (%.0f%% overlap with existing memory)",
                            exp.title[:30], overlap * 100,
                        )
                        continue

            unique.append(exp)
            self._known_titles.add(title_lower)
        return unique

    def get_stats(self) -> dict:
        """Get extraction statistics."""
        return {
            "known_titles_count": len(self._known_titles),
            "min_confidence": self.min_confidence,
            "max_per_session": self.max_extraction_per_session,
            "deduplication_enabled": self.enable_deduplication,
        }

    def reset_cache(self) -> None:
        """Reset deduplication cache (call periodically or on session boundary)."""
        self._known_titles.clear()
