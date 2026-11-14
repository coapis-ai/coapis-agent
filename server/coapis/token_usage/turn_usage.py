# -*- coding: utf-8 -*-
"""轮次级 usage 计算（B1 · 借鉴 QwenPaw ``token_usage/turn_usage.py``）。

**为什么需要这个模块**（实测 2026-11-13，``.analysis/实测底数-20261113.txt``）：
判官台账 241 行里 ``cost_cents`` 恒 0、tokens 大量取不到；流式调用不回传 usage
（我们的请求体从来没带 ``stream_options.include_usage``）。聚合面
（``buffer.py`` 的日聚合）已成熟，缺的是**逐轮**这一层。

**架构红线（实施方案 §3）**：不引入第二个持久层。本模块**只做计算与只读**，
持久化仍由 ``buffer → storage/db_writer`` 与聊天侧 ``context_usage`` 各自负责。
"""
from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Any, Iterable, Optional

__all__ = [
    "TurnUsage",
    "stream_usage_requested",
    "stream_usage_kwargs",
    "stream_usage_supported",
    "remember_stream_usage_unsupported",
    "resolve_turn_usage",
    "write_turn_usage_meta",
    "reconcile_turn_completion_from_stats",
    "mark_turn_interrupted",
    "turn_was_interrupted",
]

_STREAM_USAGE_FLAG = "COAPIS_STREAM_USAGE"
_UNSAFE = frozenset("\x00\n\r\t")


def _safe_text(value: Any, limit: int = 512) -> str:
    """落库前清洗成可读纯文本（借鉴上游：换行/NUL 不进元数据）。"""
    text = str(value if value is not None else "").strip()
    for ch in ("\x00", "\n", "\r", "\t"):
        text = text.replace(ch, " ")
    return text[:limit]


# ---------------------------------------------------------------- 开关 (D16)
def stream_usage_requested() -> bool:
    """是否请求流式 usage（D16：feature flag，默认开）。

    ``COAPIS_STREAM_USAGE=0`` 可整体关掉（网关不认时的应急阀门）。
    """
    return os.environ.get(_STREAM_USAGE_FLAG, "1").strip().lower() not in (
        "0",
        "false",
        "no",
        "off",
    )


# 进程级"这个网关/模型不认 stream_options"记忆（D16 自动降级）
_UNSUPPORTED: set[tuple[str, str]] = set()
_UNSUPPORTED_MAX = 256


def remember_stream_usage_unsupported(provider_id: str, model: str) -> None:
    key = (_safe_text(provider_id, 64), _safe_text(model, 128))
    if len(_UNSUPPORTED) >= _UNSUPPORTED_MAX:
        _UNSUPPORTED.pop(next(iter(_UNSUPPORTED)))
    _UNSUPPORTED.add(key)


def stream_usage_supported(provider_id: str, model: str) -> bool:
    return (
        (_safe_text(provider_id, 64), _safe_text(model, 128)) not in _UNSUPPORTED
    )


def stream_usage_kwargs(provider_id: str, model: str) -> dict[str, Any]:
    """需要注入的流式 usage 参数；不该注入时返回空 dict。

    只读调用方，不改传入字典。非流式 / 关旗 / 已知不支持 → 空。
    """
    if not stream_usage_requested():
        return {}
    if not stream_usage_supported(provider_id, model):
        return {}
    return {"stream_options": {"include_usage": True}}


# ------------------------------------------------------------------ TurnUsage
@dataclass
class TurnUsage:
    """单轮模型调用的 token 用量。

    ``turns`` = prompt 侧统计的 assistant 轮数（**模型角色计数**，不是聊天轮数），
    ``context_tokens`` = 本轮上下文规模，``max_input_tokens`` = 该模型的输入上限
    （由调用方传入，不在此猜）。
    """

    prompt_tokens: int = 0
    completion_tokens: int = 0
    turns: int = 0
    context_tokens: int = 0
    max_input_tokens: int = 0

    @property
    def total_tokens(self) -> int:
        return self.prompt_tokens + self.completion_tokens

    @property
    def use_ratio(self) -> float:
        """上下文占用率（0~1）；无上限时 0（诚实缺项，不猜满）。"""
        if self.max_input_tokens <= 0:
            return 0.0
        return min(1.0, self.context_tokens / self.max_input_tokens)

    def to_meta_dict(self) -> dict[str, Any]:
        return {
            "prompt_tokens": self.prompt_tokens,
            "completion_tokens": self.completion_tokens,
            "total_tokens": self.total_tokens,
            "turns": self.turns,
            "context_tokens": self.context_tokens,
            "max_input_tokens": self.max_input_tokens,
            "use_ratio": round(self.use_ratio, 4),
        }


def count_assistant_turns(messages: Iterable[dict[str, Any]]) -> int:
    """统计 ``role == "assistant"`` 的消息数。

    ⚠️ 口径声明（借鉴上游时的坑）：这是**模型角色计数**，与聊天轮数、
    与资源台账的 ``turn_id`` 都不是一个东西，三者不得混用。
    """
    return sum(1 for m in messages if m.get("role") == "assistant")


def _estimate_context_tokens(messages: Iterable[dict[str, Any]]) -> int:
    """无 usage 时的上下文估算（≈ chars/4，向上取整）。

    只在**上游没给真数**时兜底，且明确标注为估算——绝不冒充真值。
    """
    chars = 0
    for msg in messages:
        content = msg.get("content")
        if isinstance(content, str):
            chars += len(content)
        elif content is not None:
            chars += len(str(content))
    return (chars + 3) // 4


def resolve_turn_usage(
    *,
    response_usage: Any = None,
    request_messages: Iterable[dict[str, Any]],
    max_input_tokens: int = 0,
    model: str = "",
    provider_id: str = "",
) -> TurnUsage:
    """把一次调用的用量解析成 :class:`TurnUsage`，绝不让取数把主链炸了。

    ``response_usage`` 兼容三种形状：agentscope ``ChatUsage`` 对象、
    OpenAI 原始 dict（``prompt_tokens``/``completion_tokens``）、``None``。
    取不到真数时用字符估算兜底，并保证 ``context_tokens >= prompt_tokens``
    （上下文规模不可能小于本轮输入）。
    """
    msgs = list(request_messages)
    turns = count_assistant_turns(msgs)
    estimated_context = _estimate_context_tokens(msgs)

    prompt_tokens = 0
    completion_tokens = 0
    got_real = False

    if response_usage is not None:
        try:
            prompt_tokens = int(
                getattr(response_usage, "input_tokens", 0)
                or (
                    response_usage.get("prompt_tokens", 0)
                    if isinstance(response_usage, dict)
                    else 0
                )
                or 0,
            )
            completion_tokens = int(
                getattr(response_usage, "output_tokens", 0)
                or (
                    response_usage.get("completion_tokens", 0)
                    if isinstance(response_usage, dict)
                    else 0
                )
                or 0,
            )
            got_real = prompt_tokens > 0 or completion_tokens > 0
        except Exception:  # 上游自定义 __getattr__ 会抛 KeyError
            got_real = False

    context_tokens = max(prompt_tokens, estimated_context)
    if not got_real:
        # 估算兜底：prompt 侧用上下文估算，明确不是上游真值
        prompt_tokens = estimated_context

    usage = TurnUsage(
        prompt_tokens=max(0, prompt_tokens),
        completion_tokens=max(0, completion_tokens),
        turns=turns,
        context_tokens=max(0, context_tokens),
        max_input_tokens=max(0, int(max_input_tokens or 0)),
    )
    _ = model, provider_id  # 供调用方日志定位用，此处不参与计算
    return usage


def _empty_meta(model_name: str) -> dict[str, int]:
    return {
        "model_name": _safe_text(model_name, 128),
        "prompt_tokens": 0,
        "completion_tokens": 0,
        "total_tokens": 0,
        "context_tokens": 0,
        "turns": 0,
        "max_input_tokens": 0,
        "use_ratio": 0.0,
    }


def write_turn_usage_meta(
    session_id: str,
    chat_id: str = "",
    usage: TurnUsage | None = None,
    *,
    model_name: str = "",
) -> dict[str, int]:
    """构造可写入聊天侧 ``context_usage`` 的元数据（**不自己落库**）。

    落库由聊天侧既有通路负责；本函数只产出结构化 dict，空值返回全 0 结构。
    """
    _ = session_id, chat_id
    meta = _empty_meta(model_name)
    if usage is None:
        return meta
    meta.update(usage.to_meta_dict())
    meta["model_name"] = _safe_text(model_name, 128) or meta["model_name"]
    return meta


def reconcile_turn_completion_from_stats(
    stats: dict[str, Any],
    *,
    model_name: str = "",
) -> dict[str, int]:
    """会话收尾统计与逐轮台账对账（借鉴上游同名函数）。

    ``stats`` 缺失/类型不对时返回全 0 结构，**绝不抛异常**——收尾对账
    发生在请求尾部，抛异常等于把用户的对话打断。
    """
    meta = _empty_meta(model_name)
    if not isinstance(stats, dict):
        return meta
    try:
        prompt = int(stats.get("prompt_tokens") or stats.get("input_tokens") or 0)
        completion = int(
            stats.get("completion_tokens") or stats.get("output_tokens") or 0,
        )
        meta["prompt_tokens"] = max(0, prompt)
        meta["completion_tokens"] = max(0, completion)
        meta["total_tokens"] = meta["prompt_tokens"] + meta["completion_tokens"]
        meta["context_tokens"] = max(
            meta["prompt_tokens"],
            int(stats.get("context_tokens") or 0),
        )
        meta["turns"] = max(0, int(stats.get("turns") or 0))
        meta["max_input_tokens"] = max(0, int(stats.get("max_input_tokens") or 0))
        meta["use_ratio"] = round(float(stats.get("use_ratio") or 0.0), 4)
    except Exception:
        return _empty_meta(model_name)
    return meta


# --------------------------------------------------------------- 中断标记
_INTERRUPTED: dict[str, bool] = {}
_INTERRUPTED_MAX = 2048


def mark_turn_interrupted(chat_id: str) -> None:
    """标记"该会话最近一轮被中断/未正常收尾"（进程内，FIFO 封顶）。

    持久真值在 ``token_usage.stream_interrupted`` 列；这里是给"消息元数据"
    用的即时通道（落库消息与写台账不在同一个调用里）。
    """
    key = _safe_text(chat_id, 128)
    if not key:
        return
    if len(_INTERRUPTED) >= _INTERRUPTED_MAX:
        _INTERRUPTED.pop(next(iter(_INTERRUPTED)))
    _INTERRUPTED[key] = True


def clear_turn_interrupted(chat_id: str) -> None:
    _INTERRUPTED.pop(_safe_text(chat_id, 128), None)


def turn_was_interrupted(chat_id: str) -> bool:
    return bool(_INTERRUPTED.get(_safe_text(chat_id, 128)))


def optional_int(value: Any) -> Optional[int]:
    """可选整数（借鉴上游同名工具，供元数据/接口层复用）。"""
    if value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None
