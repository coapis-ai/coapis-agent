# -*- coding: utf-8 -*-
"""PlanGate: 复杂度判级 + 计划门禁（M1 推理执行核心，分册 m1-plan §3）。

D1（W1 首日）交付：ComplexityClassifier
  - 规则层（同步、确定性）：长度 / 多步子句 / 分支信号 → simple|medium|complex
  - lite judge（异步、可选）：仅对规则层判为 medium 的边界样本做一次轻量 LLM
    复核；5s 超时、温度 0、结果缓存；任何失败一律回退规则层结论。

后续日程（D2/D3）在本文件追加：Plan/Step dataclass、planner_v1 提示词加载、
PlanGate.pre_reasoning_hook。react_agent.py 接线在 D3 完成（≤60 行总预算）。
"""

from __future__ import annotations

import hashlib
import json
import logging
import re
import time
from typing import Any, ClassVar, Optional, Sequence

from .utils.thinking_budget import complexity_to_effort

logger = logging.getLogger(__name__)

SIMPLE = "simple"
MEDIUM = "medium"
COMPLEX = "complex"
LEVELS = (SIMPLE, MEDIUM, COMPLEX)

# 简单任务长度上限（字符）；超过 80 字不再可能判 simple
_SIMPLE_MAX_LEN = 80
# 超长直接判 complex
_COMPLEX_MIN_LEN = 400
# 逗号切分后，片段达到该长度才算一个独立子目标
_COMMA_SEG_MIN_CHARS = 8

# 顺序步骤标记（多步信号）：出现 ≥2 种不同标记 → complex
_SEQ_MARKER_RE = re.compile(
    r"第[一二三四五六七八九十\d]+步|首先|其次|然后|接着|随后|之后|最后|接下来|"
    r"下一步|先(?![前后生面])|再(?![次见])|\bthen\b|after that",
    re.IGNORECASE,
)
# 分支/兜底标记（条件分支信号）：出现即抬升底线到 medium
_BRANCH_MARKER_RE = re.compile(
    r"如果|假如|要是|否则|不然|替代|备选|兜底|fallback", re.IGNORECASE
)
# 连动/流水信号：前一子句的输出被后一句消费（查→整理→写入 这类管道）
_CONSEC_MARKER_RE = re.compile(
    r"把结果|将其|据此|基于其|所得|输出后|完成后|得到的|整理|统计|汇总|"
    r"举例|举一个|发给|发送给|写入|总结|归纳",
    re.IGNORECASE,
)
_COMMA_SPLIT_RE = re.compile(r"[，,]")
_COLON_SPLIT_RE = re.compile(r"[：:]")

# 判官提示词。v14 §4.4④：一次判级同时给出思考开支档位，
# 判档与思考开支必须是**同一个结论**（消灭双头决策）。
# ⚠ 必须用 .format(text=...) 注入，因此正文里不能出现裸花括号。
_JUDGE_PROMPT = """判断下面这个任务的复杂度，并给出该给它多少思考开支。

只输出一个 JSON 对象，不要解释、不要代码块标记：
{{"level": "simple 或 medium 或 complex", "reasoning_effort": "minimal 或 low 或 medium 或 high"}}

level 标准：
- simple：一句话就能做完（查、看、改一处、单步操作）。
- medium：2~3 个步骤，或需要读文件、写内容、调用工具。
- complex：多步骤串联、跨系统、需要交付物（报告/部署/重构）。

reasoning_effort 标准（默认不思考，越贵越要给到位）：
- minimal：不思考也答得对（查、看、单步操作）。
- low：照标准流程做即可（读文件、写内容、调一个工具）。
- medium：需要先规划步骤（多工具协作、有前后依赖）。
- high：需要多轮规划与自我检查（跨系统、长链、交付物）。

任务：{text}"""

# effort 词表（v14 §4.4④）。与档位词表同等严格：不认识即整次作废。
EFFORTS = ("minimal", "low", "medium", "high")

# 判档结论里记录的 effort 缓存（类级共享：判档与思考开支共用一个结论）
_EFFORT_TTL_S = 300.0


def _get_judge_provider_config(
    user_id: str | None,
    agent_id: str | None,
) -> dict | None:
    """取判官模型配置，返回 ``{api_base, api_key, model}`` 或 None。

    v14：解析链统一在 ``coapis.decision.resolver``（会话激活模型优先），
    这里只是一层薄委托，供判级调用点使用。

    取不到就返回 None，调用方必须保留自己的规则结论——严禁抓"第一个
    可用模型"兜底：把嵌入模型当判官就是这么发生的（v14 §4.4③）。
    """
    from coapis.decision.resolver import get_judgment_provider_config

    return get_judgment_provider_config(user_id, agent_id)


def _parse_level_and_effort(raw: str) -> tuple[str, str]:
    """复核输出 → (档位, 思考开支档)。

    D9：档位词表解析失败即判非法、整次作废——这里抛 ValueError，由网关
    按降级阶梯回退规则层，不做重试、不做宽松兜底。
    """
    text = (raw or "").strip()
    start, end = text.find("{"), text.rfind("}")
    if start >= 0 and end > start:
        try:
            data = json.loads(text[start : end + 1])
        except json.JSONDecodeError as exc:
            raise ValueError(f"复核输出 JSON 解析失败: {exc}") from exc
        if not isinstance(data, dict):
            raise ValueError("复核输出 JSON 不是对象")
        level = str(data.get("level") or data.get("complexity") or "")
        effort = str(data.get("reasoning_effort") or data.get("effort") or "")
    else:
        # 模型没守 JSON 约定：词表里能唯一命中就收，否则整次作废
        hits = [lv for lv in LEVELS if lv in text.lower()]
        if len(hits) != 1:
            raise ValueError(f"复核输出里没有唯一档位词: {text[:80]!r}")
        level = hits[0]
        effort = ""
    level = level.strip().lower()
    if level not in LEVELS:
        raise ValueError(f"复核输出的档位词不在词表里: {level[:40]!r}")
    effort = effort.strip().lower()
    if effort not in EFFORTS:
        # effort 缺失/不认识 → 整次判级作废（D9），回退规则层
        raise ValueError(f"复核输出的思考档不在词表里: {effort[:40]!r}")
    return level, effort


class ComplexityClassifier:
    """规则判级 + lite judge 的三级复杂度分类器。

    判级标准（与 m1-plan §3 A2.1 对齐）：
      simple  : len<=80 且 单子目标 且 无步骤/分支标记
      complex : len>400 或 子目标数>=3 或 顺序标记种类>=2
      medium  : 其余
    """

    LEVELS = LEVELS
    EFFORTS = EFFORTS

    # 判档结论里的思考开支档（§4.4④：判档与思考开支必须是同一个结论）。
    # 类级共享——判档在 plan_gate 里跑，思考开支在 react_agent 里消费。
    _effort_cache: ClassVar[dict[str, tuple[str, float]]] = {}

    # ------------------------------------------------------------------ #
    # 判档结论 → 思考开支（§4.4④）
    # ------------------------------------------------------------------ #
    @classmethod
    def remember_effort(cls, text: str, effort: str) -> None:
        """记录本次判档结论里的思考开支档。"""
        key = (text or "").strip()[:200]
        if not key:
            return
        if effort not in EFFORTS:
            cls._effort_cache.pop(key, None)
            return
        now = time.time()
        cls._effort_cache[key] = (effort, now)
        cls._effort_cache = {
            k: v for k, v in cls._effort_cache.items() if now - v[1] <= _EFFORT_TTL_S
        }

    @classmethod
    def pop_effort(cls, text: str) -> Optional[str]:
        """取本次判档的思考开支档；无结论返回 None（调用方按规则层降级）。"""
        key = (text or "").strip()[:200]
        hit = cls._effort_cache.get(key)
        if hit is None:
            return None
        if time.time() - hit[1] > _EFFORT_TTL_S:
            cls._effort_cache.pop(key, None)
            return None
        return hit[0]

    # ------------------------------------------------------------------ #
    # 规则层（同步、确定性，单测只打这一层）
    # ------------------------------------------------------------------ #
    def __init__(
        self,
        judge_enabled: bool = True,
        judge_timeout: float = 5.0,
        judge_max_tokens: int = 512,
    ) -> None:
        """兼容既有调用点的签名（react_agent 等以带参方式构造）。

        三个参数在 v14 之后都不再控制行为，这里显式收下并写明原因：

        - ``judge_enabled``：v14 §4.4① 取消了判档总开关——判断恒走网关，
          降级是网关的职责，调用方无权单方关掉判断。
        - ``judge_timeout`` / ``judge_max_tokens``：预算归中枢统一配置
          （``DecisionHubConfig``）管理；单点覆盖会让轮内预算、熔断计数和
          台账口径互相矛盾，因此不接受逐调用预算。

        三个值都保存为公开属性：不驱动行为，只用于核对调用点传进来的确实
        是中枢配置（接线测试锁这一点）。

        此前这里没有 ``__init__``：带参构造抛 TypeError 被调用点的 ``except``
        静默吞掉，判档器恒为 None，判档接线整条链断掉（骨架恒不武装）。
        """
        self.judge_enabled = judge_enabled
        self.judge_timeout = judge_timeout
        self.judge_max_tokens = judge_max_tokens
        self._ledger_scope: dict = {}

    def set_ledger_scope(self, scope: dict) -> None:
        """注入台账作用域（user_id / agent_id / chat_id），供判级入账。"""
        self._ledger_scope = dict(scope or {})

    def record_ledger(
        self,
        level: str,
        action: str,
        detail: str = "",
        source: str = "plan_gate",
    ) -> None:
        """规则判级也要入账（§4.5①）：台账得知道这一轮判了什么档、思考开没开。

        §4.5③：思考开支写进 ``action``（``thinking:effort``），台账才能还原现场。
        ``source`` 用岗位名（plan_gate/query_analysis/…），``hit_layer`` 才分层。

        台账故障绝不影响判级——判断是旁路能力，主链优先。
        """
        try:
            from coapis.decision import DecisionResult, get_bus

            scope = self._ledger_scope
            effort = complexity_to_effort(level)
            act = (action or f"规则判级为{level}")[:48]
            get_bus().emit(
                DecisionResult(
                    source=source,
                    complexity=level,
                    action=f"{act}; thinking:{effort}",
                    reason=(detail or "")[:512],
                    hit_layer="rule",
                    value=level,
                    user_id=scope.get("user_id", "") or "",
                    agent_id=scope.get("agent_id", "") or "",
                    chat_id=scope.get("chat_id", "") or "",
                    turn=int(scope.get("turn", 0) or 0),
                ),
            )
        except Exception:  # noqa: BLE001 - 台账故障不影响判级
            logger.debug("[plan-gate] 规则判级入账异常（忽略）", exc_info=True)

    def classify(self, text: str, tools_available: Optional[Sequence[str]] = None) -> str:
        """规则层判级。tools_available 预留（"需≥3类工具"信号暂由子目标数近似）。"""
        t = (text or "").strip()
        if not t:
            return SIMPLE
        n = len(t)
        seq_kinds = len(set(_SEQ_MARKER_RE.findall(t)))
        has_branch = bool(_BRANCH_MARKER_RE.search(t))
        goals = self._count_goals(t)
        if n > _COMPLEX_MIN_LEN or goals >= 3 or seq_kinds >= 2:
            return COMPLEX
        if n <= _SIMPLE_MAX_LEN and goals == 1 and seq_kinds == 0 and not has_branch:
            return SIMPLE
        return MEDIUM

    def _count_goals(self, t: str) -> int:
        """估算独立子目标数。

        判定顺序：
          1. 步骤标记：按步骤标记切分出 ≥2 个非空片段 → 取片段数（强信号）；
          2. 逗号枚举：只看第一个冒号前的文本（冒号后多为参数而非子目标），
             计长度≥8的逗号片段；≥3 个封顶记 3；
          3. 连动信号：后半句消费前半句产出（整理/统计/写入…）→ 至少 2；
          4. 否则 1。
        """
        parts = [p for p in _SEQ_MARKER_RE.split(t) if p.strip()]
        if len(parts) >= 2:
            return len(parts)
        head = _COLON_SPLIT_RE.split(t)[0]
        segs = [s for s in _COMMA_SPLIT_RE.split(head) if len(s.strip()) >= _COMMA_SEG_MIN_CHARS]
        if len(segs) >= 3:
            return 3
        if _CONSEC_MARKER_RE.search(t):
            return 2
        return 1

    # ------------------------------------------------------------------ #
    # lite judge（异步，仅复核 medium 边界样本）
    # ------------------------------------------------------------------ #
    async def classify_smart(self, text: str, tools_available: Optional[Sequence[str]] = None) -> str:
        """规则层 + lite judge。规则层非 medium 时零成本直通。"""
        level = self.classify(text, tools_available)
        if level != MEDIUM:
            # 直通样本的 thinking 来自规则映射（同一把尺子），入账含 thinking（§4.5）
            effort = complexity_to_effort(level)
            self.remember_effort(text, effort)
            # 零次判断不入账：直通没有任何判断发生，写台账等于伪造判断记录
            return level
        judged = await self._lite_judge(text)
        return judged if judged in LEVELS else level

    def set_skills_dir(self, skills_dir: Any) -> None:
        """告诉判档员去哪找**判则技能**（工作区 skills 目录）。

        判则可以按智能体/用户定制：工作区里名字含 ``判则``/``rubric`` 的
        技能会自动叠加进判档 prompt 并优先。没设过就不叠加——内置判则兜底。
        """
        self._skills_dir = str(skills_dir) if skills_dir else None

    def _judge_system(self) -> str:
        """判档岗位的**系统提示词** = 判则全文 + 取值约束（v14 §4.5）。

        判则只有一处定义（``coapis/decision/rubric.py``），工作区里名字含
        ``判则``/``rubric`` 的技能会自动叠加进来并优先。过去这里是空串——
        判则不进 prompt，判官等于在按"没人知道的尺子"判，台账里的
        judgment 回溯不到标准，"判得准不准"根本无从核对。
        """
        try:
            from coapis.decision import JSON_ONLY, rubric_for, scan_skill_rubrics

            skills_dir = getattr(self, "_skills_dir", None)
            skills = scan_skill_rubrics(skills_dir) if skills_dir else []
            return (
                rubric_for("level", skills)
                + "\n\n取值约束：level 只能是 simple/medium/complex；"
                "effort 只能是 off/light/full；confidence 取 0.0~1.0。\n"
                + JSON_ONLY
            )
        except Exception:  # pragma: no cover - 判则装载失败不该炸判断
            return ""

    async def _lite_judge(self, text: str) -> Optional[str]:
        """规则拿不准时的那一次复核，走判断网关（v14 §4.4②）。

        网关负责模型解析（只认会话激活模型链，没有"取第一个模型"兜底）、缓存、
        共用熔断、轮内预算、超时、台账。这里只提供提示词与解析器。网关降级
        返回 ``None``，由 ``classify_smart`` 回退规则层结论——判断失败不该
        打断主链，也不该让台账只剩成功样本。

        一次判级同时产出档位与思考开支（§4.4④），思考档写进台账 action。
        """
        from coapis.decision import get_judge_gateway

        scope = {
            "user_id": self._ledger_scope.get("user_id", ""),
            "agent_id": self._ledger_scope.get("agent_id", ""),
            "chat_id": self._ledger_scope.get("chat_id", ""),
            "turn": self._ledger_scope.get("turn", 0),
        }
        reply = await get_judge_gateway().judge(
            purpose="plan_gate",
            system=self._judge_system(),
            user=_JUDGE_PROMPT.format(text=text[:2000]),
            parse=_parse_level_and_effort,
            describe=lambda pair: f"复核为{pair[0]}; thinking:{pair[1]}",
            scope=scope,
            rule_fallback=lambda: (self.classify(text), complexity_to_effort(self.classify(text))),
        )
        if isinstance(reply.value, tuple) and len(reply.value) == 2:
            level, effort = reply.value
            self.remember_effort(text, effort)
            return level if level in LEVELS else None
        return None


