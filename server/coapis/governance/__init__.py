"""限制治理层（治理地基）。

设计出处：docs/03-技术方案/智能体限制治理与全面解决方案_2026-10-14.md
实施出处：docs/03-技术方案/限制治理与文档长上下文_实施方案_20260729.md 片1

本包只做两件事，刻意保持薄：

1. **限制单一来源**（``limits.LimitLedger``）
   所有运行时限制（上下文 token、工具结果字节、读取字符、轮次）都从配置一处
   读出、一处记账、一处解释。核心代码不再各自硬编码阈值。

2. **六档降级阶梯**（``limits.Tier`` / ``limits.choose_tier``）
   超限时不直接报错，而是逐级降级：
   L0 全量 → L1 头尾截断 → L2 分段按需 → L3 摘要+引用 → L4 分治 → L5 拒绝+人类下一步

治理层**不吞掉限制**，只把"撞墙"变成"可见的降级 + 可执行的下一步"。
任何调用方拿不到治理层时都必须安全退化，绝不因为治理层缺失而中断对话。
"""

from .limits import (
    GovernanceUnavailable,
    Limit,
    LimitKind,
    LimitLedger,
    LadderPlan,
    Tier,
    choose_tier,
    ledger_for_agent,
    truncate_head_tail,
)

__all__ = [
    "GovernanceUnavailable",
    "Limit",
    "LimitKind",
    "LimitLedger",
    "LadderPlan",
    "Tier",
    "choose_tier",
    "ledger_for_agent",
    "truncate_head_tail",
]
