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
from coapis.foundation.thinking_shape import thinking_request_kwargs
from ..providers.provider_manager import ProviderManager
from .breaker import get_breaker
from .bus import get_bus
from .ledger_contract import write_ledger
from .cache import get_cached_judgment, make_cache_key, put_cached_judgment
from .config import DecisionHubConfig, get_hub_config
from .resolver import get_judge_provider_config, is_local_base_url
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
PURPOSE_PLAN_REVIEW = "plan_review"  # 计划生成后的审查岗（二期）

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

# 真判断层：出现在这些 hit_layer 上代表"确实发起过一次模型判断"
# （成功或失败）。其余（rule/disabled/breaker_open/budget_cap/cache/
# inflight/abstain）是"压根不需要判"——统计判官战绩必须把两类分开，
# 否则免判行会把总数灌满，看不出判官到底有没有发生作用。
#
# D-A（2026-11-05 拍板）：``no_model`` 从白名单里摘出来。判官槽位空是
# **配置状态**，不是"判官打输了一次"；留在白名单里会让未配置判官的每一轮
# 都往熔断记一笔失败，配置一开立刻熔断。它现在由 L0 前置门在熔断计数与
# 预算占用**之前**直判返回，台账仍记 hit_layer=no_model，不计战绩。
JUDGED_LAYERS = (
    LAYER_LLM, LAYER_LLM_SESSION, LAYER_NOT_CHAT,
    LAYER_TIMEOUT, LAYER_TRANSPORT, LAYER_PARSE_FAIL, LAYER_ERROR,
)

_MAX_TURN_KEYS = 200
# 判官五岗调用名（调用方实际传进来的 purpose）：plan_gate / skill_trigger /
# tool_gate / advisor / acceptance。验收岗在预算分池里单独留额度，见
# _post_call_cap；上面那组 PURPOSE_* 是台账词表（验收写 verify），两套词
# 不是一回事，别互相覆盖。
PURPOSE_CALL_ACC = "acceptance"


def _post_call_cap(cfg: Any, purpose: str) -> int:
    """某岗位每轮可调用判官几次（预算分池，v14 §4.3）。

    上限写在配置里、可按岗位调；0/负数=该岗不限（仍受全局 7 次约束）。
    """
    limits = getattr(cfg, "judge_post_limits", {}) or {}
    cap = int(limits.get(purpose, getattr(cfg, "judge_post_limit_default", 2)))
    return max(int(cap), 0)


def _breaker_key(purpose: str) -> str:
    """熔断按岗位分池（v14 §4.3）：一个岗位连败，不该把别的岗位一起熔断。

    dev 实测 breaker_open 24 行——全局只有一把熔断闸，tool_gate 每次工具调用
    判一格、最容易把连败计数填满，一开就把判档岗与验收岗整轮熔掉。
    岗位独立计数后，慢的岗位自己歇着，闭环岗照常判断。
    """
    return f"{BREAKER_KEY}:{purpose}"


#: 连续软超时计数（按岗位，v19 P0-2 ①）。
#: 软阈值到点 = "主链等不起先走了"，判官仍在跑 —— 它不是判官的失败，
#: 不该直接推熔断计数；但判官若**一直**慢到主链等不起，主链就该歇：
#: 连续计数到 ``breaker_soft_streak`` 才按失败冷却，真判成功即清零。
_soft_streaks: dict[str, int] = {}


def _note_soft_timeout(bkey: str) -> int:
    """记一次软超时，返回该岗位当前的连续软超时次数。"""
    n = int(_soft_streaks.get(bkey, 0)) + 1
    _soft_streaks[bkey] = n
    return n


def _reset_soft_streak(bkey: str) -> None:
    """真判成功（或已触发冷却）后清零连续计数。"""
    _soft_streaks.pop(bkey, None)


def _soft_streak_of(bkey: str) -> int:
    """当前连续软超时次数（体检用）。"""
    return int(_soft_streaks.get(bkey, 0))


def _hub_breaker(purpose_key: str, cfg: Any) -> CircuitBreaker:
    """取岗位闸门，并把阈值对齐到当前在途配置（v15 F6）。

    闸门是惰性建的：第一次用到时按那一刻的配置定阈值。若那一刻中枢
    配置尚未装载（拿到默认 3 次 / 120 秒），之后配置改成 5 次也不会
    回头更新——于是「配置说 5 次才熔断、实际 3 次就熔断」，判官被记成
    故障、整轮判断被跳过。每次取用都对齐一次，口径分裂就此结束。
    """
    breaker = get_breaker(purpose_key)
    breaker.sync_thresholds(
        cfg.breaker_failure_threshold,
        cfg.breaker_cooldown_s,
        window_s=cfg.breaker_window_seconds,
        probe_s=cfg.breaker_probe_timeout_s,
    )
    return breaker

# 上游拒收形状参数时的自愈（v14 §4.2）：形状键来自单一真源，被拒就剥掉重试一次，
# 并把该 (provider_id, model) 记进进程级拉黑表——同一厂同一模型此后不再发。
_SHAPE_KEYS = ("enable_thinking", "chat_template_kwargs", "reasoning_effort")
_SHAPE_REJECT: dict[tuple[str, str], tuple[str, ...]] = {}
_PARAM_REJECT_HINTS = (
    "unknown parameter", "unrecognized", "unsupported", "unexpected keyword",
    "extra inputs", "invalid parameter", "unknown field", "not supported",
    "unhandled keyword",
)


def _param_rejection_keys(text: str) -> set:
    """上游报错点到名、且确实是我们发出去的形状键 → 该剥掉重试。

    判官的输入是自然语言，模型答得出来；形状键是我们额外塞的私有参数，
    不认识它的上游会判 400。参数被拒 ≠ 判断失败：剥掉参数再要一次结论，
    比直接落一行传输错误、再把连续失败计入熔断要诚实得多。
    """
    low = str(text).lower()
    if not any(h in low for h in _PARAM_REJECT_HINTS):
        return set()
    return {k for k in _SHAPE_KEYS if k in low}


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


# 判档档位词表，与 plan_gate.LEVELS 逐字对齐（test_decision_ledger 里
# 有断言钉住，防止两边漂移）。判断值形状是 ``select:<effort>,<level>``。
_LEVELS = frozenset({"simple", "medium", "complex"})


def _level_of(judgment: str) -> str:
    """判档行的判断值 → 档位本身。

    台账这一列要的是档位（simple/medium/complex），历史上塞进去的是
    判断值整串，实测出现 'select:low,medium' 这种值——按复杂度分组、
    筛选、算成本分布的查询全部作废。判断值是 ``select:<effort>,<level>``，
    effort 和 level 的词表有重叠（medium 两边都有），所以从右往左取第一个
    命中档位词表的词。解析不出来就返回空串——空档位比假档位好，假档位
    会污染按复杂度分组的所有统计。
    """
    text = str(judgment or "").strip()
    if text.startswith("select:"):
        text = text[len("select:"):]
    for token in reversed([t.strip().lower() for t in text.split(",") if t.strip()]):
        if token in _LEVELS:
            return token
    return ""


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

#: 后台补判任务的强引用表（v14 §批次3）。
#: ``asyncio`` 只持弱引用——没人持有的任务会被垃圾回收，回调连同补判一起蒸发。
_BG_TASKS: set = set()

class JudgeGateway:
    """判断环节统一网关（v14 §4.1）。

    进程内单例，线程安全只到"单事件循环"粒度（与决策中枢其余部件一致）。
    """

    def __init__(self) -> None:
        # 同问句在飞的判断：key -> Task（单飞，第二个人等同一个结果）
        self._inflight: dict[str, asyncio.Task] = {}
        # 单轮 LLM 判断计数：(user, agent, chat, turn) -> 次数
        self._turn_calls: dict[tuple[str, str, str, int], dict[str, int]] = {}

    # ---------------- 参数构造 ----------------

    @staticmethod
    def _thinking_kwargs(provider: Any, flag: bool) -> dict[str, Any]:
        """按端点类型给出"思考开关"参数；端点不认的一律不发。

        形状表**不在这份文件里**——取单一真源
        :mod:`coapis.foundation.thinking_shape`（主链向下取用同一份，判官与主链
        同源：主链认得的形状判官就能用）。这里以前自己抄了一张三家表
        （v14 §4.2），结果判官用的 DeepSeek
        （provider_type=deepseek、base_url=api.deepseek.com）三种形态全不命中，
        返回空 → 思考没关 → 单次 12~18 秒：4 秒软阈值的工具岗全数超时，
        连吃三条就熔断整轮，验收岗的 12 秒硬阈值也被 18 秒的思考模型击穿。
        """
        try:
            return dict(
                thinking_request_kwargs(
                    getattr(provider, "provider_type", None),
                    getattr(provider, "base_url", None),
                    getattr(provider, "provider_id", None),
                    thinking=bool(flag),
                )
                or {}
            )
        except Exception:  # noqa: BLE001 - 认不出形状就不注入思考参数，不影响判断
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
        shape = self._thinking_kwargs(provider, flag)
        # 这家这个模型以前拒收过哪些形状键，就不再发（见 _invoke_healed）
        rejected = _SHAPE_REJECT.get(
            (str(getattr(provider, "provider_id", "") or ""), str(model_id)),
            (),
        )
        for key, value in shape.items():
            if key in rejected:
                continue
            kwargs[key] = value
        return kwargs

    async def _invoke_healed(
        self,
        provider: Any,
        model_id: str,
        system: str,
        user: str,
        kwargs: dict[str, Any],
        slot_key: tuple[str, str],
    ) -> tuple[str, int, int]:
        """调判官；上游拒收形状参数时剥掉该参数重试一次，并拉黑该槽位。

        只治「参数被拒」这一类：报的是模型不存在、鉴权失败、超时，剥参数
        没有意义，原样抛给调用方分层处理。
        """
        try:
            return await self._invoke(provider, model_id, system, user, kwargs)
        except BaseException as exc:  # noqa: BLE001 - 分层交给调用方
            hits = _param_rejection_keys(str(exc)) & set(kwargs)
            if not hits:
                raise
            lean = {k: v for k, v in kwargs.items() if k not in hits}
            _SHAPE_REJECT[slot_key] = tuple(sorted(set(_SHAPE_REJECT.get(slot_key, ())) | hits))
            logger.warning(
                "[决策中枢] 上游拒收形状参数 %s（槽位 %s）→ 剥掉重试一次，"
                "该槽位此后不再发这些参数",
                sorted(hits),
                slot_key,
            )
            return await self._invoke(
                provider, model_id, system, user, lean,
            )

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
        on_late_verdict: Optional[Callable[[Any], Any]] = None,
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
            on_late_verdict: **迟到真判的回执**。软超时后主链拿降级值先走，
                判官在后台跑出的真结论只进台账——消费方（如验收回填判档行）
                拿到的永远是弃权值，闭环 0 行的真因就在这里。给了这个回调，
                后台补判成功时就用**真结论**再叫它一次；回调异常一律吞掉。
        """
        cfg = hub if hub is not None else get_hub_config()
        sc = dict(scope or {})
        ids = {
            "user_id": str(sc.get("user_id") or ""),
            "agent_id": str(sc.get("agent_id") or ""),
            "chat_id": str(sc.get("chat_id") or ""),
            # session 是 chat 取空时的预算键兜底：没有它，作用域缺失的
            # 判断行会全部共用同一个预算键（实测判官 30% 的调用被
            # budget_cap 掐死）。
            "session_id": str(sc.get("session_id") or ""),
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

        # --- L0 前置门：判官必须显式配置（D-A 2026-11-05 拍板）---
        # 判官槽位（judge_provider_id + judge_model）任一为空、或槽里的模型
        # 已删除/非 chat → 判官压根不上岗，直接拿规则结论返回。
        # 位置刻意放在熔断与单轮预算**之前**：配置缺失属于"这里不需要判"，
        # 计入熔断窗口会把"判官战绩"污染成配置问题，占预算则会让一次规则直判
        # 吃掉整轮判断额度。dev 实测（抄激活模型的旧口径）：真判 184 行
        # avg 4448ms → 超时 105 行、熔断 24 行、预算吃光 61 行，损耗 44%。
        slot = get_judge_provider_config(
            cfg, user_id=ids["user_id"], agent_id=ids["agent_id"],
        )
        if not slot or not slot.get("provider_id") or not slot.get("model"):
            return await self._degrade(
                purpose, LAYER_NO_MODEL, "未配置判断模型（判官槽位空），按规则直判",
                rule_fallback, describe, elapsed, ids,
            )

        # --- L0 前置门：熔断（近期连续失败就别再试） ---
        bkey = _breaker_key(purpose)
        if not _hub_breaker(bkey, cfg).allow(bkey):
            return await self._degrade(
                purpose, LAYER_BREAKER, "熔断中（近期判断连续失败）",
                rule_fallback, describe, elapsed, ids,
            )

        # --- L0 前置门：单轮预算（判断不能变成循环） ---
        # 键必须能区分"哪一次会话的第几轮"。曾经只有
        # (user, agent, chat, turn)：判档行的 chat 取空、turn 恒 0 时
        # 退化成"每用户一个全局键"，跑满上限后判官对该用户**永久**熔断
        # （实测 66 行台账里 20 行 hit_layer=budget_cap）。chat 空时用
        # session 兜底；四项全空时键里带上本实例身份，绝不与他人共用。
        tkey = (
            ids["user_id"],
            ids["agent_id"],
            ids["chat_id"] or ids.get("session_id", ""),
            turn,
        )
        if not any(tkey):
            tkey = (id(self), purpose, turn)
        if len(self._turn_calls) > _MAX_TURN_KEYS:
            self._turn_calls.clear()
        cap = int(cfg.judge_max_calls_per_turn)
        # 预算分池（v14 §4.3）：原先五岗抢一个 7 格的池——tool_gate 一次工具
        # 调用抢一格，池吃光后判档岗与验收岗全数落 budget_cap（dev 实测 38 行：
        # plan_gate 21 / tool_gate 9 / acceptance 4）。验收是闭环的回执岗，它
        # 抢不到预算，判档行就永远对不上账（闭环 5/39）；判档抢不到，档位只能
        # 靠规则兜底。故：验收按岗位预留，其余四岗共享余额，每岗位再各设上限。
        reserve = int(getattr(cfg, "judge_reserve_acceptance", 2) or 0)
        post_cap = _post_call_cap(cfg, purpose)
        counts = self._turn_calls.setdefault(tkey, {})
        total = sum(int(v) for v in counts.values())
        acc_used = int(counts.get(PURPOSE_CALL_ACC, 0))
        is_acc = purpose == PURPOSE_CALL_ACC
        pool_cap = cap if is_acc else max(cap - reserve, 0)
        pool_used = acc_used if is_acc else max(total - acc_used, 0)
        post_used = int(counts.get(purpose, 0))
        budget_reason = ""
        if post_used >= post_cap:
            budget_reason = f"岗位判断预算用尽（{purpose} 每轮 {post_cap} 次）"
        elif pool_used >= pool_cap:
            budget_reason = f"单轮判断预算用尽（{cap} 次）" + (
                "" if is_acc else f"，验收预留 {reserve} 次"
            )
        # v19 P2-2（启动期首格免池子闸）：一轮任务要用的判断数天然超过"池子"额度
        # ——判档1 + 计划门禁1 + 计划审查1 + 技能触发1 + 工具门禁N + 验收1，
        # 池子默认 6 格，工具门禁一多就把**后面**的判断整批砍掉。实测台账里
        # budget_cap 落点大半落在 turn=0/1 的启动期岗位上：任务从第一步就没有判断，
        # 全靠规则兜底走完，判官形同事后点评。
        #
        # 规则收窄成"只保每轮第一格"：某岗位**本轮第一次**判断（post_used==0）
        # 在启动期（前 N 轮）不受池子闸限制。反复调用同一岗位（post_used>0）
        # 照旧受闸——防打转的初衷一分不让；验收预留（acceptance reserve）也不动。
        # N=0 即关闭这个口子，行为回到 v19 之前。
        exempt = int(getattr(cfg, "budget_exempt_turns", 0) or 0)
        if (
            budget_reason
            and exempt > 0
            and 0 <= int(turn) < exempt
            and post_used == 0
        ):
            logger.debug(
                "[JudgeGateway] 启动期首格免池子闸：turn=%s purpose=%s 放过（%s）",
                turn, purpose, budget_reason,
            )
            budget_reason = ""
        if budget_reason:
            return await self._degrade(
                purpose, LAYER_BUDGET, budget_reason,
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
            counts[purpose] = post_used + 1
            task = asyncio.create_task(
                self._run_llm(
                    purpose=purpose, system=system, user=user, parse=parse,
                    rule_fallback=rule_fallback, describe=describe,
                    cfg=cfg, ckey=ckey, ids=ids, slot=slot,
                    on_late_verdict=on_late_verdict,
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
        slot: Optional[dict[str, Any]] = None,
        on_late_verdict: Optional[Callable[[Any], Any]] = None,
    ) -> JudgeReply:
        """问模型这一段的全部失败分支都收在这里，**对外永不抛**。"""
        started = time.perf_counter()

        def elapsed() -> int:
            return int((time.perf_counter() - started) * 1000)

        async def degrade(
            layer: str, reason: str, ledger: bool = True
        ) -> JudgeReply:
            return await self._degrade(
                purpose, layer, reason, rule_fallback, describe, elapsed, ids,
                ledger=ledger,
            )

        # 模型槽位由 judge() 的 L0 前置门解析好传进来（D-A：只认判官槽位，
        # 未配置在 L0 就直判，压根走不到这里）。这里不重复解析——两处各解
        # 一遍正是 v14 §0.3 抓到的"绕过配置"根因；走到这里还空，说明调用方
        # 绕过了前置门直接调本函数，兜底弃权、不自己挑模型。
        provider_id = str((slot or {}).get("provider_id") or "")
        model_id = str((slot or {}).get("model") or "")
        if not provider_id or not model_id:
            return await degrade(LAYER_NO_MODEL, "未配置判断模型（判官槽位空）")

        provider = self._get_provider(provider_id)
        if provider is None:
            return await degrade(LAYER_NO_MODEL, f"提供商不存在（{provider_id}）")

        # 模型类型闸门：嵌入/排序/语音/图像模型当判官必超时（v14 根因）
        mtype = self._model_type(provider, model_id)
        if mtype != "chat":
            return await degrade(LAYER_NOT_CHAT, f"非聊天模型（{mtype}）")

        kwargs = self._build_kwargs(provider, model_id, cfg)
        bkey = _breaker_key(purpose)
        breaker = _hub_breaker(bkey, cfg)
        # F1 自适应超时：本地链路（ollama/vLLM）8s、远端 API 5s。
        # 判官同步调用，本地思考模型实测 5~15 秒，固定短超时=台账里
        # 一整层 "判断超时（2.6s）" 的真因。
        timeout = max(
            cfg.effective_timeout_ms(is_local_base_url(slot.get("base_url"))) / 1000.0,
            0.01,
        )
        try:
            # v14 §批次3 软超时：**按岗位**取软阈值（v19 P1-2）——原先一把
            # judge_soft_ms 量七岗，判档岗在计划生成前（有人在等）吃小预算，
            # 技能/工具/改道/验收在整轮里（幕后）该吃大预算；一把尺子量七岗
            # 是真判率被绞肉机绞掉的真因（v14 P5：真判率 19% 大半是超时熔断，
            # 不是判官不行）。台账里的 timeout 行因此是"按岗位预算的诚实结果"。
            soft_ms = cfg.soft_ms_for(purpose)
            if purpose == "acceptance":
                # 验收岗在幕后：整轮交付跑完才触发，没有任何人等它的结论。
                # 拿"主链最多等 N 秒"量它 = 把唯一能判交付的岗位判成恒弃权；
                # 验收的 verdict 是判档行 outcome 的唯一来源，弃权即闭环 0 行
                # （dev 实测 180/182 行 pending 的直接成因）。单独给预算。
                soft_ms = float(getattr(cfg, "judge_soft_ms_acceptance", 12000.0))
            soft_s = min(max(soft_ms / 1000.0, 0.2), timeout)
            # 硬熔断 = "这一判最多活多久"。主链岗位用自适应预算；验收在幕后，
            # 允许判到软阈值的 1.5 倍，上限 20 秒（再长就是把连接池占干）。
            hard_s = timeout
            if purpose == "acceptance":
                hard_s = min(max(timeout, soft_s * 1.5), 20.0)
            call_task = asyncio.create_task(
                self._invoke_healed(
                    provider,
                    model_id,
                    system,
                    user,
                    kwargs,
                    (str(getattr(provider, "provider_id", "") or ""), str(model_id)),
                ),
            )
            started = time.perf_counter()
            try:
                text, tin, tout = await asyncio.wait_for(
                    asyncio.shield(call_task),
                    timeout=soft_s,
                )
            except asyncio.TimeoutError:
                # 后台补判：跑完照常写台账/进缓存；主链立刻降级先走。
                bg = asyncio.create_task(
                    self._judge_bg_complete(
                        call_task,
                        purpose=purpose,
                        model_id=model_id,
                        parse=parse,
                        ckey=ckey,
                        describe=describe,
                        ids=ids,
                        started_at=started,
                        hard_s=hard_s,
                        on_late_verdict=on_late_verdict,
                    ),
                )
                # 后台任务必须有强引用：事件循环只存弱引用，没人持有的
                # 任务会被 GC 掉（"Task was destroyed but it is pending"），
                # 迟到回填就成了碰运气。
                _BG_TASKS.add(bg)
                bg.add_done_callback(_BG_TASKS.discard)
                # v19 P0-2 ①：主链**软阈值**到点不是判官的失败——判官还在跑，
                # 成功样本照常入账（后台补判）。把"慢"记成"坏"是 dev 实测
                # "真判率 30% 时 breaker 持续开"的成因：判官本地 2.5-15s、
                # 软阈值 2s，按失败计数必然把熔断推开，之后整轮判断全灭。
                # 只有一直慢到主链等不起（连续 N 次软超时）才按失败冷却。
                # **例外**：软阈值被硬熔断夹到等于硬阈值时（soft_s == hard_s），
                # 到点就是硬熔断——判官的额度用完了，这就是失败，照常计数。
                hard_capped = soft_s >= hard_s - 1e-9
                if hard_capped:
                    breaker.record_failure(bkey)
                    _reset_soft_streak(bkey)
                    return await degrade(
                        LAYER_TIMEOUT,
                        f"判断超时（硬熔断 {hard_s:.1f}s，模型 {model_id}）",
                    )
                streak = _note_soft_timeout(bkey)
                soft_streak = max(int(getattr(cfg, "breaker_soft_streak", 5)), 1)
                if streak >= soft_streak:
                    _reset_soft_streak(bkey)
                    breaker.record_failure(bkey)
                    logger.warning(
                        "[决策中枢] %s 连续 %d 次软超时（软阈值 %.1fs），"
                        "本岗位熔断冷却 %.0fs",
                        purpose, streak, soft_s, breaker.cooldown_s(bkey),
                    )
                # v19 P0-2 ②：软阈值这一手**不写台账**——这一判没有终态，
                # 台账等后台补判出真结论（llm / 解析失败 / 硬熔断）再落一行。
                # 此前"软阈值一行 + 补判一行"= 一次判记两行，对账把一次判断
                # 算成两条样本（v19 实测：双记账 16 对推开熔断）。
                return await degrade(
                    LAYER_TIMEOUT,
                    f"判断超时（软阈值 {soft_s:.1f}s，判官后台补判中，模型 {model_id}）",
                    ledger=False,
                )
        except Exception as exc:
            # 完整 traceback 记 warning（进日志）——只记 debug 等于故障隐身。
            logger.warning(
                "[决策中枢] %s 调用失败: %s: %s", purpose, type(exc).__name__, exc,
                exc_info=True,
            )
            breaker.record_failure(bkey)
            return await degrade(
                LAYER_TRANSPORT, f"判断调用失败（{type(exc).__name__}: {exc}）",
            )

        try:
            value = parse(text) if text else None
        except Exception:
            value = None
        if value is None:
            breaker.record_failure(bkey)
            return await degrade(LAYER_PARSE_FAIL, "判断结果解析失败")

        breaker.record_success(bkey)
        _reset_soft_streak(bkey)
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

    async def _judge_bg_complete(
        self,
        call_task: Any,
        *,
        purpose: str,
        model_id: str,
        parse: Any,
        ckey: str,
        describe: Any,
        ids: dict,
        started_at: float,
        hard_s: float = 0.0,
        on_late_verdict: Optional[Callable[[Any], Any]] = None,
    ) -> None:
        """软超时后把这一判跑完：成功样本照常入账、进缓存（v14 §批次3）。

        主链已经走了，判官结果不丢弃——台账要反映"判官真实判了什么"，
        治理对账才能把"真判能力"与"预算损耗"分开。本方法在后台任务运行，
        一切异常吞掉：补判是加护，绝不反噬主链与进程。

        ``hard_s`` 是 F1 自适应预算给的**硬熔断**：软阈值只管"主链等多久"，
        硬阈值管"这一判最多活多久"，到点取消调用，绝不让一次判官调用挂到
        天荒地老把连接池占干。
        """
        try:
            if hard_s and hard_s > 0:
                text, tin, tout = await asyncio.wait_for(
                    asyncio.shield(call_task),
                    timeout=hard_s,
                )
            else:
                text, tin, tout = await call_task
        except asyncio.TimeoutError:
            call_task.cancel()
            logger.warning(
                "[决策中枢] %s 后台补判触硬熔断 %.1fs，取消调用",
                purpose,
                hard_s,
            )
            # v19 P0-2 ②：这一判到此有了**终态**（被硬熔断掐死），台账补一行。
            # 主链软阈值那一手不落账，台账只在此刻落唯一一行——判官到底判没
            # 判成，对账只看这一行。
            await self._ledger(
                purpose,
                JudgeReply(
                    value=None,
                    hit_layer=LAYER_TIMEOUT,
                    source="rule",
                    reason=f"判断超时（硬熔断 {hard_s:.1f}s，后台补判被掐停）",
                    latency_ms=int((time.perf_counter() - started_at) * 1000),
                    model=model_id,
                    ok=False,
                ),
                describe,
                **ids,
            )
            return
        except Exception as exc:  # noqa: BLE001 - 补判失败只留日志
            logger.warning(
                "[决策中枢] %s 后台补判失败: %s: %s",
                purpose,
                type(exc).__name__,
                exc,
            )
            await self._ledger(
                purpose,
                JudgeReply(
                    value=None,
                    hit_layer=LAYER_TRANSPORT,
                    source="rule",
                    reason=f"判断链路故障：{type(exc).__name__}: {exc}",
                    latency_ms=int((time.perf_counter() - started_at) * 1000),
                    model=model_id,
                    ok=False,
                ),
                describe,
                **ids,
            )
            return
        value = None
        if text:
            try:
                value = parse(text)
            except Exception:  # noqa: BLE001
                value = None
        # 局部 import：本方法跑在后台任务里， breaker 在主流程里是局部导入的，
        # 直接写 breaker 会 NameError（dev 实测：后台补判一进来就炸，
        # "Task exception was never retrieved"）。后台任务里的每个依赖都要自带。
        from .breaker import get_breaker as _get_breaker

        bkey = _breaker_key(purpose)
        breaker = _hub_breaker(bkey, get_hub_config())
        if value is None:
            breaker.record_failure(bkey)
            # 终态 = 判官回了但解析不出结论：台账落这一行（主链没落账）。
            await self._ledger(
                purpose,
                JudgeReply(
                    value=None,
                    hit_layer=LAYER_PARSE_FAIL,
                    source="rule",
                    reason="判断结果解析失败（软超时后台补判）",
                    latency_ms=int((time.perf_counter() - started_at) * 1000),
                    model=model_id,
                    ok=False,
                ),
                describe,
                **ids,
            )
            return
        breaker.record_success(bkey)
        _reset_soft_streak(bkey)
        put_cached_judgment(ckey, value)
        reply = JudgeReply(
            value=value,
            hit_layer=LAYER_LLM,
            source="llm",
            reason="判官判定（软超时后台补记）",
            model=model_id,
            input_tokens=tin,
            output_tokens=tout,
            cost=_cost_of(model_id, tin, tout),
            latency_ms=int((time.perf_counter() - started_at) * 1000),
            ok=True,
        )
        await self._ledger(purpose, reply, describe, **ids)
        # 迟到真判的回执：台账记了真结论，消费方也要拿到真结论。
        # 验收岗靠这一把回填判档行的 outcome——补判不回执，outcome 就永远
        # 停在主链拿到的弃权值上（v14 §3.2 闭环死锁的第二段）。
        if on_late_verdict is not None:
            try:
                done = on_late_verdict(value)
                if inspect.isawaitable(done):
                    await done
            except Exception:  # noqa: BLE001 - 回执是加分项，绝不反噬
                logger.debug("[决策中枢] %s 迟到真判回执失败（已吞）", purpose, exc_info=True)

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
        ledger: bool = True,
    ) -> JudgeReply:
        """拿不到结论时的统一出口：规则值 + 台账，绝不空手而归。

        ``ledger=False`` 用于"判官还在跑、这一判没有终态"的场合（v19 P0-2）：
        主链软阈值到点先走时判断并没有失败——台账要等判官出终态（真判 /
        解析失败 / 硬熔断）再落**那一行**。此前软阈值先写一行 timeout、
        后台补判再写一行 llm，一次判记两行，对账把同一次判断算成两条样本。
        """
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
        if ledger:
            await self._ledger(purpose, reply, describe, **ids)
        return reply

    # ---------------- 台账 ----------------

    async def _ledger(
        self,
        purpose: str,
        reply: JudgeReply,
        describe: Callable[[JudgeReply], str] | None,
        *,
        user_id: str = "",
        agent_id: str = "",
        chat_id: str = "",
        turn: int = 0,
        input_hash: str = "",
        **ids: Any,
    ) -> None:
        """每次判断都进台账，**原文一个字都不落**（v14 §4.3）。

        落库的是：岗位 / 命中层 / 模型 / 判断内容（结论值）/ 结果 / 耗时 /
        花费 / 输入指纹 / 轮次。判了什么必须看得见，判什么的**内容**
        （提示词、用户消息原文）一个字都不落。

        ``**ids`` 是必需的：调用点统一透传一整套会话标识（session_id、
        channel、scope、prompt、started、model_id、eng、hub……），台账只取
        其中自己要的列。签名写死成固定参数时，多出来的键会让每次判断
        直接 TypeError——异常被本函数吞掉，结果是**台账在真实判断链路上
        一条都写不进去**，界面永远空白。

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
            # 台账一律走 ledger_contract 唯一入口（v14 §批次1）：档位清洗、
            # 身份兜底、零值语义标记由契约统一负责——岗位只出判断，不再各写
            # 各的。complexity 只认判则词表：判档岗存档位，其余岗位留空，
            # 'select:low,medium' 这类判断值整串进不了档位列（原值在
            # dirty_band 留痕）。零值行带语义标记，成本对账不再把
            # "设计上为 0"和"记账坏了"混成一团。
            await asyncio.to_thread(
                write_ledger,
                source=purpose,
                purpose=purpose,
                action=(description or judgment),
                band=_level_of(judgment) if purpose == "plan_gate" else "",
                reason=reply.reason or "",
                hit_layer=reply.hit_layer,
                model=reply.model,
                latency_ms=int(reply.latency_ms),
                cost=float(reply.cost),
                tokens=int(reply.input_tokens) + int(reply.output_tokens),
                input_hash=str(input_hash or ""),
                value=judgment,
                user_id=user_id,
                agent_id=agent_id,
                chat_id=chat_id,
                turn=int(turn or 0) or None,
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
