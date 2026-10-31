# -*- coding: utf-8 -*-
"""验收回灌：一轮跑完，判官对着需求验交付（v14 §3.5 · 插手点⑤）。

Why: 台账里 ``outcome`` 恒为 ``pending`` ——「判得准不准」这件事**没有任何
人在算**：判档说 complex，最后有没有真交付 complex 的东西，没人回填。
没有回填就没有命中率，也就没有「调判则」的依据，判官永远自说自话。

How: 轮尾（POST_POST_PROCESS 之后）以**发射即忘**的方式判一次：
需求 = 用户本轮原话，交付 = 智能体本轮最终回答。判官吐
``verdict=satisfied|partial|failed`` + 两条红线（越界 / 过度设计）。
台账写一行 ``source=acceptance``（``action`` = verdict），并把**同轮的
判档行**回填成 ``outcome=hit|miss``、``rating=verdict``——这是命中率的
唯一来源，也是下一轮改道加严的输入。

刻意的设计：
* **绝不影响回答**：轮尾起后台任务，异常全吞，超时由网关的 3s 兜。
  验收是加分项，不是关键路径。
* **短对话不判**：需求少于 12 字、交付少于 40 字的多是招呼/确认，
  判了只会生产噪声台账。
* 判官不可用时**照样记一行**（hit_layer=no_model/abstain）——判官缺席
  必须可见，这是 v14 §2.2 的第 2 条根因（静默弃权）的解法。
"""
from __future__ import annotations

import asyncio
import json
import logging
import re
from typing import Any

from .rubric import JSON_ONLY, rubric_for

logger = logging.getLogger(__name__)

#: 需求/交付的最小长度（低于此不判，见模块 docstring）
_MIN_QUERY_CHARS = 12
_MIN_ANSWER_CHARS = 40

#: verdict 取值域（台账 action 列）
VERDICTS = ("satisfied", "partial", "failed", "abstain")

#: 发射即忘的任务集合（防 GC 把未完成任务掐掉——asyncio 官方要求）
_pending: set[asyncio.Task] = set()


def fire_acceptance(
    *,
    query: str,
    answer: str,
    scope: dict[str, Any],
    hub: Any,
    skills: Any = None,
) -> asyncio.Task | None:
    """轮尾发射验收（不 await，不阻塞收尾）。

    Args:
        query: 用户本轮原话。
        answer: 本轮最终交付文本。
        scope: 网关身份（``user_id/agent_id/chat_id/turn``）。
        hub: :class:`DecisionHubConfig`。
        skills: 智能体手里的技能摘要（判则技能可覆盖内置判则）。

    Returns:
        后台任务；被闸门挡掉时返回 ``None``。
    """
    if hub is None:
        return None
    if not getattr(hub, "enabled", False) or not hub.post_enabled("acceptance"):
        return None
    query = (query or "").strip()
    answer = (answer or "").strip()
    if len(query) < _MIN_QUERY_CHARS or len(answer) < _MIN_ANSWER_CHARS:
        return None
    if scope.get("agent_id") in ("", None):
        return None
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:  # 无事件循环（同步收尾路径）
        return None
    task = loop.create_task(
        _run_acceptance(query=query, answer=answer, scope=dict(scope), hub=hub,
                        skills=skills),
        name="coapis-acceptance",
    )
    _pending.add(task)
    task.add_done_callback(_pending.discard)
    return task


async def judge_acceptance(
    *,
    query: str,
    answer: str,
    scope: dict[str, Any],
    hub: Any,
    skills: Any = None,
) -> dict[str, Any]:
    """判一次验收（同步 await 版，给 E2E 与单测用）。"""
    from .gateway import get_judge_gateway

    cap = int(getattr(hub, "acceptance_max_chars", 4000) or 4000)
    prompt = (
        "用户的这轮要求：\n"
        f"{query[:1200]}\n\n"
        "智能体这轮的交付：\n"
        f"{answer[:cap]}\n\n"
        f"{rubric_for('acceptance', skills)}\n\n"
        "输出 JSON：{\"verdict\":\"satisfied|partial|failed\","
        "\"overreach\":true/false,\"overdesign\":true/false,"
        "\"reason\":\"一句话（越界/过度设计要点出具体动作）\","
        "\"missing\":\"还缺什么，没有则空串\"}\n"
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
            "overreach": bool(obj.get("overreach")),
            "overdesign": bool(obj.get("overdesign")),
            "reason": str(obj.get("reason") or "")[:200],
            "missing": str(obj.get("missing") or "")[:200],
        }

    reply = await get_judge_gateway().judge(
        purpose="acceptance",
        system=(
            "你是交付验收员，按判则核对需求与交付的对应关系。"
            + JSON_ONLY
        ),
        user=prompt,
        parse=_parse,
        rule_fallback=lambda: {
            "verdict": "abstain",
            "overreach": False,
            "overdesign": False,
            "reason": "无可用判官，弃权",
            "missing": "",
        },
        describe=lambda v: (
            f"{v.get('verdict') or ''}"
            + ("/overreach" if v.get("overreach") else "")
            + ("/overdesign" if v.get("overdesign") else "")
        ),
        hub=hub,
        scope=scope,
    )
    verdict = str((reply.value or {}).get("verdict") or "abstain")
    overreach = bool((reply.value or {}).get("overreach"))
    # 台账由网关单点写（source=acceptance，action=判官的 describe）；
    # 这里只负责把同轮的判档行回填成 hit/miss —— 命中率的唯一来源。
    await _backfill_plan_gate(scope=scope, verdict=verdict)
    return {
        "verdict": verdict,
        "overreach": overreach,
        "overdesign": bool((reply.value or {}).get("overdesign")),
        "reason": str((reply.value or {}).get("reason") or ""),
        "missing": str((reply.value or {}).get("missing") or ""),
        "hit_layer": reply.hit_layer,
    }


async def _run_acceptance(
    *,
    query: str,
    answer: str,
    scope: dict[str, Any],
    hub: Any,
    skills: Any,
) -> None:
    try:
        res = await judge_acceptance(
            query=query, answer=answer, scope=scope, hub=hub, skills=skills,
        )
        logger.info(
            "[Accept] verdict=%s overreach=%s overdesign=%s layer=%s "
            "cost=%.1fms chat=%s turn=%s",
            res["verdict"], res["overreach"], res["overdesign"],
            res["hit_layer"], 0.0, scope.get("chat_id"), scope.get("turn"),
        )
    except Exception:  # pragma: no cover - 验收是加分项，任何异常都不能影响收尾
        logger.debug("[Accept] 验收任务异常（已吞）", exc_info=True)


async def _backfill_plan_gate(
    *,
    scope: dict[str, Any],
    verdict: str,
) -> None:
    """把同轮判档行回填 outcome=hit|miss、rating=verdict。

    命中率只在这一处产生：判档行写出来时 outcome=pending，验收判完
    才知道那次判档对不对。**弃权不回填**——判官没判就没有对错，
    记成 miss 会把命中率永久污染。回填失败静默（台账是旁路）。
    """
    if verdict == "abstain":
        return
    chat_id = str(scope.get("chat_id") or "")
    turn = int(scope.get("turn") or 0)
    if not chat_id or turn <= 0:
        return
    try:
        await asyncio.to_thread(_backfill_sync, chat_id, turn, verdict)
    except Exception:  # pragma: no cover
        logger.debug("[Accept] 回填判档行失败（已吞）", exc_info=True)


def _backfill_sync(chat_id: str, turn: int, verdict: str) -> None:
    from sqlalchemy import text

    from coapis.foundation.db.engine import get_session

    hit = verdict in ("satisfied", "partial")
    outcome = "hit" if hit else "miss"
    # rating 列是整数（1=判档与交付对得上，0=对不上）
    sql = text(
        "UPDATE decision_events SET outcome = :outcome, rating = :rating "
        "WHERE chat_id = :chat_id AND source = 'plan_gate' AND turn = :turn "
        "AND outcome = 'pending'",
    )
    with get_session() as session:
        session.execute(
            sql,
            {"outcome": outcome, "rating": 1 if hit else 0,
             "chat_id": chat_id, "turn": turn},
        )


def _load_obj(text: str) -> dict[str, Any] | None:
    """从判官输出里取 JSON 对象（剥代码围栏 + 取第一个花括号块）。"""
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
