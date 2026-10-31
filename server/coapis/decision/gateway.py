# -*- coding: utf-8 -*-
"""判断中枢唯一 LLM 出口（v14 §4.1 / §5 B1+B2）。

为什么要有这个文件：判官此前有两条平行的 LLM 通路（plan_gate._call_llm
走裸 httpx、intent_classifier._call_llm 也走裸 httpx），两条都绕过
CoApis 的 provider 层，于是拿不到 get_effective_generate_kwargs 里的
参数、拿不到流式消毒、拿不到 usage；再叠加"槽位空就取
provider.models[0]"的兜底，判官在生产被静默指派给 ollama 上的
qwen3-embedding:0.6b（嵌入模型不能对话），9/9 全超时。

本模块是唯一的出口，规矩写死在代码里：

1. 模型解析只走 decision/resolver.py（其内层是 resolve_chat_model_slot
   唯一权威入口：会话激活 → 全局激活 → 用户/全局默认 → 平台默认）。
2. 硬类型校验：infer_model_type 必须是 chat，非 chat 直接降级并在台账
   写明原因——绝不"取第一个模型"。
3. 参数走 provider.get_effective_generate_kwargs（provider 级 +
   模型级），网关只追加白名单键（max_tokens / stream / enable_thinking），
   再消毒。
4. 调用走 provider 层的 compat 子类（OpenAIChatModelCompat），消毒与
   兼容在链路上。
5. 健壮性阶梯 L0→L4，任何一层给出结论立即终止，绝不重复调用。
6. 失败计数进熔断；不重试；硬超时。
7. 台账记 action/cost/tokens，不存提示词与结论原文。
"""
from __future__ import annotations

import asyncio
import hashlib
import inspect
import logging
import time
from collections import OrderedDict
from dataclasses import dataclass, replace
from typing import Any, Callable, Dict, List, Optional, Tuple

from ..providers.model_type import infer_model_type
from ..providers.provider_manager import ProviderManager
from .breaker import get_breaker
from .bus import get_bus
from .cache import get_cached_judgment, make_cache_key, put_cached_judgment
from .config import DecisionHubConfig, get_hub_config
from .resolver import get_judgment_provider_config
from .types import DecisionResult

logger = logging.getLogger(__name__)

# 岗位标识复用 config.POSTS 既有词表，不另造名字：
#   判档 -> plan_gate   技能触发 -> skill_trigger   意图 -> intent
#   事中改道 -> tool_guard   验收回灌 -> verify
PURPOSE_PLAN_GATE = "plan_gate"
PURPOSE_SKILL_TRIGGER = "skill_trigger"
PURPOSE_INTENT = "intent"
PURPOSE_ADVISOR = "tool_guard"
PURPOSE_ACCEPTANCE = "verify"

# 台账 hit_layer 词表（v14 §4.1 阶梯各层出口）
LAYER_LLM = "llm"               # L1 判官模型（显式配置）
LAYER_LLM_SESSION = "llm_session"  # L2 会话激活模型
LAYER_CACHE = "cache"           # 缓存命中
LAYER_INFLIGHT = "inflight"     # 同题在途合并
LAYER_RULE = "rule"             # 规则兜底
LAYER_ABSTAIN = "abstain"       # L4 弃权：unknown / action=none
LAYER_ERROR = "error"           # L3 失败：超时/传输/解析/非聊天模型
LAYER_DISABLED = "disabled"     # L0 前置门：总开关/岗位开关
LAYER_BREAKER = "breaker_open"  # L0 前置门：熔断
LAYER_BUDGET = "budget_cap"     # L0 前置门：每轮预算
LAYER_NO_MODEL = "no_model"     # 无可用模型（配置缺失）
# L3 失败细分（台账要能看出"怎么失败的"，一个 error 词不够用）
LAYER_NOT_CHAT = "not_chat"     # 选中了嵌入/排序/语音/图像模型
LAYER_TIMEOUT = "timeout"       # 超时
LAYER_TRANSPORT = "transport"   # 传输/调用异常
LAYER_PARSE_FAIL = "parse_fail"  # 返回了但解析不出结论

_MAX_TURN_KEYS = 200


def _text_of(response: Any) -> str:
    """取回复正文。思考块（ThinkingBlock）不算正文——台账不存原文。"""
    blocks = getattr(response, "content", None) or []
    parts: List[str] = []
    for block in blocks:
        if isinstance(block, dict):
            btype = block.get("type")
            text = block.get("text")
        else:
            btype = getattr(block, "type", None)
            text = getattr(block, "text", None)
        if btype == "text" and text:
            parts.append(str(text))
    return "".join(parts)


def _is_stream(res: Any) -> bool:
    return hasattr(res, "__aiter__")


@dataclass
class JudgeReply:
    """一次判断的结果。

    ``value`` 是调用方 ``parse`` 出来的结论；降级时是规则兜底值——
    调用方只管用 ``value``，不必关心是哪一层给的。
    """

    ok: bool = False
    value: Any = None
    text: str = ""
    source: str = "rule"
    hit_layer: str = LAYER_RULE
    reason: str = ""
    model: Optional[str] = None
    provider_id: Optional[str] = None
    latency_ms: int = 0
    input_tokens: int = 0
    output_tokens: int = 0
    cost: float = 0.0

    @property
    def from_llm(self) -> bool:
        return self.source == "llm"


# =====================================================================
# 小工具
# =====================================================================


def _usage_of(obj: Any) -> tuple[int, int]:
    """从模型响应里取 ``(输入 token, 输出 token)``，取不到给 0。

    各家返回形状不一：``usage`` 可能是 dict，也可能是带属性的对象。
    拿不到就记 0——台账少两个 token 不致命，崩了才致命。
    """
    data: Any = getattr(obj, "usage", None) if obj is not None else None
    if data is None and isinstance(obj, dict):
        data = obj.get("usage", obj)
    if data is None:
        return (0, 0)
    if isinstance(data, dict):
        return (
            int(data.get("input_tokens", 0) or 0),
            int(data.get("output_tokens", 0) or 0),
        )
    return (
        int(getattr(data, "input_tokens", 0) or 0),
        int(getattr(data, "output_tokens", 0) or 0),
    )


def _cost_of(model_id: str, tin: int, tout: int) -> float:
    """按单价表算这次判断花了多少钱；算不出给 0。"""
    if not model_id or (tin <= 0 and tout <= 0):
        return 0.0
    try:
        from ..user_system.tokens import get_model_pricing

        price = get_model_pricing(model_id)
        return (
            float(price.get("input", 0)) * tin / 1_000_000
            + float(price.get("output", 0)) * tout / 1_000_000
        )
    except Exception:
        return 0.0


# =====================================================================
# 网关主体
# =====================================================================


# 三处判断共用一个熔断键（v14 §4.3①）：任一判断连续失败就三处一起降级，
# 免得三份失败计数各攒各的、每次都重试每次都超时。
BREAKER_KEY = "judge-model"

class JudgeGateway:
    """判断环节统一网关（v14 §4.1）。

    进程内单例，线程安全只到"单事件循环"粒度（与决策中枢其余部件一致）。
    """

    def __init__(self) -> None:
        # 同问句在飞的判断：key -> Task（单飞，第二个人等同一个结果）
        self._inflight: dict[str, asyncio.Task] = {}
        # 单轮 LLM 判断计数：(user, agent, chat, turn) -> 次数
        self._turn_calls: dict[tuple[str, str, str, int], int] = {}

    # ---------------- 参数构造 ----------------

    @staticmethod
    def _thinking_kwargs(provider: Any, flag: bool) -> dict[str, Any]:
        """按端点类型给出"思考开关"参数；端点不认的一律不发。

        三家三种写法（v14 §4.2）：

        * DashScope compatible-mode → ``enable_thinking``；
        * Ollama → ``chat_template_kwargs.thinking``；
        * 其它 OpenAI 兼容端点 → 不认识这个参数，发了会被净化器丢掉，
          干脆不发，别拿未知参数去赌人家的校验。
        """
        ptype = str(getattr(provider, "provider_type", "") or "")
        base = str(getattr(provider, "base_url", "") or "")
        if ptype == "ollama" or ":11434" in base:
            return {"chat_template_kwargs": {"thinking": bool(flag)}}
        if "dashscope" in base:
            return {"enable_thinking": bool(flag)}
        if not base and ptype == "openai":
            # 本地/托管端点：类型声明就是 OpenAI 兼容，可以发。
            return {"enable_thinking": bool(flag)}
        return {}

    @staticmethod
    def _sanitize_kwargs(raw: Any) -> dict[str, Any]:
        """净化器：丢掉 None 和空容器，其余原样透传。

        提供商里存着用户填的生成参数，常见 ``{"top_k": None}`` 这种
        占位值——直接发给 OpenAI 兼容端点就是 400（provider_manager.py
        里 1617 行的注释讲的就是这件事）。
        """
        out: dict[str, Any] = {}
        for key, value in dict(raw or {}).items():
            if value is None:
                continue
            if isinstance(value, (dict, list, set, tuple, str)) and len(value) == 0:
                continue
            out[str(key)] = value
        return out

    def _build_kwargs(
        self, provider: Any, model_id: str, cfg: DecisionHubConfig
    ) -> dict[str, Any]:
        """判断调用的最终参数：提供商参数 → 净化 → 封顶 → 思考开关。"""
        try:
            raw = provider.get_effective_generate_kwargs(model_id) or {}
        except Exception:
            raw = {}
        kwargs = self._sanitize_kwargs(raw)
        kwargs["max_tokens"] = int(cfg.llm_max_tokens)
        kwargs["stream"] = True
        flag = bool(getattr(cfg, "judge_thinking_enabled", False))
        kwargs.update(self._thinking_kwargs(provider, flag))
        return kwargs

    @staticmethod
    def _model_type(provider: Any, model_id: str) -> str:
        """模型类型：**提供商目录优先**，名字推断兜底。

        目录里写着 ``type``（UI 上"模型类型管理"看到的就是它），是最权威
        的来源；目录里查不到这个模型才退回名字启发式。
        """
        for item in list(getattr(provider, "models", None) or []):
            if isinstance(item, dict):
                mid, mtype = item.get("id"), item.get("type")
            else:
                mid, mtype = getattr(item, "id", None), getattr(item, "type", None)
            if str(mid or "") == model_id and mtype:
                return str(mtype)
        return str(infer_model_type(model_id))

    @staticmethod
    def _get_provider(provider_id: str) -> Any:
        try:
            return ProviderManager.get_instance().get_provider(provider_id)
        except Exception:
            return None

    # ---------------- 主入口 ----------------

    async def judge(
        self,
        *,
        purpose: str,
        system: str,
        user: str,
        parse: Callable[[str], Any],
        rule_fallback: Optional[Callable[[], Any]] = None,
        rule_fast: Optional[Callable[[], Any]] = None,
        describe: Optional[Callable[[Any], str]] = None,
        hub: Optional[DecisionHubConfig] = None,
        scope: Optional[dict] = None,
    ) -> JudgeReply:
        """要一个判断结论。**永不抛异常**，拿不到结论就返回规则兜底值。

        参数：
            purpose: 判断用途（``plan_gate``/``skill_trigger``/``outcome``…），
                同时用作熔断 key 与台账 source。
            system/user: 提示词两段。
            parse: 把模型返回的文本解析成结论；解析失败按 L3 记。
            rule_fallback: 拿不到结论时的规则兜底（L4），None 则返回 None。
            rule_fast: 调用方的确定性预命中（如 plan_gate 的正则强词）。命中即
                返回：不查缓存、不碰模型、不占轮内预算；返回 None 表示规则没把握。
            describe: 把结论写成一句话进台账（如 ``L2→中档``）。
            hub: 配置（默认读环境变量）。
            scope: ``{user_id, agent_id, chat_id, turn}``，台账作用域与
                单轮预算的计数口径。
        """
        cfg = hub if hub is not None else get_hub_config()
        sc = dict(scope or {})
        ids = {
            "user_id": str(sc.get("user_id") or ""),
            "agent_id": str(sc.get("agent_id") or ""),
            "chat_id": str(sc.get("chat_id") or ""),
            "turn": int(sc.get("turn") or 0),
            # 台账只存输入指纹，绝不存原文（v14 §4.5①）
            "input_hash": hashlib.sha1(user.encode("utf-8")).hexdigest()[:12],
        }
        turn = int(sc.get("turn") or 0)
        started = time.perf_counter()

        def elapsed() -> int:
            return int((time.perf_counter() - started) * 1000)

        # --- L0 前置门：总开关/分开关 ---
        if not cfg.enabled or not cfg.post_enabled(purpose):
            return await self._degrade(
                purpose, LAYER_DISABLED, "判官关闭",
                rule_fallback, describe, elapsed, ids,
            )

        # --- L0 前置门：调用方的确定性预命中（rule_fast）---
        # 命中即返回：不查缓存、不碰模型、不占轮内预算。规则有把握的时候再问
        # 一次模型纯属浪费（v14 §4.4②：plan_gate 的正则强词走这层）。
        if rule_fast is not None:
            try:
                fast = rule_fast()
            except Exception:  # noqa: BLE001 - 规则层不许把异常带进主链
                fast = None
            if fast is not None:
                reply = JudgeReply(
                    hit_layer=LAYER_RULE,
                    value=fast,
                    reason="规则预命中，未问模型",
                    latency_ms=elapsed(),
                )
                await self._ledger(purpose, reply, describe, **ids)
                return reply

        # --- L0 前置门：熔断（近期连续失败就别再试） ---
        if not get_breaker(BREAKER_KEY).allow(BREAKER_KEY):
            return await self._degrade(
                purpose, LAYER_BREAKER, "熔断中（近期判断连续失败）",
                rule_fallback, describe, elapsed, ids,
            )

        # --- L0 前置门：单轮预算（判断不能变成循环） ---
        tkey = (ids["user_id"], ids["agent_id"], ids["chat_id"], turn)
        if len(self._turn_calls) > _MAX_TURN_KEYS:
            self._turn_calls.clear()
        cap = int(cfg.judge_max_calls_per_turn)
        if self._turn_calls.get(tkey, 0) >= cap:
            return await self._degrade(
                purpose, LAYER_BUDGET, f"单轮判断预算用尽（{cap} 次）",
                rule_fallback, describe, elapsed, ids,
            )

        # --- L1 缓存：同问句不重复问模型 ---
        ckey = make_cache_key(
            purpose, f"{system}\n{user}", "",
            user_id=ids["user_id"], agent_id=ids["agent_id"],
        )
        cached = get_cached_judgment(ckey)
        if cached is not None:
            reply = JudgeReply(
                value=cached, hit_layer=LAYER_CACHE, source="cache",
                reason="同问句命中已判结论", latency_ms=elapsed(),
                ok=cached is not None,
            )
            await self._ledger(purpose, reply, describe, **ids)
            return reply

        # --- L2 单飞：同问句在飞就等它，不排第二个队 ---
        task = self._inflight.get(ckey)
        leader = task is None
        if task is None:
            self._turn_calls[tkey] = self._turn_calls.get(tkey, 0) + 1
            task = asyncio.create_task(
                self._run_llm(
                    purpose=purpose, system=system, user=user, parse=parse,
                    rule_fallback=rule_fallback, describe=describe,
                    cfg=cfg, ckey=ckey, ids=ids,
                ),
            )
            self._inflight[ckey] = task
            task.add_done_callback(
                lambda _t, k=ckey: self._inflight.pop(k, None),
            )
        try:
            reply = await asyncio.shield(task)
        except asyncio.CancelledError:
            return await self._degrade(
                purpose, LAYER_TRANSPORT, "判断任务被取消",
                rule_fallback, describe, elapsed, ids,
            )
        if leader:
            # 发起人拿真实层级（llm / timeout / parse_fail…），
            # 后来者才是"搭车"的 inflight。
            return reply
        return replace(reply, hit_layer=LAYER_INFLIGHT, source="inflight")

    # ---------------- L1/L2：真去问模型 ----------------

    def rule_reply(
        self,
        *,
        purpose: str,
        value: Any,
        describe: Callable[[Any], str],
        scope: Optional[dict[str, Any]] = None,
    ) -> JudgeReply:
        """规则层出口（v14 §3.1 阶梯 L3）：零次大模型参与，只入账。

        规则判级也是判档出口，台账要能查到"这一轮判了什么档、思考开没开"；
        但它没有大模型参与，故 hit_layer=rule、cost=0、无 token——绝不冒充
        一次真判断。台账唯一写者是本网关，所以规则层不自己写行。
        """
        hub = get_hub_config()
        reply = JudgeReply(
            value=value,
            hit_layer=LAYER_RULE,
            from_llm=False,
            tokens_in=0,
            tokens_out=0,
        )
        self._ledger(
            purpose=purpose,
            reply=reply,
            started=time.perf_counter(),
            model_id="",
            eng=_EngineStat(),
            hub=hub,
            scope=scope,
            describe=describe,
            prompt=None,
        )
        return reply

    async def _run_llm(
        self,
        *,
        purpose: str,
        system: str,
        user: str,
        parse: Callable[[str], Any],
        rule_fallback: Optional[Callable[[], Any]],
        describe: Optional[Callable[[Any], str]],
        cfg: DecisionHubConfig,
        ckey: str,
        ids: dict,
    ) -> JudgeReply:
        """问模型这一段的全部失败分支都收在这里，**对外永不抛**。"""
        started = time.perf_counter()

        def elapsed() -> int:
            return int((time.perf_counter() - started) * 1000)

        async def degrade(layer: str, reason: str) -> JudgeReply:
            return await self._degrade(
                purpose, layer, reason, rule_fallback, describe, elapsed, ids,
            )

        # 模型槽位：判官显式配置 → 会话激活模型（由 resolver 决定，
        # 网关不自己挑模型——绕过配置是 v14 明令禁止的）
        slot = get_judgment_provider_config(
            user_id=ids["user_id"], agent_id=ids["agent_id"],
        ) or {}
        provider_id = str(slot.get("provider_id") or "")
        model_id = str(slot.get("model") or "")
        if not provider_id or not model_id:
            return await degrade(LAYER_NO_MODEL, "未配置可用的判断模型")

        provider = self._get_provider(provider_id)
        if provider is None:
            return await degrade(LAYER_NO_MODEL, f"提供商不存在（{provider_id}）")

        # 模型类型闸门：嵌入/排序/语音/图像模型当判官必超时（v14 根因）
        mtype = self._model_type(provider, model_id)
        if mtype != "chat":
            return await degrade(LAYER_NOT_CHAT, f"非聊天模型（{mtype}）")

        kwargs = self._build_kwargs(provider, model_id, cfg)
        breaker = get_breaker(BREAKER_KEY)
        timeout = max(float(cfg.llm_timeout_s), 0.01)
        try:
            text, tin, tout = await asyncio.wait_for(
                self._invoke(provider, model_id, system, user, kwargs),
                timeout=timeout,
            )
        except asyncio.TimeoutError:
            breaker.record_failure(BREAKER_KEY)
            return await degrade(LAYER_TIMEOUT, f"判断超时（{timeout:.1f}s）")
        except Exception as exc:
            logger.debug("[决策中枢] %s 调用失败: %s", purpose, exc)
            breaker.record_failure(BREAKER_KEY)
            return await degrade(
                LAYER_TRANSPORT, f"判断调用失败（{type(exc).__name__}）",
            )

        try:
            value = parse(text) if text else None
        except Exception:
            value = None
        if value is None:
            breaker.record_failure(BREAKER_KEY)
            return await degrade(LAYER_PARSE_FAIL, "判断结果解析失败")

        breaker.record_success(BREAKER_KEY)
        put_cached_judgment(ckey, value)
        reply = JudgeReply(
            value=value,
            hit_layer=LAYER_LLM,
            source="llm",
            reason="判官判定",
            model=model_id,
            input_tokens=tin,
            output_tokens=tout,
            cost=_cost_of(model_id, tin, tout),
            latency_ms=elapsed(),
            ok=True,
        )
        await self._ledger(purpose, reply, describe, **ids)
        return reply

    @staticmethod
    async def _invoke(
        provider: Any, model_id: str, system: str, user: str, kwargs: dict
    ) -> tuple[str, int, int]:
        """调用模型并取回文本与 token。流式必须**取最后一个块**。"""
        model = provider.get_chat_model_instance(model_id)
        messages = [
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ]
        res = model(messages, **kwargs)
        if inspect.isawaitable(res):
            res = await res
        if _is_stream(res):
            # 各家流式语义不同：有的逐字增量，有的每块都给全量。
            # 只认最后一块，是唯一两种语义都成立的取法（v14 §4.2）。
            last: Any = None
            async for chunk in res:
                last = chunk
            return _text_of(last), *_usage_of(last)
        return _text_of(res), *_usage_of(res)

    # ---------------- L4：规则兜底 ----------------

    async def _degrade(
        self,
        purpose: str,
        layer: str,
        reason: str,
        rule_fallback: Optional[Callable[[], Any]],
        describe: Optional[Callable[[Any], str]],
        elapsed: Callable[[], int],
        ids: dict,
    ) -> JudgeReply:
        """拿不到结论时的统一出口：规则值 + 台账，绝不空手而归。"""
        value: Any = None
        if rule_fallback is not None:
            try:
                value = rule_fallback()
            except Exception:
                logger.debug("[决策中枢] %s 规则兜底异常", purpose, exc_info=True)
                value = None
        reply = JudgeReply(
            value=value,
            hit_layer=layer,
            source="rule",
            reason=reason,
            latency_ms=elapsed(),
            ok=value is not None,
        )
        await self._ledger(purpose, reply, describe, **ids)
        return reply

    # ---------------- 台账 ----------------

    async def _ledger(
        self,
        purpose: str,
        reply: JudgeReply,
        describe: Callable[[JudgeReply], str] | None,
        *,
        user_id: str,
        agent_id: str,
        chat_id: str,
        turn: int = 0,
        input_hash: str = "",
    ) -> None:
        """每次判断都进台账，**原文一个字都不落**（v14 §4.3）。

        落库的是：岗位 / 命中层 / 模型 / 判断内容（结论值）/ 结果 / 耗时 /
        花费 / 输入指纹 / 轮次。判了什么必须看得见，判什么的**内容**
        （提示词、用户消息原文）一个字都不落。

        写入走 :class:`coapis.decision.bus.DecisionBus`（内部吞异常，
        台账故障绝不带回判断路径）。
        """
        if not get_hub_config().ledger_enabled:
            return
        try:
            value = reply.value
            # 判断内容 = 人话描述（describe 把结论翻成人话），没有 describe 就记结论值
            description = (
                describe(value) if describe else ("" if value is None else str(value))
            )
            if value is None:
                judgment = "none"
            elif isinstance(value, (list, tuple, set)):
                judgment = "select:" + ",".join(sorted(str(v) for v in value))
            else:
                judgment = str(value)
            await asyncio.to_thread(
                get_bus().emit,
                DecisionResult(
                    source=purpose,
                    # complexity 存**判出来的档位**（只有判档岗位有档位）。
                    # 岗位名已经在 source 列，重复存一遍是台账噪声。
                    complexity=(judgment[:64] if purpose == "plan_gate" else ""),
                    action=(description or judgment)[:64],
                    hit_layer=reply.hit_layer,
                    reason=(reply.reason or "")[:512],
                    model=reply.model,
                    latency_ms=int(reply.latency_ms),
                    cost=float(reply.cost),
                    tokens=int(reply.input_tokens) + int(reply.output_tokens),
                    user_id=user_id,
                    agent_id=agent_id,
                    chat_id=chat_id,
                    value=judgment[:256],
                    turn=int(turn or 0),
                    input_hash=str(input_hash or ""),
                    outcome="pending",
                ),
            )
        except Exception as exc:  # pragma: no cover - 台账故障不影响判断
            logger.debug("[JudgeGateway] 台账写入异常（忽略）: %s", exc)


# =====================================================================
# 单例
# =====================================================================

_gateway: Optional[JudgeGateway] = None


def get_judge_gateway() -> JudgeGateway:
    global _gateway
    if _gateway is None:
        _gateway = JudgeGateway()
    return _gateway


def reset_judge_gateway() -> None:
    """清空单例（测试用）。"""
    global _gateway
    _gateway = None
