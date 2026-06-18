# -*- coding: utf-8 -*-
"""Enterprise Metrics Collector with Prometheus integration.

This module extends the basic monitoring with:
- Prometheus metrics export
- Custom metric definitions
- Alert rules configuration
"""

from __future__ import annotations

import logging
import time
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


class MetricsCollector:
    """Enterprise metrics collector with Prometheus support.
    
    Collects system metrics and exposes them via Prometheus format.
    """
    
    def __init__(self):
        self._metrics: Dict[str, float] = {}
        self._counters: Dict[str, int] = {}
        self._gauges: Dict[str, float] = {}
        self._histograms: Dict[str, List[float]] = {}
        self._start_time = time.time()
        self._prometheus_enabled = self._check_prometheus()
    
    def _check_prometheus(self) -> bool:
        """Check if Prometheus client is available."""
        try:
            import prometheus_client  # noqa: F401
            return True
        except ImportError:
            logger.info("Prometheus client not installed. Install with: pip install prometheus-client")
            return False
    
    def collect_system_metrics(self) -> Dict[str, Any]:
        """Collect comprehensive system metrics."""
        metrics = {
            "timestamp": time.time(),
            "uptime": time.time() - self._start_time,
            "system": self._collect_system_info(),
            "process": self._collect_process_info(),
            "api": self._collect_api_stats(),
        }
        
        # Add Prometheus metrics if available
        if self._prometheus_enabled:
            metrics["prometheus"] = self._format_for_prometheus()
        
        return metrics
    
    def _collect_system_info(self) -> Dict[str, Any]:
        """Collect system-level metrics."""
        try:
            import psutil
            
            cpu = psutil.cpu_percent(interval=0.1)
            memory = psutil.virtual_memory()
            disk = psutil.disk_usage("/")
            
            return {
                "cpu_percent": cpu,
                "memory": {
                    "total": memory.total,
                    "available": memory.available,
                    "percent": memory.percent,
                },
                "disk": {
                    "total": disk.total,
                    "free": disk.free,
                    "percent": disk.percent,
                },
            }
        except ImportError:
            return {"error": "psutil not installed"}
    
    def _collect_process_info(self) -> Dict[str, Any]:
        """Collect process-level metrics."""
        try:
            import psutil
            import os
            
            process = psutil.Process(os.getpid())
            return {
                "pid": process.pid,
                "cpu_percent": process.cpu_percent(),
                "memory_rss": process.memory_info().rss,
                "threads": process.num_threads(),
                "open_files": len(process.open_files()),
            }
        except ImportError:
            return {"error": "psutil not installed"}
    
    def _collect_api_stats(self) -> Dict[str, Any]:
        """Collect API statistics."""
        # This would integrate with the actual API stats collector
        return {
            "total_requests": 0,
            "active_connections": 0,
            "avg_response_time": 0.0,
        }
    
    def _format_for_prometheus(self) -> str:
        """Format metrics in Prometheus exposition format."""
        lines = []
        
        # Add custom metrics
        for name, value in self._metrics.items():
            lines.append(f"# TYPE {name} gauge")
            lines.append(f"{name} {value}")
        
        for name, count in self._counters.items():
            lines.append(f"# TYPE {name} counter")
            lines.append(f"{name} {count}")
        
        return "\n".join(lines)
    
    def increment_counter(self, name: str, value: int = 1) -> None:
        """Increment a counter metric."""
        self._counters[name] = self._counters.get(name, 0) + value
    
    def set_gauge(self, name: str, value: float) -> None:
        """Set a gauge metric."""
        self._gauges[name] = value
    
    def observe_histogram(self, name: str, value: float) -> None:
        """Observe a value for histogram."""
        if name not in self._histograms:
            self._histograms[name] = []
        self._histograms[name].append(value)
    
    def get_prometheus_metrics(self) -> str:
        """Get metrics in Prometheus format."""
        return self._format_for_prometheus()
