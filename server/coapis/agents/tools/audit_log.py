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

"""Audit log — immutable operation audit trail with tool_stats + context_manager integration.

Every logged entry is SHA-256 chained (like a blockchain) so entries cannot be
tampered with without breaking the chain.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import os
import time
from pathlib import Path
from typing import Any


logger = logging.getLogger(__name__)

AUDIT_DIR = Path(os.environ.get("COAPIS_AUDIT_DIR",
    os.path.join(os.path.dirname(__file__), "..", "..", "..", "data", "audit")))
CHAIN_FILE = AUDIT_DIR / "chain.jsonl"
INDEX_FILE = AUDIT_DIR / "index.jsonl"


def _ensure_dir():
    AUDIT_DIR.mkdir(parents=True, exist_ok=True)


def _hash_entry(prev_hash: str, entry: dict) -> str:
    """SHA-256 hash of previous hash + entry content."""
    payload = prev_hash + json.dumps(entry, sort_keys=True, ensure_ascii=False)
    return hashlib.sha256(payload.encode()).hexdigest()


def _get_last_hash() -> str:
    """Get the hash of the last entry in the chain."""
    if not CHAIN_FILE.exists():
        return "0" * 64  # genesis hash
    try:
        with open(CHAIN_FILE, "r") as f:
            lines = f.readlines()
            if lines:
                last = json.loads(lines[-1])
                return last.get("hash", "0" * 64)
    except Exception:
        pass
    return "0" * 64


def _read_entries(limit: int = 100, filters: dict | None = None) -> list[dict]:
    """Read audit entries with optional filters."""
    if not CHAIN_FILE.exists():
        return []
    entries = []
    try:
        with open(CHAIN_FILE, "r") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                entry = json.loads(line)
                data = entry.get("data", {})

                # Apply filters
                if filters:
                    if filters.get("actor") and data.get("actor") != filters["actor"]:
                        continue
                    if filters.get("action") and data.get("action") != filters["action"]:
                        continue
                    if filters.get("resource") and data.get("resource") != filters["resource"]:
                        continue
                    if filters.get("result") and data.get("result") != filters["result"]:
                        continue
                    if filters.get("since"):
                        if data.get("timestamp", 0) < filters["since"]:
                            continue

                entries.append(entry)
                if len(entries) >= limit:
                    break
    except Exception:
        pass
    return entries


def _verify_chain() -> dict[str, Any]:
    """Verify the integrity of the audit chain."""
    if not CHAIN_FILE.exists():
        return {"valid": True, "entries": 0, "message": "审计日志为空"}

    entries = []
    try:
        with open(CHAIN_FILE, "r") as f:
            for line in f:
                line = line.strip()
                if line:
                    entries.append(json.loads(line))
    except Exception as e:
        return {"valid": False, "error": str(e)}

    prev_hash = "0" * 64
    broken_at = -1
    for i, entry in enumerate(entries):
        expected_hash = _hash_entry(prev_hash, entry.get("data", {}))
        if entry.get("hash") != expected_hash:
            broken_at = i
            break
        prev_hash = entry.get("hash", "")

    return {
        "valid": broken_at == -1,
        "entries": len(entries),
        "broken_at": broken_at if broken_at >= 0 else None,
        "message": "链完整性验证通过" if broken_at == -1 else f"链在第 {broken_at} 条记录处断裂",
    }


async def audit_log(
    action: str = "log",
    actor: str = "agent",
    operation: str = "",
    resource: str = "",
    result: str = "success",
    detail: str = "",
    since: int = 0,
    filters: str = "",
    limit: int = 50,
) -> dict[str, Any]:
    """操作审计日志。

    不可篡改的操作记录，SHA-256 链式哈希防篡改。

    Args:
        action: 操作类型 (log/query/verify/stats)
        actor: 操作者
        operation: 操作类型（如 file_write、tool_call、deploy）
        resource: 操作对象
        result: 操作结果 (success/failure/denied)
        detail: 附加详情
        since: 查询起始时间戳
        filters: 查询过滤 JSON（actor/action/resource/result）
        limit: 查询限制

    Returns:
        审计结果
    """
    _ensure_dir()

    if action == "log":
        if not operation.strip():
            return {"error": "operation 不能为空"}

        timestamp = int(time.time())
        entry_data = {
            "actor": actor,
            "action": operation.strip(),
            "resource": resource,
            "result": result,
            "detail": detail[:500] if detail else "",
            "timestamp": timestamp,
            "ts_human": time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(timestamp)),
        }

        # Chain hash
        prev_hash = _get_last_hash()
        entry_hash = _hash_entry(prev_hash, entry_data)

        entry = {"data": entry_data, "hash": entry_hash, "prev": prev_hash}

        # Append to chain file
        try:
            with open(CHAIN_FILE, "a") as f:
                f.write(json.dumps(entry, ensure_ascii=False) + "\n")
        except Exception as e:
            return {"error": f"写入审计日志失败: {e}"}

        # Append to index file (for fast querying)
        try:
            with open(INDEX_FILE, "a") as f:
                f.write(json.dumps({"ts": timestamp, "actor": actor, "action": operation.strip(),
                                    "resource": resource, "result": result, "hash": entry_hash},
                                   ensure_ascii=False) + "\n")
        except Exception:
            pass

        # Write to unified audit_logs table (SQLite)
        try:
            from ...user_system.database import UserSystemDB
            db = UserSystemDB()
            db.insert_audit_log(
                user_id=0,
                username=actor,
                action=operation.strip(),
                resource_type="hash_chain",
                resource_id=resource or "",
                details={
                    "hash": entry_hash,
                    "prev_hash": prev_hash,
                    "result": result,
                    "detail": detail[:500] if detail else "",
                },
            )
        except Exception:
            pass

        # Cross-reference with tool_stats
        tool_stats_summary = {}
        try:
            from .tool_stats import _stats
            if _stats:
                tool_stats_summary = {
                    "tracked_tools": len(_stats),
                    "total_calls": sum(d.get("calls", 0) for d in _stats.values()),
                }
        except Exception:
            pass

        return {
            "action": "logged",
            "hash": entry_hash[:16] + "...",
            "timestamp": entry_data["ts_human"],
            "tool_stats_context": tool_stats_summary,
        }

    elif action == "query":
        # Read from unified audit_logs table (primary source)
        try:
            from ...user_system.database import UserSystemDB
            db = UserSystemDB()
            parsed_filters = {}
            if filters.strip():
                try:
                    parsed_filters = json.loads(filters)
                except Exception:
                    pass
            if since:
                parsed_filters["since"] = since

            conditions = []
            params = []
            if parsed_filters.get("actor"):
                conditions.append("username = ?")
                params.append(parsed_filters["actor"])
            if parsed_filters.get("action"):
                conditions.append("action = ?")
                params.append(parsed_filters["action"])
            if parsed_filters.get("resource"):
                conditions.append("resource_id = ?")
                params.append(parsed_filters["resource"])
            if parsed_filters.get("since"):
                conditions.append("created_at >= ?")
                params.append(float(parsed_filters["since"]))

            where = "WHERE " + " AND ".join(conditions) if conditions else ""
            rows = db.execute(
                f"SELECT * FROM audit_logs {where} ORDER BY created_at DESC LIMIT ?",
                params + [limit],
            ).fetchall()

            entries = []
            for row in rows:
                details = row["details"] or "{}"
                if isinstance(details, str):
                    try:
                        details = json.loads(details)
                    except Exception:
                        details = {}
                entries.append({
                    "id": row["id"],
                    "username": row["username"],
                    "action": row["action"],
                    "resource_type": row["resource_type"],
                    "resource_id": row["resource_id"],
                    "result": details.get("result", ""),
                    "detail": details.get("detail", ""),
                    "hash": details.get("hash", "")[:16] + "..." if details.get("hash") else "",
                    "created_at": row["created_at"],
                })

            return {"action": "query", "count": len(entries), "entries": entries}
        except Exception as e:
            # Fallback to chain file
            parsed_filters = {}
            if filters.strip():
                try:
                    parsed_filters = json.loads(filters)
                except Exception:
                    pass
            if since:
                parsed_filters["since"] = since
            entries = _read_entries(limit=limit, filters=parsed_filters if parsed_filters else None)
            return {
                "action": "query",
                "count": len(entries),
                "entries": [{"data": e["data"], "hash": e["hash"][:16] + "..."} for e in entries],
                "source": "chain_fallback",
            }

    elif action == "verify":
        return {"action": "verify", **_verify_chain()}

    elif action == "stats":
        # Read from unified audit_logs table (primary source)
        try:
            from ...user_system.database import UserSystemDB
            db = UserSystemDB()

            total_row = db.execute("SELECT COUNT(*) as cnt FROM audit_logs").fetchone()
            total = total_row["cnt"] if total_row else 0

            action_rows = db.execute(
                "SELECT action, COUNT(*) as cnt FROM audit_logs GROUP BY action ORDER BY cnt DESC"
            ).fetchall()
            by_action = {r["action"]: r["cnt"] for r in action_rows}

            user_rows = db.execute(
                "SELECT username, COUNT(*) as cnt FROM audit_logs GROUP BY username ORDER BY cnt DESC LIMIT 10"
            ).fetchall()
            by_actor = {r["username"]: r["cnt"] for r in user_rows}

            latest = db.execute(
                "SELECT created_at FROM audit_logs ORDER BY created_at DESC LIMIT 1"
            ).fetchone()
            first = db.execute(
                "SELECT created_at FROM audit_logs ORDER BY created_at ASC LIMIT 1"
            ).fetchone()

            return {
                "action": "stats",
                "total": total,
                "by_actor": by_actor,
                "by_action": by_action,
                "chain_valid": _verify_chain().get("valid", False),
                "first_entry": time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(first["created_at"])) if first else "",
                "last_entry": time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(latest["created_at"])) if latest else "",
                "source": "db",
            }
        except Exception as e:
            # Fallback to chain file
            entries = _read_entries(limit=10000)
            if not entries:
                return {"action": "stats", "total": 0}
            by_actor = {}
            by_action = {}
            by_result = {}
            for en in entries:
                d = en.get("data", {})
                by_actor[d.get("actor", "unknown")] = by_actor.get(d.get("actor", "unknown"), 0) + 1
                by_action[d.get("action", "unknown")] = by_action.get(d.get("action", "unknown"), 0) + 1
                by_result[d.get("result", "unknown")] = by_result.get(d.get("result", "unknown"), 0) + 1
            return {
                "action": "stats",
                "total": len(entries),
                "by_actor": by_actor,
                "by_action": by_action,
                "by_result": by_result,
                "chain_valid": _verify_chain().get("valid", False),
                "first_entry": entries[-1].get("data", {}).get("ts_human", "") if entries else "",
                "last_entry": entries[0].get("data", {}).get("ts_human", "") if entries else "",
                "source": "chain_fallback",
            }

    else:
        return {"error": f"未知操作: {action}，支持 log/query/verify/stats"}
