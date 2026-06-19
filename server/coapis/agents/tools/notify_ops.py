# -*- coding: utf-8 -*-
# Copyright 2026 蜜蜂 & CoApis Contributors
# Licensed under the Apache License, Version 2.0
from __future__ import annotations
import asyncio, json, logging, os, time
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

NOTIFY_DIR = Path(os.environ.get("COAPIS_NOTIFY_DIR",
    os.path.join(os.path.dirname(__file__), "..", "..", "..", "data", "notify")))


def _ensure_dir():
    NOTIFY_DIR.mkdir(parents=True, exist_ok=True)


def _load_channels() -> dict[str, Any]:
    _ensure_dir()
    idx = NOTIFY_DIR / "channels.json"
    if idx.exists():
        try:
            return json.loads(idx.read_text())
        except Exception:
            pass
    return {}


def _save_channels(data: dict[str, Any]):
    _ensure_dir()
    (NOTIFY_DIR / "channels.json").write_text(json.dumps(data, ensure_ascii=False, indent=2))


def _load_history() -> list[dict]:
    _ensure_dir()
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
    return entries[-200:]  # keep last 200


def _append_history(entry: dict):
    _ensure_dir()
    hfile = NOTIFY_DIR / "history.jsonl"
    with open(hfile, "a") as f:
        f.write(json.dumps(entry, ensure_ascii=False) + "\n")


async def notify_ops(
    action: str = "send",
    channel: str = "console",
    to: str = "",
    subject: str = "",
    message: str = "",
    template: str = "",
    variables: str = "",
    channels_config: str = "",
    limit: int = 20,
) -> dict[str, Any]:
    """多渠道通知推送。

    Args:
        action: 操作类型 (send/list_channels/history/config)
        channel: 通知渠道 (console/webhook/email)
        to: 目标地址（webhook URL / email）
        subject: 通知标题
        message: 通知内容
        template: 模板名称
        variables: 模板变量 JSON
        channels_config: 渠道配置 JSON
        limit: 历史记录限制

    Returns:
        推送结果
    """
    # Render template variables
    if template.strip() and variables.strip():
        try:
            vars_dict = json.loads(variables)
            for k, v in vars_dict.items():
                message = message.replace(f"{{{{{k}}}}}", str(v))
        except Exception:
            pass

    if action == "send":
        if not message.strip():
            return {"error": "message 不能为空"}

        timestamp = time.strftime("%Y-%m-%d %H:%M:%S")
        entry = {
            "channel": channel,
            "to": to,
            "subject": subject,
            "message": message[:1000],
            "timestamp": timestamp,
        }

        result = {"channel": channel, "sent": False}

        if channel == "console":
            print(f"\n{'='*50}")
            print(f"[NOTIFY] {subject or 'Notification'}")
            print(f"Message: {message[:200]}")
            print(f"Time: {timestamp}")
            print(f"{'='*50}\n")
            result["sent"] = True
            result["method"] = "stdout"

        elif channel == "webhook":
            if not to.strip():
                return {"error": "webhook 需要 to 参数（URL）"}
            try:
                from .http_client import http_client
                payload = json.dumps({"subject": subject, "message": message, "timestamp": timestamp})
                r = await http_client(action="post", url=to, body=payload,
                                      headers='{"Content-Type": "application/json"}')
                result["sent"] = r.get("status", 0) < 400
                result["status"] = r.get("status", 0)
                result["method"] = "webhook"
            except Exception as e:
                result["error"] = str(e)

        elif channel == "email":
            try:
                from .himalaya import himalaya
                r = await himalaya(action="send", to=to, subject=subject or "Notification", body=message)
                result["sent"] = r.get("success", False)
                result["method"] = "email"
            except Exception as e:
                result["error"] = str(e)

        else:
            return {"error": f"未知渠道: {channel}，支持 console/webhook/email"}

        # Record history
        entry["sent"] = result["sent"]
        _append_history(entry)

        # Record to audit_log
        try:
            from .audit_log import audit_log
            await audit_log(action="log", actor="notify", operation="send",
                          resource=channel, result="success" if result["sent"] else "failure",
                          detail=f"to={to}, subject={subject}")
        except Exception:
            pass

        return {"action": "send", **result, "timestamp": timestamp}

    elif action == "list_channels":
        channels = _load_channels()
        return {"action": "list_channels", "channels": channels,
                "supported": ["console", "webhook", "email"]}

    elif action == "history":
        history = _load_history()
        return {"action": "history", "count": len(history), "entries": history[-limit:]}

    elif action == "config":
        if channels_config.strip():
            try:
                cfg = json.loads(channels_config)
                _save_channels(cfg)
                return {"action": "config", "saved": True, "channels": list(cfg.keys())}
            except Exception:
                return {"error": "channels_config JSON 解析失败"}
        channels = _load_channels()
        return {"action": "config", "channels": channels}

    else:
        return {"error": f"未知操作: {action}，支持 send/list_channels/history/config"}
