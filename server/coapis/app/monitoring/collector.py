# -*- coding: utf-8 -*-
"""System metrics collector using psutil."""
from __future__ import annotations

import logging
import time
from typing import Any, Dict, Optional

import psutil

logger = logging.getLogger(__name__)


class SystemMetricsCollector:
    """Collects system-level metrics via psutil.
    
    Open-source version: basic real-time metrics only.
    Enterprise version: historical data, Prometheus integration, alerting.
    """

    def __init__(self):
        self._start_time = time.time()
        self._api_calls: Dict[str, int] = {}
        self._last_snapshot: Optional[Dict[str, Any]] = None

    # ── API call tracking ──────────────────────────────────────────

    def track_api_call(self, endpoint: str) -> None:
        """Increment API call counter for *endpoint*."""
        self._api_calls[endpoint] = self._api_calls.get(endpoint, 0) + 1

    def get_api_stats(self) -> Dict[str, Any]:
        return {
            "total_calls": sum(self._api_calls.values()),
            "endpoints": dict(sorted(self._api_calls.items(), key=lambda x: -x[1])[:20]),
        }

    # ── Uptime ─────────────────────────────────────────────────────

    def get_uptime(self) -> float:
        """Seconds since process start."""
        return round(time.time() - self._start_time, 1)

    # ── CPU ────────────────────────────────────────────────────────

    def get_cpu_metrics(self) -> Dict[str, Any]:
        try:
            percent = psutil.cpu_percent(interval=0.1)
            per_cpu = psutil.cpu_percent(interval=0, percpu=True)
            counts = psutil.cpu_count()
            logical = psutil.cpu_count(logical=True)
            return {
                "percent": percent,
                "cpu_percent": percent,  # Frontend expects cpu_percent
                "per_cpu": per_cpu,
                "cores": counts,
                "logical_cores": logical,
            }
        except Exception as e:
            logger.warning(f"Failed to collect CPU metrics: {e}")
            return {"error": str(e)}

    # ── Memory ─────────────────────────────────────────────────────

    def get_memory_metrics(self) -> Dict[str, Any]:
        try:
            vm = psutil.virtual_memory()
            sw = psutil.swap_memory()
            return {
                "total": vm.total,
                "available": vm.available,
                "used": vm.used,
                "percent": vm.percent,
                "swap_total": sw.total,
                "swap_used": sw.used,
                "swap_percent": sw.percent,
            }
        except Exception as e:
            logger.warning(f"Failed to collect memory metrics: {e}")
            return {"error": str(e)}

    # ── Disk ───────────────────────────────────────────────────────

    def get_disk_metrics(self) -> Dict[str, Any]:
        try:
            partitions = psutil.disk_partitions(all=False)
            result = []
            for p in partitions:
                try:
                    usage = psutil.disk_usage(p.mountpoint)
                    result.append({
                        "device": p.device,
                        "mountpoint": p.mountpoint,
                        "fstype": p.fstype,
                        "total": usage.total,
                        "used": usage.used,
                        "free": usage.free,
                        "percent": usage.percent,
                    })
                except (PermissionError, OSError):
                    pass
            io = psutil.disk_io_counters()
            return {
                "partitions": result,
                "io": {
                    "read_count": io.read_count if io else 0,
                    "write_count": io.write_count if io else 0,
                    "read_bytes": io.read_bytes if io else 0,
                    "write_bytes": io.write_bytes if io else 0,
                },
            }
        except Exception as e:
            logger.warning(f"Failed to collect disk metrics: {e}")
            return {"error": str(e)}

    # ── Network ────────────────────────────────────────────────────

    def get_network_metrics(self) -> Dict[str, Any]:
        try:
            net = psutil.net_io_counters()
            return {
                "bytes_sent": net.bytes_sent,
                "bytes_recv": net.bytes_recv,
                "packets_sent": net.packets_sent,
                "packets_recv": net.packets_recv,
                "errin": net.errin,
                "errout": net.errout,
                "dropin": net.dropin,
                "dropout": net.dropout,
            }
        except Exception as e:
            logger.warning(f"Failed to collect network metrics: {e}")
            return {"error": str(e)}

    # ── Process ────────────────────────────────────────────────────

    def get_process_metrics(self) -> Dict[str, Any]:
        try:
            proc = psutil.Process()
            return {
                "pid": proc.pid,
                "status": proc.status(),
                "cpu_percent": proc.cpu_percent(),
                "memory_info": {
                    "rss": proc.memory_info().rss,
                    "vms": proc.memory_info().vms,
                },
                "threads": proc.num_threads(),
                "open_files": len(proc.open_files()),
                "connections": len(proc.net_connections()),
            }
        except Exception as e:
            logger.warning(f"Failed to collect process metrics: {e}")
            return {"error": str(e)}

    # ── Full snapshot ──────────────────────────────────────────────

    def get_full_snapshot(self) -> Dict[str, Any]:
        """Collect all metrics in one call."""
        snapshot = {
            "timestamp": time.time(),
            "uptime_seconds": self.get_uptime(),
            "cpu": self.get_cpu_metrics(),
            "memory": self.get_memory_metrics(),
            "disk": self.get_disk_metrics(),
            "network": self.get_network_metrics(),
            "process": self.get_process_metrics(),
            "api_stats": self.get_api_stats(),
        }
        self._last_snapshot = snapshot
        return snapshot

    # ── Health summary ─────────────────────────────────────────────

    def get_health_summary(self) -> Dict[str, Any]:
        """Quick health check with status indicators."""
        mem = self.get_memory_metrics()
        disk = self.get_disk_metrics()

        mem_ok = mem.get("percent", 0) < 90
        disk_ok = all(p.get("percent", 0) < 90 for p in disk.get("partitions", []))

        status = "healthy"
        if not mem_ok or not disk_ok:
            status = "warning"
        if mem.get("percent", 0) > 95 or any(p.get("percent", 0) > 95 for p in disk.get("partitions", [])):
            status = "critical"

        return {
            "status": status,
            "uptime_seconds": self.get_uptime(),
            "memory_percent": mem.get("percent", 0),
            "disk_usage": [(p["mountpoint"], p["percent"]) for p in disk.get("partitions", [])],
        }


# Module-level singleton
collector = SystemMetricsCollector()
