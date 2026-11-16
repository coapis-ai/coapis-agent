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

from .rubric import rubric_for

logger = logging.getLogger(__name__)

#: 改道动作取值域（台账 action 列）
VERDICTS = ("continue", "change", "stop", "abstain")

# ── 模型侧契约（D5·A3）───────────────────────────────────────────
# 对模型只要求一个词：CONTINUE / ADJUST。
#
# 为什么不再是 JSON：判官槽位上常跑 0.6B~7B 的小模型，让它吐
# ``{"verdict":..,"evidence":..,"next":..}`` 这种三字段合法 JSON 是失败常态；
# 解析一失败就吃一次 breaker 失败计数，等于把"格式不行"混进"模型不行"里，
# 最后熔断反映的根本不是真判率。单字契约把格式失败面压成 0。
#
# 代价要说清：模型不再自己写"下一步"。那本来也只是被截成 200 字的一句话，
# 且消费方还留着 next 槽位（见 react_agent._inject_advisor_hint），所以是
# "少一个不可靠字段"，不是"少一个功能"。
#
# 台账仍写 change：ADJUST 是**模型词**、change 是**台账词**，一一对应。
# 换叫法会让新旧台账行分成两代词汇、前端映射也得跟着改，不值当。
_ADJUST = "ADJUST"
_CONTINUE = "CONTINUE"
_EVIDENCE_MAX = 200

CONTRACT_PROMPT = (
    "只回答一个词，不要任何解释、标点、JSON。\n\n"
    "干得对，或者你拿不准 —— CONTINUE\n"
    "明显在原地打转、跑偏、或已经越界 —— ADJUST: 一句话讲清该怎么改\n\n"
    "注意：说不清就是 CONTINUE。你不是来刷存在感的，误拦一次比漏判一次贵。\n"
)


def _sentence_after(text: str) -> str:
    """取 ADJUST 之后那句话当证据；模型没写句子就空着，不替它编。"""
    idx = text.upper().find(_ADJUST)
    tail = text[idx + len(_ADJUST):] if idx >= 0 else text
    cleaned = tail.strip().strip(' :：.,、。；;{}[]()"')
    return cleaned.strip()[:_EVIDENCE_MAX]


def parse_contract(text: str) -> tuple[str, str] | None:
    """单字契约解析 → ``(台账词, 证据)``；``None`` = 模型什么都没吐（parse_fail）。

    口径只有一句：**非 ADJUST 一律 CONTINUE**。判官的职责是"要不要改道"，
    说不清就等于"不改"——把解析失败当"该拦"处置，等于用一个更笨的模型去
    否决主链的正常工作。

    但**空回复仍返回 None**：那不是"它说继续"，是这一判没有内容。它必须留在
    parse_fail 上可见，否则判官挂了、槽位空转，我们从台账里看到的会是一片
    祥和的 continue。
    """
    body = str(text or "").strip()
    if not body:
        return None
    upper = body.upper()
    if _ADJUST in upper and _CONTINUE in upper:
        # 两个词都冒出来 = 它自己也没定。不确定即放行。
        return ("continue", "")
    if _ADJUST in upper:
        return ("change", _sentence_after(body))
    return ("continue", "")


#: 发射即忘的任务集合（防 GC 掐掉未完成任务）
_pending: set[asyncio.Task] = set()

#: 摘要里每个动作的文本上限（字）
_ACTION_CHARS = 160
#: 摘要最多带几个动作
_MAX_ACTIONS = 8


def should_advise(hub: Any, iters: int, *, force: bool = False) -> bool:
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
    if force:
        # 规则层已经拿出"该改道"的证据（新失败形状），再等凑满 every 轮就是
        # 明知故犯。注意：上面几道闸照样生效——force 只跳过取整节奏，
        # 不能拿它越过岗位开关去开岗。
        return True
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
    # ③→④：规则层（失败签名闸）发现没见过的事件形状时，scope 里带 advise_now，
    # 该问就问一次，不用等取整节奏。
    if not should_advise(
        hub,
        int(scope.get("iters") or 0),
        force=bool(scope.get("advise_now")),
    ):
        return None

    # 判官槽位是空的 —— 它压根不上岗。此时若照打，网关每一发都在 no_model 层
    # 落一行台账，按 advisor_every_iters 的节奏天天累积，而这些行的信息量是零。
    # “台账 0 白跑行”这条验收要治的就是这个：**结构上不发射**，不是在台账侧过滤。
    # 判据与网关 :622 同一句（provider_id / model），免得两处各判一套、
    # 又长出一个“写读键名不一致”。
    try:
        from .resolver import get_judge_provider_config

        slot = get_judge_provider_config(
            hub,
            user_id=str(scope.get("user_id") or "") or None,
            agent_id=str(scope.get("agent_id") or "") or None,
        )
    except Exception:  # pragma: no cover - 取不到判据时按没配处理，宁可不问
        slot = None
    if not slot or not slot.get("provider_id") or not slot.get("model"):
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
        # 单字契约（D5·A3）：不再要 JSON。详见文件头 CONTRACT 段的取舍。
        + CONTRACT_PROMPT
    )

    def _parse(text: str) -> dict[str, Any] | None:
        hit = parse_contract(text)
        if hit is None:
            return None
        verdict, evidence = hit
        return {
            "verdict": verdict,
            "evidence": evidence,
            # 单字契约下模型不再产出"下一步"。这个键**保留**：注入提示的
            # 格式化函数（react_agent._inject_advisor_hint）在读它，留空比
            # 造一条"键已删"的兼容分支便宜，也不破坏消费方。
            "next": "",
        }

    reply = await get_judge_gateway().judge(
        purpose="advisor",
        # 不拼 JSON_ONLY：单字契约下它是一条**反向**指令（会逼模型去吐 JSON），
        # 而格式失败又会吃 breaker 失败计数——正是本批要治的病。
        system="你是任务方向纠察员。只回答 CONTINUE 或 ADJUST: 句子。",
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
