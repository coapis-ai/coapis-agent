# -*- coding: utf-8 -*-
"""统一资源检索工具（资源契约消费面的模型入口）。

**签名冻结**：``resource_search(scope, query, limit)``——与方案文档 A3.3 一致，
单一工具，不拆成 file_search/db_search/kb_search 的碎片。智能体的能力体现在
**路由判断**：先 discover（``query`` 传空）了解有什么，再选对资源面查。

``fetch()`` 是适配器层 API（供上下文注入等内部消费者用），刻意**不**暴露成
模型工具：文件内容用 ``read_file``、数据库用既有数据工具、网页用 browser，
再开一个 fetch 工具就是"各自为政的碎片"的复辟，也白占 schema token。
"""

from __future__ import annotations

import logging
from typing import Any

from .registry import register_tool

logger = logging.getLogger(__name__)


@register_tool(
    name="resource_search",
    description=(
        "统一资源检索：一次调用覆盖工作区文件 / 数据库表 / 知识库 / MCP 服务 / 网络。"
        "用法：先 scope='' 且 query='' 做一次发现（列出各面有什么）；再选对资源面查——"
        "scope 取 file|db|kb|mcp|web 之一，能判断出该查哪一面时务必指定，全查白占 token。"
        "返回带 source 标签的命中列表。取内容：file 用 read_file，db 用数据工具，网页用 browser。"
    ),
    category="builtin",
    tags=["search", "resource", "contract"],
)
async def resource_search(
    scope: str = "",
    query: str = "",
    limit: int = 10,
) -> dict[str, Any]:
    """按 scope 路由到对应资源面检索。

    Args:
        scope: 资源面（file/db/kb/mcp/web）；空串 = 并发查全部可用面
        query: 检索词；空串 = 发现模式（列导航）
        limit: 每面最多返回多少条（1..30）

    Returns:
        hits（带 source 标签）+ sources 计数 + errors + hint
    """
    from ..resources.registry import search as _search

    try:
        return await _search(scope or None, query, limit)
    except Exception as exc:  # pragma: no cover - defensive
        logger.warning("resource_search failed: %s", exc, exc_info=True)
        return {
            "mode": "search",
            "scope": scope,
            "query": query,
            "hits": [],
            "errors": {"registry": f"{type(exc).__name__}: {exc}"},
            "hint": "检索面异常，已降级为空结果（消息链路不受影响）。",
        }
