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

import asyncio
import json
import logging
import re
import time
from dataclasses import dataclass
from typing import Any, List, Optional

from ..agents.core import AgentCore
from ..constant import EnvVarLoader
from .evolution_engine import TrajectoryEntry, ExtractedExperience

logger = logging.getLogger(__name__)

# Extraction is background work, so it budgets against the model's real window
# like every other call does.  The share it may take, the room its JSON answer
# needs, and the floor below which segmentation stops paying: a 24,000-char
# segment against a 71,680-char window was refused every time (dev,
# 2026-10-18: 8 segments, 8 "Context size has been exceeded").
_EXTRACTION_WINDOW_RATIO = 0.5
_EXTRACTION_OUTPUT_RESERVE_TOKENS = 2_000
_EXTRACTION_ENVELOPE_CHARS = 400
_EXTRACTION_MIN_SEGMENT_CHARS = 4_000


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
        extract_chunk_chars: int = 24_000,
        extract_max_segments: int = 8,
        extract_round_seconds: float = 240.0,
        llm_retries: int = 2,
        llm_backoff_seconds: float = 2.0,
        llm_timeout_seconds: float | None = None,
    ):
        self.agent_core = agent_core
        self.min_confidence = min_confidence
        self.max_extraction_per_session = max_extraction_per_session
        self.enable_deduplication = enable_deduplication
        # The extractor owns a raw provider client, so nothing gated its
        # prompt: a long session (tool results included) went out whole and
        # the provider answered "Context size has been exceeded" - 849
        # extraction failures in one month on dev (2026-10-17).  Segments are
        # sized to the budget, and transient refusals are retried.
        self.extract_chunk_chars = max(4_000, extract_chunk_chars)
        # Segment count is the cost driver, not segment size.  A 2.5M-char
        # trajectory (dev, 2026-10-19) split into 81 parts per strategy, and
        # five strategies ran them back to back for minutes, holding every
        # slot of the shared LLM concurrency cap while the chat and the
        # compaction waited behind them.  Segments are capped, and a round
        # that runs out of time stops launching calls; the trajectory is
        # archived either way, so a skipped tail costs learning, not data.
        self.extract_max_segments = max(
            1,
            EnvVarLoader.get_int(
                "COAPIS_EVOLUTION_MAX_SEGMENTS",
                extract_max_segments,
                min_value=1,
            ),
        )
        self.extract_round_seconds = float(
            EnvVarLoader.get_int(
                "COAPIS_EVOLUTION_ROUND_SECONDS",
                int(extract_round_seconds),
                min_value=30,
            ),
        )
        self.llm_retries = max(1, llm_retries)
        self.llm_backoff_seconds = max(0.0, llm_backoff_seconds)
        # A raw client with no timeout inherits the SDK default (600 s), and
        # extraction runs on the turn's closing path: 5 strategies x N segments
        # x 3 retries of a call that never answers is how a delivered answer
        # kept its SSE stream open for 199 s after the last token (dev,
        # 2026-10-18).  One bounded call per segment is the difference between
        # a slow background job and a chat that never closes.
        if llm_timeout_seconds is None:
            from ..constant import EVOLUTION_EXTRACT_TIMEOUT_SECONDS

            llm_timeout_seconds = EVOLUTION_EXTRACT_TIMEOUT_SECONDS
        self.llm_timeout_seconds = max(5.0, llm_timeout_seconds)
        # Window of the model this extractor actually calls, resolved once.
        self._window: Any = None
        self._window_resolved = False

        # Cache for deduplication
        self._known_titles: set[str] = set()

        # Pre-index existing memory for content-based dedup
        self._memory_keywords: set[str] = set()
        if existing_memory_content:
            import re as _re
            words = _re.findall(r'[\u4e00-\u9fff]{2,}|[a-zA-Z]{3,}', existing_memory_content.lower())
            self._memory_keywords = set(words)

        # 批次 D-2「抽取超时降级」第三段：连续失败后熔断。
        # 实测（dev 2026-10-26 23:21）一轮抽取刷出 3 行 WARNING
        # （45s 超时 → retry 1/3 → retry 2/3），端点持续变慢时每个轮次
        # 都要付满这 141s 才退回启发式。连续 5 次失败后停 5 分钟直接走
        # 启发式抽取，并只报 1 行 WARN。
        self._llm_fail_streak = 0
        self._llm_cooldown_until = 0.0
        self._llm_cooldown_after = 5
        self._llm_cooldown_seconds = 300.0

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

        # One session is not worth less than the provider's window: the
        # conversation is cut into budget-sized segments and each is
        # extracted on its own.  A segment that fails is logged and skipped;
        # the other segments still yield experiences, and only when nothing
        # came back does this fall back to the heuristic.
        segments = self._split_conversation(
            conversation,
            len(prompt_template),
            self.extract_max_segments,
        )
        experiences: List[ExtractedExperience] = []
        # A segment is a call, and calls are the cost.  Past the round's
        # time budget the remaining segments are skipped rather than queued:
        # five strategies each grinding through a long trajectory is what
        # starves the chat and the compaction of the shared LLM slots.
        deadline = time.monotonic() + self.extract_round_seconds
        for index, segment in enumerate(segments):
            if time.monotonic() > deadline:
                logger.warning(
                    "Extraction of %s stopped after part %d/%d: the round's "
                    "%.0fs budget is spent (%d segment(s) skipped).",
                    exp_type,
                    index,
                    len(segments),
                    self.extract_round_seconds,
                    len(segments) - index,
                )
                break
            prompt = (
                prompt_template
                + f"\n\n--- Conversation part {index + 1}/{len(segments)} "
                + "---\n"
                + segment
                + "\n--- End ---"
            )
            try:
                result = await self._call_llm(prompt)
            except Exception as e:
                logger.error(
                    "LLM extraction failed for %s (part %d/%d): %s",
                    exp_type,
                    index + 1,
                    len(segments),
                    e,
                )
                continue
            experiences.extend(
                self._parse_extraction_result(
                    result,
                    exp_type,
                    session_id,
                    agent_id,
                    user_id,
                ),
            )
        if not experiences:
            # Nothing survived: keep the previous safety net.
            return self._heuristic_extract(
                trajectory,
                exp_type,
                session_id,
                agent_id,
                user_id,
            )
        return experiences

    def _resolve_window(self) -> Any:
        """The real context window of the model this extractor calls.

        The extractor talks to a raw provider client built from ``AgentCore``,
        so it has a model *name* and an endpoint and no provider id -- the
        same window the chat path resolved is the only number that makes a
        segment request fit.  Resolved once per extractor; ``None`` means the
        registry knows nothing and the configured cap is all we have.
        """
        if self._window_resolved:
            return self._window
        self._window_resolved = True
        try:
            from ..agents.context.window_source import (
                merge_window_feedback,
                reported_window_for_model_name,
                resolve_window,
            )

            model_name = getattr(self.agent_core, "model", None)
            provider_id, reported = reported_window_for_model_name(
                model_name,
                getattr(self.agent_core, "base_url", None),
            )
            reported = merge_window_feedback(
                provider_id,
                model_name,
                reported,
            )

            class _Stub:
                pass

            stub = _Stub()
            stub.max_sequence_length = reported
            running = None
            try:
                from ..config.config import load_agent_config

                running = load_agent_config("default").running
            except Exception:
                running = None
            self._window = resolve_window(stub, running)
        except Exception as exc:  # budgeting is an optimisation, never fatal
            logger.debug("Extraction window resolution failed: %s", exc)
            self._window = None
        return self._window

    def _segment_limit(self, template_chars: int) -> int:
        """Conversation characters one extraction request can carry.

        The request is ``system + template + envelope + segment`` and the
        model needs room left for the JSON it is asked to write, so the
        segment is what remains of the window -- not a constant invented
        beside it.  The configured cap still applies (a huge window does not
        make one session worth a 200K-char prompt), and the floor keeps
        segmentation meaningful on a tiny window.
        """
        window = self._resolve_window()
        if window is None:
            return self.extract_chunk_chars
        reserve_tokens = min(
            _EXTRACTION_OUTPUT_RESERVE_TOKENS,
            int(getattr(self.agent_core, "max_tokens", 2000) or 2000),
        )
        budget_chars = window.to_chars(
            int(window.effective_tokens * _EXTRACTION_WINDOW_RATIO)
            - reserve_tokens,
        )
        overhead = template_chars + _EXTRACTION_ENVELOPE_CHARS
        return max(
            _EXTRACTION_MIN_SEGMENT_CHARS,
            min(self.extract_chunk_chars, budget_chars - overhead),
        )

    def _split_conversation(
        self,
        conversation: str,
        template_chars: int = 0,
        max_segments: int = 0,
    ) -> list[str]:
        """Cut the conversation text into segments within the budget.

        Splitting is line-based so a ``User:/Tools:/Assistant:`` exchange is
        never cut in half; a single oversized line (one huge tool result) is
        sliced by characters, which is what the provider's window cares
        about.

        ``max_segments`` (0 = no cap) bounds how many calls one strategy may
        make.  Widening segments past the window to stay under the cap is the
        bug this path was built to remove, so when a conversation needs more
        segments than the cap, the cap wins and the tail is dropped -- with a
        log saying exactly how much.  The trajectory is archived either way.

        Args:
            conversation: The formatted conversation text.
            template_chars: Size of the prompt template the segment is sent
                inside, so the limit is the room the segment has and not the
                room the request has.
            max_segments: Cap on the returned segment count.

        Returns:
            Segments in original order; ``[conversation]`` when it fits.
        """
        limit = self._segment_limit(template_chars)
        if len(conversation) <= limit:
            return [conversation]
        segments: list[str] = []
        current: list[str] = []
        size = 0
        for line in conversation.split("\n"):
            while len(line) > limit:
                if current:
                    segments.append("\n".join(current))
                    current, size = [], 0
                segments.append(line[:limit])
                line = line[limit:]
            if current and size + len(line) + 1 > limit:
                segments.append("\n".join(current))
                current, size = [], 0
            current.append(line)
            size += len(line) + 1
        if current:
            segments.append("\n".join(current))
        if max_segments and len(segments) > max_segments:
            dropped = sum(len(seg) for seg in segments[max_segments:])
            logger.warning(
                "Extraction segments capped at %d: dropping %d chars of the "
                "tail (%d of %d segment(s) dropped). The trajectory is "
                "archived; the cap bounds the calls, not the record.",
                max_segments,
                dropped,
                len(segments) - max_segments,
                len(segments),
            )
            segments = segments[:max_segments]
        return segments

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
        """Call LLM for experience extraction, retrying transient refusals.

        429 / 500 / timeouts are momentary conditions on a shared key, and
        the alternative to retrying is a heuristic extraction that records
        nothing at all.  Backoff is exponential so a rate-limited key gets
        room instead of a second of hammering.

        批次 D-2「抽取超时降级」：
        * 失败不再每次尝试刷一行 WARNING（实测一轮 3 行），全部尝试用尽
          后只报 1 行。
        * 连续 _llm_cooldown_after 次失败后进入熔断：这段时间内直接抛错
          让调用方走启发式抽取，不再逐轮付满「超时 × 重试」的时间去抽一条
          可选的经验。
        """
        now = time.monotonic()
        if now < self._llm_cooldown_until:
            raise TimeoutError(
                f"extraction LLM in cooldown "
                f"({self._llm_cooldown_until - now:.0f}s left)",
            )

        attempts = self.llm_retries
        last: Exception | None = None
        for attempt in range(attempts):
            try:
                result = await self._call_llm_once(prompt)
                self._llm_fail_streak = 0
                return result
            except Exception as exc:
                last = exc
                if attempt + 1 < attempts:
                    delay = self.llm_backoff_seconds * (2**attempt)
                    await asyncio.sleep(delay)

        assert last is not None
        self._llm_fail_streak += 1
        if self._llm_fail_streak >= self._llm_cooldown_after:
            self._llm_cooldown_until = (
                time.monotonic() + self._llm_cooldown_seconds
            )
            self._llm_fail_streak = 0
            logger.warning(
                "Extraction LLM disabled for %.0fs after %d consecutive "
                "failures (last: %s); falling back to heuristic extraction",
                self._llm_cooldown_seconds,
                self._llm_cooldown_after,
                last,
            )
        else:
            logger.warning(
                "Extraction LLM call failed after %d attempts: %s",
                attempts,
                last,
            )
        raise last

    async def _call_llm_once(self, prompt: str) -> str:
        """One provider call for experience extraction, on a deadline.

        The raw client has no timeout of its own, so an unresponsive endpoint
        holds the call for the SDK default (600 s) -- five times, once per
        extraction strategy, on the path that closes the user's stream.
        """
        try:
            response = await asyncio.wait_for(
                self.agent_core.client.chat.completions.create(
                    model=self.agent_core.model,
                    messages=[
                        {
                            "role": "system",
                            "content": (
                                "You are an experience extraction assistant. "
                                "Analyze conversations and extract valuable "
                                "insights. Output ONLY valid JSON arrays."
                            ),
                        },
                        {"role": "user", "content": prompt},
                    ],
                    max_tokens=min(2000, self.agent_core.max_tokens),
                    temperature=0.5,
                ),
                timeout=self.llm_timeout_seconds,
            )
        except asyncio.TimeoutError as exc:
            raise TimeoutError(
                f"extraction call exceeded {self.llm_timeout_seconds:.0f}s",
            ) from exc
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
