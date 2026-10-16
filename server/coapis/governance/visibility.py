# -*- coding: utf-8 -*-
"""失败签名与停止原因（治理片3：循环与失败可见）。

设计文档 2.4 节「有限制很正常……智能体就是为了解决问题」的落地：限制本身
不是问题，**限制悄悄生效**才是问题。本模块解决两类静默：

1. **失败签名**：工具失败此前只以文本形式写进上下文，模型每轮重新读一遍、
   重新猜一遍，于是"同一个错误反复撞"。本模块把失败归一为
   ``(工具, 失败类别, 指纹)``，同一指纹重复出现时按 ``governance.limits``
   的六档阶梯升级——重复一次照旧重试，重复多次则给出"换路"提示。
2. **停止原因透出**：轮次耗尽、循环守卫拦截、推理重试耗尽、预算触顶……
   这些终止此前对用户完全不可见（``_summarizing`` 只交出一份摘要，读起来
   像"答完了"）。本模块记录终止原因并渲染成一句白话，附在收尾消息上。

与 ``governance.limits`` 的分工：limits 管**规模**限制（多大/多少次），
本模块管**结果**可见（失败成什么样、为什么停）。两者共用同一套阶梯语义。
"""

from __future__ import annotations

import hashlib
import os
import re
from dataclasses import dataclass, field
from enum import Enum
from typing import Optional

from .limits import LadderPlan, Tier

# 治理总开关在片7 统一落地；片3 先自带一个可关的开关，语义与片2 一致：
# 观测类能力默认开启，但必须能一键关闭，且关闭后对话行为完全不变。
_ENV_KEY = "COAPIS_GOVERNANCE_VISIBILITY"


def visibility_enabled() -> bool:
    """Master switch for failure-signature escalation (default on)."""
    raw = (os.environ.get(_ENV_KEY) or "").strip().lower()
    if raw in ("0", "false", "off", "no"):
        return False
    return True

# ---------------------------------------------------------------------------
# 失败类别
# ---------------------------------------------------------------------------


class FailureKind(str, Enum):
    """工具失败的归一类别。

    类别决定"下一步该怎么走"：文件不存在→换路径；权限→要授权；
    体积→分段；依赖缺失→装依赖。不分类时模型只能整段重读错误文本。
    """

    NOT_FOUND = "not_found"  # 文件/接口/资源不存在
    PERMISSION = "permission"  # 权限不足、被守卫拒绝
    AUTH = "auth"  # 未登录、令牌失效、401/403
    TIMEOUT = "timeout"  # 超时
    SIZE = "size"  # 体积/长度超限
    FORMAT = "format"  # 格式不识别、解析失败
    DEPENDENCY = "dependency"  # 依赖缺失、命令不存在
    NETWORK = "network"  # 连接失败、DNS、代理
    RATE_LIMIT = "rate_limit"  # 配额、限流、429
    CANCELLED = "cancelled"  # 用户取消、中断
    UNKNOWN = "unknown"  # 兜底


# 顺序敏感：越具体的规则排前面，先命中先归类。
# 注意：DEPENDENCY 必须排在 NOT_FOUND 之前 —— "command not found" 同时命中
# 两条规则，谁在前决定归类，语义上它是"缺依赖"而不是"缺文件"。
_FAILURE_PATTERNS: tuple[tuple[FailureKind, re.Pattern[str]], ...] = (
    (
        FailureKind.DEPENDENCY,
        re.compile(
            r"command not found|module named? .+ is not installed|"
            r"modulenotfounderror|importerror|no module named|"
            r"not installed|依赖缺失|未安装|未装",
            re.I,
        ),
    ),
    (
        FailureKind.NOT_FOUND,
        re.compile(
            r"no such file|file not found|not found|does not exist|"
            r"cannot find|找不到|不存在|no such (?:route|endpoint)|404",
            re.I,
        ),
    ),
    (
        FailureKind.PERMISSION,
        re.compile(
            r"permission denied|operation not permitted|eacces|"
            r"not authorized to|access denied|权限不足|无权限|被拒绝",
            re.I,
        ),
    ),
    (
        FailureKind.AUTH,
        re.compile(
            r"unauthorized|invalid (?:token|credentials)|token (?:expired|invalid)|"
            r"authentication (?:failed|required)|401|403|未登录|登录已?过期|凭据",
            re.I,
        ),
    ),
    (
        FailureKind.TIMEOUT,
        re.compile(
            r"timed? ?out|deadline exceeded|timeout|超时|响应超时",
            re.I,
        ),
    ),
    (
        FailureKind.SIZE,
        re.compile(
            r"too large|exceeds?(?: the)? (?:maximum|max) (?:size|length|tokens)|"
            r"context length|maximum context|payload too large|file too (?:big|large)|"
            r"体积过大|超出.{0,6}(?:长度|大小|上限)",
            re.I,
        ),
    ),
    (
        FailureKind.FORMAT,
        re.compile(
            r"decode|decodeerror|parse error|syntax error|invalid (?:json|utf-8)|"
            r"unsupported [\w -]*format|unsupported (?:format|file type)|"
            r"unknown format|file format|格式不|解析失败|无法解析",
            re.I,
        ),
    ),
    (
        FailureKind.NETWORK,
        re.compile(
            r"connection (?:refused|reset|error)|connect(ion)? (?:failed|error)|"
            r"name or service not known|temporary failure in name resolution|"
            r"unreachable|dns|proxy|network.*(?:unreachable|error)|"
            r"连接失败|网络不可达|无法连接",
            re.I,
        ),
    ),
    (
        FailureKind.RATE_LIMIT,
        re.compile(
            r"rate ?limit|too many requests|429|quota (?:exceeded|used up)|"
            r"insufficient (?:quota|credit)|配额|限流",
            re.I,
        ),
    ),
    (
        FailureKind.CANCELLED,
        re.compile(
            r"cancelled|canceled|interrupted|keyboardinterrupt|用户取消|已取消|被中断",
            re.I,
        ),
    ),
)

# 白话下一步：类别 → 建议动作。渲染给用户，也写进上下文让模型别再撞同一面墙。
_NEXT_STEP_HINT: dict[FailureKind, str] = {
    FailureKind.NOT_FOUND: "先确认路径/接口是否存在（列目录、查路由），不要重复同一目标",
    FailureKind.PERMISSION: "需要更高权限或用户授权，向用户说明缺什么",
    FailureKind.AUTH: "登录态或令牌失效，请用户重新授权，不要重试",
    FailureKind.TIMEOUT: "换更小范围/分段处理，或告知用户稍后重试",
    FailureKind.SIZE: "改用分段/摘要路径读取，不要整份加载",
    FailureKind.FORMAT: "换解析方式或先转格式，不要重复同一解析",
    FailureKind.DEPENDENCY: "先安装依赖或换用已具备能力的工具",
    FailureKind.NETWORK: "检查地址与网络，必要时请用户确认服务可达",
    FailureKind.RATE_LIMIT: "已达配额/限流，暂停重试并向用户说明",
    FailureKind.CANCELLED: "该步骤被取消，不要自动重放",
    FailureKind.UNKNOWN: "换一种取证方式（换命令、换路径、看日志）",
}

# 工具输出里这些前缀代表"这是失败"，不是"这是内容"。
_FAILURE_PREFIXES: tuple[str, ...] = (
    "error",
    "failed",
    "exception",
    "traceback",
    "错误",
    "失败",
    "异常",
)

_SUCCESS_HINTS: tuple[re.Pattern[str], ...] = (
    re.compile(r"^\s*(?:ok|success|succeed(?:ed)?|done)\b", re.I),
)


def _is_failure_text(text: str) -> bool:
    """Heuristic: does this tool output represent a failure?"""
    stripped = text.strip()
    if not stripped:
        return False
    head = stripped[:64].lower()
    if any(head.startswith(p) for p in _FAILURE_PREFIXES):
        return True
    if "traceback (most recent call last)" in stripped.lower():
        return True
    return False


def _fingerprint(text: str) -> str:
    """Normalize volatile parts (paths, ids, counts) before hashing.

    ``open /tmp/a.md failed`` and ``open /tmp/b.md failed`` must share one
    fingerprint — the failure is the same shape, only the target moved.
    """
    norm = text.strip().lower()
    norm = re.sub(r"[0-9a-f]{8,}", "<id>", norm)
    norm = re.sub(r"\d+", "<n>", norm)
    norm = re.sub(r"[\w./\\-]+\.(?:md|txt|py|json|docx?|xlsx?|pptx?|pdf|csv|log)", "<file>", norm)
    norm = re.sub(r"\s+", " ", norm)
    return hashlib.sha256(norm.encode("utf-8", "ignore")).hexdigest()[:12]


def classify_failure(tool_name: str, text: str) -> FailureKind:
    """Map a tool output to a failure category."""
    for kind, pattern in _FAILURE_PATTERNS:
        if pattern.search(text):
            return kind
    return FailureKind.UNKNOWN


@dataclass(frozen=True)
class FailureSignature:
    """一次工具失败的归一签名。"""

    tool: str
    kind: FailureKind
    fingerprint: str

    def describe(self) -> str:
        return f"{self.tool}／{self.kind.value}／{self.fingerprint}"


@dataclass
class FailureRecord:
    """同一签名累计出现的次数与最近一次原文。"""

    signature: FailureSignature
    count: int = 0
    last_text: str = ""

    @property
    def repeats(self) -> int:
        return self.count


def _tool_output_text(block: object) -> str:
    """Flatten a ``tool_result`` block's output into plain text."""
    if not isinstance(block, dict):
        return str(block or "")
    output = block.get("output")
    if isinstance(output, str):
        return output
    if isinstance(output, list):
        parts: list[str] = []
        for item in output:
            if isinstance(item, dict):
                parts.append(str(item.get("text") or ""))
            else:
                parts.append(str(item))
        return "\n".join(p for p in parts if p)
    return str(output or "")


def signature_of_result(block: object) -> Optional[FailureSignature]:
    """Build a signature from a tool_result block, or None when it succeeded."""
    if not isinstance(block, dict) or block.get("type") != "tool_result":
        return None
    text = _tool_output_text(block)
    if not text:
        return None
    if any(p.match(text) for p in _SUCCESS_HINTS):
        return None
    if not _is_failure_text(text):
        return None
    kind = classify_failure(str(block.get("name") or "tool"), text)
    return FailureSignature(
        tool=str(block.get("name") or "tool"),
        kind=kind,
        fingerprint=_fingerprint(text),
    )


# ---------------------------------------------------------------------------
# 失败台账
# ---------------------------------------------------------------------------


@dataclass
class FailureLedger:
    """Per-run failure ledger: counts repeats and decides when to escalate.

    阶梯语义（与 ``governance.limits`` 同一套）：
    - 第 1 次：不干预（正常重试是合理行为）。
    - 第 2 次：L1 提示——把"同类失败已出现 N 次 + 建议下一步"写进上下文。
    - 第 3 次：L3 提示——明确要求换路。
    - 第 4 次起：L5 语义——建议停止该路径并交回用户。
    """

    records: dict[FailureSignature, FailureRecord] = field(default_factory=dict)

    def record(self, signature: FailureSignature, text: str = "") -> FailureRecord:
        rec = self.records.get(signature)
        if rec is None:
            rec = FailureRecord(signature=signature, count=0)
            self.records[signature] = rec
        rec.count += 1
        rec.last_text = text[:400]
        return rec

    def repeats(self, signature: FailureSignature) -> int:
        rec = self.records.get(signature)
        return rec.count if rec else 0

    def ladder_for(self, signature: FailureSignature) -> Optional[LadderPlan]:
        """Escalation for a repeated failure, or None when it is fresh."""
        if not limits_enabled():
            return None
        repeats = self.repeats(signature)
        if repeats < 2:
            return None
        hint = _NEXT_STEP_HINT.get(signature.kind, _NEXT_STEP_HINT[FailureKind.UNKNOWN])
        reason = (
            f"同类失败已出现 {repeats} 次：{signature.describe()}"
            f"（工具 {signature.tool}，类别 {signature.kind.value}）"
        )
        if repeats == 2:
            return LadderPlan(
                tier=Tier.L1_HEAD_TAIL,
                reason=reason,
                note=f"{reason}。建议：{hint}",
                action="retry_with_hint",
                budget=repeats,
            )
        if repeats == 3:
            return LadderPlan(
                tier=Tier.L3_SUMMARY,
                reason=reason,
                note=f"{reason}。请停止重复同一调用，改为：{hint}",
                action="change_approach",
                budget=repeats,
            )
        return LadderPlan(
            tier=Tier.L5_REFUSE,
            reason=reason,
            note=(
                f"{reason}。该路径已连续 {repeats} 次失败，建议放弃并向用户说明"
                f"缺什么（{hint}）"
            ),
            action="stop_path",
            budget=repeats,
        )

    def render_context_note(self, plan: LadderPlan) -> str:
        """Compact note to append to the tool result so the model sees it.

        以 ``[治理提示]`` 开头（首字符即标记，调用方负责加换行），
        这样任何拼接位置都能被识别为"治理注入"而不是工具原文。
        """
        return f"[治理提示] {plan.note}"

    def summary(self) -> list[FailureRecord]:
        return sorted(self.records.values(), key=lambda r: -r.count)


# ---------------------------------------------------------------------------
# 开关与按智能体台账
# ---------------------------------------------------------------------------

_FAILURE_LEDGER_KEY = "__coapis_failure_ledger__"


def limits_enabled() -> bool:
    """治理干预总开关（默认开）。

    读环境变量 ``COAPIS_GOVERNANCE_ENABLED``（``0/false/no/off`` = 关）。
    取不到配置一律按"开"处理：治理层缺失只降级为不干预，绝不反向崩对话。
    """
    raw = os.getenv("COAPIS_GOVERNANCE_ENABLED", "")
    if raw.strip().lower() in {"0", "false", "no", "off"}:
        return False
    return True


def get_ledger(agent: object) -> FailureLedger:
    """Per-agent failure ledger (created on first use).

    与 ``get_stop_ledger`` 同一挂载方式：台账挂在智能体对象上，随对象生命周期
    存在；取不到就新建，绝不因治理层缺失影响主流程。
    """
    ledger = getattr(agent, _FAILURE_LEDGER_KEY, None)
    if not isinstance(ledger, FailureLedger):
        ledger = FailureLedger()
        try:
            setattr(agent, _FAILURE_LEDGER_KEY, ledger)
        except Exception:  # pragma: no cover - exotic agent objects
            pass
    return ledger


# ---------------------------------------------------------------------------
# 停止原因
# ---------------------------------------------------------------------------


class StopReason(str, Enum):
    """本轮为何结束。终止必须可解释——不能让用户以为"答完了"。"""

    COMPLETED = "completed"  # 正常答完
    MAX_ITERATIONS = "max_iterations"  # 轮次上限耗尽
    LOOP_GUARD = "loop_guard"  # 循环守卫拦截
    REASONING_RETRIES = "reasoning_retries"  # 推理重试耗尽
    FAILURE_STREAK = "failure_streak"  # 同类失败连续触顶
    BUDGET = "budget"  # 预算/配额触顶
    PLAN_GATE = "plan_gate"  # 方案授权域门禁拦下
    ACTION_GATE = "action_gate"  # 动作语义门禁拦下
    MODEL_ERROR = "model_error"  # 模型侧错误
    CANCELLED = "cancelled"  # 用户取消


_STOP_NOTE: dict[StopReason, str] = {
    StopReason.COMPLETED: "",
    StopReason.MAX_ITERATIONS: (
        "本轮达到工具调用轮次上限被中止，以上是中止前的进展，任务尚未完成。"
    ),
    StopReason.LOOP_GUARD: (
        "检测到重复调用同一工具，已中止以避免空转；需要更换思路或补充信息。"
    ),
    StopReason.REASONING_RETRIES: (
        "模型连续多次未能产出有效工具调用或回复，已中止重试。"
    ),
    StopReason.FAILURE_STREAK: (
        "同类失败连续发生，已中止该路径；缺少的条件见上文治理提示。"
    ),
    StopReason.BUDGET: (
        "本轮达到用量预算上限被中止，任务尚未完成。"
    ),
    StopReason.PLAN_GATE: (
        "该动作超出已确认方案的授权范围，已拦下，等待你确认后再执行。"
    ),
    StopReason.ACTION_GATE: (
        "该动作按动作语义分级需要你的授权，已拦下，未执行。"
    ),
    StopReason.MODEL_ERROR: (
        "模型侧返回错误，本轮未能继续；以上是已完成的进展。"
    ),
    StopReason.CANCELLED: (
        "本轮被取消，以上是取消前的进展。"
    ),
}


@dataclass
class StopLedger:
    """Records why a run ended, plus the counters behind it."""

    reason: StopReason = StopReason.COMPLETED
    iterations: int = 0
    notes: list[str] = field(default_factory=list)

    def set_reason(self, reason: StopReason) -> None:
        # 首个非正常原因优先保留：它才是真实终止原因
        if self.reason is StopReason.COMPLETED:
            self.reason = reason

    def add_note(self, note: str) -> None:
        if note and note not in self.notes:
            self.notes.append(note)

    def render(self) -> str:
        """User-visible closing line (empty when the run completed)."""
        head = _STOP_NOTE.get(self.reason, "")
        parts = [head] if head else []
        parts.extend(self.notes)
        if not parts:
            return ""
        return "\n".join(f"· {p}" for p in parts)


_LEDGER_KEY = "__coapis_stop_ledger__"


def get_stop_ledger(agent: object) -> StopLedger:
    """Per-agent stop ledger (created on first use)."""
    ledger = getattr(agent, _LEDGER_KEY, None)
    if not isinstance(ledger, StopLedger):
        ledger = StopLedger()
        try:
            setattr(agent, _LEDGER_KEY, ledger)
        except Exception:  # pragma: no cover - exotic agent objects
            pass
    return ledger


__all__ = [
    "FailureKind",
    "FailureLedger",
    "FailureRecord",
    "FailureSignature",
    "StopLedger",
    "StopReason",
    "classify_failure",
    "get_ledger",
    "get_stop_ledger",
    "limits_enabled",
    "signature_of_result",
]
