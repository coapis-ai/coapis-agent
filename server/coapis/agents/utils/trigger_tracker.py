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

"""Trigger Causality Tracker — links skill triggers to their execution outcomes.

Every skill trigger gets a unique trigger_id that persists through the entire
causal chain: trigger → LLM reasoning → tool execution → result.

This data feeds into SkillEvolutionEngine for effectiveness scoring.
"""

from __future__ import annotations

import atexit
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


def get_trigger_tracker() -> TriggerTracker:
    """Return the global TriggerTracker singleton (created on first call)."""
    global _global_tracker
    if _global_tracker is None:
        _global_tracker = TriggerTracker()
        # 兜底收口：正常情况由下一轮 agent 的 ``begin_turn()`` 结算上一轮；
        # 这里保证进程优雅退出时，最后一轮的结局不会烂在内存里。
        try:
            atexit.register(_global_tracker.flush)
        except Exception:  # pragma: no cover - 解释器退出期容错
            logger.debug("TriggerTracker: atexit registration failed", exc_info=True)
    return _global_tracker
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
    # Scene context (optional) — lets ghost/priority events be attributed to
    # the scene that declared them.
    scene_id: str = ""
    scene_name: str = ""
    workspace_id: str = ""
    channel: str = ""
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
            "scene_id": self.scene_id,
            "scene_name": self.scene_name,
            "workspace_id": self.workspace_id,
            "channel": self.channel,
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
    user_followed_up: Optional[bool] = None  # None = 未采集
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
        # Log file path (resolved lazily)
        self._log_dir: Path | None = log_dir
        self._log_path: Path | None = None
        # ── 轮次作用域（2026-11-26 治「闭环账本造假」）──
        # tracker 是进程级单例，而 CoApisAgent 实例每轮新建
        # （react_agent.py:548 注释自陈）。旧实现里 ``_active`` 只增不减：
        # ``create_event`` 只写入，``end_execution`` 只摘 ``_exec_start``，
        # ``clear_session`` 全仓 0 个调用点。于是 ``get_active_trigger_ids()``
        # 会把进程历史上所有 trigger 都带回来，而 ``react_agent._acting``
        # 每次工具调用都给它们各记一遍结局。
        # 实测（dev 数据卷 47 天）：230 条 trigger 被写成 2165 条结局，
        # 平均 9.4 倍、单条最多 140 次；学习层据此把 70 个关键词里
        # 68 个（97.1%）的权重顶到 1.5 上限钉死，等于彻底学不动。
        # 现在：一轮一个作用域，结局先在内存聚合，轮末每个 trigger 只落一行。
        self._turn_seq: int = 0
        self._pending: dict[str, dict] = {}
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
        scene_id: str = "",
        scene_name: str = "",
        workspace_id: str = "",
        channel: str = "",
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
            scene_id=scene_id,
            scene_name=scene_name,
            workspace_id=workspace_id,
            channel=channel,
        )
        self._active[event.trigger_id] = event
        # 登记本轮待结算槽：结局先在这里聚合，轮末由 ``_flush_pending``
        # 每个 trigger 只落一行。旧实现是「每次工具调用 × 每个历史
        # trigger」各写一行，这是 9.4 倍重复落账的直接来源。
        self._pending[event.trigger_id] = {
            "skill_name": event.skill_name,
            "trigger_method": event.trigger_method,
            "matched_keywords": list(event.matched_keywords),
            "session_id": event.session_id,
            "workspace_id": event.workspace_id,
            "channel": event.channel,
            "user": event.user,
            "agent": event.agent,
            "turn_seq": self._turn_seq,
            "tools_used": [],
            "tool_calls": 0,
            "tool_success": True,
            "duration_ms": 0.0,
        }

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
        """Record execution outcome for a trigger. Called from _acting finally block.

        改为汇入本轮待结算槽（不再自行写盘）。旧实现在这里硬编码
        ``skill_tool_used=True`` / ``user_followed_up=False``，且每次工具
        调用都写一行、并直接喂给学习层——这是账本造假的第二个来源。
        保留签名以兼容既有调用点。
        """
        self._exec_start.pop(trigger_id, None)
        self.record_trigger_outcome(
            trigger_id=trigger_id,
            tools_used=tools_used,
            tool_success=tool_success,
        )
    # ── Public API (matching react_agent.py calls) ──

    def settle_turn(self) -> tuple[list[TriggerEvent], list[TriggerOutcome]]:
        """轮末结算：把本轮结局落账，并只返回**本轮**的 trigger 与结局。

        给进化引擎在轮末取数用。旧代码调的是
        ``get_session_trigger_events()`` / ``get_session_trigger_outcomes()``
        ——这两个方法在本类里根本不存在（全仓 0 命中），AttributeError 被
        ``except Exception: pass`` 吞掉，于是进化引擎拿到的永远是空列表。
        而 ``get_session_outcomes()`` 是进程累计值，直接给出去会重复计数，
        所以这里按本次结算的条数切片，只交本轮那一段。
        """
        flushed = self._flush_pending()
        events = list(self._active.values())
        outcomes = self._outcomes[-flushed:] if flushed else []
        return events, outcomes

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
        """记录触发结局（兼容旧接口）——只聚合，不写盘。

        ``react_agent._acting`` 每次工具调用都会调这里，且会对本轮所有
        trigger 各调一次。因此这里必须只做内存聚合，写盘交给
        ``_flush_pending``，否则又会退化成重复落账。

        Args:
            trigger_id: 触发事件 ID
            tools_used: 本轮使用的工具列表
            tool_success: 工具是否成功
            duration_ms: 耗时（毫秒）
        """
        if trigger_id not in self._active:
            return
        slot = self._pending.get(trigger_id)
        if slot is None:
            return
        for name in tools_used:
            if name and name not in slot["tools_used"]:
                slot["tools_used"].append(name)
        if not tool_success:
            slot["tool_success"] = False
        slot["tool_calls"] += 1
        if duration_ms > 0:
            slot["duration_ms"] += duration_ms
    def begin_turn(self) -> int:
        """开一轮：先把上一轮攒的结局落账，再清空本轮作用域。

        为什么挂在 agent ``__init__``：CoApisAgent 实例每轮新建，而
        tracker 是进程级单例——新实例诞生即新一轮开始。这里同时承担
        「轮末收口」，因此不需要额外的轮末钩子；即使上一轮中途抛异常，
        其待结算结局也会在这一轮被写出，不会丢。

        Returns:
            本次结算的 trigger 条数
        """
        flushed = self._flush_pending()
        self._turn_seq += 1
        self._active.clear()
        return flushed

    def _flush_pending(self) -> int:
        """把本轮聚合的结局**每个 trigger 只落一行**，并同步学习层一次。

        这是治「闭环账本造假」的核心：旧实现每次工具调用都写一行，
        实测平均 9.4 倍、单条最多 140 次重复。现在一轮一技能一行，
        学习层的 total / hits / satisfied 才等于真实轮次。
        """
        if not self._pending:
            return 0
        pending = self._pending
        self._pending = {}
        for trigger_id, slot in pending.items():
            tools_used = list(slot["tools_used"])
            # skill_tool_used 语义修正：这里表示「本轮真的动了工具」。
            # 旧实现硬编码 True，恒真、零信息量。台账里没有「该技能自带
            # 哪些工具」这一列，无法判定用的是不是技能自带工具；宁可退化
            # 成可验证的弱信号，也不写恒真的假值。
            skill_tool_used = bool(tools_used)
            outcome = TriggerOutcome(
                trigger_id=trigger_id,
                skill_name=slot["skill_name"],
                skill_tool_used=skill_tool_used,
                tool_success=slot["tool_success"],
                # 用户是否追问/采纳，运行时从未采集。未知就写 None，
                # 不再硬编码 False——旧值 False 在学习层被当成「满意」。
                user_followed_up=None,
                duration_ms=slot["duration_ms"],
                tools_used=tools_used,
                session_id=slot["session_id"],
                user=slot["user"],
                agent=slot["agent"],
            )
            self._outcomes.append(outcome)
            self._append_log(
                {
                    "event": "trigger_outcome",
                    "trigger_id": trigger_id,
                    "skill_name": slot["skill_name"],
                    "trigger_method": slot["trigger_method"],
                    "session_id": slot["session_id"],
                    "workspace_id": slot["workspace_id"],
                    "channel": slot["channel"],
                    "turn_seq": slot["turn_seq"],
                    "tools_used": tools_used,
                    "tool_calls": slot["tool_calls"],
                    "skill_tool_used": skill_tool_used,
                    "tool_success": outcome.tool_success,
                    "user_followed_up": None,
                    "duration_ms": outcome.duration_ms,
                    "user": slot["user"],
                    "agent": slot["agent"],
                    "ts": datetime.now(timezone.utc).isoformat(),
                },
            )
            try:
                from .trigger_effectiveness import get_trigger_effectiveness

                get_trigger_effectiveness().record_outcome(
                    skill_name=slot["skill_name"],
                    matched_keywords=slot["matched_keywords"],
                    tool_success=outcome.tool_success,
                    user_followed_up=None,
                    skill_tool_used=skill_tool_used,
                )
            except Exception:
                logger.warning(
                    "trigger_tracker: effectiveness update failed",
                    exc_info=True,
                )
            # 工具使用账本同样一轮一行。旧实现在每次工具调用里写一行，
            # 和 trigger_log 一样被放大 9.4 倍。
            try:
                from .usage_tracker import (
                    record_trigger_outcome as _usage_record,
                )

                _usage_record(
                    trigger_id=trigger_id,
                    skill_name=slot["skill_name"],
                    tools_used=tools_used,
                    skill_tool_used=skill_tool_used,
                    tool_success=outcome.tool_success,
                    duration_ms=outcome.duration_ms,
                    user=slot["user"],
                    agent=slot["agent"],
                )
            except Exception:
                logger.debug(
                    "trigger_tracker: usage_tracker update failed",
                    exc_info=True,
                )
        return len(pending)


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
        """把本轮尚未结算的结局落账（轮末 / 进程退出时调用）。

        旧实现是彻底的 no-op（注释写着 "no-op for now"），而全仓又没有
        任何 ``clear_session`` 调用点，等于「轮末收口」这一环根本不存在
        ——结局只能在每次工具调用时重复写盘。
        """
        flushed = self._flush_pending()
        logger.debug(
            "TriggerTracker: flushed (%d outcomes this call, %d active, %d total)",
            flushed, len(self._active), len(self._outcomes),
        )
    # ── JSONL persistence ──

    def _append_log(self, entry: dict) -> None:
        """Append a single entry to trigger_log.jsonl."""
        try:
            path = self._get_log_path()
            safe_append_jsonl(path, entry)
        except Exception as e:
            logger.warning("TriggerTracker: failed to write log: %s", e)
