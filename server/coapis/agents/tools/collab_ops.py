# -*- coding: utf-8 -*-
# Copyright 2026 以太吃虾 & CoApis Contributors
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#     http://www.apache.org/licenses/LICENSE-2.0

"""Collaboration operations — unified tool for notifications and shared state.

Merges notify_ops + shared_state into a single tool via action parameter.
Capabilities: multi-channel notification, cross-user state sharing with locks.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import time
from pathlib import Path
from typing import Any

from .registry import register_tool

logger = logging.getLogger(__name__)

# ── Notification storage ──
NOTIFY_DIR = Path(os.environ.get("COAPIS_NOTIFY_DIR",
    os.path.join(os.path.dirname(__file__), "..", "..", "..", "data", "notify")))

# ── Shared state storage ──
STATE_DIR = Path(os.environ.get("COAPIS_STATE_DIR",
    os.path.join(os.path.dirname(__file__), "..", "..", "..", "data", "shared_state")))


def _ensure_dir(d: Path):
    d.mkdir(parents=True, exist_ok=True)


# ── Notification helpers ──

def _load_channels() -> dict[str, Any]:
    _ensure_dir(NOTIFY_DIR)
    idx = NOTIFY_DIR / "channels.json"
    if idx.exists():
        try:
            return json.loads(idx.read_text())
        except Exception:
            pass
    return {}


def _save_channels(data: dict[str, Any]):
    _ensure_dir(NOTIFY_DIR)
    (NOTIFY_DIR / "channels.json").write_text(json.dumps(data, ensure_ascii=False, indent=2))


def _load_history() -> list[dict]:
    _ensure_dir(NOTIFY_DIR)
    hfile = NOTIFY_DIR / "history.jsonl"
    if not hfile.exists():
        return []
    entries = []
    for line in hfile.read_text().split("\n"):
        if line.strip():
            try:
                entries.append(json.loads(line))
            except Exception:
                pass
    return entries[-200:]


def _append_history(entry: dict):
    _ensure_dir(NOTIFY_DIR)
    hfile = NOTIFY_DIR / "history.jsonl"
    with open(hfile, "a") as f:
        f.write(json.dumps(entry, ensure_ascii=False) + "\n")


# ── Shared state helpers ──

def _load_state() -> dict[str, Any]:
    _ensure_dir(STATE_DIR)
    sf = STATE_DIR / "state.json"
    if sf.exists():
        try:
            return json.loads(sf.read_text())
        except Exception:
            pass
    return {"keys": {}, "locks": {}}


def _save_state(data: dict[str, Any]):
    _ensure_dir(STATE_DIR)
    (STATE_DIR / "state.json").write_text(json.dumps(data, ensure_ascii=False, indent=2))


@register_tool(
    name="collab_ops",
    description="协作工具。action: notify_send(发送通知,需channel+message), notify_list_channels(列出渠道), shared_state_get/set/delete(跨用户状态共享,需key+value)。",
    category="builtin",
    tags=["collab", "notify", "state", "lock", "shared"],
    scene="collaboration",
)
async def collab_ops(
    action: str = "notify_send",
    # Notification params
    channel: str = "console",
    to: str = "",
    subject: str = "",
    message: str = "",
    template: str = "",
    variables: str = "",
    channels_config: str = "",
    # State params
    key: str = "",
    value: str = "",
    owner: str = "agent",
    lock_type: str = "optimistic",
    ttl_seconds: int = 0,
    # Common
    limit: int = 50,
    **kwargs: Any,
) -> dict[str, Any]:
    """协作操作统一工具。

    Args:
        action: 操作类型:
            通知: notify_send/notify_list_channels/notify_history/notify_config
            状态: state_get/state_set/state_delete/state_list/state_lock/state_unlock/state_history
        channel: 通知渠道 (console/webhook/email)
        to: 目标地址
        subject: 通知标题
        message: 通知内容
        template: 模板名称
        variables: 模板变量 JSON
        channels_config: 渠道配置 JSON
        key: 键名
        value: 值（JSON 字符串）
        owner: 所有者标识
        lock_type: 锁类型 (optimistic/pessimistic)
        ttl_seconds: 过期时间
        limit: 查询限制

    Returns:
        操作结果
    """
    # ── Notification actions ──
    if action in ("notify_send", "notify_list_channels", "notify_history", "notify_config"):
        # Render template variables
        if template.strip() and variables.strip():
            try:
                vars_dict = json.loads(variables)
                for k, v in vars_dict.items():
                    message = message.replace(f"{{{{{k}}}}}", str(v))
            except Exception:
                pass

        if action == "notify_send":
            if not message.strip():
                return {"error": "message 不能为空"}

            timestamp = time.strftime("%Y-%m-%d %H:%M:%S")
            entry = {"channel": channel, "to": to, "subject": subject,
                     "message": message[:2000], "timestamp": timestamp}

            # Send based on channel
            result: dict[str, Any] = {}
            if channel == "console":
                result = {"status": "delivered", "preview": message[:100] + "..." if len(message) > 100 else message}
            elif channel == "webhook":
                if not to.strip():
                    return {"error": "webhook 需要 to 参数 (URL)"}
                try:
                    import urllib.request
                    req = urllib.request.Request(
                        to, data=json.dumps({"subject": subject, "message": message}).encode("utf-8"),
                        headers={"Content-Type": "application/json"}, method="POST",
                    )
                    with urllib.request.urlopen(req, timeout=10) as resp:
                        result = {"status": "delivered", "http_code": resp.status}
                except Exception as e:
                    result = {"status": "failed", "error": str(e)}
            elif channel == "email":
                result = {"status": "queued", "note": "邮件发送需要 SMTP 配置，请使用 env_manager 配置 SMTP_* 环境变量"}
            else:
                result = {"status": "unknown_channel", "note": f"不支持的渠道: {channel}"}

            entry["result"] = result.get("status", "unknown")
            _append_history(entry)
            return {"action": "notify_send", "channel": channel, **result}

        elif action == "notify_list_channels":
            channels = _load_channels()
            return {"action": "notify_list_channels", "channels": channels}

        elif action == "notify_history":
            history = _load_history()[-limit:]
            return {"action": "notify_history", "count": len(history), "history": history}

        elif action == "notify_config":
            if channels_config.strip():
                try:
                    config = json.loads(channels_config)
                    _save_channels(config)
                    return {"action": "notify_config", "status": "saved", "channels": config}
                except Exception as e:
                    return {"error": f"配置格式错误: {e}"}
            else:
                channels = _load_channels()
                return {"action": "notify_config", "channels": channels}

    # ── Shared state actions ──
    elif action in ("state_get", "state_set", "state_delete", "state_list", "state_lock", "state_unlock", "state_history"):
        state = _load_state()

        if action == "state_get":
            if not key.strip():
                return {"error": "key 不能为空"}
            entry = state["keys"].get(key)
            if not entry:
                return {"action": "state_get", "key": key, "exists": False}
            if entry.get("expires_at") and time.time() > entry["expires_at"]:
                del state["keys"][key]
                _save_state(state)
                return {"action": "state_get", "key": key, "exists": False, "expired": True}
            lock = state["locks"].get(key)
            return {
                "action": "state_get", "key": key, "exists": True,
                "value": entry.get("value"), "owner": entry.get("owner", ""),
                "version": entry.get("version", 1),
                "locked": lock is not None, "locked_by": lock.get("owner", "") if lock else None,
                "updated_at": entry.get("updated_at", ""),
            }

        elif action == "state_set":
            if not key.strip():
                return {"error": "key 不能为空"}
            existing = state["keys"].get(key)
            lock = state["locks"].get(key)
            if lock and lock.get("owner") != owner:
                return {"error": f"键 '{key}' 被 '{lock.get('owner')}' 锁定", "locked_by": lock.get("owner")}
            version = 1
            if existing:
                if lock_type == "optimistic" and existing.get("version", 1) != kwargs.get("expected_version", existing.get("version", 1)):
                    return {"error": f"版本冲突：期望 {kwargs.get('expected_version', existing.get('version', 1))}，实际 {existing.get('version', 1)}"}
                version = existing.get("version", 1) + 1
            ts = time.strftime("%Y-%m-%d %H:%M:%S")
            expires_at = time.time() + ttl_seconds if ttl_seconds > 0 else None
            state["keys"][key] = {
                "value": value, "owner": owner, "version": version,
                "updated_at": ts, "expires_at": expires_at,
            }
            if not state.get("history"):
                state["history"] = []
            state["history"].append({"key": key, "action": "set", "owner": owner, "version": version, "ts": ts})
            state["history"] = state["history"][-200:]
            _save_state(state)
            return {"action": "state_set", "key": key, "version": version, "updated_at": ts}

        elif action == "state_delete":
            if not key.strip():
                return {"error": "key 不能为空"}
            if key not in state["keys"]:
                return {"error": f"键不存在: {key}"}
            del state["keys"][key]
            state["locks"].pop(key, None)
            _save_state(state)
            return {"action": "state_delete", "key": key, "status": "deleted"}

        elif action == "state_list":
            keys_info = []
            for k, v in state.get("keys", {}).items():
                info = {"key": k, "owner": v.get("owner", ""), "version": v.get("version", 1)}
                if v.get("expires_at") and time.time() > v["expires_at"]:
                    info["status"] = "expired"
                elif state["locks"].get(k):
                    info["status"] = "locked"
                    info["locked_by"] = state["locks"][k].get("owner", "")
                else:
                    info["status"] = "active"
                keys_info.append(info)
            return {"action": "state_list", "count": len(keys_info), "keys": keys_info[:limit]}

        elif action == "state_lock":
            if not key.strip():
                return {"error": "key 不能为空"}
            if key not in state["keys"]:
                return {"error": f"键不存在: {key}"}
            existing_lock = state["locks"].get(key)
            if existing_lock and existing_lock.get("owner") != owner:
                return {"error": f"已被 '{existing_lock.get('owner')}' 锁定"}
            state["locks"][key] = {"owner": owner, "type": lock_type, "ts": time.strftime("%Y-%m-%d %H:%M:%S")}
            _save_state(state)
            return {"action": "state_lock", "key": key, "locked_by": owner, "type": lock_type}

        elif action == "state_unlock":
            if not key.strip():
                return {"error": "key 不能为空"}
            existing_lock = state["locks"].get(key)
            if not existing_lock:
                return {"error": f"键未被锁定: {key}"}
            if existing_lock.get("owner") != owner:
                return {"error": f"只有 '{existing_lock.get('owner')}' 可以解锁"}
            del state["locks"][key]
            _save_state(state)
            return {"action": "state_unlock", "key": key, "status": "unlocked"}

        elif action == "state_history":
            history = state.get("history", [])[-limit:]
            return {"action": "state_history", "count": len(history), "history": history}

    else:
        return {"error": f"未知操作: {action}。通知: notify_send/notify_list_channels/notify_history/notify_config; 状态: state_get/state_set/state_delete/state_list/state_lock/state_unlock/state_history"}


# ── Aliases for backward compatibility ──
notify_ops = collab_ops
shared_state = collab_ops
