# -*- coding: utf-8 -*-
"""MCP 出站 HTTP 完整请求/响应日志。

每个 MCP 客户端发出的 HTTP 请求都会追加到
``{WORKING_DIR}/logs/mcp_access.log``，包含完整的请求头、请求体、
响应状态、响应头和响应体，供外部服务（如 OA 的 MCP Server）从我们
这一侧定位认证/协议问题。

环境变量（面向排障，默认开启、默认不脱敏）：
- ``COAPIS_MCP_ACCESS_LOG``           : "on"/"off"，总开关（默认 on）
- ``COAPIS_MCP_ACCESS_LOG_MASK_AUTH`` : "on"/"off"，对 Authorization /
                                        Cookie 等鉴权头的取值打码
                                        （默认 off —— 完整保真，便于
                                        OA 服务端核对 token）
- ``COAPIS_MCP_ACCESS_LOG_MAX_BODY``  : 单个 body 的最大记录字节数
                                        （默认 65536，超出截断）

注意：
- 仅在开发环境使用。生产部署前应显式关闭或评估脱敏。
- SSE 流式响应不会被读取正文（读了会吃掉事件流），只记录请求侧。
"""

from __future__ import annotations

import logging
import os
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Optional

try:
    import httpx
except ImportError:  # pragma: no cover
    httpx = None  # type: ignore[assignment]

from ...constant import WORKING_DIR

_LOG_NAME = "coapis.mcp.access"
_MAX_BODY_DEFAULT = 65536
_SENSITIVE_HEADERS = ("authorization", "cookie", "x-api-key", "proxy-authorization")


def _env_flag(name: str, default: bool = False) -> bool:
    val = os.environ.get(name, "").strip().lower()
    if not val:
        return default
    return val in ("1", "on", "true", "yes")


def _max_body() -> int:
    try:
        return int(os.environ.get("COAPIS_MCP_ACCESS_LOG_MAX_BODY", "") or _MAX_BODY_DEFAULT)
    except ValueError:
        return _MAX_BODY_DEFAULT


def _enabled() -> bool:
    return _env_flag("COAPIS_MCP_ACCESS_LOG", default=True)


def _mask_auth() -> bool:
    return _env_flag("COAPIS_MCP_ACCESS_LOG_MASK_AUTH", default=False)


_logger: Optional[logging.Logger] = None


def _get_logger() -> logging.Logger:
    """懒初始化：独立 FileHandler 写到 logs/mcp_access.log。"""
    global _logger
    if _logger is not None:
        return _logger
    lg = logging.getLogger(_LOG_NAME)
    lg.setLevel(logging.INFO)
    lg.propagate = False
    if not lg.handlers:
        log_dir = Path(WORKING_DIR) / "logs"
        try:
            log_dir.mkdir(parents=True, exist_ok=True)
            handler = logging.FileHandler(log_dir / "mcp_access.log", encoding="utf-8")
            handler.setFormatter(logging.Formatter("%(asctime)s %(message)s"))
            lg.addHandler(handler)
        except OSError:
            lg.addHandler(logging.NullHandler())
    _logger = lg
    return lg


def _decode_body(data: bytes, limit: int) -> str:
    if not data:
        return "<empty>"
    if len(data) > limit:
        return data[:limit].decode("utf-8", errors="replace") + f"...[truncated, total {len(data)} bytes]"
    return data.decode("utf-8", errors="replace")


def _format_headers(headers: Any) -> str:
    lines = []
    try:
        items = list(headers.items())
    except AttributeError:  # pragma: no cover
        return repr(headers)
    for key, value in items:
        if _mask_auth() and key.lower() in _SENSITIVE_HEADERS:
            value = "***MASKED***"
        lines.append(f"  {key}: {value}")
    return "\n".join(lines) if lines else "  <none>"


def _now_iso() -> str:
    return datetime.now(timezone.utc).astimezone().isoformat(timespec="milliseconds")


def make_request_hook(server_name: str) -> Callable[..., None]:
    """构造 httpx request 钩子：记录完整出站请求。

    同时把发出时刻挂在 response.extensions 上，供响应钩子算耗时。
    """

    async def _hook(request: "httpx.Request") -> None:
        # httpx >=0.27 无条件 await 事件钩子，同步钩子会导致
        # "object NoneType can't be used in 'await' expression"，
        # 使整个 MCP 握手在发送前崩溃，故此处必须为协程。
        if not _enabled():
            return
        lg = _get_logger()
        try:
            limit = _max_body()
            entry = (
                f"\n========== MCP ACCESS [{server_name}] ==========\n"
                f"phase   : request\n"
                f"ts      : {_now_iso()}\n"
                f"method  : {request.method}\n"
                f"url     : {request.url}\n"
                f"headers :\n{_format_headers(request.headers)}\n"
                f"body    : {_decode_body(bytes(request.content), limit)}\n"
                f"--------------------------------------------------"
            )
            lg.info(entry)
        except Exception as exc:  # 日志失败绝不影响业务
            lg.warning("mcp access log request failed: %s", exc)
        # 挂出发时刻（httpx 允许在 extensions 里塞任意键）
        try:
            request.extensions["coapis_req_start"] = time.monotonic()
        except Exception:  # pragma: no cover
            pass

    return _hook


def make_response_hook(server_name: str) -> Callable[..., Any]:
    """构造 httpx response 钩子：记录状态/头/正文（异步）。

    仅用于 streamable-http 传输；SSE 流式响应禁止读正文。
    """

    async def _hook(response: "httpx.Response") -> None:
        if not _enabled():
            return
        lg = _get_logger()
        try:
            ctype = (response.headers.get("content-type") or "").lower()
            if "text/event-stream" in ctype:
                body_repr = "<streaming event-stream, body not captured>"
            else:
                await response.aread()
                body_repr = _decode_body(response.content, _max_body())
            start = None
            try:
                start = response.extensions.get("coapis_req_start")
            except Exception:
                start = None
            elapsed = (
                f"{(time.monotonic() - start) * 1000:.1f}" if start is not None else "?"
            )
            entry = (
                f"phase   : response\n"
                f"status  : {response.status_code}\n"
                f"elapsed_ms: {elapsed}\n"
                f"headers :\n{_format_headers(response.headers)}\n"
                f"body    : {body_repr}\n"
                f"========================================\n"
            )
            lg.info(entry)
        except Exception as exc:  # 日志失败绝不影响业务
            lg.warning("mcp access log response failed: %s", exc)

    return _hook
