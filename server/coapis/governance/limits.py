"""限制治理地基：限制单一来源 + 六档降级阶梯。

对应实施方案 片1（治理层归一）。三条硬约束：

1. **单一来源**：运行时限制只从 ``LimitLedger`` 读，值全部来自配置
   （``ContextCompactConfig`` / ``ToolResultPruningConfig`` / ``RunningConfig``）。
   核心代码里不再新增硬编码阈值；已有阈值以 ``source`` 字段登记出处。
2. **六档阶梯**：超限不报错，逐级降级（见 ``Tier``）。
3. **不吞限制**：每一档都产出可见说明（``LadderPlan.note``），
   让用户知道"发生了什么、还剩什么、下一步能做什么"。

治理层是纯计算 + 记账，不碰网络、不碰模型、不碰磁盘，因此可以安全地在
任意调用点使用；调用方拿不到治理层时一律按"未超限"处理，绝不阻断对话。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Optional

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


class GovernanceUnavailable(RuntimeError):
    """治理层不可用（配置缺失/损坏）。

    调用方必须捕获它并按"未超限"继续执行——治理层缺失绝不能中断对话。
    """


# ---------------------------------------------------------------------------
# 限制单一来源
# ---------------------------------------------------------------------------


class LimitKind(str, Enum):
    """受治理的限制类别。

    新增类别时在此登记，同时必须在 ``LimitLedger._build`` 里给出出处，
    避免出现"某处有个阈值但台账里查不到"的漂移。
    """

    CONTEXT_TOKENS = "context_tokens"  # 单轮送进模型的上下文 token
    TOOL_RESULT_BYTES = "tool_result_bytes"  # 单条工具结果写入上下文的字节
    READ_CHARS = "read_chars"  # 单次读文件返回的字符
    ROUNDS = "rounds"  # 单轮工具调用轮次
    PLAN_STEPS = "plan_steps"  # 计划步骤数


@dataclass(frozen=True)
class Limit:
    """一条限制。

    Attributes:
        kind: 限制类别。
        budget: 软预算。超过即进入降级阶梯（不是报错）。
        hard: 硬上限。超过即进入最高档（拒绝 + 人类下一步）。None 表示无硬顶。
        source: 出处（配置字段路径），用于"限制从哪来"可追溯。
        unit: 计量单位，仅用于展示。
    """

    kind: LimitKind
    budget: int
    hard: Optional[int]
    source: str
    unit: str = "units"

    def describe(self) -> str:
        hard = f"，硬顶 {self.hard}" if self.hard is not None else ""
        return f"{self.kind.value}：预算 {self.budget}{hard} {self.unit}（出处 {self.source}）"


@dataclass
class LimitLedger:
    """限制台账：单一来源 + 用量记账。

    用法::

        ledger = LimitLedger.from_config(cfg)
        lim = ledger.limit(LimitKind.TOOL_RESULT_BYTES)
        plan = choose_tier(size, lim)
        ledger.record(LimitKind.TOOL_RESULT_BYTES, len(text))
    """

    limits: dict[LimitKind, Limit] = field(default_factory=dict)
    used: dict[LimitKind, int] = field(default_factory=dict)

    # -- 读取 ---------------------------------------------------------------

    def limit(self, kind: LimitKind) -> Limit:
        try:
            return self.limits[kind]
        except KeyError as exc:  # 台账未登记该类别属于编程错误
            raise GovernanceUnavailable(f"未登记的限制类别：{kind}") from exc

    def budget_of(self, kind: LimitKind, default: int) -> int:
        """取预算；台账缺失时返回 ``default``，不抛异常。

        给"薄接线"场景用：调用方不想引入异常处理时可直接取预算。
        """
        lim = self.limits.get(kind)
        return default if lim is None else lim.budget

    def remaining(self, kind: LimitKind) -> Optional[int]:
        """硬顶剩余；无硬顶返回 None。"""
        lim = self.limits.get(kind)
        if lim is None or lim.hard is None:
            return None
        return max(0, lim.hard - self.used.get(kind, 0))

    def explain(self, kind: LimitKind) -> str:
        lim = self.limits.get(kind)
        if lim is None:
            return f"{kind.value}：未登记"
        return f"{lim.describe()}；已用 {self.used.get(kind, 0)}"

    # -- 记账 ---------------------------------------------------------------

    def record(self, kind: LimitKind, amount: int) -> int:
        """累加用量，返回累计值。"""
        total = self.used.get(kind, 0) + max(0, int(amount))
        self.used[kind] = total
        return total

    def reset(self) -> None:
        self.used.clear()

    # -- 构建 ---------------------------------------------------------------

    @classmethod
    def from_config(
        cls,
        running_config: Any = None,
        context_config: Any = None,
        pruning_config: Any = None,
    ) -> "LimitLedger":
        """从配置构建台账（单一来源）。

        任何字段缺失都跳过该类别，不抛异常——配置层比治理层宽松是常态。
        """
        ledger = cls()

        def add(kind: LimitKind, budget: Any, hard: Any, source: str, unit: str) -> None:
            if not isinstance(budget, int) or budget <= 0:
                return
            ledger.limits[kind] = Limit(
                kind=kind,
                budget=budget,
                hard=hard if isinstance(hard, int) and hard >= budget else None,
                source=source,
                unit=unit,
            )

        if context_config is not None:
            ratio = getattr(context_config, "reserve_ratio", 0.2) or 0.2
            add(
                LimitKind.CONTEXT_TOKENS,
                int(getattr(context_config, "max_input_length", 0) * (1.0 - ratio)),
                getattr(context_config, "max_input_length", None),
                "context_compact.max_input_length×(1-reserve_ratio)",
                "tokens",
            )
            add(
                LimitKind.PLAN_STEPS,
                getattr(context_config, "max_compact_message_bytes", None),
                None,
                "context_compact.max_compact_message_bytes",
                "bytes",
            )

        if pruning_config is not None:
            add(
                LimitKind.TOOL_RESULT_BYTES,
                getattr(pruning_config, "pruning_recent_msg_max_bytes", None),
                None,
                "tool_result_pruning.pruning_recent_msg_max_bytes",
                "bytes",
            )
            add(
                LimitKind.READ_CHARS,
                getattr(pruning_config, "pruning_recent_msg_max_bytes", None),
                None,
                "tool_result_pruning.pruning_recent_msg_max_bytes",
                "chars",
            )

        if running_config is not None:
            add(
                LimitKind.ROUNDS,
                getattr(running_config, "max_iters", None),
                getattr(running_config, "max_iters", None),
                "running.max_iters",
                "轮",
            )

        return ledger


# ---------------------------------------------------------------------------
# 六档降级阶梯
# ---------------------------------------------------------------------------


class Tier(str, Enum):
    """降级阶梯档位（设计文档 2.2 节）。"""

    L0_FULL = "L0"  # 全量
    L1_HEAD_TAIL = "L1"  # 头尾截断
    L2_SEGMENTED = "L2"  # 分段按需
    L3_SUMMARY = "L3"  # 摘要 + 引用
    L4_SPLIT = "L4"  # 分治（拆子任务）
    L5_REFUSE = "L5"  # 拒绝 + 人类下一步


@dataclass(frozen=True)
class LadderPlan:
    """一次降级决策。

    Attributes:
        tier: 落到的档位。
        reason: 为什么（含实测规模与预算）。
        note: 给用户看的白话说明——"发生了什么、还剩什么、下一步"。
        action: 机器可读的下一步动作提示，供调用方分派。
        budget: 本次生效的预算。
    """

    tier: Tier
    reason: str
    note: str
    action: str
    budget: int

    @property
    def is_full(self) -> bool:
        return self.tier is Tier.L0_FULL

    @property
    def is_refusal(self) -> bool:
        return self.tier is Tier.L5_REFUSE


# 阶梯系数：相对预算的倍率，超过即落到对应档
_LADDER_STEPS: tuple[tuple[float, Tier], ...] = (
    (1.0, Tier.L0_FULL),
    (1.0, Tier.L1_HEAD_TAIL),
    (4.0, Tier.L2_SEGMENTED),
    (12.0, Tier.L3_SUMMARY),
    (40.0, Tier.L4_SPLIT),
)


def choose_tier(
    size: int,
    limit: Limit,
    *,
    allow_split: bool = True,
) -> LadderPlan:
    """按规模选档。纯函数，无副作用。

    Args:
        size: 实测规模（字节/字符/token，与 ``limit.unit`` 同单位）。
        limit: 来自台账的限制。
        allow_split: 为 False 时跳过 L4 分治（例如调用方无法派子任务），
            直接落到 L5。

    Returns:
        LadderPlan。任何情况下都返回有效档位，不抛异常。
    """
    budget = max(1, int(limit.budget))
    size = max(0, int(size))
    ratio = size / budget

    if limit.hard is not None and size > limit.hard:
        return LadderPlan(
            tier=Tier.L5_REFUSE,
            reason=f"规模 {size} 超过硬顶 {limit.hard}（预算 {budget}）",
            note=(
                f"这次的内容规模 {size} 已超过硬顶 {limit.hard}，"
                "直接处理会失败。可以：① 只取关键片段；② 拆成多次处理；"
                "③ 让我先给出目录/索引再逐段处理。"
            ),
            action="refuse_with_next_steps",
            budget=budget,
        )

    if ratio <= 1.0:
        return LadderPlan(
            tier=Tier.L0_FULL,
            reason=f"规模 {size} 在预算 {budget} 内",
            note="",
            action="full",
            budget=budget,
        )

    if ratio <= 4.0:
        return LadderPlan(
            tier=Tier.L1_HEAD_TAIL,
            reason=f"规模 {size} 超预算 {budget} 约 {ratio:.1f} 倍",
            note=f"内容超出单次预算约 {ratio:.1f} 倍，已保留头尾关键部分并标注省略规模。",
            action="truncate_head_tail",
            budget=budget,
        )

    if ratio <= 12.0:
        return LadderPlan(
            tier=Tier.L2_SEGMENTED,
            reason=f"规模 {size} 超预算 {budget} 约 {ratio:.1f} 倍",
            note=(
                f"内容超出单次预算约 {ratio:.1f} 倍，整读会失真。"
                "已改为分段按需读取：先看目录/索引，再按行号范围逐段取。"
            ),
            action="read_segmented",
            budget=budget,
        )

    if ratio <= 40.0:
        return LadderPlan(
            tier=Tier.L3_SUMMARY,
            reason=f"规模 {size} 超预算 {budget} 约 {ratio:.1f} 倍",
            note=(
                f"内容超出单次预算约 {ratio:.1f} 倍。"
                "已改为「摘要 + 原文引用」：给出结构化摘要，细节按位置引用，需要时再取原文。"
            ),
            action="summarize_with_citations",
            budget=budget,
        )

    if not allow_split:
        return LadderPlan(
            tier=Tier.L5_REFUSE,
            reason=f"规模 {size} 超预算 {budget} 约 {ratio:.1f} 倍，且当前调用点无法分治",
            note=(
                f"内容超出单次预算约 {ratio:.1f} 倍，当前路径无法分片处理。"
                "可以：① 指定要处理的行号范围；② 指定要回答的具体问题；"
                "③ 把文件按章节拆分后再交给我。"
            ),
            action="refuse_with_next_steps",
            budget=budget,
        )

    return LadderPlan(
        tier=Tier.L4_SPLIT,
        reason=f"规模 {size} 超预算 {budget} 约 {ratio:.1f} 倍",
        note=(
            f"内容超出单次预算约 {ratio:.1f} 倍。"
            "已改为分治：拆成若干子任务分别处理，最后汇总。"
        ),
        action="split_into_subtasks",
        budget=budget,
    )


# ---------------------------------------------------------------------------
# 截断（接入现成函数）
# ---------------------------------------------------------------------------


def truncate_head_tail(text: str, budget: int) -> str:
    """头尾保留式截断（阶梯 L1）。

    接入社区版现成实现 ``coapis.agents.utils.tool_message_utils._truncate_text``
    ——该函数此前零调用，本函数是它的治理层入口；它本身就是「头 + 尾保留、
    中间替换为省略标记」的实现，治理层不重复造轮子。

    Args:
        text: 原文。
        budget: 保留预算（字符数）。

    Returns:
        截断后的文本；未超预算时原样返回。
    """
    if not text:
        return text
    budget = max(1, int(budget))
    if len(text) <= budget:
        return text
    # 延迟导入：避免治理层被广泛引用时把工具层拉进依赖图
    from ..agents.utils.tool_message_utils import _truncate_text

    return _truncate_text(text, budget)


# ---------------------------------------------------------------------------
# 便捷入口
# ---------------------------------------------------------------------------


_LEDGER_CACHE: dict[tuple[int, int], LimitLedger] = {}


def ledger_for_agent(
    running_config: Any = None,
    context_config: Any = None,
    pruning_config: Any = None,
) -> LimitLedger:
    """构建（并缓存）台账。

    以配置对象身份缓存，配置换了自然重建；不做全局单例，避免测试串味。
    """
    key = (id(running_config), id(context_config), id(pruning_config))
    ledger = _LEDGER_CACHE.get(key)
    if ledger is None:
        ledger = LimitLedger.from_config(
            running_config=running_config,
            context_config=context_config,
            pruning_config=pruning_config,
        )
        _LEDGER_CACHE[key] = ledger
    return ledger
