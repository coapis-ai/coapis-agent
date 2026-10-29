# -*- coding: utf-8 -*-
"""判断中枢数据结构（一期）。

设计约束（v13 第 15 章拍板）：

- **D3 指纹不落原文**：只存 sha256 + 长度 + 元数据，**绝不存用户原文**。
- **D6 判断日志进台账**：``DecisionResult.to_row()`` 出行，由 ``bus`` 落
  ``decision_events``（与资源台账同库、同为 fire-and-forget 范式）。
- **D10 判官自审一期不做**：这里没有「判官的判官」。
"""
from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from typing import Any, Literal, Mapping

#: 台账 reason 写入上限（超长截断，避免判断依据把台账撑爆）
REASON_MAX_CHARS = 500

Complexity = Literal["simple", "medium", "complex"]
Action = Literal["direct_answer", "single_tool", "multi_tool", "plan_required"]
Outcome = Literal["pending", "accepted", "overridden", "timeout", "error"]
DecisionSource = Literal[
    "intent",
    "skill_trigger",
    "plan_gate",
    "tool_guard",
    "verify",
    "context",
]


def content_fingerprint(text: str) -> str:
    """内容指纹（sha256 十六进制）。

    D3 红线：**只算指纹，不落原文**。上传去重（D9）与判断台账共用这一把
    指纹，保证「同一份内容」在去重、台账、引用注入三处口径一致。
    """
    data = text.encode("utf-8", errors="replace") if isinstance(text, str) else bytes(text)
    return hashlib.sha256(data).hexdigest()


def file_fingerprint(path: str) -> str | None:
    """按文件内容算指纹；读不到返回 None（调用方自行降级）。"""
    try:
        from pathlib import Path

        p = Path(path)
        if not p.is_file():
            return None
        return hashlib.sha256(p.read_bytes()).hexdigest()
    except Exception:  # pragma: no cover - 文件系统异常不应影响主流程
        return None


@dataclass
class DecisionResult:
    """一次判断的结果，对应台账表 ``decision_events`` 的一行。"""

    source: str
    event_id: str = ""
    complexity: str | None = None
    action: str | None = None
    reason: str = ""
    hit_layer: str = ""
    model: str = ""
    latency_ms: int = 0
    cost: float = 0.0
    tokens: int = 0
    user_id: str = ""
    agent_id: str = ""
    chat_id: str = ""
    outcome: str = "pending"
    created_at: float = 0.0
    payload: Mapping[str, Any] = field(default_factory=dict)

    def to_row(self) -> dict[str, Any]:
        """转成台账行（全字段显式列举，配合全字段非空红线）。"""
        return {
            "event_id": str(self.event_id),
            "source": str(self.source),
            "complexity": str(self.complexity or ""),
            "action": str(self.action or ""),
            "reason": str(self.reason)[:REASON_MAX_CHARS],
            "hit_layer": str(self.hit_layer),
            "model": str(self.model),
            "latency_ms": int(self.latency_ms),
            "cost": float(self.cost),
            "tokens": int(self.tokens),
            "user_id": str(self.user_id),
            "agent_id": str(self.agent_id),
            "chat_id": str(self.chat_id),
            "outcome": str(self.outcome or "pending"),
            "created_at": float(self.created_at),
        }


__all__ = [
    "Complexity",
    "Action",
    "Outcome",
    "DecisionSource",
    "DecisionResult",
    "content_fingerprint",
    "file_fingerprint",
    "REASON_MAX_CHARS",
]
