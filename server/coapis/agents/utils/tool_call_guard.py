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
programmatic enforcement. Four layers of protection:

1. Exact dedup: same tool + same params → return cached result
2. Consecutive block: same tool 3+ times in a row → hard block
3. Empty-result block: consecutive empty/no-output results → hard block
4. Session stats: track per-tool call counts for diagnostics
"""

from __future__ import annotations

import hashlib
import json
import logging
import threading
from collections import defaultdict
from typing import Any

logger = logging.getLogger(__name__)

# ── Thresholds ──
_EXACT_DEDUP_THRESHOLD = 2    # Same call this many times → inject warning
_CONSECUTIVE_BLOCK = 3        # Same tool this many times in a row → hard block
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
        # last tool_name for consecutive detection
        self._last_tool_name: str = ""
        self._consecutive_count: int = 0
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

            # ── Layer 2: Consecutive same-tool hard block ──
            if tool_name != self._last_tool_name:
                self._consecutive_count = 0
            self._consecutive_count += 1
            self._last_tool_name = tool_name

            if self._consecutive_count >= _CONSECUTIVE_BLOCK:
                logger.warning(
                    "ToolCallGuard: consecutive BLOCK for %s "
                    "(%d consecutive calls)",
                    tool_name, self._consecutive_count,
                )
                return (
                    f"[系统阻断] 你已连续 {self._consecutive_count} 次调用 "
                    f"{tool_name}，已触发循环保护。"
                    f"禁止继续调用此工具，请直接基于已有信息给出结论。"
                )

            # ── Layer 2b: Empty-result hard block ──
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
            self._last_tool_name = ""
            self._consecutive_count = 0
            self._consecutive_empty = 0
