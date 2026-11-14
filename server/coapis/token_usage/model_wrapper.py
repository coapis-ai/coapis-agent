# -*- coding: utf-8 -*-
# -*- coding: utf-8 -*-
# Copyright 2026 蜜蜂 & CoApis Contributors
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU Affero General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU Affero General Public License for more details.
#
# You should have received a copy of the GNU Affero General Public License
# along with this program.  If not, see <https://www.gnu.org/licenses/>.

"""Model wrapper that records token usage from LLM responses."""

import time
from datetime import date, datetime, timezone
from typing import Any, AsyncGenerator, Literal, Type

from agentscope.model import ChatModelBase
from agentscope.model._model_response import ChatResponse
from agentscope.model._model_usage import ChatUsage
from pydantic import BaseModel

from .buffer import _UsageEvent
from .manager import get_token_usage_manager


def _opt(obj: Any, name: str, default: str = "") -> str:
    """安全取属性（缺失一律回默认值）。

    agentscope 的 ``ChatUsage`` 自定义了 ``__getattr__``，缺失键抛 **KeyError**
    （不是 AttributeError），因此 ``getattr(obj, name, default)`` 兜不住。
    逐轮明细是"有则记、无则空"，取字段这一步绝不能把主链炸了。
    """
    try:
        val = getattr(obj, name)
    except Exception:  # KeyError / AttributeError / 上游自定义异常
        return default
    if val is None:
        return default
    return str(val)



class TokenRecordingModelWrapper(ChatModelBase):
    """Wraps a ChatModelBase to record token usage on each call."""

    _usage_by_session: dict[str, dict[str, Any]] = {}
    # 逐轮计数（B1 台账口径：一次模型调用 = 一轮，会话内从 1 起自增）
    _turn_counters: dict[str, int] = {}

    def __init__(self, provider_id: str, model: ChatModelBase) -> None:
        super().__init__(
            model_name=getattr(model, "model_name", "unknown"),
            stream=getattr(model, "stream", True),
        )
        self._model = model
        self._provider_id = provider_id

    def _with_stream_usage(self, kwargs: dict[str, Any]) -> dict[str, Any]:
        """流式时补 ``stream_options={"include_usage": True}``（D16）。

        - 非流式不注入（OpenAI 协议里 stream_options 只对 stream=True 合法）；
          本包装器不掌握 stream 开关（由底层模型实例决定），因此只在
          调用方/模型侧确有流式迹象时注入，且失败只降级一次。
        - ``COAPIS_STREAM_USAGE=0`` 整体关闭（应急阀门）。
        - 已知该 (provider, model) 不认 → 不再试（降级记忆在 turn_usage）。
        - 调用方显式传的同名参数**优先**，不覆盖。
        """
        from .turn_usage import stream_usage_kwargs

        # OpenAI 协议：stream_options 只对 stream=True 合法。本包装器不
        # 掌握开关（在底层模型实例上），因此读它；读不到就不注入。
        if not bool(getattr(self._model, "stream", False)):
            return kwargs

        extra = stream_usage_kwargs(self._provider_id, self.model_name)
        if not extra:
            return kwargs
        merged = dict(kwargs)
        for key, value in extra.items():
            merged.setdefault(key, value)
        return merged

    def _mark_turn_interrupted(self) -> None:
        """即时标记"该会话最近一轮未正常收尾"。

        持久真值是 ``token_usage.stream_interrupted`` 列；这里是给聊天侧
        写消息元数据用的即时通道（落库消息与写台账不在同一个调用里）。
        """
        try:
            from ..config.session_context import get_current_chat_id

            from .turn_usage import mark_turn_interrupted

            chat_id = get_current_chat_id() or ""
            if chat_id:
                mark_turn_interrupted(chat_id)
        except Exception:  # 观测面绝不反噬主链
            return

    def _record_usage(
        self,
        usage: ChatUsage | None,
        *,
        latency_ms: int | None = None,
        stream_interrupted: bool | None = None,
    ) -> None:
        """Enqueue a usage event synchronously — never blocks the caller.

        逐轮明细（B1 台账口径）：``latency_ms`` 缺省取 ChatUsage.time×1000
        （缺失记 0，诚实缺项）；``chat_id`` 取聊天上下文（聊天页会话即
        聊天单位）；``turn_index`` 按会话自增；``stream_interrupted``
        标记流未正常耗尽。
        """
        if usage is None:
            return
        pt = getattr(usage, "input_tokens", 0) or 0
        ct = getattr(usage, "output_tokens", 0) or 0
        if pt <= 0 and ct <= 0:
            return

        from ..config.session_context import (
            get_current_chat_id,
            get_current_session_id,
        )

        session_id = get_current_session_id()
        chat_id = get_current_chat_id() or session_id
        turn_index = self._next_turn_index(session_id)
        if latency_ms is None:
            latency_ms = int((getattr(usage, "time", 0) or 0) * 1000)
        if stream_interrupted is None:
            stream_interrupted = False

        event = _UsageEvent(
            provider_id=self._provider_id,
            model_name=self.model_name,
            prompt_tokens=pt,
            completion_tokens=ct,
            date_str=date.today().isoformat(),
            now_iso=datetime.now(tz=timezone.utc).isoformat(
                timespec="seconds",
            ),
            chat_id=chat_id or "",
            session_id=session_id or "",
            turn_index=int(turn_index),
            latency_ms=int(latency_ms),
            api_call_id=_opt(usage, "call_id"),
        )
        # Fire-and-forget: synchronous put_nowait, ~100 ns, no await needed.
        get_token_usage_manager().enqueue(event)

        # Save to SQLite for per-user, per-agent tracking
        self._record_usage_to_db(
            pt,
            ct,
            chat_id=chat_id,
            session_id=session_id,
            turn_index=turn_index,
            latency_ms=int(latency_ms),
            stream_interrupted=bool(stream_interrupted),
        )

        usage_data = {
            "provider_id": self._provider_id,
            "model_name": self.model_name,
            "prompt_tokens": pt,
            "completion_tokens": ct,
            "total_tokens": pt + ct,
            # 逐轮明细键（B1 契约锁定面）：input/output 双键并存
            "input_tokens": int(pt),
            "output_tokens": int(ct),
            "chat_id": chat_id,
            "session_id": session_id,
            "turn_index": int(turn_index),
            "latency_ms": int(latency_ms),
            "stream_interrupted": bool(stream_interrupted),
            "api_call_id": _opt(usage, "call_id"),
        }
        self._store_usage(usage_data)

    _TURN_COUNTER_MAX = 2048

    @classmethod
    def _next_turn_index(cls, session_id: str | None) -> int:
        """该会话内的第 N 次模型调用（1 起）。

        B1 台账口径：``turn_index`` 是**调用序号**（不是 runner 的轮号字符串
        ——轮号另有 ``turn_id``，两者语义不同，不混用）。无会话 id 时返回 0，
        表示"未知轮"（诚实缺项，不猜 1）。计数表 FIFO 封顶，长驻服务不涨内存。
        """
        if not session_id:
            return 0
        counters = cls._turn_counters
        index = counters.get(session_id, 0) + 1
        counters[session_id] = index
        while len(counters) > cls._TURN_COUNTER_MAX:
            counters.pop(next(iter(counters)), None)
        return index

    @classmethod
    def pop_usage_for_session(cls, session_id: str) -> dict[str, Any] | None:
        return cls._usage_by_session.pop(session_id, None)

    def _store_usage(self, usage: dict[str, Any] | None) -> None:
        from ..config.session_context import get_current_session_id

        session_id = get_current_session_id()
        if session_id and usage:
            TokenRecordingModelWrapper._usage_by_session[session_id] = usage

    def _record_usage_to_db(
        self,
        input_tokens: int,
        output_tokens: int,
        *,
        chat_id: str | None = None,
        session_id: str | None = None,
        turn_index: int | None = None,
        latency_ms: int | None = None,
        stream_interrupted: bool | None = None,
    ) -> None:
        """Save token usage to SQLite database for per-user, per-agent tracking.

        逐轮列（chat_id/session_id/turn_index/latency_ms/stream_interrupted）
        是 B1 台账口径：每轮一行，缺项 NULL。落库失败只记日志（旁路设计，
        绝不把异常抛回聊天主链）。
        """
        try:
            from ..config.session_context import (
                get_current_agent_id,
                get_current_user_id,
                get_current_username,
            )
            from .db_writer import save_token_usage

            # Get agent_id from context (set by request handler)
            agent_id = get_current_agent_id()

            # Extract username from agent_id (format: "user:{username}")
            username = "anonymous"

            if agent_id and agent_id.startswith("user:"):
                username = agent_id[5:]  # Remove "user:" prefix
            # username 真值优先（会话 id 不是用户身份，不得充当）
            username = get_current_username() or username

            # user_id 是真凶（B1 实测）：token_usage.user_id 是 NOT NULL，
            # 此前恒传 None → 每次 INSERT 都 IntegrityError 被 debug 级吞掉，
            # 台账 0 行、tokens/cost 全 0。口径：请求上下文的用户 id 优先，
            # 其次登录名（与 username 同源），再次 agent_id 里的用户名。
            user_id = get_current_user_id()
            if not user_id and username != "anonymous":
                user_id = username
            if not user_id and agent_id and agent_id.startswith("user:"):
                user_id = agent_id[5:]
            if not user_id:
                logger.warning(
                    "本轮用量无法归属用户，跳过逐轮台账（chat_id=%s model=%s）。"
                    "请检查请求上下文是否设置 user_id/username。",
                    chat_id,
                    self.model_name,
                )
                return

            # Save to database
            save_token_usage(
                user_id=user_id,
                username=username,
                agent_id=agent_id,
                model=self.model_name,
                input_tokens=input_tokens,
                output_tokens=output_tokens,
                total_tokens=input_tokens + output_tokens,
                cost_cents=_compute_cost_cents(
                    self._provider_id,
                    self.model_name,
                    int(input_tokens),
                    int(output_tokens),
                ),
                provider_id=self._provider_id,
                chat_id=chat_id,
                session_id=session_id,
                turn_index=turn_index,
                latency_ms=latency_ms,
                stream_interrupted=stream_interrupted,
            )
            
        except Exception as e:
            # Don't let database errors break the main flow
            import logging
            logging.getLogger(__name__).debug("Failed to record token usage to DB: %s", e)

    async def __call__(
        self,
        messages: list[dict],
        tools: list[dict] | None = None,
        tool_choice: Literal["auto", "none", "required"] | str | None = None,
        structured_model: Type[BaseModel] | None = None,
        **kwargs: Any,
    ) -> ChatResponse | AsyncGenerator[ChatResponse, None]:
        # Fix: Omit tool_choice="auto" for some OpenAI-compatible servers
        # Some servers without auto-tool-choice support will reject requests when
        # tool_choice="auto" is present, even if tools are provided.
        # By omitting tool_choice when it's "auto", we bypass the check
        # while keeping tools available for correct tool calling behavior.
        if tool_choice == "auto":
            tool_choice = None

        started = time.perf_counter()
        # D16：流式请求带 usage（feature flag + 网关不认时自动降级一次）
        kwargs = self._with_stream_usage(kwargs)
        try:
            result = await self._model(
                messages=messages,
                tools=tools,
                tool_choice=tool_choice,
                structured_model=structured_model,
                **kwargs,
            )
        except Exception as exc:
            if "stream_options" not in kwargs:
                raise
            from .turn_usage import remember_stream_usage_unsupported

            remember_stream_usage_unsupported(self._provider_id, self.model_name)
            logger.warning(
                "TokenRecordingModelWrapper: 网关不认 stream_options，"
                "已摘掉重试 (%s/%s): %s",
                self._provider_id,
                self.model_name,
                exc,
            )
            kwargs.pop("stream_options", None)
            result = await self._model(
                messages=messages,
                tools=tools,
                tool_choice=tool_choice,
                structured_model=structured_model,
                **kwargs,
            )

        if isinstance(result, AsyncGenerator):
            return self._wrap_stream(result, started=started)
        usage = getattr(result, "usage", None)
        if usage is not None:
            self._record_usage(
                usage,
                latency_ms=int((time.perf_counter() - started) * 1000),
                stream_interrupted=False,
            )
        return result

    async def _wrap_stream(
        self,
        stream: AsyncGenerator[ChatResponse, None],
        *,
        started: float | None = None,
    ) -> AsyncGenerator[ChatResponse, None]:
        last_usage: ChatUsage | None = None
        # 默认视为中断：只有生成器被正常耗尽（消费者读到
        # StopAsyncIteration）才置 False。客户端断连/取消/异常都落在
        # "中断"侧——中断收口（B2）与判官对账都依赖这个标记。
        interrupted = True
        t0 = started if started is not None else time.perf_counter()
        try:
            async for chunk in stream:
                if getattr(chunk, "usage", None) is not None:
                    last_usage = chunk.usage
                yield chunk
            interrupted = False
        finally:
            if interrupted:
                self._mark_turn_interrupted()
            if last_usage is not None:
                self._record_usage(
                    last_usage,
                    latency_ms=int((time.perf_counter() - t0) * 1000),
                    stream_interrupted=interrupted,
                )

def _compute_cost_cents(
    provider_id: str | None,
    model_name: str,
    input_tokens: int,
    output_tokens: int,
) -> float:
    """成本真值：provider 模型带定价（每百万 token 单价）则计算，无定价 = 0。

    内网/私有部署模型没有定价是**事实**——记 0 是诚实值；缺项语义由
    逐轮列的 NULL 表达，不在 cost 上造假。
    """
    if not provider_id:
        return 0.0
    try:
        from ..providers.provider_manager import ProviderManager

        manager = ProviderManager.get_instance()
        if manager is None:
            return 0.0
        provider = manager.get_provider(provider_id)
        if provider is None:
            return 0.0
        models = getattr(provider, "list_models", None)
        if not callable(models):
            return 0.0
        for model in models():
            name = (
                model.get("name")
                if isinstance(model, dict)
                else getattr(model, "name", None)
            )
            if name != model_name:
                continue
            pricing = (
                model.get("pricing")
                if isinstance(model, dict)
                else getattr(model, "pricing", None)
            )
            if not isinstance(pricing, dict):
                return 0.0
            in_rate = float(pricing.get("input") or 0)
            out_rate = float(pricing.get("output") or 0)
            cents = (input_tokens * in_rate + output_tokens * out_rate) / 1_000_000 * 100
            return round(float(cents), 4)
    except Exception:
        return 0.0
    return 0.0
