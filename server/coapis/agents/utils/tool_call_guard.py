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

"""Tool call guard — programmatic dedup and rate limiting.

Replaces the prompt-only "反循环铁律" in AGENTS.md with actual
programmatic enforcement. Three layers of protection:

1. Exact dedup: same tool + same params → return cached result
2. Empty-result block: consecutive empty/no-output results → hard block
3. Session stats: track per-tool call counts for diagnostics

Note: reasoning-level loops (same reasoning pattern, different params)
are handled by ReasoningLoopDetector, not here.
"""

from __future__ import annotations

import hashlib
import json
import os
import logging
import threading
from collections import defaultdict
from typing import Any

logger = logging.getLogger(__name__)

# ── Thresholds ──
_EXACT_DEDUP_THRESHOLD = 2    # Same call this many times → inject warning
_EMPTY_RESULT_BLOCK = 2       # Consecutive empty results → hard block
_SESSION_WARN = 10            # Same tool this many times per session → warn


class ToolCallGuard:
    """Per-session tool call guard for dedup and rate limiting.

    Thread-safe: uses a lock for all state mutations.
    Lifecycle: one instance per session (created in CoApisAgent.__init__).
    """

    def __init__(self) -> None:
        self._lock = threading.Lock()
        # (tool_name, params_hash) → cached result string
        self._result_cache: dict[str, str] = {}
        # tool_name → list of params_hash (in call order)
        self._call_history: dict[str, list[str]] = defaultdict(list)
        # tool_name → total call count
        self._call_counts: dict[str, int] = defaultdict(int)
        # (tool_name, params_hash) → number of times check_and_dedup returned cached
        self._dedup_hits: dict[str, int] = defaultdict(int)
        # consecutive empty-result tracking
        self._consecutive_empty: int = 0

    @staticmethod
    def _params_hash(params: dict[str, Any] | None) -> str:
        """Stable hash of tool parameters."""
        try:
            raw = json.dumps(params or {}, sort_keys=True, default=str)[:2048]
        except Exception:
            raw = str(params)[:2048]
        return hashlib.md5(raw.encode()).hexdigest()[:16]

    def check_and_dedup(
        self,
        tool_name: str,
        params: dict[str, Any] | None,
    ) -> str | None:
        """Check if this call should be short-circuited.

        Returns:
            None → proceed with normal tool execution.
            str  → return this cached/hint result directly (skip execution).
        """
        ph = self._params_hash(params)
        call_key = f"{tool_name}:{ph}"

        with self._lock:
            # ── Layer 1: Exact dedup ──
            if call_key in self._result_cache:
                self._dedup_hits[call_key] += 1
                hit_count = self._dedup_hits[call_key]
                if hit_count >= _EXACT_DEDUP_THRESHOLD:
                    cached = self._result_cache[call_key]
                    logger.info(
                        "ToolCallGuard: exact dedup hit for %s "
                        "(hit %d times with same params)",
                        tool_name, hit_count,
                    )
                    return (
                        f"[系统提示] 你已经用完全相同的参数调用过 "
                        f"{tool_name} {hit_count + 1} 次，结果不会变化。"
                        f"请勿重复调用，直接使用已有信息继续。\n\n"
                        f"上次结果（截断）:\n{cached[:800]}"
                    )
                # First re-hit: return cached but don't block
                return self._result_cache[call_key]

            # ── Layer 2: Empty-result hard block ──
            if self._consecutive_empty >= _EMPTY_RESULT_BLOCK:
                logger.warning(
                    "ToolCallGuard: empty-result BLOCK for %s "
                    "(%d consecutive empty results)",
                    tool_name, self._consecutive_empty,
                )
                return (
                    f"[系统阻断] {tool_name} 已连续 {self._consecutive_empty} 次返回空结果，"
                    f"已触发空结果保护。禁止继续调用此工具，请直接基于已有信息给出结论。"
                )

            # ── Layer 4: Session-level count warning (non-blocking) ──
            total = self._call_counts[tool_name]
            if total == _SESSION_WARN:
                logger.info(
                    "ToolCallGuard: session-level warning for %s "
                    "(%d total calls)",
                    tool_name, total,
                )
                # Don't block, just log — the hint will be in the next
                # system prompt rebuild if needed

        return None  # proceed normally

    def record(
        self,
        tool_name: str,
        params: dict[str, Any] | None,
        result_text: str,
    ) -> None:
        """Record a completed tool call result for future dedup.

        Also tracks consecutive empty results for early loop detection.

        Args:
            tool_name: Name of the tool.
            params: Parameters passed to the tool.
            result_text: Text result (will be truncated for cache).
        """
        ph = self._params_hash(params)
        call_key = f"{tool_name}:{ph}"

        with self._lock:
            self._call_counts[tool_name] += 1
            self._call_history[tool_name].append(ph)
            # Cache truncated result (max 2KB)
            if result_text:
                self._result_cache[call_key] = result_text[:2048]

            # Track consecutive empty results
            is_empty = not result_text or not result_text.strip()
            is_no_output = (
                "no output" in result_text.lower()
                if result_text else False
            )
            if is_empty or is_no_output:
                self._consecutive_empty += 1
            else:
                self._consecutive_empty = 0

    def get_stats(self) -> dict[str, int]:
        """Return per-tool call counts for diagnostics."""
        with self._lock:
            return dict(self._call_counts)

    def reset(self) -> None:
        """Reset all state (for testing or new session)."""
        with self._lock:
            self._result_cache.clear()
            self._call_history.clear()
            self._call_counts.clear()
            self._dedup_hits.clear()
            self._consecutive_empty = 0


# ── Reasoning Loop Detector ──
# Detects when the model produces nearly identical reasoning output
# (thinking + tool_use pattern) across consecutive iterations.
# This catches loops that ToolCallGuard misses because the tool calls
# may have different params but the overall reasoning is stuck.

_REASONING_SIMILAR_THRESHOLD = int(os.environ.get("REASONING_SIMILAR_THRESHOLD", "60"))
_REASONING_FORCE_EXIT = int(os.environ.get("REASONING_FORCE_EXIT", "100"))


class ReasoningLoopDetector:
    """Detects reasoning-level loops in the ReAct agent.

    While ToolCallGuard catches duplicate *tool calls*, this detector
    catches the broader pattern where the model produces nearly identical
    reasoning output (same thinking content + same tool_use names) across
    consecutive iterations — a sign the model is stuck.

    Lifecycle: one instance per session (created alongside ToolCallGuard).
    """

    def __init__(self) -> None:
        self._lock = threading.Lock()
        # Hash of the last reasoning output (text + tool_use names)
        self._last_reasoning_hash: str = ""
        self._consecutive_same: int = 0
        # Track the last few reasoning hashes for pattern detection
        self._recent_hashes: list[str] = []
        # Total iterations tracked
        self._total_iterations: int = 0

    @staticmethod
    def _compute_reasoning_hash(reasoning_content: str, tool_names: list[str]) -> str:
        """Compute a stable hash of reasoning output.

        Uses the text content (truncated) combined with sorted tool names
        to create a fingerprint of the reasoning step.
        """
        # Truncate text to first 500 chars to focus on the core reasoning
        text_part = reasoning_content[:500] if reasoning_content else ""
        tools_part = ",".join(sorted(tool_names)) if tool_names else ""
        combined = f"{text_part}|||{tools_part}"
        return hashlib.md5(combined.encode()).hexdigest()[:16]

    def check_and_detect(
        self,
        reasoning_content: str,
        tool_names: list[str],
    ) -> str | None:
        """Check if the current reasoning is stuck in a loop.

        Args:
            reasoning_content: The text/thinking content from _reasoning.
            tool_names: List of tool names from the reasoning output's tool_use blocks.

        Returns:
            None → reasoning looks fresh, proceed normally.
            "hint" → inject a hint to try something different.
            "force_exit" → force text-only mode (tool_choice="none").
        """
        rhash = self._compute_reasoning_hash(reasoning_content, tool_names)

        with self._lock:
            self._total_iterations += 1
            self._recent_hashes.append(rhash)
            # Keep only last 5 hashes
            if len(self._recent_hashes) > 5:
                self._recent_hashes = self._recent_hashes[-5:]

            if rhash == self._last_reasoning_hash:
                self._consecutive_same += 1
            else:
                self._consecutive_same = 0
                self._last_reasoning_hash = rhash

            # ── Check 1: Consecutive identical reasoning ──
            if self._consecutive_same >= _REASONING_FORCE_EXIT:
                logger.warning(
                    "ReasoningLoopDetector: FORCE EXIT — identical reasoning "
                    "for %d consecutive iterations",
                    self._consecutive_same,
                )
                return "force_exit"

            if self._consecutive_same >= _REASONING_SIMILAR_THRESHOLD:
                logger.info(
                    "ReasoningLoopDetector: HINT — identical reasoning "
                    "for %d consecutive iterations",
                    self._consecutive_same,
                )
                return "hint"

            # ── Check 2: Oscillation pattern (A-B-A-B) ──
            recent = self._recent_hashes
            if len(recent) >= 4:
                if (recent[-1] == recent[-3] and recent[-2] == recent[-4]
                        and recent[-1] != recent[-2]):
                    logger.warning(
                        "ReasoningLoopDetector: oscillation detected (A-B-A-B pattern)"
                    )
                    return "force_exit"

        return None

    def reset(self) -> None:
        """Reset all state."""
        with self._lock:
            self._last_reasoning_hash = ""
            self._consecutive_same = 0
            self._recent_hashes.clear()
            self._total_iterations = 0
