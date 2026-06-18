# -*- coding: utf-8 -*-
"""Enterprise Audit API Router.

Provides audit log management and compliance reporting endpoints.
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, HTTPException, Query, Request

from coapis.app.auth import require_admin

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/audit", tags=["enterprise-audit"])

# Import audit logger
from .audit_logger import AuditLogger

_audit_logger = AuditLogger()


@router.get("/logs")
async def get_audit_logs(
    request: Request,
    user: Optional[str] = Query(None),
    action: Optional[str] = Query(None),
    limit: int = Query(100, ge=1, le=1000),
) -> Dict[str, Any]:
    """Get audit log entries.
    
    Enterprise feature: Comprehensive audit logging.
    """
    require_admin(request)
    
    entries = _audit_logger.get_entries(user=user, action=action, limit=limit)
    
    return {
        "entries": [e.model_dump() for e in entries],
        "total": len(entries),
    }


@router.post("/logs")
async def create_audit_log(
    request: Request,
    user: str = "",
    action: str = "",
    resource: str = "",
    success: bool = True,
) -> Dict[str, Any]:
    """Create audit log entry.
    
    Enterprise feature: Comprehensive audit logging.
    """
    require_admin(request)
    
    entry = _audit_logger.log(
        user=user,
        action=action,
        resource=resource,
        success=success,
        ip_address=request.client.host if request.client else "",
    )
    
    return {
        "success": True,
        "entry": entry.model_dump(),
    }


@router.get("/integrity")
async def verify_log_integrity(request: Request) -> Dict[str, Any]:
    """Verify audit log integrity.
    
    Enterprise feature: Tamper-proof log storage.
    """
    require_admin(request)
    
    return _audit_logger.verify_integrity()


@router.get("/reports/compliance")
async def get_compliance_report(
    request: Request,
    standard: str = Query("SOC2", regex="^(SOC2|GDPR)$"),
) -> Dict[str, Any]:
    """Generate compliance report.
    
    Enterprise feature: Compliance reporting.
    """
    require_admin(request)
    
    return _audit_logger.get_compliance_report(standard)


@router.get("/stats")
async def get_audit_stats(request: Request) -> Dict[str, Any]:
    """Get audit statistics.
    
    Enterprise feature: Audit analytics.
    """
    require_admin(request)
    
    return _audit_logger.get_stats()
