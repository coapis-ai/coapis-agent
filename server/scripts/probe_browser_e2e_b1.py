"""Real browser E2E after B1/B2: start → open → snapshot → screenshot(path) → stop."""
import asyncio
import json
import os
import sys

sys.path.insert(0, "/app")

from coapis.agents.tools.browser_control import browser_use  # noqa: E402


def text(resp) -> str:
    out = []
    for block in getattr(resp, "content", []) or []:
        out.append(block.get("text", "") if isinstance(block, dict) else getattr(block, "text", ""))
    return "".join(out)


async def step(label, **kw):
    resp = await browser_use(**kw)
    body = text(resp)
    head = body[:160].replace("\n", " ")
    print(f"  {label:34s} -> {head}")
    return body


async def main():
    await step("start", action="start")
    await step("open", action="open", url="https://example.com")
    snap = await step("snapshot", action="snapshot")
    await step("screenshot(带path)", action="screenshot", path="/tmp/e2e_b1.png")
    await step("evaluate", action="evaluate", code="document.title")
    await step("stop", action="stop")
    print("\nsnapshot 长度 =", len(snap))
    print("截图存在 =", os.path.exists("/tmp/e2e_b1.png"),
          os.path.getsize("/tmp/e2e_b1.png") if os.path.exists("/tmp/e2e_b1.png") else 0, "bytes")


if __name__ == "__main__":
    asyncio.run(main())
