"""Probe: does a document-flavoured query preactivate the docs group? (B5)"""
from __future__ import annotations

import inspect
import sys

sys.path.insert(0, ".")

from coapis.agents.tools import groups as G

print("signature:", inspect.signature(G.active_groups_for_query))

QUERIES = [
    "帮我解析这份pdf文档",
    "把这个word转成docx",
    "读一下这个excel表格",
    "请分析附件里的内容",
    "把这份markdown导出成word",
    "帮我搜索一下最新的新闻",
    "今天天气如何",
]

for q in QUERIES:
    try:
        res = G.active_groups_for_query(q)
    except TypeError:
        res = G.active_groups_for_query(q, [])
    has_doc = "doc_reader" in set(res) if isinstance(res, (list, set, tuple)) else res
    print("   ", q, "->", res)
