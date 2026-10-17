#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""压缩摘要结构化输出实测（只读，1 次小调用）。

agentscope 压缩依赖 structured_model（JSON schema）拿摘要；若服务端不返回结构化
内容，metadata 为空 → 摘要不落盘、消息不标记 → 每次请求重复压缩同一批历史。
"""
import json
import urllib.request

PROV = "/apps/ai/coapis-dev/system/.secret/providers/custom/local_vllm.json"

SCHEMA = {
    "type": "object",
    "properties": {
        "summary": {"type": "string", "description": "对话要点摘要"},
        "task": {"type": "string", "description": "用户任务"},
        "next_step": {"type": "string", "description": "下一步"},
    },
    "required": ["summary", "task", "next_step"],
}


def main():
    p = json.load(open(PROV))
    url = p["base_url"].rstrip("/") + "/chat/completions"
    key = p.get("api_key") or ""
    model = p["models"][0]["id"]

    for mode in ("json_schema", "json_object"):
        if mode == "json_schema":
            rf = {"type": "json_schema", "json_schema": {
                "name": "summary", "schema": SCHEMA, "strict": True}}
        else:
            rf = {"type": "json_object"}
        body = {
            "model": model,
            "messages": [
                {"role": "system", "content": "你是对话摘要器，只输出 JSON。"},
                {"role": "user", "content": "对话：用户要求读取 AGENTS.md 前20行并总结；助手读取后回答。请输出摘要 JSON。"},
            ],
            "max_tokens": 200,
            "temperature": 0,
            "stream": False,
            "response_format": rf,
        }
        req = urllib.request.Request(url, data=json.dumps(body).encode(),
                                     headers={"Content-Type": "application/json",
                                              "Authorization": "Bearer " + key},
                                     method="POST")
        try:
            r = json.loads(urllib.request.urlopen(req, timeout=120).read().decode())
        except Exception as e:
            print(mode, "ERROR:", str(e)[:300])
            continue
        ch = r["choices"][0]["message"]
        print(mode, "-> content:", repr(ch.get("content"))[:220])
        print("     refusal:", repr(ch.get("refusal")), "usage:", r.get("usage"))


main()
