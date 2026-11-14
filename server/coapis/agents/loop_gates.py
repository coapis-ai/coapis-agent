# -*- coding: utf-8 -*-
"""循环闸（loop gates）—— 观察、归因、分桶计数、按门降级。

设计边界（实施方案 v1 §7.1 / §7.4，按真码校正）：

* **尺子只有一把**：重复调用与停滞的判定逻辑在
  ``agents/utils/tool_call_guard.py`` 的 ``ToolCallGuard`` /
  ``ReasoningLoopDetector`` 里（实测 303 行，阈值硬编码 2/2/10/5/15）。
  本模块**不重造判定**，只做三件现成机制没有的事：
  ① 把每次触发归因到稳定的闸码；② 按门分桶计数；③ 按门选择降级动作。
* **只做新增闸**：``tool_guard_mixin.py`` 1498 行明确禁止顺手重构，
  本模块对外只暴露观察接口，接线处每处 ≤10 行。
* **台账零迁移**：``decision_events.source`` 是自由 Text（实测无 CHECK
  约束），新岗位 ``loop_gate`` 直接复用 ``decision.ledger_contract.write_ledger``。
* **计数节流**：闸触发是高频事件，台账按"每门每会话每 N 次一行"写，
  不逐次刷行；分桶计数永远在内存，端点读内存 + 台账读历史。
"""
from __future__ import annotations

import os
import time
from dataclasses import dataclass, field
from typing import Any, Iterable

# ---------------------------------------------------------------------------
# 闸码 SSOT —— 像 judge_reasons 一样：新增闸码必须先在此登记
# ---------------------------------------------------------------------------

GATE_DUPLICATE = "dup"           # 重复调用（同工具同参数精确重复）
GATE_DUP_GLOBAL = "dup_global"   # 跨工具全局重复（参数变形重复）
GATE_EMPTY_STREAK = "empty"      # 空结果连击
GATE_STRATEGY = "strategy"       # 策略阻断/提示（连续调用无有效产出）
GATE_SESSION_VOLUME = "volume"   # 会话调用量过大
GATE_STAGNATION = "stagnant"     # 思考停滞（相似思考刷屏）
GATE_OSCILLATION = "oscillate"   # 思考震荡（来回切换不收敛）
GATE_ROUND_BUDGET = "round"      # 单轮调用预算耗尽
GATE_PLAN_DRIFT = "plan_drift"   # 越出计划范围
GATE_STOP_PHRASE = "stop_phrase"  # 自称完成却继续调写操作

GATE_CODES: tuple[str, ...] = (
    GATE_DUPLICATE,
    GATE_DUP_GLOBAL,
    GATE_EMPTY_STREAK,
    GATE_STRATEGY,
    GATE_SESSION_VOLUME,
    GATE_STAGNATION,
    GATE_OSCILLATION,
    GATE_ROUND_BUDGET,
    GATE_PLAN_DRIFT,
    GATE_STOP_PHRASE,
)

# 闸码 → 白话说明（治理页/日志用；不给用户看行话）
GATE_LABELS: dict[str, str] = {
    GATE_DUPLICATE: "同参数重复调用同一工具",
    GATE_DUP_GLOBAL: "跨工具参数变形重复",
    GATE_EMPTY_STREAK: "工具连续返回空结果",
    GATE_STRATEGY: "连续调用无有效产出（策略阻断）",
    GATE_SESSION_VOLUME: "单次会话工具调用量过大",
    GATE_STAGNATION: "思考停滞（反复同样的想法）",
    GATE_OSCILLATION: "思考震荡（来回切换不收敛）",
    GATE_ROUND_BUDGET: "本轮调用预算已用尽",
    GATE_PLAN_DRIFT: "越出本轮计划范围",
    GATE_STOP_PHRASE: "自称完成却继续动手",
}

# 闸码 → 台账岗位语义（岗位=loop_gate，purpose=闸码）
LEDGER_SOURCE = "loop_gate"

# 台账节流：每门每会话累计 N 次触发才追加一行
_LEDGER_EVERY = int(os.getenv("COAPIS_LOOP_GATE_LEDGER_EVERY", "5"))
_GATE_LEDGER_ON = os.getenv("COAPIS_LOOP_GATE_LEDGER", "1").strip().lower() not in (
    "0", "false", "off", "no",
)
# 停止句门默认关（会改行为；先影子运行看数据，同 B3 灰度口径）
_STOP_PHRASE_ON = os.getenv("COAPIS_LOOP_GATE_STOP_PHRASE", "0").strip().lower() in (
    "1", "true", "on", "yes",
)
# 单轮调用预算默认 0 = 关（只做观察计数，不拦；>0 才生效）
_ROUND_BUDGET = int(os.getenv("COAPIS_LOOP_GATE_ROUND_BUDGET", "0"))


def _env_int(name: str, default: int) -> int:
    raw = os.getenv(name, "").strip()
    if not raw:
        return default
    try:
        value = int(raw)
    except ValueError:
        return default
    return value if value > 0 else default


@dataclass(frozen=True)
class GateThresholds:
    """循环闸阈值（D9：从硬编码常量变成可配，默认值=现值，零行为变化）。"""

    exact_dedup: int = 2
    dup_global: int = 3
    empty_streak: int = 2
    session_warn: int = 10
    stagnation_similarity: int = 5
    stagnation_force_exit: int = 15
    round_budget: int = 0  # 0 = 不拦（只计数）
    stop_phrase_enabled: bool = False

    @classmethod
    def from_env(cls) -> "GateThresholds":
        """阈值读取：env > 现值。env 未设时与现状逐字节一致。"""
        return cls(
            exact_dedup=_env_int("COAPIS_LOOP_GATE_DEDUP", 2),
            dup_global=_env_int("COAPIS_LOOP_GATE_DUP_GLOBAL", 3),
            empty_streak=_env_int("COAPIS_LOOP_GATE_EMPTY", 2),
            session_warn=_env_int("COAPIS_LOOP_GATE_SESSION_WARN", 10),
            stagnation_similarity=_env_int("COAPIS_LOOP_GATE_STAGNANT", 5),
            stagnation_force_exit=_env_int("COAPIS_LOOP_GATE_FORCE_EXIT", 15),
            round_budget=_ROUND_BUDGET,
            stop_phrase_enabled=_STOP_PHRASE_ON,
        )


@dataclass(frozen=True)
class GateVerdict:
    """一次闸触发：闸码 + 白话 + 动作 + 该门累计次数。"""

    gate: str
    label: str
    action: str          # block / hint / force_text_only / finalize / observe
    detail: str = ""
    hits: int = 0        # 该门在本会话的累计触发次数

    @property
    def is_blocking(self) -> bool:
        return self.action in ("block", "force_text_only", "finalize")


# 现成去重文案 → 闸码（实测文案见 tool_call_guard.py:108-163）
_DEDUP_MARKERS: tuple[tuple[str, str, str], ...] = (
    ("[策略阻断]", GATE_STRATEGY, "block"),
    ("[策略提示]", GATE_STRATEGY, "hint"),
    ("[DEDUP-GLOBAL]", GATE_DUP_GLOBAL, "block"),
    ("[DEDUP]", GATE_DUPLICATE, "block"),
    ("[TOOL-GUARD]", GATE_DUPLICATE, "hint"),
    ("[EMPTY-STREAK]", GATE_EMPTY_STREAK, "block"),
    ("[SESSION-VOLUME]", GATE_SESSION_VOLUME, "hint"),
)

# 思考停滞文案 → 闸码（实测见 tool_call_guard.py:273-291）
_REASONING_MARKERS: tuple[tuple[str, str, str], ...] = (
    ("[FORCE-EXIT]", GATE_STAGNATION, "finalize"),
    ("[LOOP-STAGNANT]", GATE_STAGNATION, "force_text_only"),
    ("[LOOP-OSCILLATING]", GATE_OSCILLATION, "force_text_only"),
)

# 完成句模式（停止句门；保守清单，宁漏不误伤）
_STOP_PHRASES: tuple[str, ...] = (
    "已完成", "已经完成", "搞定了", "已搞定", "完成了", "任务完成",
    "全部完成", "已修复", "修复完成", "done", "completed",
)
_WRITE_TOOLS: frozenset[str] = frozenset({
    "execute_shell_command", "write_file", "edit_file", "browser_use",
    "send_file_to_user", "send_file",
})


def attribute_dedup(text: str) -> tuple[str, str]:
    """把现成去重文案归因成 (闸码, 动作)。认不出 → ("", "observe")。纯函数。"""
    body = str(text or "")
    for marker, gate, action in _DEDUP_MARKERS:
        if marker in body:
            return gate, action
    return "", "observe"


def attribute_reasoning(text: str) -> tuple[str, str]:
    """把现成思考环检测文案归因成 (闸码, 动作)。纯函数。"""
    body = str(text or "")
    for marker, gate, action in _REASONING_MARKERS:
        if marker in body:
            return gate, action
    return "", "observe"


def gate_stop_phrase(text: str, tool_name: str) -> bool:
    """停止句门：自称完成、却又要动写操作 → 命中。纯函数，宁漏不误伤。"""
    body = str(text or "").strip().lower()
    if not body:
        return False
    if str(tool_name or "") not in _WRITE_TOOLS:
        return False
    return any(p.lower() in body for p in _STOP_PHRASES)


def gate_round_budget(calls_this_round: int, budget: int) -> bool:
    """单轮调用预算：budget<=0 表示不拦。纯函数。"""
    return int(budget) > 0 and int(calls_this_round) >= int(budget)


def gate_plan_drift(approved_scope: dict | None, tool_name: str,
                    path: str = "") -> bool:
    """越出计划范围（B2 口径：approved_scope={"paths":[..]} 非空=有范围）。

    无范围 → 不判（不新增限制）；有范围且路径越界 → 命中。纯函数。
    """
    scope = approved_scope if isinstance(approved_scope, dict) else None
    if not scope:
        return False
    paths = [str(p) for p in (scope.get("paths") or []) if str(p).strip()]
    if not paths:
        return False
    target = str(path or "").strip()
    if not target:
        return False
    return not any(target.startswith(p) for p in paths)


@dataclass
class LoopGateChain:
    """会话级闸链：分桶计数 + 节流入账。

    不是新闸，是"闸的观察器"——现成判定（ToolCallGuard /
    ReasoningLoopDetector / B2 计划范围门）判定后，由这里归因、计数、
    按门降级、写台账。
    """

    thresholds: GateThresholds = field(default_factory=GateThresholds.from_env)
    session_id: str = ""
    chat_id: str = ""
    user_id: str = ""
    agent_id: str = ""
    ledger_enabled: bool = True

    _hits: dict[str, int] = field(default_factory=dict)
    _unwritten: dict[str, int] = field(default_factory=dict)
    _round_calls: int = 0

    def __post_init__(self) -> None:
        # 构造说关就关；构造说开时，env 总闸仍可关闭。
        if self.ledger_enabled:
            self.ledger_enabled = _GATE_LEDGER_ON

    # -- 观察入口 ---------------------------------------------------------
    def observe_dedup(self, text: str, *, tool_name: str = "") -> GateVerdict | None:
        """记录一次现成去重触发（``_acting`` 里 dedup 返回处）。"""
        gate, action = attribute_dedup(text)
        if not gate:
            return None
        return self._hit(gate, action, detail=str(tool_name or ""))

    def observe_reasoning(self, text: str) -> GateVerdict | None:
        """记录一次现成思考环触发（``_reasoning`` 里拦截处）。"""
        gate, action = attribute_reasoning(text)
        if not gate:
            return None
        return self._hit(gate, action)

    def observe_round(self, tool_name: str = "") -> GateVerdict | None:
        """单轮调用预算：每次工具调用计一次，超预算按门降级。"""
        self._round_calls += 1
        if gate_round_budget(self._round_calls, self.thresholds.round_budget):
            return self._hit(
                GATE_ROUND_BUDGET, "finalize",
                detail=f"本轮已调用 {self._round_calls} 次工具",
            )
        return None

    def observe_plan_drift(self, approved_scope: dict | None,
                           tool_name: str = "", path: str = "") -> GateVerdict | None:
        """越出计划范围（B2 范围门判定后调用；判定逻辑不搬第二套）。"""
        if gate_plan_drift(approved_scope, tool_name, path):
            return self._hit(GATE_PLAN_DRIFT, "block", detail=str(path or tool_name))
        return None

    def observe_stop_phrase(self, text: str, tool_name: str = "") -> GateVerdict | None:
        """停止句门（默认关；开时命中即禁止写操作）。"""
        if not self.thresholds.stop_phrase_enabled:
            return None
        if gate_stop_phrase(text, tool_name):
            return self._hit(GATE_STOP_PHRASE, "force_text_only", detail=str(tool_name))
        return None

    def round_calls(self) -> int:
        return int(self._round_calls)

    def new_round(self) -> None:
        self._round_calls = 0

    # -- 计数与台账 -------------------------------------------------------
    def hits(self) -> dict[str, int]:
        """按门分桶计数（端点读这份；台账读历史行）。"""
        return {code: int(self._hits.get(code, 0)) for code in GATE_CODES}

    def total_hits(self) -> int:
        return sum(int(v) for v in self._hits.values())

    def _hit(self, gate: str, action: str, *, detail: str = "") -> GateVerdict:
        hits = int(self._hits.get(gate, 0)) + 1
        self._hits[gate] = hits
        self._unwritten[gate] = int(self._unwritten.get(gate, 0)) + 1
        verdict = GateVerdict(
            gate=gate,
            label=GATE_LABELS.get(gate, gate),
            action=action,
            detail=detail,
            hits=hits,
        )
        if self._unwritten[gate] >= max(1, _LEDGER_EVERY):
            self._unwritten[gate] = 0
            self._write_ledger(verdict)
        return verdict

    def _write_ledger(self, verdict: GateVerdict) -> None:
        if not self.ledger_enabled:
            return
        try:
            try:
                from decision import ledger_contract as _ledger
            except ImportError:
                from coapis.decision import ledger_contract as _ledger
        except Exception:
            return
        try:
            _ledger.write_ledger(
                source=LEDGER_SOURCE,
                purpose=verdict.gate,
                action=verdict.action,
                hit_layer="rule",
                reason=f"[{verdict.gate}] {verdict.label}"
                       + (f"（{verdict.detail}）" if verdict.detail else ""),
                complexity="",
                user_id=self.user_id,
                agent_id=self.agent_id,
                session_id=self.session_id,
                chat_id=self.chat_id,
                zero_reason_hint="" if verdict.hits else "no_gate_hit",
            )
        except Exception:
            pass  # 台账永不阻断主流程

    def flush(self) -> int:
        """收尾补记：把未满节流阈值的触发写进台账（回合结束调用）。"""
        rows = 0
        for gate, n in list(self._unwritten.items()):
            if n > 0:
                self._unwritten[gate] = 0
                self._write_ledger(
                    GateVerdict(
                        gate=gate,
                        label=GATE_LABELS.get(gate, gate),
                        action="observe",
                        hits=int(self._hits.get(gate, 0)),
                    ),
                )
                rows += 1
        return rows


__all__ = [
    "GATE_CODES",
    "GATE_LABELS",
    "GateThresholds",
    "GateVerdict",
    "LEDGER_SOURCE",
    "LoopGateChain",
    "attribute_dedup",
    "attribute_reasoning",
    "gate_plan_drift",
    "gate_round_budget",
    "gate_stop_phrase",
]
