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
    # 注：设计稿里的 confidence / tokens_in / tokens_out **不在这里**（2026-11-01 删）。
    # 它们曾以模型列存在（b7240d9），但既没有配套迁移、也不在写入列清单
    # ``bus._LEDGER_COLUMNS`` 里 —— 于是 dev/生产（alembic 建表，19 列）与测试
    # （create_all 按模型建表，22 列）长成两套 schema：写入走裸 SQL 显式列名
    # 一切正常，而任何走 ORM 实体的读取在真实环境必炸
    # ``no such column: decision_events.confidence``（dev 实测复现）。
    # 判官当前也不产出置信度，留着只会长期摆空值。真要记"判得准不准"，
    # 连同写入链与迁移一起做，模型与库必须同一批落地。

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

    # ---- v14 §4.3 台账补列（迁移 0020）----
    # 同样遵守非空红线：老行读出为 ''/0（未知），不引入可空列。
    # 输入指纹（sha1 前 12 位，**不存原文**）
    input_hash: Mapped[str] = mapped_column(
        Text, nullable=False, default="", server_default=text("''")
    )
    # 判断内容（结论值本身，如 select:pdf / complex / advise:change）
    judgment: Mapped[str] = mapped_column(
        Text, nullable=False, default="", server_default=text("''")
    )
    # 轮次号（单轮判官预算按轮清账，"本轮判官花了几次"按轮聚合）
    turn: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default=text("0")
    )
    # 用户评价：0 无效 / 1 有用 / 2 很有用 / 3 没评价
    rating: Mapped[int] = mapped_column(
        Integer, nullable=False, default=3, server_default=text("3")
    )

    # ---- 治理列（v14 §批次1/§批次5，迁移 0021）----
    # 行来源：web=聊天会话 test=测试/合成 ''=存量未知。预检 KPI 只数 web，
    # 测试行不得掺入生产指标（v14 P7：真判率掺 e2e 合成行虚高）。
    origin: Mapped[str] = mapped_column(
        Text, nullable=False, default="", server_default=text("''")
    )
    # 零值语义：no_llm_cost=设计为0 / usage_missing=该有记账没有 /
    # write_failure=降级路径写的行。无标记且 cost=0 = 记账坏了。
    zero_reason: Mapped[str] = mapped_column(
        Text, nullable=False, default="", server_default=text("''")
    )
    # 被清洗出档位词表的原值留痕（清洗不销毁证据）
    dirty_band: Mapped[str] = mapped_column(
        Text, nullable=False, default="", server_default=text("''")
    )

    __table_args__ = (
        Index("ix_decision_events_source_created", "source", "created_at"),
        Index("ix_decision_events_user_created", "user_id", "created_at"),
        Index("ix_decision_events_chat", "chat_id"),
    )
