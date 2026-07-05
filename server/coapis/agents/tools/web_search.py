# -*- coding: utf-8 -*-
# Copyright 2026 以太吃虾 & CoApis Contributors
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

"""Built-in web search tool with browser + Baidu/Sogou fallback.

Provides a unified ``web_search`` tool that tries browser (Bing) first
(no API key needed), then falls back to Baidu, Sogou, DuckDuckGo, Tavily.
Results are cached in-memory to avoid redundant calls.
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import re
import time
from typing import Any
from urllib.parse import quote

from .registry import register_tool

logger = logging.getLogger(__name__)

# ── Config (env-driven) ─────────────────────────────────────────────
_DEFAULT_BACKEND = os.environ.get("COAPIS_WEB_SEARCH_DEFAULT_BACKEND", "auto")
_BACKEND_ORDER = [
    b.strip()
    for b in os.environ.get(
        "COAPIS_WEB_SEARCH_BACKEND_ORDER",
        "browser,baidu,sogou,ddgs,tavily",
    ).split(",")
    if b.strip()
]
_CACHE_TTL = int(os.environ.get("COAPIS_WEB_SEARCH_CACHE_TTL", "600"))
_TIMEOUT = int(os.environ.get("COAPIS_WEB_SEARCH_TIMEOUT", "15"))

# ── Cache ─────────────────────────────────────────────────────────────

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
    if len(_cache) > 200:
        now = time.time()
        stale = [k for k, (ts, _) in _cache.items() if now - ts > _CACHE_TTL]
        for k in stale:
            del _cache[k]


# ── Backend: Browser (Playwright CDP → Bing) ─────────────────────────

async def _search_browser(query: str, max_results: int = 5) -> list[dict] | None:
    """Search via Playwright browser visiting Bing. Free, no API key."""
    try:
        import httpx

        cdp_url = os.environ.get("BROWSER_CDP_URL", "")
        if not cdp_url:
            logger.debug("BROWSER_CDP_URL not set, skipping browser search")
            return None

        search_urls = {
            "bing": f"https://www.bing.com/search?q={quote(query)}&count={max_results}",
            "baidu": f"https://www.baidu.com/s?wd={quote(query)}&rn={max_results}",
            "google": f"https://www.google.com/search?q={quote(query)}&num={max_results}",
        }
        search_engine = os.environ.get("COAPIS_WEB_SEARCH_ENGINE", "bing")
        url = search_urls.get(search_engine, search_urls["bing"])

        async with httpx.AsyncClient(timeout=_TIMEOUT, follow_redirects=True, verify=False) as client:
            resp = await client.get(url, headers={
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
                "Accept": "text/html,application/xhtml+xml",
                "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
            })
            if resp.status_code != 200:
                logger.warning("Browser search returned status %d", resp.status_code)
                return None

            html = resp.text
            results = []

            if search_engine == "bing":
                # Bing: split by result blocks, then extract title + snippet per block
                blocks = re.split(r'(?=<li class="b_algo")', html)
                for block in blocks[1:max_results + 1]:
                    # Title + URL from <h2><a>
                    title_m = re.search(
                        r'<h2>\s*<a[^>]*href="(https?://[^"]*)"[^>]*>(.*?)</a>', block, re.DOTALL
                    )
                    if not title_m:
                        continue
                    url, title_html = title_m.group(1), title_m.group(2)
                    title = re.sub(r'<[^>]+>', '', title_html).strip()
                    if not title or len(title) <= 5:
                        continue
                    # Snippet: try multiple Bing DOM patterns
                    snippet = ""
                    for sp in [
                        r'<p[^>]*>(.*?)</p>',
                        r'<div[^>]*class="[^"]*b_caption[^"]*"[^>]*>.*?<p[^>]*>(.*?)</p>',
                    ]:
                        sm = re.search(sp, block, re.DOTALL)
                        if sm:
                            snippet = re.sub(r'<[^>]+>', '', sm.group(1)).strip()
                            if len(snippet) > 10:
                                break
                            snippet = ""
                    results.append({"title": title, "url": url, "snippet": snippet})

            elif search_engine == "baidu":
                # Extract title + snippet pairs: title from <h3><a>, snippet from nearby <span>/<div>
                # Baidu wraps each result in <div class="result ..."> or <div class="c-container">
                blocks = re.split(r'(?=<h3[^>]*>)', html)
                for block in blocks[1:max_results + 1]:
                    title_m = re.search(r'<h3[^>]*>\s*<a[^>]*href="([^"]*)"[^>]*>(.*?)</a>', block, re.DOTALL)
                    if not title_m:
                        continue
                    title = re.sub(r'<[^>]+>', '', title_m.group(2)).strip()
                    if not title or len(title) <= 2:
                        continue
                    # Snippet: try multiple Baidu DOM patterns
                    snippet = ""
                    for sp in [
                        r'<span[^>]*class="[^"]*content-right[^"]*"[^>]*>(.*?)</span>',
                        r'<div[^>]*class="[^"]*c-abstract[^"]*"[^>]*>(.*?)</div>',
                        r'<span[^>]*class="[^"]*c-color-text[^"]*"[^>]*>(.*?)</span>',
                        r'<div[^>]*class="[^"]*c-span-last[^"]*"[^>]*>(.*?)</div>',
                    ]:
                        sm = re.search(sp, block, re.DOTALL)
                        if sm:
                            snippet = re.sub(r'<[^>]+>', '', sm.group(1)).strip()
                            if len(snippet) > 10:
                                break
                            snippet = ""
                    results.append({"title": title, "url": title_m.group(1), "snippet": snippet})

            elif search_engine == "google":
                # Google: split by result blocks, extract title + snippet
                blocks = re.split(r'(?=<a[^>]*href="/url\?q=)', html)
                for block in blocks[1:max_results + 1]:
                    title_m = re.search(r'<a[^>]*href="/url\?q=([^&"]*)"[^>]*><[^>]*>(.*?)</[^>]*></a>', block, re.DOTALL)
                    if not title_m:
                        continue
                    title = re.sub(r'<[^>]+>', '', title_m.group(2)).strip()
                    if not title or len(title) <= 2:
                        continue
                    # Snippet: look for <span> or <div> with text content
                    snippet = ""
                    for sp in [
                        r'<span[^>]*>(.*?)</span>',
                        r'<div[^>]*>(.*?)</div>',
                    ]:
                        sm = re.search(sp, block, re.DOTALL)
                        if sm:
                            snippet = re.sub(r'<[^>]+>', '', sm.group(1)).strip()
                            if len(snippet) > 20:
                                break
                            snippet = ""
                    results.append({"title": title, "url": title_m.group(1), "snippet": snippet})

            if results:
                logger.info("Browser search (%s) returned %d results for: %s", search_engine, len(results), query)
                return results
            logger.warning("Browser search parsed 0 results from %s (html len=%d)", search_engine, len(html))
            return None

    except Exception as e:
        logger.warning("Browser search failed: %s", e)
        return None


# ── Backend: Baidu (httpx direct) ───────────────────────────────────

def _search_baidu(query: str, max_results: int = 5) -> list[dict] | None:
    """Search via Baidu by scraping search results page with httpx."""
    try:
        import httpx
        url = f"https://www.baidu.com/s?wd={quote(query)}&rn={max_results}"
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
            "Accept": "text/html,application/xhtml+xml",
            "Accept-Language": "zh-CN,zh;q=0.9",
        }
        resp = httpx.get(url, headers=headers, timeout=_TIMEOUT, follow_redirects=True, verify=False)
        if resp.status_code != 200:
            return None
        html = resp.text
        if len(html) < 5000 or "百度安全验证" in html or "wappass.baidu.com" in html:
            logger.warning("Baidu returned captcha or empty page (len=%d)", len(html))
            return None
        results = []
        pattern = r'<h3[^>]*>\s*<a[^>]*href="([^"]*)"[^>]*>(.*?)</a>'
        for href, title_html in re.findall(pattern, html, re.DOTALL)[:max_results]:
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


# ── Backend: Sogou ──────────────────────────────────────────────────

def _search_sogou(query: str, max_results: int = 5) -> list[dict] | None:
    """Search via Sogou by scraping search results page."""
    try:
        import httpx
        url = f"https://www.sogou.com/web?query={quote(query)}"
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
            "Accept": "text/html,application/xhtml+xml",
            "Accept-Language": "zh-CN,zh;q=0.9",
        }
        resp = httpx.get(url, headers=headers, timeout=_TIMEOUT, follow_redirects=True, verify=False)
        if resp.status_code != 200:
            return None
        html = resp.text
        if len(html) < 5000:
            return None
        results = []
        # Sogou wraps each result in a block; split by <h3> to get per-result chunks
        blocks = re.split(r'(?=<h3[^>]*>)', html)
        for block in blocks[1:max_results + 1]:
            title_m = re.search(r'<h3[^>]*>\s*<a[^>]*href="([^"]*)"[^>]*>(.*?)</a>', block, re.DOTALL)
            if not title_m:
                continue
            href, title_html = title_m.group(1), title_m.group(2)
            title = re.sub(r'<[^>]+>', '', title_html).strip()
            if not title or len(title) <= 2:
                continue
            full_url = href if href.startswith("http") else f"https://www.sogou.com{href}"
            # Snippet: try multiple Sogou DOM patterns
            snippet = ""
            for sp in [
                r'<p[^>]*class="[^"]*str_info[^"]*"[^>]*>(.*?)</p>',
                r'<p[^>]*class="[^"]*str-text[^"]*"[^>]*>(.*?)</p>',
                r'<div[^>]*class="[^"]*space-txt[^"]*"[^>]*>(.*?)</div>',
                r'<div[^>]*class="[^"]*rb[^"]*"[^>]*>(.*?)</div>',
            ]:
                sm = re.search(sp, block, re.DOTALL)
                if sm:
                    snippet = re.sub(r'<[^>]+>', '', sm.group(1)).strip()
                    if len(snippet) > 10:
                        break
                    snippet = ""
            results.append({"title": title, "url": full_url, "snippet": snippet})
        if results:
            logger.info("Sogou search returned %d results for: %s", len(results), query)
            return results
        return None
    except Exception as e:
        logger.warning("Sogou search failed: %s", e)
        return None


# ── Backend: DuckDuckGo ──────────────────────────────────────────────

def _search_ddgs(query: str, max_results: int = 5) -> list[dict] | None:
    """Search via DuckDuckGo (free, no API key)."""
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


# ── Backend: Tavily ──────────────────────────────────────────────────

def _search_tavily(query: str, max_results: int = 5) -> list[dict] | None:
    """Search via Tavily API. Returns None if unavailable."""
    try:
        from tavily import TavilyClient
        api_key = os.environ.get("TAVILY_API_KEY") or os.environ.get("TAVILY_SEARCH_API_KEY")
        if not api_key:
            return None
        client = TavilyClient(api_key=api_key)
        response = client.search(query=query, max_results=max_results, search_depth="basic")
        results = []
        for item in response.get("results", []):
            results.append({
                "title": item.get("title", ""),
                "url": item.get("url", ""),
                "snippet": item.get("content", ""),
            })
        return results
    except ImportError:
        return None
    except Exception as e:
        logger.warning("Tavily search failed: %s", e)
        return None


# ── Backend dispatch table ──────────────────────────────────────────

_BACKENDS = {
    "browser": _search_browser,
    "baidu": _search_baidu,
    "sogou": _search_sogou,
    "ddgs": _search_ddgs,
    "tavily": _search_tavily,
}

# ── Tool entry ────────────────────────────────────────────────────────

@register_tool(
    name="web_search",
    description="网络搜索工具，无需 API Key 即可使用。默认通过浏览器（Bing）搜索，自动 fallback 到其他后端。返回 results 数组含 title/url/snippet。",
    category="builtin",
    tags=["search", "web"],
    scene="general"
)
async def web_search(
    query: str = "",
    backend: str = "",
    max_results: int = 5,
) -> dict[str, Any]:
    """网络搜索，无需 API Key。默认通过浏览器访问 Bing 搜索。

    Args:
        query: 搜索关键词
        backend: 搜索后端（browser/baidu/sogou/tavily/ddgs），默认 browser
        max_results: 最大返回结果数，默认 5

    Returns:
        搜索结果列表 + 使用的后端
    """
    if not query.strip():
        return {"error": "搜索关键词不能为空"}

    query = query.strip()
    try:
        max_results = int(max_results)
    except (ValueError, TypeError):
        max_results = 5
    max_results = max(1, min(max_results, 10))
    backend = (backend or "").strip() or _DEFAULT_BACKEND

    # Check cache first
    cached = _get_cached(query, backend)
    if cached is not None:
        return {
            "results": cached,
            "count": len(cached),
            "backend": f"{backend} (cached)",
            "query": query,
        }

    # Build backend order
    if backend != "auto":
        order = [backend]
    else:
        order = list(_BACKEND_ORDER)

    # ── 并发竞速 + 总超时 ──
    import asyncio

    _TOTAL_TIMEOUT = int(os.environ.get("COAPIS_WEB_SEARCH_TOTAL_TIMEOUT", "20"))
    results = None
    used_backend = backend

    # 构建可用 backend 任务
    available = []
    for b in order:
        search_fn = _BACKENDS.get(b)
        if search_fn is None:
            continue
        available.append((b, search_fn))

    if len(available) == 1:
        # 只有一个 backend，直接调用（带单个超时）
        b, search_fn = available[0]
        try:
            if asyncio.iscoroutinefunction(search_fn):
                results = await asyncio.wait_for(
                    search_fn(query, max_results),
                    timeout=_TOTAL_TIMEOUT,
                )
            else:
                results = search_fn(query, max_results)
            if results is not None:
                used_backend = b
        except (asyncio.TimeoutError, Exception) as e:
            logger.warning("Backend %s failed: %s", b, e)
    else:
        # 多个 backend：并发竞速，返回第一个成功的结果
        async def _try_backend(b_name, fn):
            try:
                if asyncio.iscoroutinefunction(fn):
                    r = await asyncio.wait_for(fn(query, max_results), timeout=_TIMEOUT)
                else:
                    r = fn(query, max_results)
                return b_name, r
            except (asyncio.TimeoutError, Exception) as e:
                logger.debug("Backend %s failed: %s", b_name, e)
                return b_name, None

        tasks = {
            asyncio.create_task(_try_backend(b, fn)): b
            for b, fn in available
        }

        try:
            done, pending = await asyncio.wait(
                tasks.keys(),
                timeout=_TOTAL_TIMEOUT,
                return_when=asyncio.FIRST_COMPLETED,
            )
        except Exception:
            done, pending = set(), set(tasks.keys())

        # 取第一个成功的结果
        for t in done:
            b_name, r = t.result()
            if r is not None and results is None:
                results = r
                used_backend = b_name

        # 取消剩余任务
        for t in pending:
            t.cancel()
            try:
                await t
            except (asyncio.CancelledError, Exception):
                pass

    if results is None:
        return {
            "error": f"所有搜索后端不可用（{_TOTAL_TIMEOUT}s超时）。已尝试: {', '.join(order)}",
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
