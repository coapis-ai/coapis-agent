# -*- coding: utf-8 -*-
"""一次性预览票据（预览窗口方案 D6）

背景（实测）：预览/下载直链是 ``/api/myfiles/preview?path=x&token=<JWT>``，
JWT 有效期 24h 且**明文躺在 URL 里** —— 浏览器历史、访问日志、Referer 全都能捞到，
等于把 24 小时的全局凭证挂在每一条文件链接上。

本模块给出治本形态：**签发即焚的一次性短票据**。

- 票据由已登录会话（走 header 认证）签发，绑定 ``(username, path, category, mode)``；
- 有效期 :data:`TTL_SECONDS`（60 秒），**兑换一次即失效**；
- 兑换端点不携带任何长期凭证，URL 泄露的可用窗口 ≤ 60 秒且已被消费。

内存态即可：票据只在「签发 → 浏览器发起请求」这一跳里存活，进程重启后
未兑换的票据作废（前端会重新签发），无需持久化。
"""
from __future__ import annotations

import secrets
import threading
import time
from typing import NamedTuple, Optional

# 票据有效期（秒）。够一次页面加载用，短到泄露后基本无用。
TTL_SECONDS = 60

# 内存驻留上限：签发后用户关页面就不会有兑换，靠这个上限兜住内存。
MAX_LIVE = 4000

# 允许的兑换方式
MODE_PREVIEW = "preview"
MODE_DOWNLOAD = "download"
VALID_MODES = (MODE_PREVIEW, MODE_DOWNLOAD)


class Ticket(NamedTuple):
    """一张已签发的票据。"""

    username: str
    path: str
    category: str
    mode: str
    expires: float


_lock = threading.Lock()
_store: dict[str, Ticket] = {}


def _sweep_locked(now: float) -> None:
    """清掉过期票据（调用方持锁）。"""
    for key in [k for k, v in _store.items() if v.expires < now]:
        _store.pop(key, None)


def issue(username: str, path: str, category: str, mode: str) -> tuple[str, int]:
    """为 ``(username, path, category, mode)`` 签发一张一次性票据。

    Returns:
        ``(token, ttl_seconds)``
    """
    if mode not in VALID_MODES:
        raise ValueError(f"非法票据模式: {mode!r}")
    token = secrets.token_urlsafe(24)
    now = time.time()
    with _lock:
        _sweep_locked(now)
        # 驻留超限时按最早过期淘汰（签发频率远高于兑换频率时兜底）
        overflow = len(_store) - MAX_LIVE + 1
        if overflow > 0:
            for key, _ in sorted(_store.items(), key=lambda kv: kv[1].expires)[:overflow]:
                _store.pop(key, None)
        _store[token] = Ticket(
            username=username,
            path=path,
            category=category,
            mode=mode,
            expires=now + TTL_SECONDS,
        )
    return token, TTL_SECONDS


def redeem(token: str, mode: str) -> Optional[Ticket]:
    """兑换票据：**无论成功失败票据即失效**（一次性）。

    Returns:
        票据内容；票据不存在/已用过/已过期/模式不符时返回 ``None``。
    """
    if not token:
        return None
    with _lock:
        ticket = _store.pop(token, None)
    if ticket is None:
        return None
    if ticket.expires < time.time():
        return None
    if ticket.mode != mode:
        return None
    return ticket


def live_count() -> int:
    """当前驻留票据数（测试与自检用）。"""
    with _lock:
        return len(_store)


def reset() -> None:
    """清空票据表（测试用）。"""
    with _lock:
        _store.clear()
