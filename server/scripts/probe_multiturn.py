#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""多轮对话真实 token 账单实测（只读诊断，不改代码）。

用法: python3 probe_multiturn.py <轮数>
每轮发一条会触发工具调用的消息，逐轮记录 SSE 时长与回复长度。
配合 docker logs 里的 "Context budget" 行读取每步 fixed/history/total。
"""
import json
import sys
import time
import urllib.request

BASE = "http://localhost:4308/api"
STAMP = int(time.time())
SID = "probe-mt-%d" % STAMP

TURNS = [
    "请用 read_file 读取 AGENTS.md 的前 20 行，然后一句话说明它讲了什么。",
    "再用 grep_search 在 AGENTS.md 里搜索 Heartbeats，把匹配行原文列出来。",
    "把上面两次工具调用的内容合并成三行要点，不要调用任何工具。",
]


def post(path, body, token=None, timeout=300):
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
    n = int(sys.argv[1]) if len(sys.argv) > 1 else len(TURNS)
    token = json.load(post("/auth/login", {"username": "admin", "password": "admin123"}))["token"]
    print("session:", SID, "start:", time.strftime("%H:%M:%S"))
    for i, text in enumerate(TURNS[:n], 1):
        body = {
            "input": [{
                "role": "user",
                "type": "message",
                "content": [{"type": "text", "text": text}],
                "session": {"session_id": SID, "agent_id": "user:admin",
                            "user_id": "admin", "channel": "console"},
            }],
            "session_id": SID,
            "user_id": "admin",
            "channel": "console",
            "stream": True,
            "biz_params": {"agent_id": "user:admin"},
            "chat_id": SID,
        }
        t0 = time.time()
        raw = post("/console/chat", body, token).read().decode("utf-8", "replace")
        dt = time.time() - t0
        reply = ""
        compact = ""
        for ln in raw.splitlines():
            if not ln.startswith("data:"):
                continue
            try:
                d = json.loads(ln[5:])
            except Exception:
                continue
            if d.get("object") == "content" and d.get("text") and d.get("delta") is None:
                reply += d["text"]
            if "compacted" in (d.get("text") or ""):
                compact = d["text"][:200]
        print("--- turn %d: %.1fs, sse %d bytes, reply %d chars" % (i, dt, len(raw), len(reply)))
        print("    reply head:", reply[:160].replace("\n", " "))
        if compact:
            print("    COMPACT:", compact.replace("\n", " ")[:200])
    print("end:", time.strftime("%H:%M:%S"))


main()
