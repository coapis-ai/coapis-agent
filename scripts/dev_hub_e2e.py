"""判断中枢 dev 端到端体检（v14 §验收 5）。

跑法（宿主直接跑，库走 dev 的 SQLite）：
    python scripts/dev_hub_e2e.py --base http://localhost:4308 --user admin --password <pw>
或塞进容器里跑（容器有 httpx）：
    docker exec -w /app -e COAPIS_DEV_BASE=http://localhost:8000 coapis-server-dev python3 /app/../scripts/dev_hub_e2e.py
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
import time

import httpx


async def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", default="http://localhost:8000")
    ap.add_argument("--user", default="admin")
    ap.add_argument("--password", required=True)
    ap.add_argument("--agent", default="", help="agent id；留空用默认")
    ap.add_argument("--prompt", default="用工具查一下当前时间，然后把结果写成一句话回复我")
    ap.add_argument("--poll", type=float, default=120.0, help="等这轮跑完的秒数")
    args = ap.parse_args()

    async with httpx.AsyncClient(base_url=args.base, timeout=30.0) as cli:
        r = await cli.post("/api/auth/login", json={
            "username": args.user, "password": args.password,
        })
        if r.status_code >= 400:
            print(f"登录失败 {r.status_code}: {r.text[:200]}")
            return 1
        data = r.json()
        token = data.get("access_token") or data.get("token") or (data.get("data") or {}).get("access_token")
        if not token:
            print("登录响应里没有 token：", json.dumps(data, ensure_ascii=False)[:300])
            return 1
        cli.headers["Authorization"] = f"Bearer {token}"
        print(f"登录 OK（{args.user}）")

        body = {"message": args.prompt}
        if args.agent:
            body["agent_id"] = args.agent
        t0 = time.time()
        r = await cli.post("/api/console/chat", json=body)
        print(f"POST /api/console/chat -> {r.status_code} 用时 {time.time()-t0:.1f}s")
        print("响应片段:", r.text[:400].replace("\n", " "))
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
