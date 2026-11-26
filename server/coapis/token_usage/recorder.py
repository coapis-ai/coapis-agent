# -*- coding: utf-8 -*-
"""token_usage 统一记账入口与计量客户端。

为什么要有这个模块
------------------
台账此前只有一条写入路径：``model_wrapper.TokenRecordingModelWrapper``，
它包在 agentscope ChatModelBase 外面。于是只有「走 agentscope 模型对象」
的调用会被记账；其余链路各写各的，实测结果：

* 决策模型（判官）直接 ``provider.get_chat_model_instance()`` 拿裸模型调用
  → 69 次真判、67457 tokens 只落在 decision_events，台账 0 条；
* 进化引擎 / 会话标题 / 语音转写直接 ``client.chat.completions.create``
  裸调 SDK → 台账 0 条；
* 台账 930 行里只出现聊天主链的三个模型名。

本模块提供两样东西，把「烧 token 必须入账」变成结构性保证：

1. ``compute_cost_cents`` —— 唯一一把成本尺子。此前有两把：判官用
   ``user_system.tokens.get_model_pricing``（有效），包装器读 provider 的
   ``pricing`` 属性（实测全空）→ 台账 cost_cents 930/930 全 0。现在两把
   合一：provider 显式定价优先，缺省回落到全局定价表。
2. ``record_llm_usage`` —— 任何链路一行入账，不要求走 agentscope。
3. ``with_usage_metering`` —— 给裸 OpenAI 客户端装计量钩子，在
   ``chat.completions.create`` 这个咽喉点自动记账，流式与非流式都覆盖。

诚实原则
--------
无定价的模型（本地/免费）成本记 0，但 **token 照记**：用户要的是「只要
调用就计量」，不是「收费才计量」。缺字段落 NULL，不写假 0。
"""
from __future__ import annotations

import contextlib
import logging
import time
from contextvars import ContextVar
from typing import Any, AsyncIterator, Awaitable, Callable, Iterable, Mapping

logger = logging.getLogger("coapis.token_usage.recorder")

# 去重闸门：聊天主链走 TokenRecordingModelWrapper，它已经记过一笔；
# 而包装器内部最终也会落到同一个底层 SDK client。若底层钩子无脑再记一次，
# 同一笔调用会在台账里出现两行、用量直接翻倍。
#
# 包装器在调用期间把这个标记置 True，底层钩子看到就只透传不记账。
# 用 ContextVar 而不是全局量，是为了并发安全：A 会话在包装器里跑，
# 不该让 B 会话的裸调用也被静默跳过。
_METERED_BY_WRAPPER: ContextVar[bool] = ContextVar(
    "coapis_token_metered_by_wrapper", default=False,
)


@contextlib.contextmanager
def metered_by_wrapper() -> Any:
    """声明「本次调用已由上层包装器记账」，底层钩子据此闭嘴。"""
    token = _METERED_BY_WRAPPER.set(True)
    try:
        yield
    finally:
        _METERED_BY_WRAPPER.reset(token)


def is_metered_by_wrapper() -> bool:
    return bool(_METERED_BY_WRAPPER.get())


def guard_wrapper_metering(fn: Callable[..., Any]) -> Callable[..., Any]:
    """装饰上层包装器的 ``__call__``：调用期间声明「我已记账」。

    用装饰器而不是在函数体里 try/finally，是为了不去动那几十行既有
    缩进——改动面越小，回归风险越小。
    """
    import functools

    @functools.wraps(fn)
    async def wrapper(*args: Any, **kwargs: Any) -> Any:
        with metered_by_wrapper():
            return await fn(*args, **kwargs)

    return wrapper

# 调用来源枚举（与 0030 迁移注释对齐）。写死在这里，避免各处自由发挥
# 造出 chat / Chat / CHAT / main_chat 四种写法然后按来源统计时漏一半。
SOURCE_CHAT = "chat"
SOURCE_DECISION = "decision"
SOURCE_EVOLUTION = "evolution"
SOURCE_TITLE = "title"
SOURCE_TRANSCRIPTION = "transcription"
SOURCE_COMPRESSION = "compression"
SOURCE_MANAGEMENT = "management"

VALID_SOURCES = frozenset({
    SOURCE_CHAT,
    SOURCE_DECISION,
    SOURCE_EVOLUTION,
    SOURCE_TITLE,
    SOURCE_TRANSCRIPTION,
    SOURCE_COMPRESSION,
    SOURCE_MANAGEMENT,
})


# ---------------------------------------------------------------------------
# 唯一一把成本尺子
# ---------------------------------------------------------------------------

def _provider_pricing(provider: Any, model: str) -> dict | None:
    """provider 上显式配置的 per-model 定价（若存在）。"""
    if provider is None or not model:
        return None
    try:
        models = provider.list_models()
    except Exception:  # noqa: BLE001 - 供应商实现五花八门
        return None
    target = (model or "").lower()
    for m in models or []:
        name = (getattr(m, "id", None) or getattr(m, "name", "") or "").lower()
        if name and (name == target or name in target or target in name):
            pricing = getattr(m, "pricing", None)
            if isinstance(pricing, Mapping) and pricing:
                return dict(pricing)
    return None


def compute_cost_cents(
    model: str,
    provider: Any,
    input_tokens: int,
    output_tokens: int,
) -> float:
    """算一条调用的成本（美分）。

    尺子优先级：provider 显式定价 → 全局 ``MODEL_PRICING``。
    两边都没有定价的模型按「免费」处理返回 0.0 —— 这是诚实值，
    不是漏算；token 数照常入账。
    """
    tin = int(input_tokens or 0)
    tout = int(output_tokens or 0)
    if tin <= 0 and tout <= 0:
        return 0.0

    pricing = _provider_pricing(provider, model)
    if pricing is None:
        try:
            from ..user_system.tokens import get_model_pricing
            pricing = get_model_pricing(model or "")
        except Exception as exc:  # noqa: BLE001
            logger.debug("recorder: pricing lookup failed for %s: %s", model, exc)
            return 0.0
    if not pricing:
        return 0.0

    try:
        pin = float(pricing.get("input", 0) or 0)
        pout = float(pricing.get("output", 0) or 0)
    except (TypeError, ValueError):
        return 0.0
    # 定价表口径：每 100 万 token 的美分（user_system/tokens.py 头部注释）
    cents = (tin / 1_000_000.0) * pin + (tout / 1_000_000.0) * pout
    return round(cents, 6)


# ---------------------------------------------------------------------------
# usage 提取（兼容 openai / agentscope / dict）
# ---------------------------------------------------------------------------

def _pick(obj: Any, *keys: str) -> int | None:
    for key in keys:
        try:
            val = obj.get(key) if isinstance(obj, Mapping) else getattr(obj, key, None)
        except Exception:  # noqa: BLE001
            val = None
        if val is not None:
            try:
                return int(val)
            except (TypeError, ValueError):
                continue
    return None


def extract_token_counts(response: Any) -> tuple[int, int]:
    """从一次 LLM 响应里取 (input_tokens, output_tokens)。

    兼容 openai 的 ``usage.prompt_tokens/completion_tokens`` 与
    agentscope 的 ``usage.input_tokens/output_tokens``；取不到返回 (0, 0)。
    """
    if response is None:
        return 0, 0
    usage = getattr(response, "usage", None)
    if usage is None and isinstance(response, Mapping):
        usage = response.get("usage")
    if usage is None:
        return 0, 0
    tin = _pick(usage, "input_tokens", "prompt_tokens") or 0
    tout = _pick(usage, "output_tokens", "completion_tokens") or 0
    return int(tin), int(tout)


# ---------------------------------------------------------------------------
# 统一记账入口
# ---------------------------------------------------------------------------

def record_llm_usage(
    *,
    model: str,
    source: str,
    input_tokens: int,
    output_tokens: int,
    user_id: Any = None,
    username: str | None = None,
    agent_id: str | None = None,
    provider_id: str | None = None,
    provider: Any = None,
    session_id: str | None = None,
    chat_id: str | None = None,
    turn_index: int | None = None,
    latency_ms: int | None = None,
    stream_interrupted: bool | None = None,
    cost_cents: float | None = None,
) -> None:
    """任何链路的一行入账（fire-and-forget，绝不抛给业务）。

    ``source`` 必填：没有这一刀，「总共用了多少」能对上、「哪条链路用的」
    永远对不上。传了未知值不丢弃——照写并 warn，让脏数据可见，比静默
    归到某个已知来源好查。
    """
    try:
        tin = int(input_tokens or 0)
        tout = int(output_tokens or 0)
        if tin <= 0 and tout <= 0:
            return
        if source not in VALID_SOURCES:
            logger.warning(
                "recorder: 非标准 source=%r（合法值：%s）",
                source, sorted(VALID_SOURCES),
            )
        cents = (
            float(cost_cents)
            if cost_cents is not None
            else compute_cost_cents(model, provider, tin, tout)
        )
        from .db_writer import save_token_usage
        save_token_usage(
            # user_id 列是 NOT NULL：没有会话归属的链路（探测、转写、判官后台
            # 补判、离线批）传 None 会撞 IntegrityError，整行被丢——代码在跑、
            # 台账恒为 0 行。空串才是「无归属」的合法写法。
            user_id="" if user_id is None else str(user_id),
            username=username,
            agent_id=agent_id,
            model=model,
            input_tokens=tin,
            output_tokens=tout,
            total_tokens=tin + tout,
            cost_cents=cents,
            provider_id=provider_id,
            session_id=session_id,
            chat_id=chat_id,
            turn_index=turn_index,
            latency_ms=latency_ms,
            stream_interrupted=stream_interrupted,
            source=source,
        )
    except Exception as exc:  # noqa: BLE001 - 记账失败不能拖垮业务链路
        logger.warning("recorder: record_llm_usage failed (source=%s): %s", source, exc)


# ---------------------------------------------------------------------------
# 裸 SDK 客户端的计量钩子
# ---------------------------------------------------------------------------

class _MeteredStream:
    """透传流式响应，同时从最后一个带 usage 的 chunk 收口用量。

    openai 兼容接口要在请求里带 ``stream_options={"include_usage": True}``
    才会在末尾 chunk 给 usage；没带就是 0 tokens —— 那是上游没给，
    不编数。
    """

    def __init__(self, stream: Any, meta: Callable[[], dict], model: str) -> None:
        self._stream = stream
        self._meta = meta
        self._model = model
        self._tin = 0
        self._tout = 0
        self._done = False

    def __aiter__(self) -> AsyncIterator[Any]:
        return self._iterate()

    async def _iterate(self) -> AsyncIterator[Any]:
        try:
            async for chunk in self._stream:
                tin, tout = extract_token_counts(chunk)
                if tin or tout:
                    self._tin, self._tout = tin, tout
                yield chunk
        finally:
            self._finish(interrupted=False)

    def _finish(self, *, interrupted: bool) -> None:
        if self._done:
            return
        self._done = True
        try:
            meta = self._meta() or {}
            record_llm_usage(
                model=meta.get("model") or self._model,
                source=meta.get("source", SOURCE_CHAT),
                input_tokens=self._tin,
                output_tokens=self._tout,
                user_id=meta.get("user_id"),
                username=meta.get("username"),
                agent_id=meta.get("agent_id"),
                provider_id=meta.get("provider_id"),
                session_id=meta.get("session_id"),
                chat_id=meta.get("chat_id"),
                turn_index=meta.get("turn_index"),
                latency_ms=meta.get("latency_ms"),
                stream_interrupted=interrupted or None,
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning("recorder: metered stream finish failed: %s", exc)


class _MeteredCompletions:
    def __init__(self, inner: Any, meta: Callable[[], dict], model_fallback: str) -> None:
        self._inner = inner
        self._meta = meta
        self._model_fallback = model_fallback

    def __getattr__(self, name: str) -> Any:
        return getattr(self._inner, name)

    async def create(self, *args: Any, **kwargs: Any) -> Any:
        # 上层包装器已经记过这笔，底层只透传，绝不重复入账。
        if _METERED_BY_WRAPPER.get():
            return await self._inner.create(*args, **kwargs)

        started = time.time()
        response = await self._inner.create(*args, **kwargs)
        model = str(kwargs.get("model") or self._model_fallback or "")

        # 流式：包一层，边透传边收口
        if kwargs.get("stream"):
            return _MeteredStream(response, self._meta, model)

        try:
            tin, tout = extract_token_counts(response)
            meta = self._meta() or {}
            record_llm_usage(
                model=meta.get("model") or model,
                source=meta.get("source", SOURCE_CHAT),
                input_tokens=tin,
                output_tokens=tout,
                user_id=meta.get("user_id"),
                username=meta.get("username"),
                agent_id=meta.get("agent_id"),
                provider_id=meta.get("provider_id"),
                session_id=meta.get("session_id"),
                chat_id=meta.get("chat_id"),
                turn_index=meta.get("turn_index"),
                latency_ms=int((time.time() - started) * 1000),
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning("recorder: metered create failed: %s", exc)
        return response


class _MeteredChat:
    def __init__(self, inner: Any, meta: Callable[[], dict], model_fallback: str) -> None:
        self.completions = _MeteredCompletions(
            getattr(inner, "completions"), meta, model_fallback,
        )


class MeteredOpenAIClient:
    """把裸 AsyncOpenAI 客户端包一层，在 chat.completions.create 处自动记账。

    只拦截这一个咽喉点，其余属性全部透传，因此对既有调用方零侵入。
    ``meta()`` 每次调用时求值，让 user_id / session_id 这类「调用时才确定」
    的信息能拿到最新值。
    """

    def __init__(self, client: Any, meta: Callable[[], dict]) -> None:
        self._client = client
        self._meta = meta
        model_fallback = str((meta() or {}).get("model") or "")
        self.chat = _MeteredChat(
            getattr(client, "chat"), meta, model_fallback,
        )

    def __getattr__(self, name: str) -> Any:
        return getattr(self._client, name)


def with_usage_metering(client: Any, meta: Callable[[], dict]) -> Any:
    """给客户端装计量钩子。meta 为 ``Callable[[], dict]``。"""
    if client is None:
        return client
    if isinstance(client, MeteredOpenAIClient):
        return client
    try:
        return MeteredOpenAIClient(client, meta)
    except Exception as exc:  # noqa: BLE001 - 装钩子失败宁可退回原客户端
        logger.warning("recorder: with_usage_metering failed, fallback raw: %s", exc)
        return client
