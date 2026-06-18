# -*- coding: utf-8 -*-
"""Enterprise Monitoring API Router.

Provides enhanced monitoring endpoints with Prometheus integration.
"""

from __future__ import annotations

import logging
from typing import Any, Dict

from fastapi import APIRouter, HTTPException, Request

from .collector import MetricsCollector

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/monitor", tags=["enterprise-monitoring"])

# Global metrics collector instance
_metrics_collector = MetricsCollector()


@router.get("/prometheus")
async def get_prometheus_metrics(request: Request) -> Dict[str, Any]:
    """Get metrics in Prometheus exposition format.
    
    Enterprise feature: Prometheus integration for metrics scraping.
    """
    from coapis.enterprise_plugin import check_enterprise_feature
    
    if not check_enterprise_feature("monitoring")["available"]:
        raise HTTPException(
            status_code=402,
            detail="Prometheus metrics require Enterprise edition"
        )
    
    return {
        "content_type": "text/plain",
        "data": _metrics_collector.get_prometheus_metrics(),
    }


@router.post("/alerts")
async def configure_alerts(request: Request, config: Dict[str, Any]) -> Dict[str, Any]:
    """Configure alert rules.
    
    Enterprise feature: Advanced alerting with custom rules.
    """
    from coapis.enterprise_plugin import check_enterprise_feature
    
    if not check_enterprise_feature("monitoring")["available"]:
        raise HTTPException(
            status_code=402,
            detail="Alert configuration requires Enterprise edition"
        )
    
    # Store alert configuration
    logger.info(f"Alert rules updated: {config}")
    
    return {
        "success": True,
        "message": "Alert rules updated successfully",
    }


@router.get("/alerts")
async def get_alerts(request: Request) -> Dict[str, Any]:
    """Get current alert status.
    
    Enterprise feature: Advanced alerting with custom rules.
    """
    from coapis.enterprise_plugin import check_enterprise_feature
    
    if not check_enterprise_feature("monitoring")["available"]:
        raise HTTPException(
            status_code=402,
            detail="Alert status requires Enterprise edition"
        )
    
    return {
        "active_alerts": [],
        "resolved_alerts": [],
        "alert_rules": [],
    }


@router.get("/custom-metrics")
async def get_custom_metrics(request: Request) -> Dict[str, Any]:
    """Get custom application metrics.
    
    Enterprise feature: Custom metric definitions and collection.
    """
    from coapis.enterprise_plugin import check_enterprise_feature
    
    if not check_enterprise_feature("monitoring")["available"]:
        raise HTTPException(
            status_code=402,
            detail="Custom metrics require Enterprise edition"
        )
    
    metrics = _metrics_collector.collect_system_metrics()
    
    return {
        "custom_metrics": metrics.get("system", {}),
        "counters": {},
        "gauges": {},
    }
