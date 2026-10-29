# -*- coding: utf-8 -*-
"""智能判断中枢 判断台账（一期）。

对应 tech_docs/智能判断中枢设计方案-定稿v13.md 第 6 章「台账」。
每一次系统内部判断（技能触发兜底判 / 计划闸门 / 意图分类 / 复杂度判级）
都落一行，用于回答三个问题：

1. 判断花了多少钱？（``cost`` + ``tokens``，与 token_usage 台账同域）
2. 判断准不准？（``outcome``：命中后用户是否采纳、是否被推翻）
3. 判断在哪个岗位失效？（``source`` × ``outcome`` 聚合出六岗健康度）

时间用 epoch **float**（``REAL`` 列），与同域的台账表
``resources.py`` / ``token_usage`` 一致 —— 本表是台账，要做时间聚合，
文本时间只能字典序比较，故不采用 M1 域的 ISO 文本约定。

**红线（v13 R4，系统内已有三起字段丢失先例）**：
全字段非空 + 服务端默认值（``server_default``），写入方逐字段显式列举。
"""

from __future__ import annotations

from typing import Optional

from sqlalchemy import Float, Index, Integer, Text, text
from sqlalchemy.orm import Mapped, mapped_column

from ..base import BaseRow


class DecisionEvent(BaseRow):
    """一次系统内部判断的台账行。"""

    __tablename__ = "decision_events"

    # 事件主键（uuid4）
    event_id: Mapped[str] = mapped_column(Text, primary_key=True, nullable=False)

    # 岗位：skill_trigger / plan_gate / intent / complexity / tool_gate
    source: Mapped[str] = mapped_column(
        Text, nullable=False, default="", server_default=text("''")
    )
    # 判级结果：trivial / light / standard / complex（无复杂度维度时为空串）
    complexity: Mapped[str] = mapped_column(
        Text, nullable=False, default="", server_default=text("''")
    )
    # 动作：direct / plan / tool / escalate / none
    action: Mapped[str] = mapped_column(
        Text, nullable=False, default="", server_default=text("''")
    )
    # 判断依据（短语，供人读；写入方截断到 500）
    reason: Mapped[str] = mapped_column(
        Text, nullable=False, default="", server_default=text("''")
    )
    # 命中层：keyword / cache / llm / slot / fallback / breaker_open / disabled
    hit_layer: Mapped[str] = mapped_column(
        Text, nullable=False, default="", server_default=text("''")
    )
    # 使用的判断模型（provider/model 文本，未落槽位时为空串）
    model: Mapped[str] = mapped_column(
        Text, nullable=False, default="", server_default=text("''")
    )
    # 本次判断耗时（毫秒）
    latency_ms: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default=text("0")
    )
    # 本次判断成本（元；无法计价时为 0）
    cost: Mapped[float] = mapped_column(
        Float, nullable=False, default=0.0, server_default=text("0")
    )
    # token 用量（prompt+completion 合计）
    tokens: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default=text("0")
    )

    # 作用域（与记忆域 scope 语义一致）
    user_id: Mapped[str] = mapped_column(
        Text, nullable=False, default="", server_default=text("''")
    )
    agent_id: Mapped[str] = mapped_column(
        Text, nullable=False, default="", server_default=text("''")
    )
    chat_id: Mapped[str] = mapped_column(
        Text, nullable=False, default="", server_default=text("''")
    )

    # 事后结果：pending / accepted / overridden / timeout / error
    outcome: Mapped[str] = mapped_column(
        Text, nullable=False, default="pending", server_default=text("'pending'")
    )

    # epoch 秒（float），与 resources / token_usage 台账一致
    created_at: Mapped[Optional[float]] = mapped_column(
        Float, nullable=False, default=0.0, server_default=text("0")
    )

    __table_args__ = (
        Index("ix_decision_events_source_created", "source", "created_at"),
        Index("ix_decision_events_user_created", "user_id", "created_at"),
        Index("ix_decision_events_chat", "chat_id"),
    )
