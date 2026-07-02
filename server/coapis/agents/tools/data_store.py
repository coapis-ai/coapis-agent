# -*- coding: utf-8 -*-
# Copyright 2026 蜜蜂 & CoApis Contributors
# Licensed under the Apache License, Version 2.0
"""Data store — unified tool for database, cache, and queue operations.

Merges: db_ops + cache_ops + queue_ops into one tool.
"""
from __future__ import annotations
import json, os, time, sqlite3, hashlib
from pathlib import Path
from collections import OrderedDict
from .registry import register_tool


def _get_db_path() -> Path:
    try:
        from ...config.context import get_current_workspace_dir
        ws = get_current_workspace_dir()
        if ws:
            return Path(ws) / "files" / "data_store.db"
    except Exception:
        pass
    return Path.cwd() / "files" / "data_store.db"


# ── DB ops ──
def _db_execute(sql: str, params: str = "") -> dict:
    db_path = _get_db_path()
    db_path.parent.mkdir(parents=True, exist_ok=True)
    try:
        conn = sqlite3.connect(str(db_path))
        conn.row_factory = sqlite3.Row
        cur = conn.cursor()
        p = json.loads(params) if params else []
        cur.execute(sql, p)
        if sql.strip().upper().startswith(("INSERT", "UPDATE", "DELETE", "CREATE", "DROP")):
            conn.commit()
            return {"affected": cur.rowcount, "status": "ok"}
        rows = [dict(r) for r in cur.fetchall()]
        return {"rows": rows[:100], "count": len(rows), "status": "ok"}
    except Exception as e:
        return {"error": str(e), "status": "failed"}
    finally:
        try:
            conn.close()
        except Exception:
            pass


# ── Cache ops ──
_cache: OrderedDict = OrderedDict()
_CACHE_MAX = 1000

def _cache_set(key: str, value: str, ttl: int = 0) -> dict:
    _cache[key] = {"value": value, "set_at": time.time(), "ttl": ttl}
    if len(_cache) > _CACHE_MAX:
        _cache.popitem(last=False)
    return {"key": key, "status": "ok"}

def _cache_get(key: str) -> dict:
    if key not in _cache:
        return {"error": f"Key not found: {key}", "status": "miss"}
    entry = _cache[key]
    if entry["ttl"] > 0 and (time.time() - entry["set_at"]) > entry["ttl"]:
        del _cache[key]
        return {"error": f"Key expired: {key}", "status": "expired"}
    return {"key": key, "value": entry["value"], "status": "hit"}

def _cache_delete(key: str) -> dict:
    if key in _cache:
        del _cache[key]
        return {"key": key, "status": "deleted"}
    return {"error": f"Key not found: {key}", "status": "miss"}

def _cache_list() -> dict:
    return {"keys": list(_cache.keys()), "count": len(_cache)}

def _cache_clear() -> dict:
    _cache.clear()
    return {"message": "Cache cleared", "status": "ok"}


# ── Queue ops ──
_queues: dict[str, list] = {}

def _queue_push(queue: str, message: str) -> dict:
    _queues.setdefault(queue, []).append({"message": message, "pushed_at": time.time()})
    return {"queue": queue, "length": len(_queues[queue]), "status": "ok"}

def _queue_pop(queue: str) -> dict:
    q = _queues.get(queue, [])
    if not q:
        return {"error": f"Queue empty: {queue}", "status": "empty"}
    item = q.pop(0)
    return {"queue": queue, **item, "status": "ok"}

def _queue_peek(queue: str) -> dict:
    q = _queues.get(queue, [])
    if not q:
        return {"queue": queue, "length": 0, "status": "empty"}
    return {"queue": queue, "next": q[0], "length": len(q)}

def _queue_list() -> dict:
    return {"queues": {k: len(v) for k, v in _queues.items()}, "total": len(_queues)}


async def data_store(
    action: str = "db",
    sql: str = "",
    key: str = "",
    value: str = "",
    queue: str = "",
    message: str = "",
    params: str = "",
    ttl: int = 0,
) -> dict:
    """数据存储工具。

    Args:
        action: db(SQL操作) / cache(缓存操作: set/get/delete/list/clear) / queue(队列操作: push/pop/peek/list)
        sql: SQL 语句 (db 时)
        key: 缓存键 (cache 时)
        value: 缓存值 (cache set 时)
        queue: 队列名 (queue 时)
        message: 队列消息 (queue push 时)
        params: SQL 参数 JSON 数组 (db 时)
        ttl: 缓存过期秒数 (cache set 时，0=不过期)
    """
    if action == "db":
        if not sql.strip():
            return {"error": "sql 不能为空"}
        return {"action": "db", **_db_execute(sql, params)}
    elif action == "cache":
        sub = (value and "set") or "get"
        if value:
            return {"action": "cache", **_cache_set(key, value, ttl)}
        elif key:
            return {"action": "cache", **_cache_get(key)}
        return {"action": "cache", **_cache_list()}
    elif action == "queue":
        if message:
            return {"action": "queue", **_queue_push(queue, message)}
        elif queue:
            return {"action": "queue", **_queue_pop(queue)}
        return {"action": "queue", **_queue_list()}
    else:
        return {"error": f"未知 action: {action}，支持 db/cache/queue"}


