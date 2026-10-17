#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""基线实测：发一条最小聊天，抓 Context budget 日志 + 真实 prompt_tokens。

只读诊断脚本（不改代码）。用法：
    python probe_chat_baseline.py [消息文本]
"""
import json
import sys
import time
import urllib.request

BASE = "http://localhost:4308/api"
SID = "probe-baseline-%d" % int(time.time())


def post(path, body, token=None, timeout=180):
    req = urllib.request.Request(
        BASE + path,
        data=json.dumps(body).encode(),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    if token:
        req.add_header("Authorization", "Bearer " + token)
    return urllib.request.urlopen(req, timeout=timeout)


def main():
    text = sys.argv[1] if len(sys.argv) > 1 else "你好"
    r = post("/auth/login", {"username": "admin", "password": "admin123"})
    token = json.load(r)["token"]
    print("login ok, session_id =", SID)

    body = {
        "input": [
            {
                "role": "user",
                "type": "message",
                "content": [{"type": "text", "text": text}],
                "session": {
                    "session_id": SID,
                    "agent_id": "user:admin",
                    "user_id": "admin",
                    "channel": "console",
                },
            }
        ],
        "session_id": SID,
        "user_id": "admin",
        "channel": "console",
        "stream": True,
        "biz_params": {"agent_id": "user:admin"},
        "chat_id": SID,
    }
    resp = post("/console/chat", body, token)
    raw = resp.read().decode("utf-8", "replace")
    print("SSE bytes:", len(raw))
    seen = []
    for ln in raw.splitlines():
        if not ln.startswith("data:"):
            continue
        try:
            d = json.loads(ln[5:])
        except Exception:
            continue
        u = d.get("usage")
        if u:
            seen.append((d.get("object"), d.get("id"), u))
    print("usage events:", len(seen))
    for o, i, u in seen[-8:]:
        print("  ", o, str(i)[:20], json.dumps(u, ensure_ascii=False)[:220])
    # 最终回复文本
    for ln in raw.splitlines():
        if ln.startswith("data:") and '"object": "response"' in ln:
            d = json.loads(ln[5:])
            for m in d.get("output") or []:
                for blk in m.get("content") or []:
                    if blk.get("type") == "text" and blk.get("text"):
                        print("REPLY:", blk["text"][:200].replace("\n", " "))


main()
