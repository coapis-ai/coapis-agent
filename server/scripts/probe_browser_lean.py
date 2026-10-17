#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""D1 最省模式验证：schema 瘦身 + 旧参数名兼容（只读探针）。"""
import asyncio
import inspect
import json
import sys

sys.path.insert(0, "/app")

from agentscope._utils._common import _parse_tool_function  # noqa: E402

from coapis.agents.tools.browser_control import browser_use  # noqa: E402

MOVED = [
    "width", "height", "level", "include_static", "screenshot_type", "slowly",
    "start_selector", "end_selector", "start_element", "end_element",
    "output_path", "filename", "snapshot_filename", "file_path",
    "cdp_port", "private_mode", "executable_path", "cdp_url",
    "port", "port_min", "port_max",
]


def main() -> None:
    sch = _parse_tool_function(
        browser_use,
        include_long_description=True,
        include_var_positional=False,
        include_var_keyword=False,
    )
    blob = json.dumps(sch, ensure_ascii=False)
    fn = sch.get("function", sch)
    props = fn.get("parameters", {}).get("properties", {})
    print("schema chars:", len(blob))
    print("schema 参数数:", len(props))
    print("kwargs 泄漏进 schema:", "kwargs" in props)
    leaked = [p for p in MOVED if p in props]
    print("已移出 schema 的参数残留:", leaked if leaked else "无")

    sig = inspect.signature(browser_use)
    print("签名参数数:", len(sig.parameters), "| 含 kwargs:",
          any(p.kind == p.VAR_KEYWORD for p in sig.parameters.values()))

    # 兼容层：旧参数名调用必须被接受（不抛 TypeError）
    async def probe() -> str:
        try:
            r = await browser_use(
                action="screenshot",
                output_path="/tmp/legacy_probe.png",  # 旧参数名
                start_ref="e99",
                cdp_port=0,
                width=800,
                height=600,
                screenshot_type="jpeg",
            )
            txt = ""
            for blk in getattr(r, "content", []) or []:
                txt += blk.get("text", "") if isinstance(blk, dict) else str(blk)
            return "accepted: " + txt[:120].replace("\n", " ")
        except TypeError as exc:
            return "TypeError: %s" % exc

    print("旧参数名调用:", asyncio.run(probe())[:200])


main()
