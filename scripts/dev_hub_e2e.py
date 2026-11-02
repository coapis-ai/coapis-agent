"""判断中枢 dev 端到端体检（v14 §验收 5）。

用法（宿主直连 dev 后端）：
    python scripts/dev_hub_e2e.py --base http://localhost:4308 --user admin --password admin123
脚本会：登录 → 建会话 → 发一条会触发工具的多步任务 → **把 SSE 流读到底** →
打印这轮的岗位/台账证据。全程只读库、只发一轮聊天，不改任何配置。
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
import time

import httpx


def _tok(data: dict) -> str | None:
    for k in ("access_token", "token"):
        if data.get(k):
            return str(data[k])
    d = data.get("data") or {}
    if isinstance(d, dict):
        for k in ("access_token", "token"):
            if d.get(k):
                return str(d[k])
    return None


async def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", default="http://localhost:4308")
    ap.add_argument("--user", default="admin")
    ap.add_argument("--password", required=True)
    ap.add_argument("--agent", default="", help="agent_id；留空用控制台默认智能体")
    ap.add_argument(
        "--prompt",
        default="请分三步完成：1) 列出当前工作目录下的文件；2) 读一下 pyproject.toml 的前 20 行；"
                "3) 用一句话总结这个仓库是做什么的。每一步都要真的调用工具，不要凭空回答。",
    )
    ap.add_argument("--max-seconds", type=float, default=420.0, help="读完这轮 SSE 的上限")
    args = ap.parse_args()

    t0 = time.time()
    async with httpx.AsyncClient(base_url=args.base, timeout=httpx.Timeout(60.0, read=120.0)) as cli:
        r = await cli.post("/api/auth/login", json={"username": args.user, "password": args.password})
        if r.status_code >= 400:
            print(f"登录失败 {r.status_code}: {r.text[:200]}")
            return 1
        token = _tok(r.json())
        if not token:
            print("登录响应里没有 token:", json.dumps(r.json(), ensure_ascii=False)[:200])
            return 1
        cli.headers["Authorization"] = f"Bearer {token}"
        print(f"[{time.time()-t0:5.1f}s] 登录 OK")

        body = {"message": args.prompt}
        if args.agent:
            body["agent_id"] = args.agent
        chunks, events, last = 0, {}, ""
        try:
            async with cli.stream("POST", "/api/console/chat", json=body) as res:
                print(f"[{time.time()-t0:5.1f}s] SSE 状态 {res.status_code}")
                if res.status_code >= 400:
                    print((await res.aread()).decode("utf-8", "replace")[:400])
                    return 1
                async for line in res.aiter_lines():
                    if time.time() - t0 > args.max_seconds:
                        print(f"[{time.time()-t0:5.1f}s] 超过 --max-seconds，停止读取")
                        break
                    if not line.startswith("data:"):
                        continue
                    chunks += 1
                    payload = line[5:].strip()
                    if payload == "[DONE]":
                        print(f"[{time.time()-t0:5.1f}s] 收到 [DONE]")
                        break
                    try:
                        obj = json.loads(payload)
                    except Exception:  # noqa: BLE001
                        continue
                    et = str(obj.get("type") or obj.get("event") or "?")
                    events[et] = events.get(et, 0) + 1
                    txt = obj.get("text") or obj.get("content") or ""
                    if isinstance(txt, str) and txt:
                        last = txt[-120:]
        except Exception as exc:  # noqa: BLE001
            print(f"[{time.time()-t0:5.1f}s] SSE 中断: {type(exc).__name__}: {exc}")

        print(f"[{time.time()-t0:5.1f}s] SSE 结束：{chunks} 个 data 帧 · 事件分布 {events}")
        print(f"末段文本: {last[:160]}")
    print(f"总用时 {time.time()-t0:.1f}s —— 台账证据请跑 scripts/coapis_dev_precheck.sh 第 1/9/12 项")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
