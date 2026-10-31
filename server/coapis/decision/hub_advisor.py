# -*- coding: utf-8 -*-
"""事中改道：动手过程中判「方向对不对」（v14 §3.4 · 插手点③）。

Why: 判档只发生在开头一次，之后整轮都是自动驾驶。台账里判档说
``complex`` 而交付只给了 ``simple`` 的东西、或越界动了用户没让动的
文件，都是**开头看不见、中途才显形**的问题；开头那次判档救不了，
收尾验收又太晚（钱已经花完、文件已经改完）。

How: 环1（ReAct 每轮动作前）按 ``advisor_every_iters`` 的节奏判一次：
输入 = 用户目标 + 最近几次动作摘要，输出 = ``continue|change|stop`` +
证据。``change/stop`` 时把结论作为一条 HINT 注进记忆，**下一轮动作**
被它影响；台账写一行 ``source=advisor``。

刻意的设计：
* **发射即忘**：判官要 1~3 秒，绝不能卡在动作前。本轮判、下轮生效。
* **前几轮不判**：``advisor_min_iters`` 之前动作太少，判了看不出来，
  只会产生噪声台账。
* **改道必须带证据**：判则要求 change/stop 引用动作序号，防判官凭
  感觉改道；拿不准判 continue（提示每轮都在花钱）。
* 预算闸门由网关统一管（``judge_max_calls_per_turn``），本模块不加闸。
"""
from __future__ import annotations

import asyncio
import json
import logging
import re
from typing import Any, Callable, Sequence

from .rubric import JSON_ONLY, rubric_for

logger = logging.getLogger(__name__)

#: 改道动作取值域（台账 action 列）
VERDICTS = ("continue", "change", "stop", "abstain")

#: 发射即忘的任务集合（防 GC 掐掉未完成任务）
_pending: set[asyncio.Task] = set()

#: 摘要里每个动作的文本上限（字）
_ACTION_CHARS = 160
#: 摘要最多带几个动作
_MAX_ACTIONS = 8


def should_advise(hub: Any, iters: int) -> bool:
    """本轮要不要判一次改道（纯函数，给单测用）。

    Args:
        hub: :class:`DecisionHubConfig`。
        iters: 本轮是第几次动作（1 起）。

    Returns:
        True 表示该判了。闸门：岗位开关 → 节奏开关 → 起判轮次 → 取整。
    """
    if hub is None:
        return False
    if not getattr(hub, "enabled", False):
        return False
    if not hub.post_enabled("advisor"):
        return False
    every = int(getattr(hub, "advisor_every_iters", 3) or 0)
    if every <= 0:
        return False
    min_iters = int(getattr(hub, "advisor_min_iters", 3) or 3)
    if iters < min_iters:
        return False
    return (iters - min_iters) % every == 0


def build_digest(tool_msgs: Sequence[Any] | None) -> str:
    """把最近几次动作压成给判官看的摘要（``1. name 参数摘要`` 形式）。"""
    lines: list[str] = []
    msgs = [m for m in (tool_msgs or []) if m is not None]
    for idx, msg in enumerate(msgs[-_MAX_ACTIONS:], start=1):
        name = str(getattr(msg, "name", "") or "tool")
        text = ""
        try:
            content = msg.get_text_content()  # type: ignore[attr-defined]
        except Exception:
            content = ""
        if isinstance(content, str):
            text = re.sub(r"\s+", " ", content).strip()
        lines.append(f"{idx}. {name} {text[:_ACTION_CHARS]}")
    if not lines:
        return "（还没有动作记录）"
    return "\n".join(lines)


def fire_advisor(
    *,
    goal: str,
    tool_msgs: Sequence[Any] | None,
    scope: dict[str, Any],
    hub: Any,
    skills: Any = None,
    on_verdict: Callable[[dict[str, Any]], Any] | None = None,
) -> asyncio.Task | None:
    """发射一次改道判断（不 await；结论回调给调用方注入提示）。

    Args:
        goal: 用户目标（本轮原话，必要时拼上已确认的计划）。
        tool_msgs: 最近的动作/工具消息，用于摘要。
        scope: 网关身份。
        hub: :class:`DecisionHubConfig`。
        skills: 技能摘要（判则技能可覆盖内置判则）。
        on_verdict: 判出 ``change/stop`` 时的回调（同步或 async），
            由智能体负责把提示注入记忆。回调异常全吞。

    Returns:
        后台任务；被闸门挡掉时返回 ``None``。
    """
    if not should_advise(hub, int(scope.get("iters") or 0)):
        return None
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        return None
    task = loop.create_task(
        _run(goal=goal, tool_msgs=tool_msgs, scope=dict(scope), hub=hub,
             skills=skills, on_verdict=on_verdict),
        name="coapis-advisor",
    )
    _pending.add(task)
    task.add_done_callback(_pending.discard)
    return task


async def advise(
    *,
    goal: str,
    tool_msgs: Sequence[Any] | None,
    scope: dict[str, Any],
    hub: Any,
    skills: Any = None,
) -> dict[str, Any]:
    """判一次改道（同步 await 版，给单测与 E2E 用）。"""
    from .gateway import get_judge_gateway

    prompt = (
        "用户的目标：\n"
        f"{(goal or '')[:1200]}\n\n"
        "智能体已经做的动作（按顺序，序号即证据编号）：\n"
        f"{build_digest(tool_msgs)}\n\n"
        f"{rubric_for('advisor', skills)}\n\n"
        "输出 JSON：{\"verdict\":\"continue|change|stop\","
        "\"evidence\":\"引用上面第几号动作（change/stop 必填）\","
        "\"next\":\"一句话讲清接下来该怎么干（continue 可空）\"}\n"
        + JSON_ONLY
    )

    def _parse(text: str) -> dict[str, Any] | None:
        obj = _load_obj(text)
        if not obj:
            return None
        verdict = str(obj.get("verdict") or "").strip().lower()
        if verdict not in VERDICTS:
            return None
        return {
            "verdict": verdict,
            "evidence": str(obj.get("evidence") or "")[:200],
            "next": str(obj.get("next") or "")[:300],
        }

    reply = await get_judge_gateway().judge(
        purpose="advisor",
        system="你是任务方向纠察员，按判则回答目标漂移三问。" + JSON_ONLY,
        user=prompt,
        parse=_parse,
        rule_fallback=lambda: {
            "verdict": "continue",
            "evidence": "",
            "next": "",
        },
        describe=lambda v: str(v.get("verdict") or ""),
        hub=hub,
        scope=scope,
    )
    value = reply.value or {}
    verdict = str(value.get("verdict") or "continue")
    return {
        "verdict": verdict,
        "evidence": str(value.get("evidence") or ""),
        "next": str(value.get("next") or ""),
        "hit_layer": reply.hit_layer,
        "layer": reply.hit_layer,
    }


async def _run(
    *,
    goal: str,
    tool_msgs: Sequence[Any] | None,
    scope: dict[str, Any],
    hub: Any,
    skills: Any,
    on_verdict: Callable[[dict[str, Any]], Any] | None,
) -> None:
    try:
        res = await advise(
            goal=goal, tool_msgs=tool_msgs, scope=scope, hub=hub,
            skills=skills,
        )
        logger.info(
            "[Advisor] verdict=%s layer=%s evidence=%s chat=%s turn=%s iters=%s",
            res["verdict"], res["hit_layer"], res["evidence"][:60],
            scope.get("chat_id"), scope.get("turn"), scope.get("iters"),
        )
        if res["verdict"] in ("change", "stop") and on_verdict is not None:
            out = on_verdict(res)
            if asyncio.iscoroutine(out):
                await out
    except Exception:  # pragma: no cover - 改道是旁路，异常不得影响动作
        logger.debug("[Advisor] 改道任务异常（已吞）", exc_info=True)


def _load_obj(text: str) -> dict[str, Any] | None:
    """从判官输出里取 JSON 对象（剥围栏 + 取第一个花括号块）。"""
    txt = (text or "").strip()
    if not txt:
        return None
    fence = re.search(r"```(?:json)?\s*(.+?)```", txt, re.S)
    if fence:
        txt = fence.group(1).strip()
    try:
        obj = json.loads(txt)
        return obj if isinstance(obj, dict) else None
    except Exception:
        pass
    brace = re.search(r"\{.*\}", txt, re.S)
    if not brace:
        return None
    try:
        obj = json.loads(brace.group(0))
        return obj if isinstance(obj, dict) else None
    except Exception:
        return None
