# -*- coding: utf-8 -*-
"""资源面注册表 —— 路由与可用性。

智能体的能力体现在**路由判断**：先 discover 了解有什么，再选对资源面查。
注册表负责两件事：

1. **可用性**：``kb`` 面在知识库为空时自动缺席，``mcp`` 面在无 MCP 配置时
   自动缺席。智能体不会看到"有知识库"的假象。
2. **路由**：``scope`` 指定单面；``scope`` 为空时并发查全部可用面，结果带
   ``source`` 标签，跨面按归一化 score 排序。

纪律：任何一面挂了都不抛异常，只在 ``errors`` 里记录——检索面绝不能把
消息链路带崩（与 ``ResourceLedger`` 的 fire-and-forget 一致）。
"""

from __future__ import annotations

import asyncio
import logging

from .contract import Hit, ResourceAdapter, ResourceMeta
from .db_adapter import DbAdapter
from .file_adapter import FileAdapter
from .kb_adapter import KbAdapter
from .mcp_adapter import McpAdapter
from .web_adapter import WebAdapter

logger = logging.getLogger(__name__)

#: 单面检索超时（秒）。网络面慢是常态，不能让它拖死整次检索。
PER_ADAPTER_TIMEOUT = 20.0

#: 跨面合并后最多返回多少条。
TOTAL_CAP = 30

ADAPTERS: dict[str, ResourceAdapter] = {}


def register_adapter(adapter: ResourceAdapter) -> None:
    ADAPTERS[adapter.name] = adapter


def available_adapters() -> list[str]:
    """当前可用的资源面（按稳定顺序）。"""
    out: list[str] = []
    for name, ad in ADAPTERS.items():
        avail = getattr(ad, "available", None)
        if callable(avail):
            try:
                if not avail():
                    continue
            except Exception:  # pragma: no cover - defensive
                continue
        out.append(name)
    # 稳定顺序：本地资源优先，网络最后
    order = ["file", "db", "kb", "mcp", "web"]
    out.sort(key=lambda n: order.index(n) if n in order else 99)
    return out


def _tag(h: Hit, source: str) -> dict:
    d = h.to_dict()
    d["source"] = source
    return d


async def search(
    scope: str | None,
    query: str,
    limit: int = 10,
) -> dict:
    """统一检索入口。``scope`` 为空 = 并发查全部可用面。"""
    names = available_adapters()
    if scope:
        if scope not in ADAPTERS:
            return {
                "mode": "search",
                "scope": scope,
                "query": query,
                "hits": [],
                "sources": {},
                "errors": {
                    scope: f"资源面不存在或不可用。可用面: {', '.join(names) or '(无)'}"
                },
                "hint": "先用 scope='' 做一次发现，看有哪些面。",
            }
        names = [scope]

    query = (query or "").strip()
    limit = max(1, min(int(limit), TOTAL_CAP))

    if not query:
        # 发现模式：逐面列导航
        hits: list[dict] = []
        errors: dict[str, str] = {}
        for name in names:
            try:
                metas = await asyncio.wait_for(ADAPTERS[name].discover(), PER_ADAPTER_TIMEOUT)
                for m in metas[:limit]:
                    hits.append(_tag(Hit(meta=m, score=0.0, snippet=m.summary), name))
            except Exception as exc:
                errors[name] = f"{type(exc).__name__}: {exc}"
        return {
            "mode": "discover",
            "scope": scope or "",
            "query": "",
            "hits": hits,
            "sources": {n: sum(1 for h in hits if h["source"] == n) for n in names},
            "total": len(hits),
            "errors": errors,
            "hint": (
                "发现模式：列出各面有什么。用 query 做检索，用 fetch(已注册工具) 取内容。"
                "选对面比全查更省 token——能判断出该查哪一面时请指定 scope。"
            ),
        }

    tasks = []
    for name in names:
        tasks.append(_safe_search(name, query, limit))
    # return_exceptions=True：单面挂了只记 errors，不抛——与 ResourceLedger 的
    # fire-and-forget 一致，检索面绝不能把消息链路带崩。
    results = await asyncio.gather(*tasks, return_exceptions=True)

    hits: list[dict] = []
    errors: dict[str, str] = {}
    counts: dict[str, int] = {}
    for name, res in zip(names, results):
        if isinstance(res, BaseException):
            errors[name] = f"{type(res).__name__}: {res}"
            continue
        counts[name] = len(res)
        for h in res:
            hits.append(_tag(h, name))
    hits.sort(key=lambda h: (-h.get("score", 0), h.get("source", ""), h.get("ref", "")))
    hits = hits[: max(limit, TOTAL_CAP) if not scope else limit]

    return {
        "mode": "search",
        "scope": scope or "",
        "query": query,
        "hits": hits,
        "sources": counts,
        "total": len(hits),
        "errors": errors,
        "hint": (
            "命中带 source 标签。要内容用 fetch（ref 必须来自本次结果）；"
            "命中分散在多面时，优先本地面（file/db/kb），网络面兜底。"
        ),
    }


async def _safe_search(name: str, query: str, limit: int) -> list[Hit]:
    """单面带超时。异常向上抛，由 gather(return_exceptions=True) 记账。"""
    return await asyncio.wait_for(ADAPTERS[name].search(query, limit), PER_ADAPTER_TIMEOUT)


def register_defaults() -> None:
    """注册五个面。幂等。"""
    for ad in (FileAdapter(), DbAdapter(), KbAdapter(), McpAdapter(), WebAdapter()):
        register_adapter(ad)


register_defaults()
