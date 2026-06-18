# -*- coding: utf-8 -*-
# -*- coding: utf-8 -*-
# Copyright 2026 以太吃虾 & CoApis Contributors
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

"""Points service - point earning, spending, and streak tracking.

Handles:
- Adding points (earning from various sources)
- Spending points
- Daily cap enforcement
- Login streak tracking (weekly/monthly bonuses)
- Point transaction history
"""
from __future__ import annotations

import logging
import time
from typing import Any, Dict, List, Optional

from ..user_system.database import get_db
from ..user_system.models import (
    PointTransaction, PointTransactionList, PointAddRequest,
)
from ..user_system.config import get_config

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Point earning
# ---------------------------------------------------------------------------

def add_points(username: str, amount: int, source: str, description: Optional[str] = None) -> int:
    """Add points to a user account.

    Returns the actual points added (may be less than requested if daily cap applies).
    Raises ValueError if user doesn't exist.
    """
    db = get_db()
    cfg = get_config()

    if not cfg.enabled:
        return 0

    row = db.fetch_one("SELECT * FROM users WHERE username = ?", (username,))
    if not row:
        raise ValueError(f"User '{username}' not found")

    # Check if this source is subject to daily cap
    source_info = _get_source_info(source, cfg)
    if source_info is None:
        logger.warning(f"Unknown point source: {source}")
        return 0

    actual_amount = amount
    capped = False

    # Enforce daily cap if applicable
    if source_info.get("cap"):
        today = _today_str()
        daily_earned = _get_daily_points_earned(username, today, cfg)
        remaining_cap = max(0, cfg.points_daily_cap - daily_earned)
        if remaining_cap <= 0:
            logger.info(f"Daily cap reached for user '{username}'")
            return 0
        if actual_amount > remaining_cap:
            actual_amount = remaining_cap
            capped = True

    if actual_amount <= 0:
        return 0

    # Update user points
    now = time.time()
    db.execute("""
        UPDATE users SET
            points = points + ?,
            total_points_earned = total_points_earned + ?,
            updated_at = ?
        WHERE username = ?
    """, (actual_amount, actual_amount, now, username))

    # Record transaction
    db.execute("""
        INSERT INTO point_transactions (
            user_id, username, type, amount, source, description, created_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?)
    """, (row["id"], username, "earned", actual_amount, source, description or _source_description(source), now))

    db.commit()

    # Check streak bonuses
    _check_login_streak(username)

    # Recalculate level
    from ..user_system.service import recalculate_level
    recalculate_level(username)

    if capped:
        logger.info(f"Points for '{username}' capped: {actual_amount}/{amount} (source: {source})")

    return actual_amount


def spend_points(username: str, amount: int, source: str, description: Optional[str] = None) -> bool:
    """Spend points from a user account.

    Returns True if successful, False if insufficient points.
    """
    db = get_db()
    cfg = get_config()

    if not cfg.enabled:
        return True  # No-op when disabled

    row = db.fetch_one("SELECT * FROM users WHERE username = ?", (username,))
    if not row:
        raise ValueError(f"User '{username}' not found")

    if row["points"] < amount:
        logger.warning(f"Insufficient points for user '{username}': {row['points']} < {amount}")
        return False

    now = time.time()
    db.execute("""
        UPDATE users SET
            points = points - ?,
            total_points_spent = total_points_spent + ?,
            updated_at = ?
        WHERE username = ?
    """, (amount, amount, now, username))

    db.execute("""
        INSERT INTO point_transactions (
            user_id, username, type, amount, source, description, created_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?)
    """, (row["id"], username, "spent", amount, source, description or _source_description(source), now))

    db.commit()

    # Recalculate level (in case spending drops below threshold)
    from ..user_system.service import recalculate_level
    recalculate_level(username)

    return True


def manual_add_points(req: PointAddRequest) -> int:
    """Manually add points (admin action)."""
    return add_points(req.username, req.amount, req.source, req.description)


# ---------------------------------------------------------------------------
# Point transaction history
# ---------------------------------------------------------------------------

def get_point_transactions(
    username: str,
    page: int = 1,
    page_size: int = 50,
    source: Optional[str] = None,
) -> PointTransactionList:
    """Get point transaction history for a user."""
    db = get_db()

    where = "username = ?"
    params: list = [username]

    if source:
        where += " AND source = ?"
        params.append(source)

    total = db.fetch_one(f"SELECT COUNT(*) as cnt FROM point_transactions WHERE {where}", tuple(params))["cnt"]

    offset = (page - 1) * page_size
    rows = db.fetch_all(
        f"SELECT * FROM point_transactions WHERE {where} ORDER BY created_at DESC LIMIT ? OFFSET ?",
        tuple(params) + [page_size, offset],
    )

    transactions = [
        PointTransaction(
            id=r["id"],
            user_id=r["user_id"],
            username=r["username"],
            type=r["type"],
            amount=r["amount"],
            source=r["source"],
            description=r.get("description"),
            created_at=r.get("created_at"),
        )
        for r in rows
    ]

    return PointTransactionList(
        transactions=transactions,
        total=total,
        page=page,
        page_size=page_size,
    )


# ---------------------------------------------------------------------------
# Login streak tracking
# ---------------------------------------------------------------------------

def _check_login_streak(username: str) -> None:
    """Check and award login streak bonuses."""
    db = get_db()
    cfg = get_config()

    row = db.fetch_one("SELECT * FROM users WHERE username = ?", (username,))
    if not row:
        return

    today = _today_str()
    last_login = row.get("last_login_date")
    consecutive = row.get("consecutive_login_days", 0)

    # Determine new streak
    if last_login == today:
        # Already logged in today, no streak update
        return

    yesterday = _yesterday_str()
    if last_login == yesterday:
        # Consecutive login
        consecutive += 1
    elif last_login != today:
        # Missed a day, reset streak
        consecutive = 1

    # Update streak
    db.execute("""
        UPDATE users SET consecutive_login_days = ?, last_login_date = ?
        WHERE username = ?
    """, (consecutive, today, username))
    db.commit()

    # Award weekly streak bonus (7 days)
    if consecutive >= 7 and consecutive % 7 == 0:
        last_weekly = _get_setting(username, "last_weekly_streak_day")
        if last_weekly != str(consecutive):
            bonus = add_points(username, cfg.points_weekly_streak, "weekly_streak",
                             f"连续登录{consecutive}天奖励")
            if bonus:
                _set_setting(username, "last_weekly_streak_day", str(consecutive))
                logger.info(f"Weekly streak bonus for '{username}': +{bonus} points")

    # Award monthly streak bonus (30 days)
    if consecutive >= 30 and consecutive % 30 == 0:
        last_monthly = _get_setting(username, "last_monthly_streak_day")
        if last_monthly != str(consecutive):
            bonus = add_points(username, cfg.points_monthly_streak, "monthly_streak",
                             f"连续登录{consecutive}天奖励")
            if bonus:
                _set_setting(username, "last_monthly_streak_day", str(consecutive))
                logger.info(f"Monthly streak bonus for '{username}': +{bonus} points")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _get_daily_points_earned(username: str, date_str: str, cfg) -> int:
    """Get total points earned by user on a given date (capped sources only)."""
    db = get_db()

    # Get all capped sources
    capped_sources = [s["source"] for s in cfg.point_rules if s.get("cap")]
    if not capped_sources:
        return 0

    placeholders = ", ".join(["?"] * len(capped_sources))
    rows = db.fetch_all(f"""
        SELECT SUM(amount) as total FROM point_transactions
        WHERE username = ? AND type = 'earned' AND source IN ({placeholders})
        AND strftime('%Y-%m-%d', created_at, 'unixepoch') = ?
    """, [username] + capped_sources + [date_str])

    return rows[0]["total"] if rows and rows[0]["total"] else 0


def _get_source_info(source: str, cfg) -> Optional[Dict[str, Any]]:
    """Get source info from config."""
    for rule in cfg.point_rules:
        if rule["source"] == source:
            return rule
    return None


def _source_description(source: str) -> str:
    """Get default description for a source."""
    descriptions = {
        "first_login": "首次登录奖励",
        "daily_login": "每日登录奖励",
        "chat": "完成对话奖励",
        "create_agent": "创建Agent奖励",
        "create_skill": "创建技能奖励",
        "mcp_config": "配置MCP工具奖励",
        "doc_import": "导入文档奖励",
        "weekly_streak": "连续登录7天奖励",
        "monthly_streak": "连续登录30天奖励",
        "manual": "手动调整",
    }
    return descriptions.get(source, source)


def _get_setting(username: str, key: str) -> Optional[str]:
    """Get user setting."""
    db = get_db()
    row = db.fetch_one(
        "SELECT s.setting_value FROM user_settings s "
        "JOIN users u ON u.id = s.user_id "
        "WHERE u.username = ? AND s.setting_key = ?",
        (username, key)
    )
    return row["setting_value"] if row else None


def _set_setting(username: str, key: str, value: str) -> None:
    """Set user setting."""
    db = get_db()
    db.execute("""
        INSERT OR REPLACE INTO user_settings (user_id, username, setting_key, setting_value)
        SELECT u.id, u.username, ?, ? FROM users u WHERE u.username = ?
    """, (key, value, username))
    db.commit()


def _today_str() -> str:
    """Return today's date as YYYY-MM-DD string."""
    return time.strftime("%Y-%m-%d")


def _yesterday_str() -> str:
    """Return yesterday's date as YYYY-MM-DD string."""
    t = time.time() - 86400
    return time.strftime("%Y-%m-%d", time.localtime(t))
