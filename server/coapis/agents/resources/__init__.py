# -*- coding: utf-8 -*-
"""资源契约 · 消费面（``ResourceAdapter``）。

五个同构资源面：``file`` / ``db`` / ``kb`` / ``mcp`` / ``web``。
KB 只是其中一个适配器（企业版启用，社区版自动缺席）。

方向冻结：消费面**只读**清单面（``ResourceLedger``），绝不改写。
"""

from .contract import Content, Hit, ResourceAdapter, ResourceMeta, score_match
from .registry import ADAPTERS, available_adapters, register_adapter, search

__all__ = [
    "ADAPTERS",
    "Content",
    "Hit",
    "ResourceAdapter",
    "ResourceMeta",
    "available_adapters",
    "register_adapter",
    "score_match",
    "search",
]
