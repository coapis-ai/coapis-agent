# -*- coding: utf-8 -*-
"""工具闸：动手前判「这一步该不该这么干」（v14 §批次4 · 拍板 D3 一期接）。

Why: 五岗里工具岗是空号——台账里没有 ``tool_gate`` 这个来源。智能体每轮要调
十几次工具，选错工具、同一个工具同一份参数反复调（原地打转）、没目标就动
破坏性动作，全部发生在「开头判档」与「收尾验收」之间那段没人看的路上。
改道岗看得见动作序列，但它按节奏抽样（每 N 轮一次），看不见单步。

How: ``react_agent._acting`` 每次要执行工具前发射一次判断（**发射即忘**，
判官要 1~4s，绝不卡在动作前面）。输入 = 用户目标 + 本次工具与参数摘要 +
最近动作摘要；输出 = ``allow|reroute`` + 理由 + 建议改用的工具。判出
``reroute`` 时把结论作为一条 HINT 注进记忆，影响**下一个**动作。台账写一行
``source=tool_gate``，``action="tool:<名>:allow|reroute"``。

刻意的设计（一期边界，讲清楚不藏）：
* **只提示不拦**：一期绝不否决工具调用。判官一期真判率 19%，拦错一次就是
  主链故障；``block`` 不进词表，判官给了也降级成 ``reroute``。
* **便宜动作不判**：纯只读、自描述的工具在 ``CHEAP_TOOLS`` 里跳过，不烧
  判断预算（v14 §4.4④：判断本身不能变成循环）。
* **规则层有把握就不问模型**：同一工具同一参数连续第 N 次 = 原地打转，这条
  规则比模型准，走 ``rule_fast``，零延迟零成本。
* 预算/熔断/缓存/软超时/台账全在网关，本模块只提供闸门、提示词与解析。
"""
from __future__ import annotations

import asyncio
import json
import logging
import re
from typing import Any, Callable, Sequence

from .rubric import JSON_ONLY, rubric_for

logger = logging.getLogger(__name__)

#: 工具闸结论取值域（台账 action 列后缀）
VERDICTS = ("allow", "reroute")

#: 一期不执行拦截：判官给的 block 一律降级 reroute（留证据，不夺权）
_BLOCK_AS_REROUTE = True

#: 不烧判断预算的动作（只读/自描述，判了也判不出什么）
CHEAP_TOOLS = frozenset(
    {
        "read_file",
        "view_image",
        "view_video",
        "get_current_time",
        "list_agents",
        "memory_search",
        "recall_history",
        "glob_search",
    },
)

#: 破坏性动作（无目标时规则层直接提示）
_LOUD_TOOLS = frozenset(
    {
        "execute_shell_command",
        "write_file",
        "edit_file",
        "browser_use",
        "send_file_to_user",
    },
)

#: 同一工具同一参数连续第几次算原地打转
_LOOP_HITS = 3

#: 参数摘要上限（字）
_ARGS_CHARS = 220
#: 提示词里目标摘要上限（字）
_GOAL_CHARS = 700
#: 提示词里带几个历史动作
_MAX_RECENT = 6


def should_gate(hub: Any, tool_name: str) -> bool:
    """这个动作要不要过闸（纯函数，给单测用）。

    Args:
        hub: :class:`DecisionHubConfig`。
        tool_name: 本次要执行的工具名。

    Returns:
        True 表示要判。闸门：总开关 → 岗位开关 → 有名工具 → 非便宜动作。
    """
    if hub is None:
        return False
    if not getattr(hub, "enabled", False):
        return False
    if not hub.post_enabled("tool_gate"):
        return False
    name = str(tool_name or "")
    if not name:
        return False
    return name not in CHEAP_TOOLS


def _short(value: Any) -> Any:
    """参数值过长就截断，避免整份文件内容进摘要。"""
    if isinstance(value, str) and len(value) > 80:
        return value[:80] + "…"
    return value


def args_digest(tool_call: Any) -> str:
    """工具参数摘要：定长、键序稳定，可直接当规则层指纹。

    Args:
        tool_call: 工具调用块（dict，或带 ``input``/``arguments`` 的对象）。

    Returns:
        规范化参数摘要字符串（超长截断）。
    """
    raw: Any = None
    if isinstance(tool_call, dict):
        raw = tool_call.get("input", tool_call.get("arguments"))
    else:
        raw = getattr(tool_call, "input", None) or getattr(tool_call, "arguments", None)
    if isinstance(raw, str):
        try:
            raw = json.loads(raw)
        except Exception:  # noqa: BLE001 - 参数本来就是文本也照摘要
            pass
    if isinstance(raw, dict):
        raw = {k: _short(v) for k, v in sorted(raw.items())}
    try:
        text = json.dumps(raw, ensure_ascii=False, sort_keys=True, default=str)
    except Exception:  # noqa: BLE001
        text = str(raw)
    return re.sub(r"\s+", " ", text).strip()[:_ARGS_CHARS]


def tool_name_of(tool_call: Any) -> str:
    """取工具名（dict / 对象两种形状都认）。"""
    if isinstance(tool_call, dict):
        return str(tool_call.get("name") or "")
    return str(getattr(tool_call, "name", "") or "")


def rule_fast(
    tool_name: str,
    digest: str,
    recent: Sequence[tuple[str, str]] | None,
    goal: str,
) -> dict[str, Any] | None:
    """规则层有把握的结论（走网关 ``rule_fast``，命中就不问模型、不占预算）。

    Args:
        tool_name: 本次工具名。
        digest: 本次参数摘要。
        recent: 最近若干次 ``(工具名, 参数摘要)``，按时间顺序。
        goal: 用户目标（空目标时动破坏性工具要提示）。

    Returns:
        ``{"verdict","why","tool"}``；规则没把握时返回 ``None``（交模型判）。
    """
    prior = list(recent or [])[-(_LOOP_HITS - 1):]
    hits = sum(1 for name, dig in prior if name == tool_name and dig == digest)
    if hits >= _LOOP_HITS - 1:
        return {
            "verdict": "reroute",
            "why": f"同一工具同一参数连续第 {hits + 1} 次（原地打转）",
            "tool": "",
        }
    if tool_name in _LOUD_TOOLS and not str(goal or "").strip():
        return {
            "verdict": "reroute",
            "why": "没有明确目标就动破坏性动作",
            "tool": "",
        }
    return None


def _parse_verdict(raw: str) -> dict[str, Any]:
    """判官输出 → ``{verdict, why, tool}``。不成 JSON 抛 ValueError。"""
    text = raw.strip()
    match = re.search(r"\{.*\}", text, re.S)
    if match:
        text = match.group(0)
    try:
        data = json.loads(text)
    except Exception as exc:  # noqa: BLE001 - 交网关记 parse_fail
        raise ValueError(f"判官输出不是 JSON 对象: {raw[:80]!r}") from exc
    if not isinstance(data, dict):
        raise ValueError(f"判官输出不是对象: {raw[:80]!r}")
    verdict = str(data.get("verdict") or "").strip().lower()
    if verdict == "block" and _BLOCK_AS_REROUTE:
        verdict = "reroute"
    if verdict not in VERDICTS:
        raise ValueError(f"判官给了词表外的结论: {verdict!r}")
    return {
        "verdict": verdict,
        "why": str(data.get("why") or "")[:200],
        "tool": str(data.get("tool") or "")[:60],
    }


def build_prompt(
    *,
    goal: str,
    tool_name: str,
    digest: str,
    recent: Sequence[tuple[str, str]] | None,
    skills: Any = None,
) -> str:
    """工具闸提示词（目标 + 本次动作 + 历史动作 + 判则）。"""
    lines: list[str] = []
    for idx, (name, dig) in enumerate(list(recent or [])[-_MAX_RECENT:], start=1):
        lines.append(f"{idx}. {name} {dig}")
    history = "\n".join(lines) if lines else "（本轮还没有动作）"
    return (
        "用户的目标：\n"
        f"{(goal or '')[:_GOAL_CHARS]}\n\n"
        "智能体此刻准备执行的动作：\n"
        f"0. {tool_name} {digest}\n\n"
        "此前已经执行的动作（序号即证据编号）：\n"
        f"{history}\n\n"
        f"{rubric_for('tools', skills)}\n\n"
        "输出 JSON："
        '{"verdict":"allow|reroute","why":"一句话理由（reroute 必填）",'
        '"tool":"建议改用的工具名，没有就空串"}\n' + JSON_ONLY
    )


#: 后台任务集合（防 GC 掐掉未完成任务）
_pending: set[asyncio.Task] = set()


async def judge_tool_gate(
    *,
    goal: str,
    tool_name: str,
    digest: str,
    recent: Sequence[tuple[str, str]] | None,
    scope: dict[str, Any],
    hub: Any = None,
    skills: Any = None,
    on_verdict: Callable[[dict[str, Any]], Any] | None = None,
) -> dict[str, Any]:
    """判一次工具闸（await 版，给单测与 E2E 用）。

    Args:
        goal: 用户目标（本轮原话）。
        tool_name: 本次工具名。
        digest: 参数摘要。
        recent: 最近 ``(工具名, 摘要)`` 序列。
        scope: 网关身份（``user_id/agent_id/chat_id/turn``）。
        hub: 配置（默认读环境变量）。
        skills: 技能摘要（判则技能可覆盖内置判则）。
        on_verdict: 判出 ``reroute`` 时的回调（同步或 async），由智能体负责
            注入提示。回调异常全吞——提示失败不影响主链。

    Returns:
        ``{"verdict","why","tool"}``。判断失败时返回 ``allow``：闸门的失败
        姿态是放行，拦错比放过贵。
    """
    from .gateway import get_judge_gateway

    snapshot = list(recent or ())
    reply = await get_judge_gateway().judge(
        purpose="tool_gate",
        system="",
        user=build_prompt(
            goal=goal,
            tool_name=tool_name,
            digest=digest,
            recent=snapshot,
            skills=skills,
        ),
        parse=_parse_verdict,
        rule_fast=lambda: rule_fast(tool_name, digest, snapshot, goal),
        rule_fallback=lambda: {
            "verdict": "allow",
            "why": "判断失败，闸门放行",
            "tool": "",
        },
        describe=lambda v: (
            f"tool:{tool_name}:{v.get('verdict', 'allow')}"
            if isinstance(v, dict)
            else f"tool:{tool_name}:allow"
        ),
        hub=hub,
        scope=scope,
    )
    verdict = (
        reply.value
        if isinstance(reply.value, dict)
        else {"verdict": "allow", "why": "", "tool": ""}
    )
    if verdict.get("verdict") == "reroute" and on_verdict is not None:
        try:
            out = on_verdict(verdict)
            if asyncio.iscoroutine(out):
                await out
        except Exception:  # noqa: BLE001 - 回调绝不影响主链
            logger.debug("[工具闸] 提示注入失败", exc_info=True)
    return verdict


def fire_tool_gate(
    *,
    goal: str,
    tool_name: str,
    digest: str,
    recent: Sequence[tuple[str, str]] | None,
    scope: dict[str, Any],
    hub: Any = None,
    skills: Any = None,
    on_verdict: Callable[[dict[str, Any]], Any] | None = None,
) -> asyncio.Task | None:
    """发射一次工具闸判断（不 await；结论交回调，下一个动作才生效）。

    Args:
        goal: 用户目标（本轮原话）。
        tool_name: 本次工具名。
        digest: 参数摘要。
        recent: 最近 ``(工具名, 摘要)`` 序列。
        scope: 网关身份。
        hub: 配置。
        skills: 技能摘要。
        on_verdict: 判出 ``reroute`` 时的回调。

    Returns:
        后台任务；被闸门挡掉或无事件循环时返回 ``None``。
    """
    if not should_gate(hub, tool_name):
        return None
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:  # 无事件循环（同步路径/单测）→ 不判
        return None
    task = loop.create_task(
        judge_tool_gate(
            goal=goal,
            tool_name=tool_name,
            digest=digest,
            recent=recent,
            scope=dict(scope or {}),
            hub=hub,
            skills=skills,
            on_verdict=on_verdict,
        ),
        name="coapis-tool-gate",
    )
    _pending.add(task)
    task.add_done_callback(_pending.discard)
    return task


__all__ = [
    "CHEAP_TOOLS",
    "VERDICTS",
    "args_digest",
    "build_prompt",
    "fire_tool_gate",
    "judge_tool_gate",
    "rule_fast",
    "should_gate",
    "tool_name_of",
]
