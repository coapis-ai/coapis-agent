# -*- coding: utf-8 -*-
"""判断结论缓存（一期）。

缓存的是**判断结论**，不是用户原文（v13 第 15 章 D3 红线）：键里只落
sha256 指纹，值里只有结论（技能名 / 复杂度档位）。键带岗位 + 作用域，
保证跨用户、跨智能体不串味。

TTL/容量是代码常量（300s / 512），不作为配置项暴露。
"""
from __future__ import annotations

import hashlib
import time
from collections import OrderedDict
from typing import Any, Callable, Iterable, Optional

from .config import DecisionHubConfig

#: 结论缓存默认 TTL（秒）与容量
DEFAULT_TTL_S = 300.0
DEFAULT_MAX_ENTRIES = 512
#: 多值拼接分隔符（不可打印字符，避免与内容本身冲突）
_SEP = "\u241f"


def _sha(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8", "replace")).hexdigest()


class TTLCache:
    """带 TTL 的 LRU 结论缓存。"""

    def __init__(self, max_entries: int = DEFAULT_MAX_ENTRIES, ttl_s: float = DEFAULT_TTL_S) -> None:
        self.max_entries = max(1, int(max_entries))
        self.ttl_s = float(ttl_s)
        #: key -> (expires_at, value)
        self._data: "OrderedDict[str, tuple[float, Any]]" = OrderedDict()

    def get(self, key: str) -> Any | None:
        item = self._data.get(key)
        if item is None:
            return None
        expires, value = item
        if time.monotonic() >= expires:
            self._data.pop(key, None)
            return None
        self._data.move_to_end(key)
        return value

    def put(self, key: str, value: Any) -> None:
        if self.ttl_s <= 0:
            return
        self._data[key] = (time.monotonic() + self.ttl_s, value)
        self._data.move_to_end(key)
        while len(self._data) > self.max_entries:
            self._data.popitem(last=False)

    def clear(self) -> None:
        self._data.clear()

    def __len__(self) -> int:
        return len(self._data)


_cache: Optional[TTLCache] = None


def get_judgment_cache() -> TTLCache:
    """进程内单例缓存（参数取判断中枢配置）。"""
    global _cache
    if _cache is None:
        cfg = DecisionHubConfig.from_env().normalized()
        _cache = TTLCache(max_entries=cfg.cache_max_entries, ttl_s=cfg.cache_ttl_s)
    return _cache


def reset_judgment_cache() -> None:
    """清空并释放单例缓存（测试/运维用）。"""
    global _cache
    if _cache is not None:
        _cache.clear()
    _cache = None


def make_cache_key(
    source: str,
    text: str,
    candidates: Iterable[str] | None = None,
    user_id: str = "",
    agent_id: str = "",
) -> str:
    """结论缓存键：岗位 + 内容指纹 + 候选集合指纹 + 作用域指纹。

    只落 sha256，**不落原文**（D3 红线）。作用域（用户/智能体）进键，
    保证跨用户、跨智能体的判断结论不互相命中。
    """
    parts = [source, _sha(text)]
    cand = sorted(str(c) for c in (candidates or ()))
    if cand:
        parts.append(_sha(_SEP.join(cand)))
    if user_id or agent_id:
        parts.append(_sha(f"u={user_id}\u241fa={agent_id}"))
    return _SEP.join(parts)


def get_cached_judgment(key: str, cache: TTLCache | None = None) -> Any | None:
    """读缓存（未命中返回 None）。"""
    # TTLCache 定义了 __len__，空缓存是「假值」——必须用 is not None 判定，
    # 否则显式传入的空缓存会被静默换成进程级缓存（跨请求串味）。
    target = cache if cache is not None else get_judgment_cache()
    return target.get(key)


def put_cached_judgment(key: str, value: Any, cache: TTLCache | None = None) -> None:
    """写缓存。空结论不缓存——未命中是常态，缓存只存命中结果。"""
    if not value:
        return
    target = cache if cache is not None else get_judgment_cache()
    target.put(key, value)


def cached_judgment(
    key: str,
    compute: Callable[[], Any],
    cache: TTLCache | None = None,
) -> tuple[Any, bool]:
    """命中返回 ``(值, True)``；未命中计算后缓存，返回 ``(值, False)``。

    空结论不缓存（未命中是常态，缓存只存命中结果）。
    """
    store = cache or get_judgment_cache()
    hit = store.get(key)
    if hit is not None:
        return hit, True
    value = compute()
    if value:
        store.put(key, value)
    return value, False


__all__ = [
    "TTLCache",
    "get_judgment_cache",
    "reset_judgment_cache",
    "make_cache_key",
    "get_cached_judgment",
    "put_cached_judgment",
    "cached_judgment",
    "DEFAULT_TTL_S",
    "DEFAULT_MAX_ENTRIES",
]
