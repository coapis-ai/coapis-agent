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

"""Trigger Causality Tracker — links skill triggers to their execution outcomes.

Every skill trigger gets a unique trigger_id that persists through the entire
causal chain: trigger → LLM reasoning → tool execution → result.

This data feeds into SkillEvolutionEngine for effectiveness scoring.
"""

from __future__ import annotations

import json
import logging
import time
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

from coapis.utils.file_lock import safe_append_jsonl

logger = logging.getLogger(__name__)

# ── Module-level singleton ──
_global_tracker: Optional["TriggerTracker"] = None


def get_trigger_tracker() -> "TriggerTracker":
    """Return the global TriggerTracker singleton (created on first call)."""
    global _global_tracker
    if _global_tracker is None:
        _global_tracker = TriggerTracker()
    return _global_tracker


# =========================================================================
# Data Models
# =========================================================================

@dataclass
class TriggerEvent:
    """A skill trigger event — created when on-demand skill is loaded."""
    trigger_id: str = field(default_factory=lambda: uuid.uuid4().hex[:12])
    skill_name: str = ""
    trigger_method: str = ""       # "keyword" | "llm" | "manual"
    matched_keywords: list[str] = field(default_factory=list)
    user_message: str = ""
    user: str = "unknown"
    agent: str = "default"
    session_id: str = ""
    timestamp: float = field(default_factory=time.time)

    def to_dict(self) -> dict:
        return {
            "trigger_id": self.trigger_id,
            "skill_name": self.skill_name,
            "trigger_method": self.trigger_method,
            "matched_keywords": self.matched_keywords,
            "user_message": self.user_message[:200],  # truncate for storage
            "user": self.user,
            "agent": self.agent,
            "session_id": self.session_id,
            "timestamp": self.timestamp,
        }


@dataclass
class TriggerOutcome:
    """Execution outcome linked to a TriggerEvent via trigger_id."""
    trigger_id: str = ""
    skill_name: str = ""
    tools_used: list[str] = field(default_factory=list)
    skill_tool_used: bool = False   # LLM actually used a skill-provided tool
    tool_success: bool = True       # all tool calls succeeded
    duration_ms: float = 0
    user_followed_up: bool = False  # user repeated request in same session
    session_id: str = ""
    user: str = "unknown"
    agent: str = "default"

    def to_dict(self) -> dict:
        return {
            "trigger_id": self.trigger_id,
            "skill_name": self.skill_name,
            "tools_used": self.tools_used,
            "skill_tool_used": self.skill_tool_used,
            "tool_success": self.tool_success,
            "duration_ms": round(self.duration_ms, 1),
            "user_followed_up": self.user_followed_up,
            "session_id": self.session_id,
            "user": self.user,
            "agent": self.agent,
        }


# =========================================================================
# Tracker
# =========================================================================

class TriggerTracker:
    """Manages active trigger events and correlates them with outcomes.

    Usage in react_agent.py:
        1. _load_on_demand_skills() → tracker.create_event(skill, method, keywords, ...)
        2. _acting()                → tracker.start_execution(trigger_id)
        3. _acting() finally        → tracker.end_execution(trigger_id, tools, success, ...)
        4. on_turn_end / session_end → tracker.flush()  (persist to JSONL)
    """

    def __init__(self, log_dir: Path | None = None):
        # Active trigger events keyed by trigger_id
        self._active: dict[str, TriggerEvent] = {}
        # Outcomes collected this session (flushed on session end)
        self._outcomes: list[TriggerOutcome] = []
        # Execution timing
        self._exec_start: dict[str, float] = {}
        # Log directory for trigger_log.jsonl
        self._log_dir = log_dir
        # JSONL file handle cache
        self._log_path: Optional[Path] = None

    def _get_log_path(self) -> Path:
        if self._log_path is None:
            if self._log_dir:
                self._log_dir.mkdir(parents=True, exist_ok=True)
                self._log_path = self._log_dir / "trigger_log.jsonl"
            else:
                # Default: system/skill_evolution/trigger_log.jsonl
                import os
                wd = os.environ.get("COAPIS_WORKING_DIR")
                if wd:
                    base = Path(wd) / "system" / "skill_evolution"
                else:
                    base = Path(__file__).resolve().parent.parent.parent.parent / "system" / "skill_evolution"
                base.mkdir(parents=True, exist_ok=True)
                self._log_path = base / "trigger_log.jsonl"
        return self._log_path

    # ── Event creation ──

    def create_event(
        self,
        *,
        skill_name: str,
        trigger_method: str,
        matched_keywords: list[str],
        user_message: str = "",
        user: str = "unknown",
        agent: str = "default",
        session_id: str = "",
    ) -> str:
        """Create a new trigger event and return its trigger_id.

        Called from _load_on_demand_skills when a skill is triggered.
        """
        event = TriggerEvent(
            skill_name=skill_name,
            trigger_method=trigger_method,
            matched_keywords=matched_keywords,
            user_message=user_message,
            user=user,
            agent=agent,
            session_id=session_id,
        )
        self._active[event.trigger_id] = event

        # Persist trigger event to JSONL
        self._append_log({
            "ts": datetime.now(timezone.utc).isoformat(),
            "event": "skill_trigger",
            **event.to_dict(),
        })

        logger.debug(
            "TriggerTracker: created event %s for skill=%s method=%s keywords=%s",
            event.trigger_id, skill_name, trigger_method, matched_keywords,
        )
        return event.trigger_id

    # ── Execution timing ──

    def start_execution(self, trigger_id: str) -> None:
        """Mark the start of tool execution for a trigger. Called from _acting."""
        self._exec_start[trigger_id] = time.monotonic()

    def end_execution(
        self,
        trigger_id: str,
        *,
        tools_used: list[str],
        skill_tool_used: bool = False,
        tool_success: bool = True,
    ) -> None:
        """Record execution outcome for a trigger. Called from _acting finally block."""
        event = self._active.get(trigger_id)
        if not event:
            return

        start = self._exec_start.pop(trigger_id, time.monotonic())
        duration_ms = (time.monotonic() - start) * 1000

        outcome = TriggerOutcome(
            trigger_id=trigger_id,
            skill_name=event.skill_name,
            tools_used=tools_used,
            skill_tool_used=skill_tool_used,
            tool_success=tool_success,
            duration_ms=duration_ms,
            session_id=event.session_id,
            user=event.user,
            agent=event.agent,
        )
        self._outcomes.append(outcome)

        # Persist trigger outcome to JSONL
        self._append_log({
            "ts": datetime.now(timezone.utc).isoformat(),
            "event": "trigger_outcome",
            **outcome.to_dict(),
        })

        # ── 更新触发词效能追踪 ──
        try:
            from .trigger_effectiveness import get_trigger_effectiveness
            tracker = get_trigger_effectiveness()
            tracker.record_outcome(
                skill_name=event.skill_name,
                matched_keywords=event.matched_keywords,
                tool_success=tool_success,
                user_followed_up=False,  # will be updated in flush if followed up
            )
        except Exception:
            pass

        logger.debug(
            "TriggerTracker: recorded outcome for %s skill=%s tools=%s success=%s",
            trigger_id, event.skill_name, tools_used, tool_success,
        )

    # ── Public API (matching react_agent.py calls) ──

    def record_trigger_event(self, **kwargs) -> str:
        """Alias for create_event — called from react_agent._load_on_demand_skills."""
        return self.create_event(**kwargs)

    def get_active_trigger_ids(self) -> dict[str, str]:
        """Return {skill_name: trigger_id} for all active triggers.

        Called from react_agent._acting to find which triggers to record outcomes for.
        """
        return {evt.skill_name: evt.trigger_id for evt in self._active.values()}

    def record_trigger_outcome(
        self,
        *,
        trigger_id: str,
        tools_used: list[str],
        tool_success: bool = True,
        duration_ms: float = 0,
    ) -> None:
        """Record execution outcome for a trigger — called from react_agent._acting."""
        self.end_execution(
            trigger_id,
            tools_used=tools_used,
            skill_tool_used=True,  # if we're recording outcome, the skill was involved
            tool_success=tool_success,
        )
        # Also record via usage_tracker for consistency
        try:
            from .usage_tracker import record_trigger_outcome as _record_outcome
            event = self._active.get(trigger_id)
            _record_outcome(
                trigger_id=trigger_id,
                skill_name=event.skill_name if event else "unknown",
                tools_used=tools_used,
                skill_tool_used=True,
                tool_success=tool_success,
                duration_ms=duration_ms,
                user=event.user if event else "unknown",
                agent=event.agent if event else "default",
            )
        except Exception:
            pass

    # ── Session lifecycle ──

    def get_active_events(self) -> list[TriggerEvent]:
        """Return all active trigger events (for trajectory injection)."""
        return list(self._active.values())

    def get_session_outcomes(self) -> list[TriggerOutcome]:
        """Return all outcomes collected this session (for trajectory injection)."""
        return self._outcomes.copy()

    def clear_session(self) -> None:
        """Clear active events and outcomes for a new session."""
        self._active.clear()
        self._outcomes.clear()
        self._exec_start.clear()

    def flush(self) -> None:
        """Flush any pending data. Called at session end."""
        # Data is already persisted per-event, this is a no-op for now
        # but provides a hook for future batch optimization
        logger.debug(
            "TriggerTracker: flushed (%d active events, %d outcomes)",
            len(self._active), len(self._outcomes),
        )

    # ── JSONL persistence ──

    def _append_log(self, entry: dict) -> None:
        """Append a single entry to trigger_log.jsonl."""
        try:
            path = self._get_log_path()
            safe_append_jsonl(path, entry)
        except Exception as e:
            logger.warning("TriggerTracker: failed to write log: %s", e)
