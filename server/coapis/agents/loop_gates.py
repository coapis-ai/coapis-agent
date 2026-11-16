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
GATE_FAIL_SIG = "fail_sig"       # 同一工具连续同类失败（签名表归因）

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
    GATE_FAIL_SIG,
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
    GATE_FAIL_SIG: "同一工具连续同类失败",
}

# 闸码 → 台账岗位语义（岗位=loop_gate，purpose=闸码）
LEDGER_SOURCE = "loop_gate"

# 台账节流粒度：默认 1 = 每次触发一行，治理页看到的就是真实计数。
# （闸触发天然稀疏：去重拦截、会话量告警、停滞强制都是低频事件。）
# 需要省行时用它，不是靠端点做估算。
_LEDGER_EVERY = max(1, int(os.getenv("COAPIS_LOOP_GATE_LEDGER_EVERY", "1")))
_GATE_LEDGER_ON = os.getenv("COAPIS_LOOP_GATE_LEDGER", "1").strip().lower() not in (
    "0", "false", "off", "no",
)
# 停止句门默认关（会改行为；先影子运行看数据，同 B3 灰度口径）
_STOP_PHRASE_ON = os.getenv("COAPIS_LOOP_GATE_STOP_PHRASE", "0").strip().lower() in (
    "1", "true", "on", "yes",
)
# 单轮调用预算默认 0 = 关（只做观察计数，不拦；>0 才生效）
_ROUND_BUDGET = int(os.getenv("COAPIS_LOOP_GATE_ROUND_BUDGET", "0"))


def ledger_every() -> int:
    """节流入账粒度：每门每 N 次触发写一行（端点据此说明计数口径）。"""
    return max(1, _LEDGER_EVERY)


_TRUE = ("1", "true", "on", "yes")


def _env_flag(name: str, default: bool) -> bool:
    """布尔阈值的 env 读取：未设用默认，设了按真值串判定。"""
    raw = os.getenv(name, "").strip().lower()
    if not raw:
        return bool(default)
    return raw in _TRUE


def _env_int(name: str, default: int) -> int:
    raw = os.getenv(name, "").strip()
    if not raw:
        return default
    try:
        value = int(raw)
    except ValueError:
        return default
    return value if value > 0 else default


def _env_int_zero_ok(name: str, default: int) -> int:
    """允许显式设 0 的整数阈值（0 在这里是合法语义，如"不要冷却"）。"""
    raw = os.getenv(name, "").strip()
    if not raw:
        return default
    try:
        value = int(raw)
    except ValueError:
        return default
    return value if value >= 0 else default


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
    # 失败签名闸（A1）：同一工具连续同类失败达到 N 次 → 提示换路 + 冷却
    fail_gate_enabled: bool = True
    fail_streak: int = 2
    fail_cooldown_s: int = 60
    fail_hint_enabled: bool = True

    @classmethod
    def from_env(cls) -> "GateThresholds":
        """阈值读取：env > 现值。**每次调用都读 env**——模块导入时定值
        会让运行期调参失效，治理页也就看不到当前真实值了。
        env 未设时与现状逐字节一致（默认值 = 原硬编码常量）。
        """
        return cls(
            exact_dedup=_env_int("COAPIS_LOOP_GATE_DEDUP", 2),
            dup_global=_env_int("COAPIS_LOOP_GATE_DUP_GLOBAL", 3),
            empty_streak=_env_int("COAPIS_LOOP_GATE_EMPTY", 2),
            session_warn=_env_int("COAPIS_LOOP_GATE_SESSION_WARN", 10),
            stagnation_similarity=_env_int("COAPIS_LOOP_GATE_STAGNANT", 5),
            stagnation_force_exit=_env_int("COAPIS_LOOP_GATE_FORCE_EXIT", 15),
            round_budget=_env_int("COAPIS_LOOP_GATE_ROUND_BUDGET", _ROUND_BUDGET),
            stop_phrase_enabled=_env_flag(
                "COAPIS_LOOP_GATE_STOP_PHRASE", _STOP_PHRASE_ON,
            ),
            fail_gate_enabled=_env_flag("COAPIS_LOOP_GATE_FAIL", True),
            fail_streak=_env_int("COAPIS_LOOP_GATE_FAIL_STREAK", 2),
            fail_cooldown_s=_env_int_zero_ok("COAPIS_LOOP_GATE_FAIL_COOLDOWN", 60),
            fail_hint_enabled=_env_flag("COAPIS_LOOP_GATE_FAIL_HINT", True),
        )


@dataclass(frozen=True)
class GateVerdict:
    """一次闸触发：闸码 + 白话 + 动作 + 该门累计次数。"""

    gate: str
    label: str
    action: str          # block / hint / force_text_only / finalize / observe
    detail: str = ""
    hits: int = 0        # 该门在本会话的累计触发次数
    # 失败签名码（目前只有 fail_sig 闸会带）。带上它，下游（顾问、治理页）才能
    # 按"哪种失败"归因，而不是只知道"闸响了"。
    code: str = ""

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
    # 失败签名闸：key = "工具名:签名码" → 连续次数 / 冷却截止时间
    _fail_streak: dict[str, int] = field(default_factory=dict)
    _fail_cooldown: dict[str, float] = field(default_factory=dict)

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

    # -- 失败签名闸（A1）-------------------------------------------------
    def observe_failure(self, tool_name: str, output: str) -> GateVerdict | None:
        """工具执行后观察一次输出：签名归因 → 连续同类计数 → 达阈值提示换路。

        三条语义（对齐方案 §1③"连续失败计数 + 冷却 + 触发归零"）：

        * **归零**：这次没失败（成功或认不出形状）→ 该工具**所有**签名连击清零。
          换签名**不**归零：不同签名各算各的、各自达阈值各自提示。这不是偷懒，
          是安全边界——若换签名就清零，模型在同两条坏路之间来回切换就能把连击
          永远压在阈值下，失败闸形同虚设，而那正是最该拦的振荡形状；
        * **冷却**：提示过一次后进冷却，冷却期内只计数不重复提示、不重复入账，
          免得同一条错误把上下文和台账刷屏。冷却同样按 ``工具:签名`` 独立，
          旧签名的冷却**不会**连坐新签名——否则模型换个错误形状就能躲过提示；
        * **提示**：同一工具同一签名连续 ``fail_streak`` 次 → ``hint``，
          文案由 ``failure_signatures.hint_text`` 统一生成。

        返回 ``None`` 表示"不用管"。判定不靠 LLM，纯签名表。
        """
        if not self.thresholds.fail_gate_enabled:
            return None
        try:
            from .utils.failure_signatures import classify_failure
        except Exception:  # pragma: no cover - 观察件不得影响主流程
            return None
        try:
            sig = classify_failure(tool_name, output)
        except Exception:  # pragma: no cover
            return None

        tool = str(tool_name or "")
        if sig is None:
            # 成功（或认不出失败）→ 该工具所有签名连击归零
            for key in [k for k in self._fail_streak if k.startswith(f"{tool}:")]:
                self._fail_streak.pop(key, None)
            return None

        key = f"{tool}:{sig.code}"
        now = time.monotonic()
        streak = int(self._fail_streak.get(key, 0)) + 1
        self._fail_streak[key] = streak

        cooldown = int(self.thresholds.fail_cooldown_s)
        if cooldown > 0 and now < float(self._fail_cooldown.get(key, 0.0)):
            return None  # 冷却中：只累计，不再提示/入账
        if streak < int(self.thresholds.fail_streak):
            return None

        if cooldown > 0:
            self._fail_cooldown[key] = now + cooldown
        from .utils.failure_signatures import hint_text
        return self._hit(
            GATE_FAIL_SIG, "hint",
            detail=hint_text(sig, streak)
            if self.thresholds.fail_hint_enabled else f"{tool}×{sig.code}×{streak}",
            # 把签名码一路带到下游：治理页与顾问都要按"哪种失败"归因，
            # 只知道"闸响了"决定不了该换什么路。
            code=sig.code,
        )

    def failure_streaks(self) -> dict[str, int]:
        """当前连击快照（key=工具:签名码），治理页与单测看这个。"""
        return {k: int(v) for k, v in self._fail_streak.items() if int(v) > 0}

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

    def _hit(self, gate: str, action: str, *, detail: str = "",
             code: str = "") -> GateVerdict:
        hits = int(self._hits.get(gate, 0)) + 1
        self._hits[gate] = hits
        self._unwritten[gate] = int(self._unwritten.get(gate, 0)) + 1
        verdict = GateVerdict(
            gate=gate,
            label=GATE_LABELS.get(gate, gate),
            action=action,
            detail=detail,
            hits=hits,
            code=code,
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
    "ledger_every",
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
