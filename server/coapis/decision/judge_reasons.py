# -*- coding: utf-8 -*-
"""决策模型弃权原因码 —— 台账里"为什么没判"的唯一真源（收尾方案 v1 §6.2 · B3）。

为什么要有这个文件：决策模型不给结论的时刻比给结论的多，台账必须说清**为什么**。
此前原因是一句自由文本，写在 gateway 的十七个出口里，各写各的字面量：
"未配置决策模型（决策模型槽位空）"、"熔断中（…）"、"判断超时（2.6s）"……
看板上想按原因分桶，只能对中文句子做 LIKE——一句话改字，分桶就断档；
同一件事（槽位空）在 L0 前置门、_run_llm、后台补判三处措辞还各不相同。

本模块只做两件事：
1. 码表：每个"决策模型没意见"的原因一个稳定码 + 一句人话。码是机读的，
   句子是给人看的，两者绑在一起，句子改了码不变。
2. 装配：``format_reason(code, detail)`` 出 ``[码] 人话`` 形状，
   直接进台账 ``reason`` 列（该列是文本列，没有独立的 payload 列——
   plan §6.2 说的"原因码进 payload 列"在本表结构下落不到，实证：
   ``_LEDGER_COLUMNS`` 里没有 payload，加列要走迁移，属 B3 额外范围）。
   分桶按 ``reason LIKE '[码]%'`` 聚合。

红线：本模块纯函数、无状态、无 IO——它是决策模型各出口的一把尺子，
不是又一个判断层。
"""
from __future__ import annotations

# --- 码表（判官不产出结论的全部原因）--------------------------------
# 命名纪律：码是**原因**，不是岗位、不是层级。与 hit_layer 正交：
# hit_layer 说"结论出自哪一层"，码说"判官为什么没上岗/为什么没结论"。
NO_SLOT = "no_slot"                 # 判官槽位空：压根没配判官
SLOT_MODEL_INCAPABLE = "slot_model_incapable"  # 槽里的模型不具备判官能力（B3 能力闸）
PROVIDER_MISSING = "provider_missing"          # 槽里的提供商不存在（配置坏了）
NOT_CHAT = "not_chat"               # 嵌入/排序/语音/图像模型不能当判官
BREAKER_OPEN = "breaker_open"       # 熔断中：这一岗近期连败
RATE_LIMITED = "rate_limited"       # 上游 429/限流
BUDGET_EXHAUSTED = "budget_exhausted"  # 本轮判断预算用尽
QUOTA_EXHAUSTED = "quota_exhausted"   # 当日判官配额用尽 / 在途判断过多（v20 F6）
RULE_DECIDED = "rule_decided"       # 规则已定论，无需问模型
DISABLED = "disabled"               # 岗位开关/总开关关闭
TIMEOUT_SOFT = "timeout_soft"       # 软阈值到点，主链先走（判官仍在跑）
TIMEOUT_HARD = "timeout_hard"       # 硬阈值到点：这一判判官确实没跑完
TRANSPORT = "transport"             # 传输/调用异常（连不上、报错）
PARSE_FAIL = "parse_fail"           # 模型答了但读不出结论
ABSTAIN = "abstain"                 # 模型弃权（unknown / action=none）
CANCELLED = "cancelled"             # 判断任务被取消
USAGE_MISSING = "usage_missing"     # 真判成功但 usage 取回 0

#: 码 → 人话。台账读侧与看板 tooltip 都用它，不再各抄一份。
REASON_TEXT: dict[str, str] = {
    NO_SLOT: "未配置决策模型（决策模型槽位空）",
    SLOT_MODEL_INCAPABLE: "决策模型不具备判断能力",
    PROVIDER_MISSING: "决策模型提供商不存在",
    NOT_CHAT: "非聊天模型不能当决策模型",
    BREAKER_OPEN: "熔断中",
    RATE_LIMITED: "上游限流",
    BUDGET_EXHAUSTED: "本轮判断预算用尽",
    QUOTA_EXHAUSTED: "当日决策模型配额用尽（在途过多或 token 到顶）",
    RULE_DECIDED: "规则已定论，未问模型",
    DISABLED: "决策模型开关关闭",
    TIMEOUT_SOFT: "主链等到软阈值先走（决策模型仍在后台跑）",
    TIMEOUT_HARD: "判断超时（硬阈值）",
    TRANSPORT: "判断调用失败",
    PARSE_FAIL: "决策模型回复解析不出结论",
    ABSTAIN: "决策模型弃权",
    CANCELLED: "判断任务被取消",
    USAGE_MISSING: "决策模型用时未取到用量",
}

ALL_CODES = frozenset(REASON_TEXT)


def format_reason(code: str, detail: str = "") -> str:
    """装配台账 ``reason`` 列的文本：``[码] 人话（细节）``。

    未知码不抛异常——台账纪律是"行必须写得出"；未知码原样带进码位，
    读侧会看到它，比静默降级成空串好查。整串截到 500（列约定）。
    """
    code = str(code or "").strip()
    text = REASON_TEXT.get(code, "决策模型未给出结论")
    detail = str(detail or "").strip()
    out = f"[{code or 'unknown'}] {text}"
    if detail:
        out = f"{out}（{detail}）"
    return out[:500]


def parse_code(reason: str) -> str:
    """从台账 ``reason`` 文本取回码；非 ``[码]`` 形状返回空串。

    读侧分桶唯一入口：看板统计"决策模型为什么沉默"只认这个函数，
    禁止再对中文句子做字符串匹配。
    """
    raw = str(reason or "")
    if not raw.startswith("["):
        return ""
    end = raw.find("]")
    if end <= 1:
        return ""
    return raw[1:end].strip()


__all__ = [
    "ALL_CODES",
    "ABSTAIN",
    "BREAKER_OPEN",
    "BUDGET_EXHAUSTED",
    "CANCELLED",
    "DISABLED",
    "NOT_CHAT",
    "NO_SLOT",
    "PARSE_FAIL",
    "PROVIDER_MISSING",
    "QUOTA_EXHAUSTED",
    "RATE_LIMITED",
    "REASON_TEXT",
    "RULE_DECIDED",
    "SLOT_MODEL_INCAPABLE",
    "TIMEOUT_HARD",
    "TIMEOUT_SOFT",
    "TRANSPORT",
    "USAGE_MISSING",
    "format_reason",
    "parse_code",
]
