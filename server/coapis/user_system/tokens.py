# -*- coding: utf-8 -*-
# -*- coding: utf-8 -*-
# Copyright 2026 蜜蜂 & CoApis Contributors
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU Affero General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU Affero General Public License for more details.
#
# You should have received a copy of the GNU Affero General Public License
# along with this program.  If not, see <https://www.gnu.org/licenses/>.

"""Token service - token usage tracking, quota management, and billing.

Handles:
- Recording token usage per request
- Monthly quota tracking and reset
- Usage statistics and summaries
- Cost calculation based on model pricing
- Quota enforcement (soft/hard limits)
"""
from __future__ import annotations

import logging
import time
from typing import Any, Dict, List, Optional

from ..user_system.database import get_db
from ..user_system.models import (
    TokenUsageRecord, TokenUsageSummary, TokenUsageList, TokenRecordRequest,
)
from ..user_system.config import get_config

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Model pricing (per 1M tokens, in cents)
# ---------------------------------------------------------------------------

# Default pricing table - configurable via env or admin
MODEL_PRICING: Dict[str, Dict[str, float]] = {
    # Lightweight models
    "qwen2.5-7b": {"input": 50, "output": 100},
    "qwen2.5-14b": {"input": 100, "output": 200},
    "qwen2.5-32b": {"input": 150, "output": 300},
    # Standard models
    "qwen3.6-27b": {"input": 200, "output": 400},
    "qwen-plus": {"input": 300, "output": 600},
    # Advanced models
    "qwen-max": {"input": 1000, "output": 2000},
    "gpt-4o": {"input": 2500, "output": 10000},
    "claude-sonnet-4": {"input": 5000, "output": 10000},
    # Local models (free by default)
}


def get_model_pricing(model: str) -> Dict[str, float]:
    """Get pricing for a model. Returns free pricing if not found."""
    # Normalize model name
    model_lower = model.lower()
    for key, pricing in MODEL_PRICING.items():
        if key in model_lower or model_lower in key:
            return pricing
    # Default pricing for unknown models
    return {"input": 200, "output": 400}


# ---------------------------------------------------------------------------
# Token recording
# ---------------------------------------------------------------------------

def record_token_usage(req: TokenRecordRequest) -> TokenUsageRecord:
    """Record token usage for a user.

    Returns the created record.
    Raises ValueError if user doesn't exist.
    """
    db = get_db()
    cfg = get_config()

    row = db.fetch_one("SELECT * FROM users WHERE username = ?", (req.username,))
    if not row:
        raise ValueError(f"User '{req.username}' not found")

    total_tokens = req.input_tokens + req.output_tokens
    if total_tokens <= 0:
        return TokenUsageRecord(
            id=0,
            user_id=row["id"],
            username=req.username,
            agent_id=req.agent_id,
            model=req.model,
            input_tokens=0,
            output_tokens=0,
            total_tokens=0,
            cost_cents=0.0,
        )

    # Calculate cost
    pricing = get_model_pricing(req.model)
    cost_cents = (req.input_tokens * pricing["input"] + req.output_tokens * pricing["output"]) / 1_000_000

    # Check if local model (free tokens)
    is_local = _is_local_model(req.model)
    if cfg.local_model_free_tokens and is_local:
        cost_cents = 0.0

    # Record usage
    now = time.time()
    cur = db.execute("""
        INSERT INTO token_usage (
            user_id, username, agent_id, model,
            input_tokens, output_tokens, total_tokens,
            cost_cents, created_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (
        row["id"],
        req.username,
        req.agent_id,
        req.model,
        req.input_tokens,
        req.output_tokens,
        total_tokens,
        cost_cents,
        now,
    ))
    db.commit()

    # Update monthly usage counter
    db.execute("""
        UPDATE users SET
            token_used_monthly = token_used_monthly + ?,
            updated_at = ?
        WHERE username = ?
    """, (total_tokens, now, req.username))
    db.commit()

    return TokenUsageRecord(
        id=cur.lastrowid,
        user_id=row["id"],
        username=req.username,
        agent_id=req.agent_id,
        model=req.model,
        input_tokens=req.input_tokens,
        output_tokens=req.output_tokens,
        total_tokens=total_tokens,
        cost_cents=cost_cents,
        created_at=now,
    )


def record_token_usage_simple(
    username: str,
    model: str,
    input_tokens: int,
    output_tokens: int,
    agent_id: Optional[str] = None,
) -> TokenUsageRecord:
    """Convenience method to record token usage."""
    return record_token_usage(TokenRecordRequest(
        username=username,
        model=model,
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        agent_id=agent_id,
    ))


# ---------------------------------------------------------------------------
# Quota checking
# ---------------------------------------------------------------------------

def check_quota(username: str, requested_tokens: int = 0) -> Dict[str, Any]:
    """Check token quota status for a user.

    Returns:
        {
            "allowed": bool,
            "quota": int,
            "used": int,
            "remaining": int,
            "usage_percent": float,
            "hard_limit": bool,
        }
    """
    db = get_db()
    cfg = get_config()

    row = db.fetch_one("SELECT * FROM users WHERE username = ?", (username,))
    if not row:
        return {
            "allowed": True,  # Anonymous users always allowed
            "quota": 0,
            "used": 0,
            "remaining": 0,
            "usage_percent": 0.0,
            "hard_limit": False,
        }

    quota = row.get("token_quota_monthly", 1_000_000)
    used = row.get("token_used_monthly", 0)
    remaining = max(0, quota - used)
    usage_percent = (used / quota * 100) if quota > 0 else 0.0

    # Unlimited quota (L4 enterprise)
    if quota < 0:
        return {
            "allowed": True,
            "quota": -1,
            "used": used,
            "remaining": -1,
            "usage_percent": 0.0,
            "hard_limit": False,
        }

    # Check if request would exceed quota
    allowed = True
    if not cfg.token_quota_hard_limit:
        # Soft limit: allow up to 120% with warning
        if used + requested_tokens > quota * 1.2:
            allowed = False
    else:
        # Hard limit: stop at 100%
        if used + requested_tokens > quota:
            allowed = False

    return {
        "allowed": allowed,
        "quota": quota,
        "used": used,
        "remaining": remaining,
        "usage_percent": round(usage_percent, 2),
        "hard_limit": cfg.token_quota_hard_limit,
    }


def is_quota_exceeded(username: str) -> bool:
    """Quick check if user has exceeded quota."""
    status = check_quota(username)
    return not status["allowed"]


# ---------------------------------------------------------------------------
# Usage statistics
# ---------------------------------------------------------------------------

def get_usage_summary(username: str) -> TokenUsageSummary:
    """Get token usage summary for a user."""
    db = get_db()

    row = db.fetch_one("SELECT * FROM users WHERE username = ?", (username,))
    if not row:
        return TokenUsageSummary(
            username=username,
            quota_monthly=0,
            used_monthly=0,
            remaining=0,
            usage_percent=0.0,
        )

    quota = row.get("token_quota_monthly", 1_000_000)
    used = row.get("token_used_monthly", 0)

    # Get total stats
    stats = db.fetch_one("""
        SELECT
            COALESCE(SUM(input_tokens), 0) as total_input,
            COALESCE(SUM(output_tokens), 0) as total_output,
            COALESCE(SUM(cost_cents), 0) as total_cost
        FROM token_usage WHERE username = ?
    """, (username,))

    # Get top models
    top_models = db.fetch_all("""
        SELECT
            model,
            COUNT(*) as requests,
            SUM(input_tokens) as input_tokens,
            SUM(output_tokens) as output_tokens,
            SUM(cost_cents) as cost_cents
        FROM token_usage
        WHERE username = ?
        GROUP BY model
        ORDER BY cost_cents DESC
        LIMIT 5
    """, (username,))

    return TokenUsageSummary(
        username=username,
        quota_monthly=quota,
        used_monthly=used,
        remaining=max(0, quota - used) if quota > 0 else -1,
        usage_percent=(used / quota * 100) if quota > 0 else 0.0,
        total_input_tokens=stats["total_input"],
        total_output_tokens=stats["total_output"],
        total_cost_cents=stats["total_cost"],
        top_models=[dict(r) for r in top_models],
    )


def get_usage_history(
    username: str,
    page: int = 1,
    page_size: int = 50,
    model: Optional[str] = None,
    agent_id: Optional[str] = None,
) -> TokenUsageList:
    """Get token usage history for a user."""
    db = get_db()

    where = "username = ?"
    params: list = [username]

    if model:
        where += " AND model = ?"
        params.append(model)

    if agent_id:
        where += " AND agent_id = ?"
        params.append(agent_id)

    total = db.fetch_one(f"SELECT COUNT(*) as cnt FROM token_usage WHERE {where}", tuple(params))["cnt"]

    offset = (page - 1) * page_size
    rows = db.fetch_all(
        f"SELECT * FROM token_usage WHERE {where} ORDER BY created_at DESC LIMIT ? OFFSET ?",
        tuple(params) + [page_size, offset],
    )

    records = [
        TokenUsageRecord(
            id=r["id"],
            user_id=r["user_id"],
            username=r["username"],
            agent_id=r.get("agent_id"),
            model=r["model"],
            input_tokens=r.get("input_tokens", 0),
            output_tokens=r.get("output_tokens", 0),
            total_tokens=r.get("total_tokens", 0),
            cost_cents=r.get("cost_cents", 0.0),
            created_at=r.get("created_at"),
        )
        for r in rows
    ]

    return TokenUsageList(
        records=records,
        total=total,
        page=page,
        page_size=page_size,
    )


# ---------------------------------------------------------------------------
# Monthly reset
# ---------------------------------------------------------------------------

def reset_monthly_quotas() -> int:
    """Reset monthly token usage for all users.

    Returns number of users reset.
    """
    db = get_db()
    today = _today_str()

    cur = db.execute("""
        UPDATE users SET
            token_used_monthly = 0,
            token_quota_reset_date = ?
        WHERE token_used_monthly > 0
    """, (today,))
    db.commit()

    count = cur.rowcount
    if count:
        logger.info(f"Reset monthly token quotas for {count} users")
    return count


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _is_local_model(model: str) -> bool:
    """Check if a model is a local model (running on local LLM server)."""
    local_indicators = ["local", "localhost", "127.0.0.1", "172.16."]
    model_lower = model.lower()
    return any(indicator in model_lower for indicator in local_indicators)


def _today_str() -> str:
    """Return today's date as YYYY-MM-DD string."""
    return time.strftime("%Y-%m-%d")
