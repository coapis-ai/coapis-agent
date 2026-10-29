# -*- coding: utf-8 -*-
"""智能判断中枢（一期骨架）。

一期只做三件事（v13 第 15 章范围）：

1. **判断模型自动跟随会话模型**（复用 active_model，零配置）——
   :func:`get_judgment_provider_config`
2. **判断日志进台账**（同库、status 三态可查）—— :class:`DecisionBus`
3. **判断模型不可用自动降级**（熔断 + 超时，绝不卡死）—— :class:`CircuitBreaker`

红线：判断是旁路能力，**永不抛异常、永不阻塞消息路径**；指纹不落原文。
"""
from __future__ import annotations

from .breaker import CircuitBreaker, get_breaker, make_breaker_from_config
from .bus import DecisionBus, get_bus, set_bus
from .cache import (
    TTLCache,
    cached_judgment,
    get_cached_judgment,
    get_judgment_cache,
    make_cache_key,
    put_cached_judgment,
    reset_judgment_cache,
)
from .config import DecisionHubConfig
from .resolver import get_judgment_provider_config
from .types import (
    Action,
    Complexity,
    DecisionResult,
    DecisionSource,
    Outcome,
    content_fingerprint,
    file_fingerprint,
)

__all__ = [
    "DecisionHubConfig",
    "DecisionResult",
    "Complexity",
    "Action",
    "Outcome",
    "DecisionSource",
    "content_fingerprint",
    "file_fingerprint",
    "get_judgment_provider_config",
    "TTLCache",
    "get_judgment_cache",
    "reset_judgment_cache",
    "make_cache_key",
    "get_cached_judgment",
    "put_cached_judgment",
    "cached_judgment",
    "CircuitBreaker",
    "get_breaker",
    "make_breaker_from_config",
    "DecisionBus",
    "get_bus",
    "set_bus",
]
