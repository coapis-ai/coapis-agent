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

"""Built-in web search tool with Tavily + DDGS fallback.

Provides a unified ``web_search`` tool that tries Tavily first (AI-powered
search with good snippets), then falls back to DuckDuckGo (free, no API
key required). Results are cached in-memory to avoid redundant calls.
"""

from __future__ import annotations

import hashlib
import json
import logging
import time
from typing import Any

from .registry import register_tool

logger = logging.getLogger(__name__)

# ── Cache ─────────────────────────────────────────────────────────────

_CACHE_TTL = 600  # 10 minutes
_cache: dict[str, tuple[float, list[dict]]] = {}


def _cache_key(query: str, backend: str) -> str:
    return hashlib.md5(f"{backend}:{query}".encode()).hexdigest()


def _get_cached(query: str, backend: str) -> list[dict] | None:
    key = _cache_key(query, backend)
    if key in _cache:
        ts, results = _cache[key]
        if time.time() - ts < _CACHE_TTL:
            return results
        del _cache[key]
    return None


def _set_cache(query: str, backend: str, results: list[dict]) -> None:
    key = _cache_key(query, backend)
    _cache[key] = (time.time(), results)
    # Evict old entries if cache grows too large
    if len(_cache) > 200:
        now = time.time()
        stale = [k for k, (ts, _) in _cache.items() if now - ts > _CACHE_TTL]
        for k in stale:
            del _cache[k]


# ── Backend: Tavily ──────────────────────────────────────────────────

def _search_tavily(query: str, max_results: int = 5) -> list[dict] | None:
    """Search via Tavily API. Returns None if unavailable."""
    try:
        from tavily import TavilyClient
        import os
        api_key = os.environ.get("TAVILY_API_KEY") or os.environ.get("TAVILY_SEARCH_API_KEY")
        if not api_key:
            logger.debug("Tavily API key not set, skipping")
            return None

        client = TavilyClient(api_key=api_key)
        response = client.search(
            query=query,
            max_results=max_results,
            search_depth="basic",
        )
        results = []
        for item in response.get("results", []):
            results.append({
                "title": item.get("title", ""),
                "url": item.get("url", ""),
                "snippet": item.get("content", ""),
            })
        return results
    except ImportError:
        logger.debug("tavily-python not installed")
        return None
    except Exception as e:
        logger.warning("Tavily search failed: %s", e)
        return None


# ── Backend: DuckDuckGo ──────────────────────────────────────────────

def _search_ddgs(query: str, max_results: int = 5) -> list[dict] | None:
    """Search via DuckDuckGo (free, no API key). Returns None if unavailable."""
    try:
        from duckduckgo_search import DDGS
        with DDGS() as ddgs:
            items = list(ddgs.text(query, max_results=max_results))
        results = []
        for item in items:
            results.append({
                "title": item.get("title", ""),
                "url": item.get("href", ""),
                "snippet": item.get("body", ""),
            })
        return results
    except ImportError:
        logger.debug("duckduckgo-search not installed")
        return None
    except Exception as e:
        logger.warning("DDGS search failed: %s", e)
        return None


# ── Backend: Baidu (httpx direct) ───────────────────────────────────

def _search_baidu(query: str, max_results: int = 5) -> list[dict] | None:
    """Search via Baidu by scraping search results page with httpx."""
    try:
        import httpx
        from urllib.parse import quote

        url = f"https://www.baidu.com/s?wd={quote(query)}&rn={max_results}"
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
            "Accept": "text/html,application/xhtml+xml",
            "Accept-Language": "zh-CN,zh;q=0.9",
        }
        resp = httpx.get(url, headers=headers, timeout=15, follow_redirects=True, verify=False)
        if resp.status_code != 200:
            logger.warning("Baidu returned status %d", resp.status_code)
            return None

        html = resp.text
        if len(html) < 5000 or "百度安全验证" in html or "wappass.baidu.com" in html:
            logger.warning("Baidu returned captcha or empty page (len=%d)", len(html))
            return None

        results = []
        import re
        pattern = r'<h3[^>]*>\s*<a[^>]*href="([^"]*)"[^>]*>(.*?)</a>'
        matches = re.findall(pattern, html, re.DOTALL)
        for href, title_html in matches[:max_results]:
            title = re.sub(r'<[^>]+>', '', title_html).strip()
            if title and len(title) > 2:
                results.append({"title": title, "url": href, "snippet": ""})

        if results:
            logger.info("Baidu search returned %d results for: %s", len(results), query)
            return results
        return None
    except Exception as e:
        logger.warning("Baidu search failed: %s", e)
        return None


def _search_sogou(query: str, max_results: int = 5) -> list[dict] | None:
    """Search via Sogou by scraping search results page."""
    try:
        import httpx
        import re
        from urllib.parse import quote

        url = f"https://www.sogou.com/web?query={quote(query)}"
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
            "Accept": "text/html,application/xhtml+xml",
            "Accept-Language": "zh-CN,zh;q=0.9",
        }
        resp = httpx.get(url, headers=headers, timeout=15, follow_redirects=True, verify=False)
        if resp.status_code != 200:
            logger.warning("Sogou returned status %d", resp.status_code)
            return None

        html = resp.text
        if len(html) < 5000:
            logger.warning("Sogou returned empty page (len=%d)", len(html))
            return None

        results = []
        pattern = r'<h3[^>]*>\s*<a[^>]*href="([^"]*)"[^>]*>(.*?)</a>'
        matches = re.findall(pattern, html, re.DOTALL)
        for href, title_html in matches[:max_results]:
            title = re.sub(r'<[^>]+>', '', title_html).strip()
            if title and len(title) > 2:
                full_url = href if href.startswith("http") else f"https://www.sogou.com{href}"
                results.append({"title": title, "url": full_url, "snippet": ""})

        if results:
            logger.info("Sogou search returned %d results for: %s", len(results), query)
            return results
        return None
    except Exception as e:
        logger.warning("Sogou search failed: %s", e)
        return None


# ── Tool entry ────────────────────────────────────────────────────────

@register_tool(
    name="web_search",
    description="网络搜索工具。backend=auto时自动fallback: Tavily→DDGS→百度→搜狗。也可指定backend=baidu/sogou/ddgs/tavily。返回results数组含title/url/snippet。",
    category="builtin",
    tags=["search", "web"],
    scene="general"
)
async def web_search(
    query: str = "",
    backend: str = "auto",
    max_results: int = 5,
) -> dict[str, Any]:
    """网络搜索，支持自动 fallback。

    Args:
        query: 搜索关键词
        backend: 搜索后端（auto/tavily/ddgs），默认 auto（Tavily 优先）
        max_results: 最大返回结果数，默认 5

    Returns:
        搜索结果列表 + 使用的后端
    """
    if not query.strip():
        return {"error": "搜索关键词不能为空"}

    query = query.strip()
    max_results = max(1, min(max_results, 10))

    # Check cache first
    cached = _get_cached(query, backend)
    if cached is not None:
        return {
            "results": cached,
            "count": len(cached),
            "backend": f"{backend} (cached)",
            "query": query,
        }

    # Try backends in order: fast reliable ones first
    results = None
    used_backend = backend

    if backend in ("auto", "tavily"):
        results = _search_tavily(query, max_results)
        if results is not None:
            used_backend = "tavily"

    if results is None and backend in ("auto", "sogou"):
        results = _search_sogou(query, max_results)
        if results is not None:
            used_backend = "sogou"

    if results is None and backend in ("auto", "baidu"):
        results = _search_baidu(query, max_results)
        if results is not None:
            used_backend = "baidu"

    if results is None and backend in ("auto", "ddgs"):
        results = _search_ddgs(query, max_results)
        if results is not None:
            used_backend = "ddgs"

    if results is None:
        return {
            "error": f"所有搜索后端不可用（backend={backend}）。尝试的后端: tavily→ddgs→baidu→sogou 均失败。",
            "query": query,
        }

    # Cache results
    _set_cache(query, backend, results)

    return {
        "results": results,
        "count": len(results),
        "backend": used_backend,
        "query": query,
    }
