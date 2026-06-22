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

"""JSON file writer for token usage — per-user, per-agent tracking.

Writes to token_usage_details.json for detailed analytics.
No database dependency - pure JSON file storage.
"""

import json
import logging
import os
import time
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

# File path (can be overridden via env var)
_USAGE_FILE: Optional[Path] = None


def _get_usage_file() -> Path:
    """Get the token_usage_details.json path."""
    global _USAGE_FILE
    if _USAGE_FILE is not None:
        return _USAGE_FILE
    
    # Check env var first
    env_path = os.environ.get("COAPIS_TOKEN_USAGE_DETAILS_FILE")
    if env_path:
        _USAGE_FILE = Path(env_path)
        return _USAGE_FILE
    
    # Default path: same directory as token_usage.json
    from ..constant import SYSTEM_DIR
    _USAGE_FILE = SYSTEM_DIR / "token_usage_details.json"
    return _USAGE_FILE


def _load_data() -> dict:
    """Load token usage data from JSON file."""
    usage_file = _get_usage_file()
    
    if not usage_file.exists():
        return {"records": []}
    
    try:
        with open(usage_file, "r", encoding="utf-8") as f:
            data = json.load(f)
            if "records" not in data:
                data["records"] = []
            return data
    except (json.JSONDecodeError, OSError) as e:
        logger.warning("Failed to load token usage data: %s", e)
        return {"records": []}


def _save_data(data: dict) -> None:
    """Save token usage data to JSON file atomically."""
    usage_file = _get_usage_file()
    
    try:
        # Ensure directory exists
        usage_file.parent.mkdir(parents=True, exist_ok=True)
        
        # Atomic write: write to temp file, then rename
        tmp_file = usage_file.with_suffix(".tmp")
        with open(tmp_file, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        
        # Rename (atomic on most systems)
        os.replace(tmp_file, usage_file)
    except OSError as e:
        logger.warning("Failed to save token usage data: %s", e)


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
    """Save a token usage record to JSON file.
    
    Returns True on success, False on failure.
    """
    # Provide default values
    if user_id is None:
        user_id = 0
    if not username:
        username = "anonymous"
    
    record = {
        "user_id": user_id,
        "username": username,
        "agent_id": agent_id,
        "model": model,
        "input_tokens": input_tokens,
        "output_tokens": output_tokens,
        "total_tokens": total_tokens,
        "cost_cents": cost_cents,
        "created_at": time.time(),
    }
    
    try:
        data = _load_data()
        data["records"].append(record)
        
        # Keep only last 100000 records to prevent file from growing too large
        if len(data["records"]) > 100000:
            data["records"] = data["records"][-100000:]
        
        _save_data(data)
        
        logger.debug(
            "Token usage saved: user=%s, agent=%s, model=%s, tokens=%d",
            username, agent_id, model, total_tokens
        )
        return True
        
    except Exception as e:
        logger.warning("Failed to save token usage: %s", e)
        return False


def _filter_records(
    records: list,
    username: Optional[str] = None,
    agent_id: Optional[str] = None,
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
) -> list:
    """Filter records by criteria."""
    filtered = records
    
    if username:
        filtered = [r for r in filtered if r.get("username") == username]
    
    if agent_id:
        filtered = [r for r in filtered if r.get("agent_id") == agent_id]
    
    if start_date:
        import datetime
        start_ts = datetime.datetime.strptime(start_date, "%Y-%m-%d").timestamp()
        filtered = [r for r in filtered if r.get("created_at", 0) >= start_ts]
    
    if end_date:
        import datetime
        end_ts = datetime.datetime.strptime(end_date, "%Y-%m-%d").timestamp() + 86399
        filtered = [r for r in filtered if r.get("created_at", 0) <= end_ts]
    
    return filtered


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
    try:
        data = _load_data()
        records = data.get("records", [])
        
        # Filter by username and date range
        filtered = _filter_records(records, username=username, start_date=start_date, end_date=end_date)
        
        # Aggregate
        total_input = 0
        total_output = 0
        total_tokens = 0
        by_agent = {}
        by_model = {}
        
        for record in filtered:
            total_input += record.get("input_tokens", 0)
            total_output += record.get("output_tokens", 0)
            total_tokens += record.get("total_tokens", 0)
            
            # By agent
            aid = record.get("agent_id") or "unknown"
            if aid not in by_agent:
                by_agent[aid] = {"input_tokens": 0, "output_tokens": 0, "total_tokens": 0, "calls": 0}
            by_agent[aid]["input_tokens"] += record.get("input_tokens", 0)
            by_agent[aid]["output_tokens"] += record.get("output_tokens", 0)
            by_agent[aid]["total_tokens"] += record.get("total_tokens", 0)
            by_agent[aid]["calls"] += 1
            
            # By model
            model = record.get("model") or "unknown"
            if model not in by_model:
                by_model[model] = {"input_tokens": 0, "output_tokens": 0, "total_tokens": 0, "calls": 0}
            by_model[model]["input_tokens"] += record.get("input_tokens", 0)
            by_model[model]["output_tokens"] += record.get("output_tokens", 0)
            by_model[model]["total_tokens"] += record.get("total_tokens", 0)
            by_model[model]["calls"] += 1
        
        return {
            "username": username,
            "total_input_tokens": total_input,
            "total_output_tokens": total_output,
            "total_tokens": total_tokens,
            "total_calls": len(filtered),
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
    try:
        data = _load_data()
        records = data.get("records", [])
        
        # Filter by agent_id and date range
        filtered = _filter_records(records, agent_id=agent_id, start_date=start_date, end_date=end_date)
        
        # Aggregate
        total_input = 0
        total_output = 0
        total_tokens = 0
        by_user = {}
        by_model = {}
        
        for record in filtered:
            total_input += record.get("input_tokens", 0)
            total_output += record.get("output_tokens", 0)
            total_tokens += record.get("total_tokens", 0)
            
            # By user
            uname = record.get("username") or "unknown"
            if uname not in by_user:
                by_user[uname] = {"input_tokens": 0, "output_tokens": 0, "total_tokens": 0, "calls": 0}
            by_user[uname]["input_tokens"] += record.get("input_tokens", 0)
            by_user[uname]["output_tokens"] += record.get("output_tokens", 0)
            by_user[uname]["total_tokens"] += record.get("total_tokens", 0)
            by_user[uname]["calls"] += 1
            
            # By model
            model = record.get("model") or "unknown"
            if model not in by_model:
                by_model[model] = {"input_tokens": 0, "output_tokens": 0, "total_tokens": 0, "calls": 0}
            by_model[model]["input_tokens"] += record.get("input_tokens", 0)
            by_model[model]["output_tokens"] += record.get("output_tokens", 0)
            by_model[model]["total_tokens"] += record.get("total_tokens", 0)
            by_model[model]["calls"] += 1
        
        return {
            "agent_id": agent_id,
            "total_input_tokens": total_input,
            "total_output_tokens": total_output,
            "total_tokens": total_tokens,
            "total_calls": len(filtered),
            "by_user": by_user,
            "by_model": by_model,
        }
        
    except Exception as e:
        logger.warning("Failed to get token usage for agent %s: %s", agent_id, e)
        return {"total_tokens": 0, "by_user": {}, "by_model": {}}
