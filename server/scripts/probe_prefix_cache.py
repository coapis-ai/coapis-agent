#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""前缀缓存实测（只读探测外部推理服务，不改任何状态）。

目的：验证 local_vllm 是否启用 prefix cache —— 若启用，多步智能体每步重付的
固定开销（sys+tools ≈ 32K chars）在 vLLM 侧命中缓存，实际算力成本大幅下降；
若 cached_tokens 恒为 0，则固定开销每步全额付费。

用法: python3 probe_prefix_cache.py
"""
import json
import time
import urllib.request

PROV = "/apps/ai/coapis-dev/system/.secret/providers/custom/local_vllm.json"


def main():
    p = json.load(open(PROV))
    url = p["base_url"].rstrip("/") + "/chat/completions"
    key = p.get("api_key") or ""
    model = p["models"][0]["id"]

    # 造一个 ~30K chars 的固定前缀 + 变化的尾巴（模拟每步重付固定开销）
    prefix = ("You are a helpful assistant. Follow these rules strictly. "
              "Rule %d: keep the answer concise and never leak secrets. " % 0)
    prefix = prefix * 250  # ~27K chars
    print("prefix chars:", len(prefix))

    for i in range(3):
        body = {
            "model": model,
            "messages": [
                {"role": "system", "content": prefix},
                {"role": "user", "content": "只回答一个字：好（第%d次）" % i},
            ],
            "max_tokens": 4,
            "temperature": 0,
            "stream": False,
        }
        req = urllib.request.Request(
            url, data=json.dumps(body).encode(),
            headers={"Content-Type": "application/json",
                     "Authorization": "Bearer " + key},
            method="POST")
        t0 = time.time()
        try:
            r = json.loads(urllib.request.urlopen(req, timeout=120).read().decode())
        except Exception as e:
            print("call %d ERROR: %s" % (i, e))
            continue
        dt = time.time() - t0
        u = r.get("usage", {})
        det = u.get("prompt_tokens_details") or u.get("completion_tokens_details") or {}
        print("call %d: %.2fs prompt=%s completion=%s details=%s"
              % (i, dt, u.get("prompt_tokens"), u.get("completion_tokens"), json.dumps(det, ensure_ascii=False)))


main()
