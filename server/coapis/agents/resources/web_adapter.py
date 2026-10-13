# -*- coding: utf-8 -*-
"""``web`` 资源面适配器 —— 复用既有 web_search 后端，不重复造轮子。

``discover()`` 返回的是**能力描述**而不是资源列表：网络没有可枚举的清单，
智能体需要知道的是"这一面存在、怎么用"。这是五个面里唯一的特例，刻意保留
统一签名（``discover()`` 无参）而不给 web 开特例接口。

``fetch()`` 只支持 http/https，且做 HTML 粗剥离 + 长度截断——取的是可读正文，
不是把整页 HTML 塞进上下文。需要 JS 渲染的页面请用 browser 工具，不在本面。
"""

from __future__ import annotations

import logging
import re
import urllib.request

from .contract import (
    MAX_DISCOVER_ITEMS,
    MAX_FETCH_CHARS,
    Content,
    Hit,
    ResourceAdapter,
    ResourceMeta,
    score_match,
)

logger = logging.getLogger(__name__)

_TIMEOUT = 12


def _strip_html(html: str) -> str:
    html = re.sub(r"(?is)<(script|style)[^>]*>.*?</\1>", " ", html)
    text = re.sub(r"(?s)<[^>]+>", " ", html)
    text = re.sub(r"&nbsp;", " ", text)
    text = re.sub(r"&amp;", "&", text)
    return re.sub(r"\s+", " ", text).strip()


class WebAdapter(ResourceAdapter):
    name = "web"

    async def discover(self) -> list[ResourceMeta]:
        return [
            ResourceMeta(
                kind="web",
                ref="web",
                title="实时网络检索",
                summary=(
                    "无固定清单，用 search 直接查。后端顺序 browser→baidu→sogou→ddgs→tavily，"
                    "无需 API Key。fetch(ref=url) 取网页正文（需 JS 渲染的页面请用 browser 工具）。"
                ),
                status="capability",
                extra={"backends": "browser,baidu,sogou,ddgs,tavily"},
            )
        ]

    async def search(self, query: str, limit: int = 10) -> list[Hit]:
        try:
            from ..tools.web_search import web_search as _web_search

            res = await _web_search(query=query, max_results=max(1, min(int(limit), 10)))
        except Exception as exc:  # pragma: no cover - defensive
            logger.debug("web adapter search failed (ignored): %s", exc)
            return []
        if not isinstance(res, dict):
            return []
        hits: list[Hit] = []
        for item in res.get("results", []) or []:
            title = str(item.get("title") or "")
            url = str(item.get("url") or "")
            snippet = str(item.get("snippet") or "")
            s = max(score_match(query, title), score_match(query, snippet))
            if s <= 0:
                s = 0.30  # 搜索引擎已做过相关性排序，保底给分避免全被阈值滤掉
            hits.append(
                Hit(
                    meta=ResourceMeta(
                        kind="web",
                        ref=url,
                        title=title,
                        summary="web result",
                        status="result",
                        extra={"backend": res.get("backend", "")},
                    ),
                    score=s,
                    snippet=snippet[:200],
                )
            )
        hits.sort(key=lambda h: -h.score)
        return hits[:MAX_DISCOVER_ITEMS]

    async def fetch(self, ref: str) -> Content:
        url = (ref or "").strip()
        if not url.startswith(("http://", "https://")):
            return Content(kind="web", ref=url, text="", meta={"error": "只支持 http/https URL"})
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 (coapis-resource-adapter)"})
            with urllib.request.urlopen(req, timeout=_TIMEOUT) as resp:  # noqa: S310 - scheme 已校验
                raw = resp.read(400_000).decode("utf-8", errors="replace")
        except Exception as exc:
            return Content(kind="web", ref=url, text="", meta={"error": f"抓取失败: {exc}"})
        text = _strip_html(raw)
        truncated = len(text) > MAX_FETCH_CHARS
        return Content(
            kind="web",
            ref=url,
            text=text[:MAX_FETCH_CHARS],
            truncated=truncated,
            meta={"raw_chars": len(raw)},
        )
