# -*- coding: utf-8 -*-
"""审批意图台账（B2 · 方案 v1 §4 验收 5）。

为什么单独一张表：审批队列 ``_pending`` 是**内存态**，裁决取走即消失。
于是"用户到底选了什么、为什么选、超时了多少次"在盘上没有任何一行，
看板只能看见"当前有几张卡"，看不见历史意图 —— 验收口径要求"用户选择
要能回答选了哪种、为什么"，今天答不了。

台账与队列严格分工：

* 队列（内存）= 待办，服务"现在要不要批"；
* 台账（本表）= 事实，服务"批过什么、谁批的、怎么收的场"。

红线：台账是**旁路**。写失败只 debug 日志，绝不把异常抛回审批主链 ——
审批卡住了用户还能点，主链停了是事故。
"""
from __future__ import annotations

from typing import Optional

from sqlalchemy import Float, Index, Integer, Text, text
from sqlalchemy.orm import Mapped, mapped_column

from ..base import BaseRow

#: 裁决字面量（台账尺子）= **用户做了什么动作**。
#:
#: ``""`` 未收场（卡在队列里）；``approved`` / ``denied`` 用户明示；
#: ``timed_out`` 超时即默认拒绝；``system_cancelled`` 系统撤销
#: （会话取消 / 重连清理），不是用户意图，统计时与用户拒绝分开。
#:
#: ⚠️ 与 ``outcome`` 严格分工：本列记**意图**（用户点了批准，就是
#: ``approved``），系统是否采纳记在 ``outcome``。此前两件事挤在一列，
#: 身份校验拒绝的未遂选择只能被记成"拒绝"—— 用户明明点了批准，台账
#: 却说他拒绝，这是对用户行为的歪曲。
VALID_INTENT_DECISIONS = frozenset(
    {"", "approved", "denied", "timed_out", "system_cancelled"}
)

#: 系统采纳结果（"这个意图最后算不算数"）。
#:
#: ``applied`` 采纳收场；``refused:<原因>`` 身份/边界校验拒绝（未遂留痕，
#: 跨用户审批的证据就在这列，不靠日志大海捞针）；``auto`` 系统自动收场
#: （超时、清理）。空串 = 未收场。
VALID_OUTCOME_PREFIXES = frozenset({"applied", "refused", "auto"})

#: 裁决来源（"谁/经哪条通道收的场"）。
#:
#: 身份边界（B2）的落账面：``identity_check`` 拒绝的行照写台账留痕，
#: 跨用户审批未遂才有据可查。
VALID_DECIDE_SOURCES = frozenset(
    {
        "",
        "http",           # /console/approve 等 Web 端点
        "card_callback",  # 企微卡片回调
        "internal",       # 服务内部（超时、清理）
        "agent",          # 代理侧自动决定
        "control",        # /approve 控制命令
        "refused",        # 身份校验拒绝（未遂留痕）
        "admin_override",  # 管理员代批（D7：谁替谁批的，台账直接查）
    }
)


class ApprovalIntent(BaseRow):
    """一次审批请求的完整生命周期（一行到底，不追加多行）。"""

    __tablename__ = "approval_intents"

    request_id: Mapped[str] = mapped_column(Text, primary_key=True)

    # ---- 身份（与 PendingApproval 同行取值，不二次推断）----
    session_id: Mapped[str] = mapped_column(
        Text, nullable=False, default="", server_default=text("''")
    )
    root_session_id: Mapped[str] = mapped_column(
        Text, nullable=False, default="", server_default=text("''")
    )
    user_id: Mapped[str] = mapped_column(
        Text, nullable=False, default="", server_default=text("''")
    )
    agent_id: Mapped[str] = mapped_column(
        Text, nullable=False, default="", server_default=text("''")
    )
    channel: Mapped[str] = mapped_column(
        Text, nullable=False, default="", server_default=text("''")
    )

    # ---- 被审批的对象 ----
    tool_name: Mapped[str] = mapped_column(
        Text, nullable=False, default="", server_default=text("''")
    )
    #: 严重度：与 ``ToolGuardSeverity`` 同一把尺子（low/medium/high/critical），
    #: 台账不另造数值刻度，读侧直接按档位聚合。
    severity: Mapped[str] = mapped_column(
        Text, nullable=False, default="", server_default=text("''")
    )
    findings_count: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default=text("0")
    )
    timeout_seconds: Mapped[float] = mapped_column(
        Float, nullable=False, default=60.0, server_default=text("60")
    )

    # ---- 裁决 ----
    #: 空串 = 仍在队列里等；非空 = 已收场（见 VALID_INTENT_DECISIONS）。
    decision: Mapped[str] = mapped_column(
        Text, nullable=False, default="", server_default=text("''")
    )
    #: 实际做决定的人（用户 id；超时/清理为空）。
    decided_by: Mapped[str] = mapped_column(
        Text, nullable=False, default="", server_default=text("''")
    )
    #: 收场通道（见 VALID_DECIDE_SOURCES）。
    decide_source: Mapped[str] = mapped_column(
        Text, nullable=False, default="", server_default=text("''")
    )
    #: 系统采纳结果：``applied`` / ``refused:<原因>`` / ``auto`` / 空=未收场。
    #: 与 ``decision``（用户意图）分列 —— 用户点了批准而系统拒绝时，
    #: 两列各说各的事，台账不歪曲用户行为。
    outcome: Mapped[str] = mapped_column(
        Text, nullable=False, default="", server_default=text("''")
    )
    #: 为什么这么决定（命中规则/身份拒绝原因等人话，截 500）。
    why: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    # ---- 时间（epoch 浮点，与用户域表同一口径：前端 new Date(ts*1000)）----
    created_at: Mapped[float] = mapped_column(
        Float, nullable=False, default=0.0, server_default=text("0")
    )
    resolved_at: Mapped[Optional[float]] = mapped_column(Float, nullable=True)

    __table_args__ = (
        Index("ix_approval_intents_session", "session_id", "created_at"),
        Index("ix_approval_intents_decision", "decision", "created_at"),
        Index("ix_approval_intents_user", "user_id", "created_at"),
    )


__all__ = [
    "ApprovalIntent",
    "VALID_DECIDE_SOURCES",
    "VALID_INTENT_DECISIONS",
    "VALID_OUTCOME_PREFIXES",
]
