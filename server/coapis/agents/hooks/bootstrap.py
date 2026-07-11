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

"""Bootstrap hook for first-time user interaction guidance.

v3: No longer injects any message into agent memory during reasoning.
Instead, the runner appends a conversational prompt to the assistant's
final response after streaming ends.  This hook only tracks attempt
counters and auto-completes after ``max_attempts`` (default 3) non-
cooperative rounds.

The actual guidance text is appended in runner.py's query_handler
finally block, ensuring:
1. LLM answers the user's question without interference
2. Guidance appears naturally after the answer
3. No internal directives leak to the user
"""
import json
import logging
from pathlib import Path
from typing import Any

from ..utils import has_pending_bootstrap

logger = logging.getLogger(__name__)

_DEFAULT_MAX_ATTEMPTS = 3

# Conversational prompts appended to assistant response after streaming.
# Indexed by attempt number (0-based).
# Using Markdown for better visibility.
BOOTSTRAP_PROMPTS_ZH = [
    "\n\n---\n\n**初次见面，让我先自我介绍一下** 👋\n\n我是 CoApis 智能助手，很高兴认识你！我可以帮你处理各种任务、回答问题、管理日程，甚至帮你写代码。\n\n**请问我该怎么称呼你呢？**",
    "\n\n---\n\n**想更好地为你服务** 💡\n\n了解你的偏好能让我更好地协助你。**你希望我用什么样的风格跟你交流？** 比如：\n- 简洁高效 vs 详细解释\n- 正式专业 vs 轻松友好\n- 或者你有其他想法？",
    "\n\n---\n\n**让我更懂你** 🎯\n\n每个人都有独特的工作方式和偏好。**有什么我可以为你定制的吗？** 比如称呼、交流风格、或者你希望我优先关注的事情？",
]

BOOTSTRAP_PROMPTS_EN = [
    "\n\n---\n\n**Let me introduce myself first** 👋\n\nI'm your CoApis assistant, nice to meet you! I can help with tasks, answer questions, manage schedules, and even write code for you.\n\n**What should I call you?**",
    "\n\n---\n\n**Let me serve you better** 💡\n\nUnderstanding your preferences helps me assist you better. **What communication style do you prefer?** For example:\n- Concise & efficient vs Detailed explanations\n- Formal & professional vs Casual & friendly\n- Or do you have other ideas?",
    "\n\n---\n\n**Making it about you** 🎯\n\nEveryone has unique work styles and preferences. **Is there anything I can customize for you?** Like how to address you, communication style, or things you'd like me to prioritize?",
]


def get_bootstrap_prompt(attempt: int, language: str = "zh") -> str:
    """Get the conversational prompt for the given attempt."""
    prompts = BOOTSTRAP_PROMPTS_ZH if language == "zh" else BOOTSTRAP_PROMPTS_EN
    idx = min(attempt - 1, len(prompts) - 1)
    return prompts[idx]


class BootstrapHook:
    """Hook for first-time user interaction guidance.

    v3: Only tracks attempt counters.  Guidance text is appended
    by the runner after streaming ends.
    """

    def __init__(
        self,
        working_dir: Path,
        language: str = "zh",
        max_attempts: int = _DEFAULT_MAX_ATTEMPTS,
    ):
        self.working_dir = working_dir
        self.language = language
        self.max_attempts = max_attempts

    async def __call__(
        self,
        agent,
        kwargs: dict[str, Any],
    ) -> dict[str, Any] | None:
        """Pre-reasoning hook: check if bootstrap should auto-complete.

        v3: This hook does NOT inject any message into memory.
        It only checks if we've exceeded max attempts and marks
        bootstrap as completed if so.  The runner handles appending
        guidance text and incrementing the attempt counter.

        Returns {"bootstrap_pending": bool} for runner reference.
        """
        try:
            # Double-check: Only guide default agents (global_default or user:xxx)
            # Sub-agents should NOT trigger bootstrap
            agent_config = getattr(agent, "_agent_config", None)
            if agent_config:
                agent_id = getattr(agent_config, "id", "")
                # Skip bootstrap for non-default agents
                if not (agent_id == "global_default" or agent_id.startswith("user:")):
                    logger.debug(
                        "Skipping bootstrap for non-default agent: %s", agent_id,
                    )
                    return None
            
            if not has_pending_bootstrap(self.working_dir):
                return None

            # Only trigger on actual first interaction — skip if there
            # are already assistant messages in memory (i.e., returning user)
            try:
                memory_content = getattr(agent.memory, "content", [])
                has_assistant = any(
                    isinstance(m, (list, tuple))
                    and len(m) >= 1
                    and isinstance(m[0], dict)
                    and m[0].get("role") == "assistant"
                    for m in memory_content
                )
                if has_assistant:
                    return None
            except Exception:
                pass  # if memory inspection fails, proceed

            # Check if we've already sent all prompts — if so, complete
            state_file = self.working_dir / ".bootstrap_state"
            state = {"attempts": 0, "max_attempts": self.max_attempts}
            if state_file.exists():
                try:
                    state = json.loads(
                        state_file.read_text(encoding="utf-8"),
                    )
                except Exception:
                    pass  # corrupt file → reset

            prompts_sent = state.get("attempts", 0)
            max_att = state.get("max_attempts", self.max_attempts)

            # If all prompts have been sent, mark completed
            if prompts_sent >= max_att:
                (self.working_dir / ".bootstrap_completed").write_text(
                    "", encoding="utf-8",
                )
                logger.info(
                    "Bootstrap auto-completed after %d prompts sent", max_att,
                )

        except Exception as e:
            logger.error("Bootstrap hook failed: %s", e, exc_info=True)

        return None
