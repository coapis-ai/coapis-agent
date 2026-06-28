# -*- coding: utf-8 -*-
"""Input Guard rules management API."""

from __future__ import annotations

import re
from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from ...security.input_guard import get_input_guard_engine
from ...security.input_guard.models import InputGuardSeverity, InputGuardThreatCategory

router = APIRouter(prefix="/input-guard", tags=["input-guard"])


# ── Request/Response models ──

class InputGuardRuleBody(BaseModel):
    id: str
    category: str
    severity: str
    patterns: list[str]
    description: str = ""


class InputGuardTestBody(BaseModel):
    text: str


# ── Endpoints ──

@router.get("/rules")
async def list_rules() -> list[dict[str, Any]]:
    """List all input guard rules."""
    engine = get_input_guard_engine()
    return engine.list_rules()


@router.get("/rules/{rule_id}")
async def get_rule(rule_id: str) -> dict[str, Any]:
    """Get a single rule by id."""
    engine = get_input_guard_engine()
    rule = engine.get_rule(rule_id)
    if not rule:
        raise HTTPException(status_code=404, detail=f"Rule '{rule_id}' not found")
    return rule


@router.post("/rules")
async def add_rule(body: InputGuardRuleBody) -> dict[str, Any]:
    """Add a new input guard rule."""
    engine = get_input_guard_engine()
    # Check duplicate
    if engine.get_rule(body.id):
        raise HTTPException(status_code=409, detail=f"Rule '{body.id}' already exists")
    # Validate patterns
    for p in body.patterns:
        try:
            re.compile(p, re.IGNORECASE)
        except re.error as e:
            raise HTTPException(status_code=400, detail=f"Invalid pattern '{p}': {e}")
    # Validate severity / category
    if body.severity not in [s.value for s in InputGuardSeverity]:
        raise HTTPException(status_code=400, detail=f"Invalid severity: {body.severity}")
    if body.category not in [c.value for c in InputGuardThreatCategory]:
        raise HTTPException(status_code=400, detail=f"Invalid category: {body.category}")
    rule = body.model_dump()
    engine.add_rule(rule)
    return rule


@router.put("/rules/{rule_id}")
async def update_rule(rule_id: str, body: InputGuardRuleBody) -> dict[str, Any]:
    """Update an existing rule."""
    engine = get_input_guard_engine()
    if not engine.get_rule(rule_id):
        raise HTTPException(status_code=404, detail=f"Rule '{rule_id}' not found")
    # Validate patterns
    for p in body.patterns:
        try:
            re.compile(p, re.IGNORECASE)
        except re.error as e:
            raise HTTPException(status_code=400, detail=f"Invalid pattern '{p}': {e}")
    rule = body.model_dump()
    engine.update_rule(rule_id, rule)
    return rule


@router.delete("/rules/{rule_id}")
async def delete_rule(rule_id: str) -> dict[str, str]:
    """Delete a rule by id."""
    engine = get_input_guard_engine()
    if not engine.delete_rule(rule_id):
        raise HTTPException(status_code=404, detail=f"Rule '{rule_id}' not found")
    return {"status": "deleted", "id": rule_id}


@router.post("/test")
async def test_text(body: InputGuardTestBody) -> dict[str, Any]:
    """Test a text against current rules."""
    engine = get_input_guard_engine()
    result = engine.check(body.text)
    return result.to_dict()


@router.post("/reload")
async def reload_rules() -> dict[str, Any]:
    """Hot-reload rules from disk."""
    engine = get_input_guard_engine()
    count = engine.reload()
    return {"status": "reloaded", "rule_count": count}
