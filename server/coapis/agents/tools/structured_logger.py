# -*- coding: utf-8 -*-
# Copyright 2026 以太吃虾 & CoApis Contributors
# Licensed under the Apache License, Version 2.0
from __future__ import annotations
import asyncio, json, logging, os, time, gzip
from pathlib import Path
from typing import Any
from .registry import register_tool

logger = logging.getLogger(__name__)

LOG_DIR = Path(os.environ.get("COAPIS_LOG_DIR",
    os.path.join(os.path.dirname(__file__), "..", "..", "..", "data", "logs")))


def _ensure_dir():
    LOG_DIR.mkdir(parents=True, exist_ok=True)


def _rotate_if_needed(log_file: Path, max_size_mb: int = 10):
    """Rotate log file if it exceeds max size."""
    if log_file.exists() and log_file.stat().st_size > max_size_mb * 1024 * 1024:
        ts = time.strftime("%Y%m%d_%H%M%S")
        rotated = log_file.with_suffix(f".{ts}.jsonl.gz")
        try:
            with open(log_file, "rb") as f_in:
                with gzip.open(rotated, "wb") as f_out:
                    f_out.write(f_in.read())
            log_file.write_text("")  # truncate
        except Exception:
            pass


@register_tool(
    name="structured_logger",
    description="JSON 结构化日志：记录/查询/统计/轮转，支持级别过滤和字段搜索，与 audit_log + perf_monitor 联动。",
    category="builtin",
    tags=["ops", "logging", "structured", "monitoring"],
    scene="ops"
)
async def structured_logger(
    action: str = "log",
    level: str = "info",
    message: str = "",
    module: str = "",
    extra: str = "",
    query: str = "",
    min_level: str = "debug",
    since: int = 0,
    limit: int = 100,
    max_size_mb: int = 10,
) -> dict[str, Any]:
    """结构化日志。

    Args:
        action: 操作类型 (log/query/stats/rotate/clear)
        level: 日志级别 (debug/info/warning/error/critical)
        message: 日志消息
        module: 模块名
        extra: 附加字段 JSON
        query: 搜索关键词
        min_level: 查询最低级别
        since: 查询起始时间戳
        limit: 查询限制
        max_size_mb: 轮转阈值 MB

    Returns:
        操作结果
    """
    _ensure_dir()
    log_file = LOG_DIR / "structured.jsonl"

    LEVEL_ORDER = {"debug": 0, "info": 1, "warning": 2, "error": 3, "critical": 4}

    if action == "log":
        if not message.strip():
            return {"error": "message 不能为空"}
        extra_data = {}
        if extra.strip():
            try:
                extra_data = json.loads(extra)
            except Exception:
                pass
        entry = {
            "ts": time.time(),
            "ts_human": time.strftime("%Y-%m-%d %H:%M:%S"),
            "level": level,
            "module": module or "agent",
            "message": message,
            **extra_data,
        }
        try:
            _rotate_if_needed(log_file, max_size_mb)
            with open(log_file, "a") as f:
                f.write(json.dumps(entry, ensure_ascii=False) + "\n")
        except Exception as e:
            return {"error": f"写入日志失败: {e}"}
        return {"action": "logged", "level": level, "ts": entry["ts_human"]}

    elif action == "query":
        if not log_file.exists():
            return {"action": "query", "entries": [], "count": 0}
        min_sev = LEVEL_ORDER.get(min_level, 0)
        entries = []
        try:
            with open(log_file, "r") as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        entry = json.loads(line)
                    except Exception:
                        continue
                    if LEVEL_ORDER.get(entry.get("level", "info"), 0) < min_sev:
                        continue
                    if since and entry.get("ts", 0) < since:
                        continue
                    if query and query.lower() not in json.dumps(entry, ensure_ascii=False).lower():
                        continue
                    entries.append(entry)
                    if len(entries) >= limit:
                        break
        except Exception:
            pass
        return {"action": "query", "count": len(entries), "entries": entries[-limit:]}

    elif action == "stats":
        if not log_file.exists():
            return {"action": "stats", "total": 0}
        by_level = {}
        by_module = {}
        total = 0
        try:
            with open(log_file, "r") as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        entry = json.loads(line)
                        total += 1
                        lvl = entry.get("level", "unknown")
                        mod = entry.get("module", "unknown")
                        by_level[lvl] = by_level.get(lvl, 0) + 1
                        by_module[mod] = by_module.get(mod, 0) + 1
                    except Exception:
                        continue
        except Exception:
            pass
        file_size = log_file.stat().st_size if log_file.exists() else 0
        return {"action": "stats", "total": total, "by_level": by_level,
                "by_module": by_module, "file_size_mb": round(file_size / 1024 / 1024, 2)}

    elif action == "rotate":
        _rotate_if_needed(log_file, max_size_mb)
        return {"action": "rotated", "file": str(log_file)}

    elif action == "clear":
        if log_file.exists():
            log_file.write_text("")
        return {"action": "cleared"}

    else:
        return {"error": f"未知操作: {action}，支持 log/query/stats/rotate/clear"}
