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

"""GrowthSystem - Self-improvement through experience.

Inspired by external reference's background review mechanism.
Nudge-based system that triggers skill/memory review after thresholds.
"""

import json
import logging
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional, Any

from ..constant import MEMORY_NUDGE_INTERVAL, SKILL_NUDGE_INTERVAL

logger = logging.getLogger(__name__)


class GrowthSystem:
    """Agent self-improvement system.

    Tracks conversation metrics and triggers review when thresholds are met:
    - Memory review: After N turns without memory save
    - Skill review: After N tool calls without skill creation

    Review prompts (standard):
    - "Review conversation and consider saving/updating a skill"
    - "Review conversation and consider saving to memory"
    """

    def __init__(
        self,
        workspace_dir: Path,
        memory: Any,
        skills: Any,
        memory_nudge_interval: int = MEMORY_NUDGE_INTERVAL,
        skill_nudge_interval: int = SKILL_NUDGE_INTERVAL,
    ):
        self.workspace_dir = workspace_dir
        self.memory = memory
        self.skills = skills

        # Nudge intervals
        self.memory_nudge_interval = memory_nudge_interval
        self.skill_nudge_interval = skill_nudge_interval

        # Counters
        self.turns_since_memory = 0
        self.calls_since_skill = 0

        # State
        self._last_review_time: Optional[datetime] = None
        self._review_log: List[Dict[str, Any]] = []

    def on_turn(self):
        """Called after each conversation turn."""
        self.turns_since_memory += 1

    def on_tool_call(self):
        """Called after each tool call."""
        self.calls_since_skill += 1

    async def check_nudges(self, context: Any) -> List[Dict[str, Any]]:
        """Check if any nudges should trigger.

        Args:
            context: ChatContext with message history

        Returns:
            List of review actions taken
        """
        actions = []

        # Check memory nudge
        if (self.memory_nudge_interval > 0 and
                self.turns_since_memory >= self.memory_nudge_interval):
            action = await self._review_memory(context)
            if action:
                actions.append(action)
                self.turns_since_memory = 0

        # Check skill nudge
        if (self.skill_nudge_interval > 0 and
                self.calls_since_skill >= self.skill_nudge_interval):
            action = await self._review_skill(context)
            if action:
                actions.append(action)
                self.calls_since_skill = 0

        if actions:
            self._last_review_time = datetime.now()
            self._review_log.append({
                "time": self._last_review_time.isoformat(),
                "actions": actions,
            })

        return actions

    async def _review_memory(self, context: Any) -> Optional[Dict[str, Any]]:
        """Review conversation for memory-worthy content.

        standard prompt:
        "Review the conversation and consider saving to memory.
        Focus on: user preferences, persona, behavior expectations.
        If nothing worth saving, say 'Nothing to save.' and stop."
        """
        messages = context.get_messages()
        if not messages:
            return None

        # Analyze for memory-worthy content
        result = self._analyze_for_memory(messages)

        if result.get("should_save"):
            self.memory.save("user", result["content"])
            return {
                "type": "memory_save",
                "content": result["content"][:100] + "...",
            }

        return None

    async def _review_skill(self, context: Any) -> Optional[Dict[str, Any]]:
        """Review conversation for skill-worthy patterns.

        standard prompt:
        "Review the conversation and consider saving a skill.
        Focus on: non-trivial approaches, trial and error, reusable patterns.
        If nothing worth saving, say 'Nothing to save.' and stop."
        """
        messages = context.get_messages()
        if not messages:
            return None

        # Analyze for skill-worthy patterns
        result = self._analyze_for_skill(messages)

        if result.get("should_create"):
            return {
                "type": "skill_creation_suggested",
                "name": result.get("name"),
                "description": result.get("description"),
            }

        return None

    def _analyze_for_memory(self, messages: List[Dict]) -> Dict[str, Any]:
        """Analyze messages for memory-worthy content.

        Simple heuristic analysis (replace with LLM in production).
        """
        # Look for preference expressions
        preference_patterns = [
            "I prefer", "I like", "I always", "I never",
            "I want you to", "Please always", "Don't ever",
        ]

        for msg in messages:
            if msg.get("role") != "user":
                continue
            content = msg.get("content", "")
            for pattern in preference_patterns:
                if pattern.lower() in content.lower():
                    return {
                        "should_save": True,
                        "content": content.strip(),
                    }

        return {"should_save": False}

    def _analyze_for_skill(self, messages: List[Dict]) -> Dict[str, Any]:
        """Analyze messages for skill-worthy patterns.

        Simple heuristic analysis (replace with LLM in production).
        """
        # Count tool calls and errors
        tool_calls = sum(1 for m in messages if "tool_call" in str(m))
        errors = sum(1 for m in messages if "error" in str(m).lower())

        # Skill-worthy if: multiple tool calls + some errors (trial and error)
        if tool_calls >= 5 and errors >= 1:
            return {
                "should_create": True,
                "name": "complex-task-pattern",
                "description": f"Pattern from {tool_calls} tool calls with {errors} errors",
            }

        return {"should_create": False}

    def get_stats(self) -> Dict[str, Any]:
        """Get growth statistics."""
        return {
            "turns_since_memory": self.turns_since_memory,
            "calls_since_skill": self.calls_since_skill,
            "last_review": self._last_review_time.isoformat() if self._last_review_time else None,
            "total_reviews": len(self._review_log),
        }
