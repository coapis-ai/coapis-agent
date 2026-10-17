#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""A/B 实测：一次聊天请求的真实 token 与 GPU 时间（压缩触发 vs 不触发）。

推理服务 /metrics 返回 JSON：totals(requests/prompt_tokens/reused/output_tokens/
prompt_ms/decode_ms) + requests[] 逐条明细。做前后差分即得该请求实际发生的全部
LLM 调用（含压缩摘要调用）的真实消耗。只读探测。
"""
import json
import time
import urllib.request

METRICS = "http://172.16.6.241:8082/metrics"
BASE = "http://localhost:4308/api"


def totals():
    d = json.loads(urllib.request.urlopen(METRICS, timeout=30).read().decode())
    t = d.get("totals", {})
    return {k: float(t.get(k) or 0) for k in
            ("requests", "prompt_tokens", "reused", "output_tokens", "prompt_ms", "decode_ms")}


def chat(token, chat_id, text):
    body = {
        "input": [{"role": "user", "type": "message",
                   "content": [{"type": "text", "text": text}],
                   "session": {"session_id": chat_id, "agent_id": "user:admin",
                               "user_id": "admin", "channel": "console"}}],
        "session_id": chat_id, "user_id": "admin", "channel": "console",
        "stream": True, "biz_params": {"agent_id": "user:admin"}, "chat_id": chat_id,
    }
    req = urllib.request.Request(BASE + "/console/chat",
                                 data=json.dumps(body).encode(),
                                 headers={"Content-Type": "application/json",
                                          "Authorization": "Bearer " + token},
                                 method="POST")
    t0 = time.time()
    raw = urllib.request.urlopen(req, timeout=900).read().decode("utf-8", "replace")
    return time.time() - t0, len(raw)


def login():
    req = urllib.request.Request(BASE + "/auth/login",
                                 data=json.dumps({"username": "admin", "password": "admin123"}).encode(),
                                 headers={"Content-Type": "application/json"}, method="POST")
    return json.loads(urllib.request.urlopen(req, timeout=30).read())["token"]


def main():
    tok = login()
    for label, cid in [(a.split("=", 1)[0], a.split("=", 1)[1]) for a in __import__("sys").argv[1:]]:
        a = totals()
        dt, n = chat(tok, cid, "只回复两个字：收到")
        b = totals()
        dpt = b["prompt_tokens"] - a["prompt_tokens"]
        dreu = b["reused"] - a["reused"]
        dgen = b["output_tokens"] - a["output_tokens"]
        dreq = int(b["requests"] - a["requests"])
        dpms = (b["prompt_ms"] - a["prompt_ms"]) / 1000.0
        ddms = (b["decode_ms"] - a["decode_ms"]) / 1000.0
        print("%-24s 墙钟 %.1fs | LLM调用 %d 次 | prompt %d tok (复用 %d / 实算 %d) | 输出 %d tok | 预填充 %.1fs 解码 %.1fs | sse %dB"
              % (label, dt, dreq, dpt, dreu, dpt - dreu, dgen, dpms, ddms, n))


main()
