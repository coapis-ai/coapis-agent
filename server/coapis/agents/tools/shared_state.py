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
from __future__ import annotations
import asyncio, json, logging, os, time
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

STATE_DIR = Path(os.environ.get("COAPIS_STATE_DIR",
    os.path.join(os.path.dirname(__file__), "..", "..", "..", "data", "shared_state")))


def _ensure_dir():
    STATE_DIR.mkdir(parents=True, exist_ok=True)


def _load_state() -> dict[str, Any]:
    _ensure_dir()
    sf = STATE_DIR / "state.json"
    if sf.exists():
        try:
            return json.loads(sf.read_text())
        except Exception:
            pass
    return {"keys": {}, "locks": {}}


def _save_state(data: dict[str, Any]):
    _ensure_dir()
    (STATE_DIR / "state.json").write_text(json.dumps(data, ensure_ascii=False, indent=2))


async def shared_state(
    action: str = "get",
    key: str = "",
    value: str = "",
    owner: str = "agent",
    lock_type: str = "optimistic",
    ttl_seconds: int = 0,
    limit: int = 50,
) -> dict[str, Any]:
    """跨用户状态共享。

    Args:
        action: 操作类型 (get/set/delete/list/lock/unlock/history)
        key: 键名
        value: 值（JSON 字符串）
        owner: 所有者标识
        lock_type: 锁类型 (optimistic/pessimistic)
        ttl_seconds: 过期时间（0=永不过期）
        limit: 查询限制

    Returns:
        操作结果
    """
    state = _load_state()

    if action == "get":
        if not key.strip():
            return {"error": "key 不能为空"}
        entry = state["keys"].get(key)
        if not entry:
            return {"action": "get", "key": key, "exists": False}
        # Check TTL
        if entry.get("expires_at") and time.time() > entry["expires_at"]:
            del state["keys"][key]
            _save_state(state)
            return {"action": "get", "key": key, "exists": False, "expired": True}
        # Check lock
        lock = state["locks"].get(key)
        return {
            "action": "get", "key": key, "exists": True,
            "value": entry.get("value"), "owner": entry.get("owner", ""),
            "version": entry.get("version", 1),
            "locked": lock is not None, "locked_by": lock.get("owner", "") if lock else None,
            "updated_at": entry.get("updated_at", ""),
        }

    elif action == "set":
        if not key.strip():
            return {"error": "key 不能为空"}
        existing = state["keys"].get(key)
        # Check if locked by someone else
        lock = state["locks"].get(key)
        if lock and lock.get("owner") != owner:
            return {"error": f"键 {key} 被 {lock['owner']} 锁定", "locked_by": lock["owner"]}

        version = (existing.get("version", 0) + 1) if existing else 1
        expires_at = time.time() + ttl_seconds if ttl_seconds > 0 else None
        state["keys"][key] = {
            "value": value,
            "owner": owner,
            "version": version,
            "updated_at": time.strftime("%Y-%m-%d %H:%M:%S"),
            "expires_at": expires_at,
        }
        # Release lock if held by this owner
        if lock and lock.get("owner") == owner:
            del state["locks"][key]
        _save_state(state)
        return {"action": "set", "key": key, "version": version, "owner": owner}

    elif action == "delete":
        if not key.strip():
            return {"error": "key 不能为空"}
        lock = state["locks"].get(key)
        if lock and lock.get("owner") != owner:
            return {"error": f"键 {key} 被 {lock['owner']} 锁定"}
        existed = key in state["keys"]
        state["keys"].pop(key, None)
        state["locks"].pop(key, None)
        _save_state(state)
        return {"action": "delete", "key": key, "existed": existed}

    elif action == "list":
        keys_info = []
        for k, v in state["keys"].items():
            if v.get("expires_at") and time.time() > v["expires_at"]:
                continue
            keys_info.append({"key": k, "owner": v.get("owner", ""), "version": v.get("version", 1),
                              "locked": k in state["locks"]})
        return {"action": "list", "count": len(keys_info), "keys": keys_info[:limit]}

    elif action == "lock":
        if not key.strip():
            return {"error": "key 不能为空"}
        if key in state["locks"]:
            existing_lock = state["locks"][key]
            if existing_lock.get("owner") != owner:
                return {"error": f"键 {key} 已被 {existing_lock['owner']} 锁定", "locked_by": existing_lock["owner"]}
            return {"action": "lock", "key": key, "already_locked": True, "by": owner}
        state["locks"][key] = {"owner": owner, "type": lock_type,
                               "locked_at": time.strftime("%Y-%m-%d %H:%M:%S")}
        _save_state(state)
        return {"action": "lock", "key": key, "owner": owner, "type": lock_type}

    elif action == "unlock":
        if not key.strip():
            return {"error": "key 不能为空"}
        lock = state["locks"].get(key)
        if not lock:
            return {"action": "unlock", "key": key, "was_locked": False}
        if lock.get("owner") != owner:
            return {"error": f"键 {key} 不是由 {owner} 锁定的"}
        del state["locks"][key]
        _save_state(state)
        return {"action": "unlock", "key": key, "owner": owner}

    elif action == "stats":
        return {"action": "stats", "total_keys": len(state["keys"]),
                "total_locks": len(state["locks"]),
                "owners": list(set(v.get("owner", "") for v in state["keys"].values()))}

    else:
        return {"error": f"未知操作: {action}，支持 get/set/delete/list/lock/unlock/stats"}
