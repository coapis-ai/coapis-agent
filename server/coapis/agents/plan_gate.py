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
from typing import Optional, Sequence

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

# 判官提示词。要求模型只回一个词，解析层做宽松匹配。
# ⚠ 必须用 .format(text=...) 注入，因此正文里不能出现裸花括号。
_JUDGE_PROMPT = """判断下面这个任务的复杂度，只回答一个词：simple、medium 或 complex。

标准：
- simple：一句话就能做完（查、看、改一处、单步操作）。
- medium：2~3 个步骤，或需要读文件、写内容、调用工具。
- complex：多步骤串联、跨系统、需要交付物（报告/部署/重构）。

不要解释，不要标点，只输出那一个词。

任务：{text}"""


class ComplexityClassifier:
    """规则判级 + lite judge 的三级复杂度分类器。

    判级标准（与 m1-plan §3 A2.1 对齐）：
      simple  : len<=80 且 单子目标 且 无步骤/分支标记
      complex : len>400 或 子目标数>=3 或 顺序标记种类>=2
      medium  : 其余
    """

    LEVELS = LEVELS

    def __init__(
        self,
        judge_enabled: bool = True,
        judge_timeout: float = 5.0,
        judge_max_tokens: int = 512,
    ):
        self.judge_enabled = judge_enabled
        self.judge_timeout = judge_timeout
        # 推理型模型要先思考后作答：预算太小 = 判官必败。
        self.judge_max_tokens = max(64, int(judge_max_tokens))
        self._judge_cache: dict[str, tuple[str, float]] = {}
        # 台账作用域（user_id / agent_id / chat_id），由接线方注入
        self._ledger_scope: dict[str, str] = {}

    # ------------------------------------------------------------------ #
    # 规则层（同步、确定性，单测只打这一层）
    # ------------------------------------------------------------------ #
    def set_ledger_scope(self, scope: dict) -> None:
        """注入台账作用域（user_id / agent_id / chat_id），供判级入账。"""
        self._ledger_scope = dict(scope or {})

    def _emit_judgment(
        self,
        text: str,
        *,
        complexity: str,
        action: str,
        reason: str,
        hit_layer: str,
        model: str,
        latency_ms: int,
    ) -> None:
        """复杂度判级入账（台账岗位 ``plan_gate``）。

        只在真正调用判级模型时入账：规则层判级零成本且每条消息都跑，
        入账会淹没台账。失败静默 —— 台账不得影响闸门。
        """
        try:
            from ..decision import DecisionResult, get_bus

            get_bus().emit(
                DecisionResult(
                    source="plan_gate",
                    action=action or None,
                    complexity=complexity,
                    reason=reason,
                    hit_layer=hit_layer,
                    model=model,
                    latency_ms=latency_ms,
                ),
                user_id=str(self._ledger_scope.get("user_id", "") or ""),
                agent_id=str(self._ledger_scope.get("agent_id", "") or ""),
                chat_id=str(self._ledger_scope.get("chat_id", "") or ""),
            )
        except Exception:  # pragma: no cover - 台账不得影响主流程
            pass

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
        if level != MEDIUM or not self.judge_enabled:
            return level
        judged = await self._lite_judge(text)
        return judged if judged in LEVELS else level

    async def _lite_judge(self, text: str) -> Optional[str]:
        """判级模型兜底判：命中缓存直接返回；失败返回 None（不阻断）。

        三条硬约束：
        - **判断模型跟随会话激活模型**（v13 D1/D2，零配置）；
        - **台账只记真实调用过判级模型的轮次**，无模型/熔断期不写，
          避免把台账灌成噪音；
        - **熔断 + 超时**双保险，判级模型挂了直接降级为规则层，绝不卡死。
        """
        key = hashlib.md5(text[:2000].encode("utf-8", errors="replace")).hexdigest()
        cached = self._judge_cache.get(key)
        if cached and time.monotonic() - cached[1] < 300:
            return cached[0]

        config = _get_judge_provider_config(
            self._ledger_scope.get("user_id", ""),
            self._ledger_scope.get("agent_id", ""),
        )
        if not config:
            # 无判级模型 → 降级为规则层，不写台账
            return None

        from ..decision.breaker import get_breaker

        breaker = get_breaker()
        if not breaker.allow("plan_gate"):
            # 熔断打开 → 冷却期内直接跳过判级模型，绝不阻塞消息路径
            return None

        started = time.monotonic()
        try:
            import httpx

            async with httpx.AsyncClient(timeout=self.judge_timeout) as client:
                resp = await client.post(
                    f"{config['api_base']}/chat/completions",
                    headers={"Authorization": f"Bearer {config['api_key']}"},
                    json={
                        "model": config["model"],
                        "messages": [{"role": "user", "content": _JUDGE_PROMPT.format(text=text[:2000])}],
                        "max_tokens": self.judge_max_tokens,
                        "temperature": 0.0,
                        "chat_template_kwargs": {"enable_thinking": False},
                    },
                )
                resp.raise_for_status()
                content = resp.json()["choices"][0]["message"]["content"]
            latency = int((time.monotonic() - started) * 1000)
        except Exception as e:
            logger.debug("ComplexityClassifier lite judge failed: %s", e)
            breaker.record_failure("plan_gate")
            self._emit_judgment(
                text,
                complexity="",
                action="",
                reason=f"判级模型调用失败，降级为规则层: {type(e).__name__}",
                hit_layer="error",
                model=config.get("model", ""),
                latency_ms=int((time.monotonic() - started) * 1000),
            )
            return None

        breaker.record_success("plan_gate")
        for lv in LEVELS:
            if lv in content:
                self._judge_cache[key] = (lv, time.monotonic())
                self._emit_judgment(
                    text,
                    complexity=lv,
                    action="",
                    reason=f"判级={lv}",
                    hit_layer="llm",
                    model=config["model"],
                    latency_ms=latency,
                )
                return lv
        return None



def _get_judge_provider_config(
    user_id: str = "",
    agent_id: str = "",
) -> Optional[dict]:
    """读取判级模型配置（与 intent_classifier 同源）。

    判级模型**跟随会话激活模型**（v13 第 15 章 D1/D2：复用 active_model，
    零配置）：用户偏好 → 智能体 active_model → 全局默认 → 第一个可用
    provider 兜底。
    """
    try:
        from coapis.decision.resolver import get_judgment_provider_config
    except ModuleNotFoundError:
        try:
            from decision.resolver import get_judgment_provider_config
        except ImportError:
            get_judgment_provider_config = None

    if get_judgment_provider_config is not None:
        try:
            judged = get_judgment_provider_config(user_id, agent_id)
            if judged and judged.get("api_base") and judged.get("model"):
                return {
                    "api_base": judged["api_base"],
                    "api_key": judged.get("api_key") or "none",
                    "model": judged["model"],
                }
        except Exception as e:
            logger.debug("Judgment slot chain unavailable for lite judge: %s", e)

    try:
        from coapis.providers.provider_manager import ProviderManager
    except ModuleNotFoundError:
        try:
            from providers.provider_manager import ProviderManager
        except ImportError:
            return None
    try:
        pm = ProviderManager.get_instance()
        active = pm.get_active_model()
        if active:
            provider = pm.get_provider(active.provider_id)
            if provider and provider.base_url:
                return {
                    "api_base": provider.base_url.rstrip("/"),
                    "api_key": provider.api_key or "none",
                    "model": active.model,
                }
        for pid, provider in {**pm.builtin_providers, **pm.custom_providers}.items():
            if provider.models and provider.base_url:
                return {
                    "api_base": provider.base_url.rstrip("/"),
                    "api_key": provider.api_key or "none",
                    "model": provider.models[0].id,
                }
    except Exception as e:
        logger.debug("Failed to read provider config for lite judge: %s", e)
    return None
