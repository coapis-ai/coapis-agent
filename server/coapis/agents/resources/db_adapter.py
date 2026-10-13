# -*- coding: utf-8 -*-
"""``db`` 资源面适配器 —— 只读，发现表 / 检索表 / 取表结构与样本行。

三条硬约束：

1. **只读**。用 ``Inspector`` 与 ``SELECT``，绝不发 DML/DDL。
2. **不转储**。``fetch()`` 返回结构 + 最多 3 行样本，行数只用于摘要。
   把整表喂给模型不是"资源运用"，是上下文自杀。
3. **脱敏**。``salt`` / ``hash`` / ``token`` / ``secret`` / ``api_key`` /
   ``password`` 列的值一律替换成 ``***``。凭据列进模型上下文等于把凭据
   交给日志、缓存与远端 API——这是不可接受的泄露面。
"""

from __future__ import annotations

import logging
from typing import Any

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

#: 采样行数。够模型看清"这表长什么样"，不够模型把数据当结论。
SAMPLE_ROWS = 3

#: 值必须脱敏的列名子串（小写匹配）。
REDACT_SUBSTRINGS = (
    "salt",
    "hash",
    "token",
    "secret",
    "api_key",
    "apikey",
    "password",
    "passwd",
    "credential",
    "private_key",
)


def _is_sensitive(col: str) -> bool:
    c = (col or "").lower()
    return any(s in c for s in REDACT_SUBSTRINGS)


def _engine():
    from ...foundation.db.engine import get_engine

    return get_engine()


def _table_names() -> list[str]:
    try:
        from sqlalchemy import inspect

        return sorted(inspect(_engine()).get_table_names())
    except Exception as exc:  # pragma: no cover - defensive
        logger.debug("db adapter table list failed (ignored): %s", exc)
        return []


def _columns(table: str) -> list[str]:
    try:
        from sqlalchemy import inspect

        return [c["name"] for c in inspect(_engine()).get_columns(table)]
    except Exception:
        return []


def _row_count(table: str) -> int:
    try:
        from sqlalchemy import text

        with _engine().connect() as conn:
            return int(conn.execute(text(f'SELECT COUNT(*) FROM "{table}"')).scalar() or 0)
    except Exception:
        return -1


class DbAdapter(ResourceAdapter):
    name = "db"

    async def discover(self) -> list[ResourceMeta]:
        metas: list[ResourceMeta] = []
        for t in _table_names()[:MAX_DISCOVER_ITEMS]:
            cols = _columns(t)
            n = _row_count(t)
            metas.append(
                ResourceMeta(
                    kind="db",
                    ref=t,
                    title=t,
                    summary=f"rows={n} cols={len(cols)}",
                    status="table",
                    extra={"columns": cols[:40], "row_count": n},
                )
            )
        return metas

    async def search(self, query: str, limit: int = 10) -> list[Hit]:
        hits: list[Hit] = []
        for m in await self.discover():
            # 表名命中权重高于列名命中：模型问"用户表"要的是表，不是列。
            s = max(
                score_match(query, m.title),
                0.6 * score_match(query, " ".join(m.extra.get("columns", []))),
            )
            if s > 0:
                hits.append(Hit(meta=m, score=s, snippet=m.summary))
        hits.sort(key=lambda h: (-h.score, h.meta.ref))
        return hits[: max(1, min(int(limit), MAX_DISCOVER_ITEMS))]

    async def fetch(self, ref: str) -> Content:
        table = (ref or "").strip()
        if not table or not table.replace("_", "").isalnum():
            return Content(kind="db", ref=ref, text="", meta={"error": "表名非法"})
        if table not in _table_names():
            return Content(kind="db", ref=ref, text="", meta={"error": f"表不存在: {table}"})

        cols = _columns(table)
        n = _row_count(table)
        rows: list[dict[str, Any]] = []
        try:
            from sqlalchemy import text

            with _engine().connect() as conn:
                res = conn.execute(text(f'SELECT * FROM "{table}" LIMIT {SAMPLE_ROWS}'))
                # 用 mappings() 拿列名→值；老版本 Row 当 tuple 索引会炸
                for row in res.mappings().all():
                    d = {}
                    for k, v in row.items():
                        if _is_sensitive(k):
                            d[k] = "***"
                        elif isinstance(v, (bytes, bytearray)):
                            d[k] = f"<binary {len(v)}B>"
                        else:
                            d[k] = v
                    rows.append(d)
        except Exception as exc:
            return Content(kind="db", ref=table, text="", meta={"error": f"采样失败: {exc}"})

        body = {
            "table": table,
            "row_count": n,
            "columns": cols,
            "sample_rows": rows,
            "note": "仅采样前若干行；取全量请用专用查询接口，不要把整表塞进对话。",
        }
        import json

        txt = json.dumps(body, ensure_ascii=False, default=str, indent=2)
        truncated = len(txt) > MAX_FETCH_CHARS
        return Content(
            kind="db",
            ref=table,
            text=txt[:MAX_FETCH_CHARS],
            truncated=truncated,
            meta={"row_count": n, "columns": len(cols)},
        )
