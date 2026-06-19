# -*- coding: utf-8 -*-
# Copyright 2026 蜜蜂 & CoApis Contributors
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

"""SQLite writer for token usage — per-user, per-agent tracking.

Writes to user_system.db's token_usage table for detailed analytics.
"""

import logging
import os
import sqlite3
import time
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

# Database path (can be overridden via env var)
_DB_PATH: Optional[Path] = None


def _get_db_path() -> Path:
    """Get the user_system.db path."""
    global _DB_PATH
    if _DB_PATH is not None:
        return _DB_PATH
    
    # Check env var first
    env_path = os.environ.get("COAPIS_USER_SYSTEM_DB")
    if env_path:
        _DB_PATH = Path(env_path)
        return _DB_PATH
    
    # Default path
    _DB_PATH = Path("/apps/ai/coapis/system/user_system.db")
    return _DB_PATH


def _ensure_table_exists(conn: sqlite3.Connection) -> None:
    """Create token_usage table if it doesn't exist."""
    conn.execute("""
        CREATE TABLE IF NOT EXISTS token_usage (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL DEFAULT 0,
            username TEXT NOT NULL DEFAULT 'anonymous',
            agent_id TEXT,
            model TEXT NOT NULL,
            input_tokens INTEGER DEFAULT 0,
            output_tokens INTEGER DEFAULT 0,
            total_tokens INTEGER DEFAULT 0,
            cost_cents REAL DEFAULT 0.0,
            created_at REAL DEFAULT (strftime('%s', 'now'))
        )
    """)
    conn.commit()


def save_token_usage(
    user_id: Optional[int],
    username: Optional[str],
    agent_id: Optional[str],
    model: str,
    input_tokens: int,
    output_tokens: int,
    total_tokens: int,
    cost_cents: float = 0.0,
) -> bool:
    """Save a token usage record to SQLite.
    
    Returns True on success, False on failure.
    """
    db_path = _get_db_path()
    
    # Provide default values for NOT NULL fields
    if user_id is None:
        user_id = 0
    if not username:
        username = "anonymous"
    
    try:
        conn = sqlite3.connect(str(db_path), timeout=5.0)
        _ensure_table_exists(conn)
        
        conn.execute("""
            INSERT INTO token_usage 
            (user_id, username, agent_id, model, input_tokens, output_tokens, total_tokens, cost_cents, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            user_id,
            username,
            agent_id,
            model,
            input_tokens,
            output_tokens,
            total_tokens,
            cost_cents,
            time.time(),
        ))
        conn.commit()
        conn.close()
        
        logger.debug(
            "Token usage saved: user=%s, agent=%s, model=%s, tokens=%d",
            username, agent_id, model, total_tokens
        )
        return True
        
    except Exception as e:
        logger.warning("Failed to save token usage to SQLite: %s", e)
        return False


def get_user_token_usage(
    username: str,
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
) -> dict:
    """Get token usage summary for a user.
    
    Args:
        username: Username to query
        start_date: Start date (YYYY-MM-DD), inclusive
        end_date: End date (YYYY-MM-DD), inclusive
    
    Returns:
        Dictionary with total tokens, by_agent, by_model breakdowns
    """
    db_path = _get_db_path()
    
    if not db_path.exists():
        return {"total_tokens": 0, "by_agent": {}, "by_model": {}}
    
    try:
        conn = sqlite3.connect(str(db_path), timeout=5.0)
        conn.row_factory = sqlite3.Row
        
        # Build query
        query = "SELECT * FROM token_usage WHERE username = ?"
        params = [username]
        
        if start_date:
            query += " AND created_at >= ?"
            # Convert date string to timestamp
            import datetime
            start_ts = datetime.datetime.strptime(start_date, "%Y-%m-%d").timestamp()
            params.append(start_ts)
        
        if end_date:
            query += " AND created_at <= ?"
            # Convert date string to timestamp (end of day)
            import datetime
            end_ts = datetime.datetime.strptime(end_date, "%Y-%m-%d").timestamp() + 86399
            params.append(end_ts)
        
        cursor = conn.execute(query, params)
        rows = cursor.fetchall()
        conn.close()
        
        # Aggregate
        total_input = 0
        total_output = 0
        total_tokens = 0
        by_agent = {}
        by_model = {}
        
        for row in rows:
            total_input += row["input_tokens"]
            total_output += row["output_tokens"]
            total_tokens += row["total_tokens"]
            
            # By agent
            agent_id = row["agent_id"] or "unknown"
            if agent_id not in by_agent:
                by_agent[agent_id] = {"input_tokens": 0, "output_tokens": 0, "total_tokens": 0, "calls": 0}
            by_agent[agent_id]["input_tokens"] += row["input_tokens"]
            by_agent[agent_id]["output_tokens"] += row["output_tokens"]
            by_agent[agent_id]["total_tokens"] += row["total_tokens"]
            by_agent[agent_id]["calls"] += 1
            
            # By model
            model = row["model"] or "unknown"
            if model not in by_model:
                by_model[model] = {"input_tokens": 0, "output_tokens": 0, "total_tokens": 0, "calls": 0}
            by_model[model]["input_tokens"] += row["input_tokens"]
            by_model[model]["output_tokens"] += row["output_tokens"]
            by_model[model]["total_tokens"] += row["total_tokens"]
            by_model[model]["calls"] += 1
        
        return {
            "username": username,
            "total_input_tokens": total_input,
            "total_output_tokens": total_output,
            "total_tokens": total_tokens,
            "total_calls": len(rows),
            "by_agent": by_agent,
            "by_model": by_model,
        }
        
    except Exception as e:
        logger.warning("Failed to get token usage for user %s: %s", username, e)
        return {"total_tokens": 0, "by_agent": {}, "by_model": {}}


def get_agent_token_usage(
    agent_id: str,
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
) -> dict:
    """Get token usage summary for an agent."""
    db_path = _get_db_path()
    
    if not db_path.exists():
        return {"total_tokens": 0, "by_user": {}, "by_model": {}}
    
    try:
        conn = sqlite3.connect(str(db_path), timeout=5.0)
        conn.row_factory = sqlite3.Row
        
        query = "SELECT * FROM token_usage WHERE agent_id = ?"
        params = [agent_id]
        
        if start_date:
            query += " AND created_at >= ?"
            import datetime
            start_ts = datetime.datetime.strptime(start_date, "%Y-%m-%d").timestamp()
            params.append(start_ts)
        
        if end_date:
            query += " AND created_at <= ?"
            import datetime
            end_ts = datetime.datetime.strptime(end_date, "%Y-%m-%d").timestamp() + 86399
            params.append(end_ts)
        
        cursor = conn.execute(query, params)
        rows = cursor.fetchall()
        conn.close()
        
        total_input = 0
        total_output = 0
        total_tokens = 0
        by_user = {}
        by_model = {}
        
        for row in rows:
            total_input += row["input_tokens"]
            total_output += row["output_tokens"]
            total_tokens += row["total_tokens"]
            
            username = row["username"] or "unknown"
            if username not in by_user:
                by_user[username] = {"input_tokens": 0, "output_tokens": 0, "total_tokens": 0, "calls": 0}
            by_user[username]["input_tokens"] += row["input_tokens"]
            by_user[username]["output_tokens"] += row["output_tokens"]
            by_user[username]["total_tokens"] += row["total_tokens"]
            by_user[username]["calls"] += 1
            
            model = row["model"] or "unknown"
            if model not in by_model:
                by_model[model] = {"input_tokens": 0, "output_tokens": 0, "total_tokens": 0, "calls": 0}
            by_model[model]["input_tokens"] += row["input_tokens"]
            by_model[model]["output_tokens"] += row["output_tokens"]
            by_model[model]["total_tokens"] += row["total_tokens"]
            by_model[model]["calls"] += 1
        
        return {
            "agent_id": agent_id,
            "total_input_tokens": total_input,
            "total_output_tokens": total_output,
            "total_tokens": total_tokens,
            "total_calls": len(rows),
            "by_user": by_user,
            "by_model": by_model,
        }
        
    except Exception as e:
        logger.warning("Failed to get token usage for agent %s: %s", agent_id, e)
        return {"total_tokens": 0, "by_user": {}, "by_model": {}}
