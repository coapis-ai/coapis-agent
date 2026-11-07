"""台账写入契约 —— 判断中枢所有岗位入账的唯一入口（v14 §批次1）。

为什么要有这个文件：此前 5 个写点（gateway._ledger / gateway._degrade /
plan_gate.record_ledger / hub_acceptance 回填 / 计划中的 tool_gate）各写各的，
实测三类脏数据全在这层，不在判断层（v14 根因 A）：

1. 档位脏值：complexity 被写成 "plan_gate"、"select:low,medium" 这类
   非档位字面量 —— 写入口对档位没有校验；
2. 身份漏填：主链 chat_id 传不进来，大半台账行归不了因；
3. 零值无标记：非 L3 行 cost/tokens 恒 0 且无标记，成本对账把
   "设计上为 0"和"记账坏了"混成一团。

本模块只负责**归一与写入**，不做任何判断：档位按 rubric 词表校验，
身份按 scope→ContextVar 兜底，零值按层给语义标记。判断逻辑不变。

红线：write_ledger 永不抛异常、永不阻塞主链——台账坏了可以修，
主链停了是事故。失败只记日志。
"""
from __future__ import annotations

import logging
import threading
import time
from typing import Any, Optional

logger = logging.getLogger(__name__)

# 台账行的合法档位词表：与判则同源（rubric），杜绝岗位自带小词表。
from .rubric import LEVELS as _LEVELS

# 岗位 source 合法集合（写侧枚举，防岗位名漂移）
SOURCES = frozenset({
    "plan_gate", "plan_review", "skill_trigger", "tool_gate", "acceptance",
    "advisor",
})

# 写入语义标记（zero_reason 列）取值：
#   no_llm_cost    —— 非 llm 层/未调用模型，cost=0 是设计使然
#   usage_missing  —— llm 层调用成功但 usage 取回 0，记账侧要查
#   write_failure  —— 行由降级/失败路径写出
#   ""             —— 正常行（cost>0 有记账，contract 不落标记）
ZERO_NO_LLM = "no_llm_cost"
ZERO_USAGE_MISSING = "usage_missing"
ZERO_WRITE_FAILURE = "write_failure"

_TEST_ID_PREFIXES = ("e2e", "console:", "test", "synthetic")

# 进程内轮次计数（chat_id → 轮次）。台账的 turn 以"对话"为单位，
# 进程重启后从 1 重新数——对账看趋势够用，精确轮次以会话状态为准。
_turn_lock = threading.Lock()
_turn_counts: dict[str, int] = {}


def next_turn(chat_id: str) -> int:
    """本轮在该对话内的序号（进程内计数，重启后重计）。"""
    if not chat_id:
        return 0
    with _turn_lock:
        n = _turn_counts.get(chat_id, 0) + 1
        _turn_counts[chat_id] = n
        return n


def normalize_band(value: Any) -> tuple[str, str]:
    """档位归一：只认 rubric 词表。返回 (档位, 被清洗的原值)。

    岗位想写 "plan_gate"/"select:low,medium" 这种非档位字面量，一律清洗
    为空、原值进 dirty_band 留痕——台账里出现的每一个非空 complexity 都
    必须是判则档位之一，预检的档位尺子才有意义（清洗不销毁证据）。
    """
    raw = str(value or "").strip()
    text = raw.lower()
    if text in _LEVELS:
        return text, ""
    return "", (raw[:120] if raw else "")


def detect_origin(chat_id: str, session_id: str) -> str:
    """行来源：test / no_identity / web（v14 §批次5 写侧，v19 P2-1 补身份缺失）。

    v19 P2-1：chat_id 与 session_id 都空时单列 ``no_identity``。实测判官台账里有
    66 行 chat_id/turn_id/user_id 全空——它们既进不了闭环对账、也无法按会话归因，
    却一路混在真判率分母里，于是"真判率"这种数字根本无法复核。宁可承认这批不知道
    是谁的，也不要拿它去算成绩。
    """
    if not str(chat_id or "").strip() and not str(session_id or "").strip():
        return "no_identity"
    for ident in (chat_id, session_id):
        text = str(ident or "").strip().lower()
        if text.startswith(_TEST_ID_PREFIXES):
            return "test"
    return "web"


def resolve_ids(scope: Optional[dict]) -> tuple[str, str, str, str, int]:
    """身份四件套：scope 显式值 → ContextVar → session 兜底，逐层不退让。

    主链的 chat_id 贯通（批次2）后 scope 会带真值；贯通前/渠道侧缺值时
    从 ContextVar 拿，全空才落 session 键——保证同一对话的行至少可聚合。
    """
    scope = scope or {}
    user_id = scope.get("user_id") or ""
    agent_id = scope.get("agent_id") or ""
    session_id = scope.get("session_id") or ""
    chat_id = scope.get("chat_id") or ""
    turn = scope.get("turn")
    try:
        from ..config.session_context import (
            get_current_chat_id,
            get_current_session_id,
            get_current_user_id,
            get_current_agent_id,
        )
        chat_id = chat_id or (get_current_chat_id() or "")
        session_id = session_id or (get_current_session_id() or "")
        user_id = user_id or (get_current_user_id() or "")
        agent_id = agent_id or (get_current_agent_id() or "")
    except Exception:  # noqa: BLE001 - context 取不到时用 scope 原值
        pass
    if not chat_id and session_id:
        chat_id = session_id  # 兜底归集键（v14 §批次2 兜底条款）
    if turn is None:
        turn = next_turn(chat_id)
    try:
        turn = int(turn)
    except (TypeError, ValueError):
        turn = 0
    return user_id, agent_id, session_id, chat_id, turn


def write_ledger(
    *,
    source: str,
    purpose: str,
    action: str = "",
    band: str = "",
    reason: str = "",
    hit_layer: str = "",
    model: str = "",
    latency_ms: int = 0,
    cost: float = 0.0,
    tokens: int = 0,
    input_hash: str = "",
    value: str = "",
    outcome: str = "pending",
    user_id: str = "",
    agent_id: str = "",
    session_id: str = "",
    chat_id: str = "",
    turn: Optional[int] = None,
    zero_reason_hint: str = "",
    scope: Optional[dict] = None,
    hub: Any = None,
) -> bool:
    """台账写入唯一入口。返回是否入账；永不抛异常。

    岗位负责判断出什么（action/band/reason），本函数负责把行写成
    可对账的形状：身份补齐、档位清洗、零值语义标记。
    """
    try:
        uid, aid, sid, cid, tn = resolve_ids(
            {
                "user_id": user_id,
                "agent_id": agent_id,
                "session_id": session_id,
                "chat_id": chat_id,
                "turn": turn,
                **(scope or {}),
            }
        )
        clean_band, dirty = normalize_band(band)
        model = (model or "").strip().lower()
        if not model:
            model = "none" if hit_layer != "llm" else "unknown"
        latency_ms = max(0, int(latency_ms or 0))
        tokens = max(0, int(tokens or 0))
        cost = max(0.0, float(cost or 0.0))

        if cost > 0:
            zero_reason = ""
        elif zero_reason_hint in (ZERO_WRITE_FAILURE, ZERO_USAGE_MISSING):
            zero_reason = zero_reason_hint
        elif hit_layer == "llm":
            # 真判层却没有记账 = 记账侧坏了，不是设计为 0
            zero_reason = ZERO_USAGE_MISSING
        else:
            zero_reason = ZERO_NO_LLM

        # 写侧自检：source 必须是已知岗位（治理枚举，防岗位名漂移）
        if source not in SOURCES:
            logger.warning(
                "ledger_contract: 未知岗位 source=%s（行照写，治理对账要查）",
                source,
            )

        from .bus import get_bus
        from .types import DecisionResult

        # 总线签名：emit(event)——身份已在事件对象上，绝不用位置参数传 source
        # （历史事故：契约层按 emit(source, result) 调用，TypeError 被
        # 兜底吞掉，dev 台账连续多轮 0 行）。
        get_bus().emit(
            DecisionResult(
                source=source,
                hit_layer=hit_layer or "none",
                complexity=clean_band,
                action=str(action or ""),
                reason=str(reason or ""),
                model=model,
                latency_ms=latency_ms,
                cost=cost,
                tokens=tokens,
                user_id=uid,
                agent_id=aid,
                chat_id=cid,
                value=str(value or "")[:256],
                turn=tn,
                input_hash=str(input_hash or ""),
                outcome=str(outcome or "pending")[:16],
                # purpose/session_id 不在 DecisionResult 的字段上（dataclass
                # 严格签名，多传即 TypeError——dev 台账 0 行的事故源头），
                # 只能走 payload 带进台账。
                payload={"purpose": purpose, "session_id": sid, "zero_reason": zero_reason},
            ),
        )
        _write_governance(source, cid, tn, dirty, zero_reason)
        return True
    except Exception:  # noqa: BLE001
        logger.debug("ledger_contract: 台账写入失败 source=%s", source, exc_info=True)
        return False


def _write_governance(
    source: str, chat_id: str, turn: int, dirty: str, zero_reason: str
) -> None:
    """治理列补写（origin/zero_reason/dirty_band）。

    emit 走 DecisionResult.to_row()，不认治理列；这里按 (source, chat_id,
    turn, created_at 窗口) 精准补写刚刚那一行（complexity 清洗值已由
    to_row 写入）。库未跑迁移 0021 时列不存在——整段吞掉，主行已入账，
    治理列缺席不阻断判断。
    """
    try:
        from sqlalchemy import update as _sa_update

        from ..foundation.db import get_session
        from ..foundation.db.models.decision import DecisionEvent

        values = {"origin": detect_origin(chat_id, "")}
        if zero_reason:
            values["zero_reason"] = zero_reason[:32]
        if dirty:
            values["dirty_band"] = dirty
        with get_session() as session:
            session.execute(
                _sa_update(DecisionEvent)
                .where(
                    DecisionEvent.source == source,
                    DecisionEvent.chat_id == chat_id,
                    DecisionEvent.turn == turn,
                    DecisionEvent.created_at >= time.time() - 5,
                )
                .values(**values)
            )
    except Exception:  # noqa: BLE001 - 治理列是加护，不阻断
        logger.debug("ledger_contract: 治理列补写失败 source=%s", source, exc_info=True)


def backfill_outcome(
    *,
    chat_id: str,
    turn: int,
    outcome: str,
    cost: float,
    tokens: int,
    note: str = "",
) -> int:
    """验收回填：把本轮判定行的 outcome 落定。返回更新行数；永不抛异常。

    主匹配键是 (chat_id, turn)。chat_id 贯通（批次2）后新行都有主键；
    贯通前的历史行不追溯回填——台账纪律是"新行必须可对账"，不粉饰旧账。
    """
    try:
        from sqlalchemy import update as _sa_update

        from ..foundation.db import get_session
        from ..foundation.db.models.decision import DecisionEvent

        if not chat_id or not turn:
            return 0
        with get_session() as session:
            result = session.execute(
                _sa_update(DecisionEvent)
                .where(DecisionEvent.chat_id == chat_id, DecisionEvent.turn == turn)
                .values(
                    outcome=str(outcome)[:16],
                    cost=max(0.0, float(cost)),
                    tokens=max(0, int(tokens)),
                    **({"reason": note[:500]} if note else {}),
                )
            )
            return int(result.rowcount or 0)
    except Exception:  # noqa: BLE001
        logger.debug("ledger_contract: outcome 回填失败 chat=%s", str(chat_id)[:24], exc_info=True)
        return 0
