# -*- coding: utf-8 -*-
# Copyright 2026 蜜蜂 & CoApis Contributors
# Licensed under the Apache License, Version 2.0
"""System monitor — unified tool for performance monitoring, health checks, and tracing.

Merges: perf_monitor + health_check + trace_ops into one tool.
"""
from __future__ import annotations
import json, os, time, socket, threading
from datetime import datetime
from .registry import register_tool


# ── perf_monitor ──
def _get_perf() -> dict:
    """Collect system performance metrics."""
    result = {"timestamp": datetime.now().isoformat()}
    try:
        import psutil
        cpu = psutil.cpu_percent(interval=0.1)
        mem = psutil.virtual_memory()
        disk = psutil.disk_usage("/")
        result["cpu_percent"] = cpu
        result["memory"] = {"total_gb": round(mem.total / 1e9, 2), "used_gb": round(mem.used / 1e9, 2), "percent": mem.percent}
        result["disk"] = {"total_gb": round(disk.total / 1e9, 2), "used_gb": round(disk.used / 1e9, 2), "percent": disk.percent}
        procs = []
        for p in psutil.process_iter(["pid", "name", "cpu_percent", "memory_percent"]):
            info = p.info
            if info["cpu_percent"] and info["cpu_percent"] > 1.0:
                procs.append(info)
        procs.sort(key=lambda x: -(x.get("cpu_percent") or 0))
        result["top_processes"] = procs[:5]
    except ImportError:
        result["note"] = "psutil not installed, limited metrics"
        try:
            result["load_avg"] = list(os.getloadavg())
        except Exception:
            pass
    return result


# ── health_check ──
def _check_tcp(host: str, port: int, timeout: float = 3.0) -> dict:
    start = time.time()
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        s.settimeout(timeout)
        s.connect((host, port))
        s.close()
        return {"host": host, "port": port, "status": "up", "latency_ms": round((time.time() - start) * 1000, 1)}
    except Exception as e:
        return {"host": host, "port": port, "status": "down", "error": str(e)}

def _check_http(url: str, timeout: int = 5) -> dict:
    try:
        import httpx
        start = time.time()
        r = httpx.get(url, timeout=timeout, follow_redirects=True)
        return {"url": url, "status": "up", "status_code": r.status_code, "latency_ms": round((time.time() - start) * 1000, 1)}
    except Exception as e:
        return {"url": url, "status": "down", "error": str(e)}


# ── trace_ops ──
_traces: dict[str, list] = {}

def _start_trace(name: str) -> dict:
    trace_id = f"{name}_{int(time.time()*1000)}"
    _traces[trace_id] = [{"name": name, "start": time.time(), "event": "start"}]
    return {"trace_id": trace_id, "status": "started"}

def _end_trace(trace_id: str) -> dict:
    if trace_id not in _traces:
        return {"error": f"Trace not found: {trace_id}"}
    span = _traces[trace_id]
    span.append({"event": "end", "time": time.time()})
    start = span[0]["start"]
    end = span[-1]["time"]
    return {"trace_id": trace_id, "duration_ms": round((end - start) * 1000, 2), "spans": len(span)}

def _add_span(trace_id: str, name: str) -> dict:
    if trace_id not in _traces:
        return {"error": f"Trace not found: {trace_id}"}
    _traces[trace_id].append({"name": name, "start": time.time(), "event": "span"})
    return {"trace_id": trace_id, "span_name": name}


async def sys_monitor(
    action: str = "perf",
    host: str = "127.0.0.1",
    port: int = 80,
    url: str = "",
    trace_id: str = "",
    span_name: str = "",
) -> dict:
    """系统监控工具。

    Args:
        action: perf(性能指标) / health(服务探活) / trace(追踪管理: start/end/span)
        host: 探活目标主机 (health 时)
        port: 探活目标端口 (health 时)
        url: HTTP 探活 URL (health 时)
        trace_id: 追踪 ID (trace 时)
        span_name: span 名称 (trace span 时)
    """
    if action == "perf":
        return {"action": "perf", **_get_perf()}
    elif action == "health":
        results = []
        if url:
            results.append(_check_http(url))
        else:
            results.append(_check_tcp(host, port))
        return {"action": "health", "results": results}
    elif action == "trace":
        sub = span_name or "default"
        if trace_id:
            if span_name:
                return {"action": "trace", **_add_span(trace_id, span_name)}
            return {"action": "trace", **_end_trace(trace_id)}
        return {"action": "trace", **_start_trace(sub)}
    else:
        return {"error": f"未知 action: {action}，支持 perf/health/trace"}
