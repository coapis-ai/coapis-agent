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

v2: Injects guidance as an independent system message instead of
mutating the user's message.  Tracks attempts via ``.bootstrap_state``
and auto-completes after ``max_attempts`` (default 3).
"""
import json
import logging
from pathlib import Path
from typing import Any

from agentscope.message import Msg

from ..prompt import (
    _BOOTSTRAP_GUIDANCE_TAG,
    build_bootstrap_guidance_v2,
)
from ..utils import has_pending_bootstrap

logger = logging.getLogger(__name__)

_DEFAULT_MAX_ATTEMPTS = 3


class BootstrapHook:
    """Hook for soft bootstrap guidance on first user interactions.

    Unlike v1 which prepends guidance into the user message (destroying
    the original input), v2:
    * keeps the user message intact
    * injects a separate ``system`` message into agent memory
    * tracks attempts in ``.bootstrap_state`` (JSON)
    * auto-stops after *max_attempts* non-cooperative rounds
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
        """Pre-reasoning hook: inject bootstrap guidance system message.

        Returns None (does not modify kwargs).
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
                pass  # if memory inspection fails, proceed with bootstrap

            state_file = self.working_dir / ".bootstrap_state"
            state = {"attempts": 0, "max_attempts": self.max_attempts}
            if state_file.exists():
                try:
                    state = json.loads(
                        state_file.read_text(encoding="utf-8"),
                    )
                except Exception:
                    pass  # corrupt file → reset

            current_attempt = state.get("attempts", 0) + 1
            max_att = state.get("max_attempts", self.max_attempts)

            # If we've already exhausted attempts, mark completed and stop
            if current_attempt > max_att:
                (self.working_dir / ".bootstrap_completed").write_text(
                    "", encoding="utf-8",
                )
                logger.info(
                    "Bootstrap auto-completed after %d attempts", max_att,
                )
                return None

            # Persist updated state
            state["attempts"] = current_attempt
            state["max_attempts"] = max_att
            state_file.write_text(
                json.dumps(state, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )

            guidance = build_bootstrap_guidance_v2(
                language=self.language,
                attempt=current_attempt,
                max_attempts=max_att,
            )

            logger.info(
                "Bootstrap guidance injected (attempt %d/%d, lang=%s)",
                current_attempt, max_att, self.language,
            )

            # Inject as independent system message into agent memory.
            # This runs in pre_reasoning, so the user message has already
            # been added to memory.  We append the guidance AFTER it.
            guidance_msg = Msg(
                name="system",
                role="system",
                content=guidance,
            )
            await agent.memory.add(guidance_msg)

        except Exception as e:
            logger.error("Bootstrap hook failed: %s", e, exc_info=True)

        return None
