# -*- coding: utf-8 -*-
# Copyright 2026 蜜蜂 & CoApis Contributors
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

"""HTTP client tool — make HTTP requests to external APIs.

Complements web_search (searching) with general-purpose HTTP capability:
GET, POST, PUT, DELETE, PATCH with timeout, retries, and header management.
"""

from __future__ import annotations

import json
import logging
import time
from typing import Any

from .registry import register_tool

logger = logging.getLogger(__name__)

# Defaults
_DEFAULT_TIMEOUT = 60
_MAX_RETRIES = 3
_MAX_RESPONSE_SIZE = 500_000  # 500KB

# Blocked URL patterns (security)
_BLOCKED_PATTERNS = [
    "localhost",
    "127.0.0.1",
    "0.0.0.0",
    "169.254.169.254",  # AWS metadata
    "metadata.google.internal",  # GCP metadata
]

# Private RFC ranges for IP-based blocking
_PRIVATE_IPV4_PREFIXES = [
    "10.",       # 10.0.0.0/8
    "172.16.",   # 172.16.0.0/12 (simplified first match)
    "172.17.",
    "172.18.",
    "172.19.",
    "172.20.",
    "172.21.",
    "172.22.",
    "172.23.",
    "172.24.",
    "172.25.",
    "172.26.",
    "172.27.",
    "172.28.",
    "172.29.",
    "172.30.",
    "172.31.",
    "192.168.",  # 192.168.0.0/16
]


def _is_blocked_url(url: str) -> bool:
    """Check if URL targets a blocked internal endpoint (string + IP ranges)."""
    url_lower = url.lower()
    # String pattern match
    for pattern in _BLOCKED_PATTERNS:
        if pattern in url_lower:
            return True
    # IPv4 private range match
    import re
    m = re.search(r"https?://([0-9.]+)", url_lower)
    if m:
        ip = m.group(1)
        for prefix in _PRIVATE_IPV4_PREFIXES:
            if ip.startswith(prefix):
                return True
    # IPv6 private/link-local
    if "[:\\[]fe80:" in url_lower or "[:\\[]fd" in url_lower or "[:\\[]fc" in url_lower:
        return True
    return False


async def _do_request(
    method: str,
    url: str,
    headers: dict | None = None,
    body: str | None = None,
    timeout: int = _DEFAULT_TIMEOUT,
    retries: int = _MAX_RETRIES,
) -> dict[str, Any]:
    """Execute HTTP request with retries."""
    import httpx

    last_error = None
    for attempt in range(retries):
        try:
            async with httpx.AsyncClient(
                timeout=timeout,
                follow_redirects=True,
                verify=True,
            ) as client:
                kwargs: dict[str, Any] = {"headers": headers or {}}

                # Parse body
                if body:
                    try:
                        kwargs["content"] = body.encode("utf-8")
                    except Exception:
                        kwargs["content"] = body.encode("utf-8", errors="replace")

                start = time.time()
                resp = await client.request(method, url, **kwargs)
                elapsed = round(time.time() - start, 3)

                # Read response
                resp_text = resp.text[:_MAX_RESPONSE_SIZE] if resp.text else ""
                truncated = len(resp.text) > _MAX_RESPONSE_SIZE

                # Try to parse JSON
                resp_json = None
                try:
                    resp_json = resp.json()
                except Exception:
                    pass

                return {
                    "status_code": resp.status_code,
                    "headers": dict(resp.headers),
                    "body": resp_text,
                    "json": resp_json,
                    "elapsed_seconds": elapsed,
                    "truncated": truncated,
                    "attempt": attempt + 1,
                    "url": str(resp.url),
                }

        except httpx.TimeoutException as e:
            last_error = f"超时 ({timeout}s): {e}"
            logger.warning(f"HTTP timeout attempt {attempt+1}: {e}")
        except httpx.ConnectError as e:
            last_error = f"连接失败: {e}"
            logger.warning(f"HTTP connect error attempt {attempt+1}: {e}")
        except Exception as e:
            last_error = f"请求失败: {type(e).__name__}: {e}"
            logger.warning(f"HTTP error attempt {attempt+1}: {e}")

        # Wait before retry (exponential backoff)
        if attempt < retries - 1:
            import asyncio
            await asyncio.sleep(min(2 ** attempt, 10))

    return {"error": last_error or "请求失败", "attempt": retries}


async def http_client(
    method: str = "GET",
    url: str = "",
    headers: str = "",
    body: str = "",
    timeout: int = _DEFAULT_TIMEOUT,
    retries: int = 3,
) -> dict[str, Any]:
    # Coerce string args from LLM function calling to correct types
    try:
        timeout = int(timeout)
    except (ValueError, TypeError):
        timeout = _DEFAULT_TIMEOUT
    try:
        retries = int(retries)
    except (ValueError, TypeError):
        retries = 3
    """HTTP 客户端。

    支持 GET/POST/PUT/DELETE/PATCH 请求，带超时和自动重试。

    Args:
        method: HTTP 方法 (GET/POST/PUT/DELETE/PATCH)
        url: 请求 URL（必须是 http:// 或 https://）
        headers: 请求头（JSON 格式字符串）
        body: 请求体（POST/PUT/PATCH 时使用）
        timeout: 超时时间（秒），默认 30
        retries: 最大重试次数，默认 3

    Returns:
        响应结果（status_code/headers/body/json/elapsed_seconds）
    """
    # Validate method
    method = method.upper().strip()
    if method not in ("GET", "POST", "PUT", "DELETE", "PATCH", "HEAD", "OPTIONS"):
        return {"error": f"不支持的 HTTP 方法: {method}，支持 GET/POST/PUT/DELETE/PATCH"}

    # Validate URL
    url = url.strip()
    if not url:
        return {"error": "URL 不能为空"}
    if not url.startswith(("http://", "https://")):
        return {"error": f"URL 必须以 http:// 或 https:// 开头: {url}"}

    # Security: block internal endpoints
    if _is_blocked_url(url):
        return {"error": f"禁止访问内部端点: {url}"}

    # Validate retries
    retries = max(1, min(retries, 5))

    # Parse headers
    parsed_headers: dict[str, str] = {}
    if headers.strip():
        try:
            parsed = json.loads(headers)
            if isinstance(parsed, dict):
                parsed_headers = {str(k): str(v) for k, v in parsed.items()}
        except json.JSONDecodeError:
            return {"error": f"headers 不是有效的 JSON: {headers[:100]}"}

    # Add default User-Agent
    if "user-agent" not in {k.lower() for k in parsed_headers}:
        parsed_headers["User-Agent"] = "CoApis/0.7 HTTP-Client"

    result = await _do_request(
        method=method,
        url=url,
        headers=parsed_headers,
        body=body if body.strip() else None,
        timeout=timeout,
        retries=retries,
    )

    if "error" in result:
        return result

    return {
        "method": method,
        "url": url,
        "status_code": result["status_code"],
        "headers": result["headers"],
        "body": result["body"][:2000] if result["body"] else "",
        "json": result["json"],
        "elapsed_seconds": result["elapsed_seconds"],
        "truncated": result["truncated"],
        "attempt": result["attempt"],
        "final_url": result["url"],
    }
