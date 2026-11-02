"""Audit log query endpoints.

Moved off raw SQL 2026-11: this router used to call ``db.execute(...)`` on the
delegating ``UserSystemDB``, which has no such method, so every endpoint here
answered 500 -- on the community edition *and* the enterprise one
(``AttributeError: 'UserSystemDB' object has no attribute 'execute'``). The
reads now go through the repository seam (``list_audit_logs`` / ``audit_stats``),
which is also where each edition keeps its own ``created_at`` semantics
(REAL epoch on SQLite, TIMESTAMPTZ on PostgreSQL).
"""

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import JSONResponse
from datetime import datetime, timezone

from coapis.user_system.database import UserSystemDB, get_db
from coapis.foundation.db import get_session_factory
from coapis.app.services.admin_service import verify_admin, verify_admin_token
from coapis.app.services.rbac_service import require_role
from coapis.app.services.auth_service import AuthContext, hash_password

router = APIRouter()


def _epoch(value: str) -> float:
    """Accept an ISO-8601 string and return unix seconds."""
    try:
        return datetime.fromisoformat(value).timestamp()
    except Exception:
        raise HTTPException(status_code=400, detail=f"Invalid timestamp: {value}")


@router.get("/audit")
def list_audit_logs(
    limit: int = Query(50, ge=1, le=500),
    offset: int = Query(0, ge=0),
    username: str = None,
    action: str = None,
    resource_type: str = None,
    start_time: str = None,
    end_time: str = None,
    _ctx: AuthContext = Depends(verify_admin_token),
    db: UserSystemDB = Depends(get_db),
):
    """List audit logs with optional filters."""
    rows, total = db.list_audit_logs(
        limit=limit,
        offset=offset,
        username=username,
        action=action,
        resource_type=resource_type,
        start_time=_epoch(start_time) if start_time else None,
        end_time=_epoch(end_time) if end_time else None,
    )
    return {"logs": rows, "total": total}


@router.get("/audit/stats")
def audit_stats(
    _ctx: AuthContext = Depends(verify_admin),
    db: UserSystemDB = Depends(get_db),
):
    """Get audit log statistics summary."""
    return db.audit_stats()


@router.get("/audit/export")
def export_audit_logs(
    username: str = None,
    action: str = None,
    start_time: str = None,
    end_time: str = None,
    _ctx: AuthContext = Depends(verify_admin),
    db: UserSystemDB = Depends(get_db),
):
    """Export audit logs as JSON (max 10000 records)."""
    rows, total = db.list_audit_logs(
        limit=10000,
        offset=0,
        username=username,
        action=action,
        start_time=_epoch(start_time) if start_time else None,
        end_time=_epoch(end_time) if end_time else None,
    )
    ts = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    return JSONResponse(
        content={"logs": rows, "exported_at": ts, "total": total},
        headers={
            "Content-Disposition": f"attachment; filename=audit_log_{ts}.json",
        },
    )
