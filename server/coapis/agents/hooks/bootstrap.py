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
BOOTSTRAP_PROMPTS_ZH = [
    "\n\n对了，怎么称呼您比较合适？",
    "\n\n对了，您希望我平时用什么样的风格跟您交流？",
    "\n\n有什么我可以帮您定制的吗？比如称呼或者交流风格。",
]

BOOTSTRAP_PROMPTS_EN = [
    "\n\nBy the way, what should I call you?",
    "\n\nBy the way, what communication style do you prefer?",
    "\n\nIs there anything I can customize for you? Like how to address you or my tone.",
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
