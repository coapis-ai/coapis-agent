#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""实测 chars→token 真实比率（只读诊断）。

用真实系统提示词 + 一条真实用户消息组成基线 prompt，直发模型读 usage.input_tokens。
"""
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, "/app")

from agentscope.message import Msg  # noqa: E402

from coapis.agents.prompt import build_system_prompt_from_working_dir  # noqa: E402
from coapis.config.utils import create_model_and_formatter  # noqa: E402


async def main() -> None:
    ws = Path(sys.argv[1] if len(sys.argv) > 1 else "/apps/ai/coapis/agents/user:admin")
    agent_id = sys.argv[2] if len(sys.argv) > 2 else "user:admin"
    sysp = build_system_prompt_from_working_dir(working_dir=ws, agent_id=agent_id)
    user_text = "只回复一个字：好"
    print("sys chars:", len(sysp))

    model, formatter = create_model_and_formatter(agent_id)
    print("model:", getattr(model, "model_name", "?"), "stream:", getattr(model, "stream", "?"))

    # 基线 prompt：系统提示词 + 用户消息（合成一条 user 消息，读真实 token 数）
    combo = sysp + "\n\n" + user_text
    msgs = [Msg(name="user", role="user", content=combo)]
    formatted = await formatter.format(msgs)
    resp = await model(formatted)
    # stream=True → 收敛最后一个 chunk
    usage = None
    if hasattr(resp, "__aiter__") or hasattr(resp, "__anext__"):
        last = None
        async for chunk in resp:
            last = chunk
        usage = getattr(last, "usage", None)
    else:
        usage = getattr(resp, "usage", None)
        if usage is None and isinstance(resp, dict):
            usage = resp.get("usage")
    print("usage:", usage)
    pt = getattr(usage, "input_tokens", None) if usage else None
    if pt:
        print("prompt_tokens:", pt)
        print("observed chars/token: %.3f" % (len(combo) / pt))
        fixed = 26056
        total = 28808
        print(
            "=> 固定开销 %d chars ≈ %d tokens；一次基线请求 %d chars ≈ %d tokens"
            % (fixed, round(fixed / (len(combo) / pt)), total,
               round(total / (len(combo) / pt)))
        )


asyncio.run(main())
