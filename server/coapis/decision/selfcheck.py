# -*- coding: utf-8 -*-
"""自检验收（v27 · 拍板 D3）——判官不在岗时，让本轮主模型按同一张清单自评。

Why（为什么要有这条）:
    dev 七天台账实测：判官槽位空、验收 0 行真判、outcome 100% 停在 pending。
    验收回填链（:func:`coapis.decision.hub_acceptance._backfill_plan_gate`）
    只在判官真判时才跑，判官一离线，「本轮算不算交付」在台账里就是空白——
    档位命中率、目标达成率这些数字全部读不出来，优化没有尺子。

What（这条做什么）:
    回合结束、判官不在岗时，用**本轮的会话模型**按验收判则
    （:func:`coapis.decision.rubric.rubric_for` 的 acceptance 节，与判官同一张
    清单）自评三条红线，结论做两件事：① 写一行 ``source=selfcheck`` 的台账；
    ② 用同一套 hit/miss 口径回填本轮档位行。

Boundaries（这条不做什么——比做什么重要）:
    * 不拦动作、不加动作、不改回答：自评只是记账。判官有「建议权」，自评连建议权
      都没有——让模型给自己的作业打分再据此改道，等于把考官换成考生本人。
    * 判官在岗时不抢话：调用方（``react_agent``）只在判官槽位空时才发射本模块。
    * 不进主链：轮尾 fire-and-forget，超时即弃，不占主链时间、不占判官轮内预算。
    * 台账单独一列来源（``selfcheck``），看板能把「自己给自己打分」与「判官外部
      验收」分开统计。混在一起算命中率 = 自欺。

台账口径:
    cost 用 :func:`coapis.decision.gateway._cost_of` 按模型计价；取不到价就是 0，
    由台账契约标 ``usage_missing``——自评消耗的是会话模型的 token，记账要如实，
    别把「没计价」写成「没花钱」。
"""
from __future__ import annotations

import asyncio
import json
import logging
import re
from typing import Any, Callable, Optional, Sequence

from .ledger_contract import write_ledger
from .rubric import JSON_ONLY, rubric_for

logger = logging.getLogger(__name__)

#: 自评可用的结论（与验收口径同源，别造第四种说法）
VERDICTS = ("satisfied", "partial", "failed")

#: 自评用的角色设定。与验收判则同一段开头，只把「判官」换成「考生本人自评」——
#: 清单是同一张，身份必须说清，否则模型会按考官口吻替被验收者补做、补解释。
_SELFCHECK_SYS = (
    "你在验收一轮已完成的工作，做**自评**：考生本人按考官给的同一张清单逐条核对，"
    "目的不是给自己脸上贴金，是让后续优化有一把能用的尺子。\n"
    "规则：① 三条红线逐条判，有一条不满足就不能给 satisfied；"
    "② 只依据材料里的用户目标与交付文本，不许替被验收者补做、补解释；"
    "③ 证据不足判 partial，并在 reason/missing 里写清缺什么，不要猜；"
    "④ 严按 JSON 形状输出，不要解释、不要代码块围栏。\n"
)

#: 在跑的自评任务（fire-and-forget 任务必须持强引用，防 GC 中途回收）
_pending: set[asyncio.Task] = set()


def build_prompt(
    *,
    query: str,
    answer: str,
    skills: Sequence[Any] | None = None,
    cap: int = 4000,
) -> str:
    """自评提示词：与验收同一张判则、同一个 JSON 形状（同一把尺子）。

    Args:
        query: 用户目标（本轮输入）。
        answer: 本轮交付文本（智能体的回答）。
        skills: 技能摘要（工作区判则可覆盖内置判则）。
        cap: 交付文本喂入上限（字），沿用验收的 ``acceptance_max_chars``。

    Returns:
        给模型的 user 消息文本。
    """
    return (
        "用户的这轮要求：\n"
        f"{str(query or '（无）')[:1200]}\n\n"
        "智能体这轮的交付：\n"
        f"{str(answer or '')[:int(cap) if cap else 4000]}\n\n"
        f"{rubric_for('acceptance', skills)}\n\n"
        "输出 JSON：{\"verdict\":\"satisfied|partial|failed\","
        "\"overreach\":true/false,\"overdesign\":true/false,"
        "\"reason\":\"一句话（越界/过度设计要点出具体动作）\","
        "\"missing\":\"还缺什么，没有则空串\"}\n"
        + JSON_ONLY
    )


def parse_selfcheck(raw: str) -> dict[str, Any]:
    """把模型返回文本解析成自评结论。

    Args:
        raw: 模型返回文本（含围栏也认）。

    Returns:
        ``{"verdict","overreach","overdesign","reason","missing"}``。

    Raises:
        ValueError: 形状不对、verdict 取值不在口径内。
    """
    txt = str(raw or "").strip()
    if not txt:
        raise ValueError("空返回")
    m = re.search(r"\{.*\}", txt, re.S)
    if not m:
        raise ValueError("返回里没有 JSON 对象")
    obj = json.loads(m.group(0))
    if not isinstance(obj, dict):
        raise ValueError("返回不是 JSON 对象")
    verdict = str(obj.get("verdict") or "").strip().lower()
    if verdict not in VERDICTS:
        raise ValueError(f"verdict 取值不对：{verdict!r}")
    return {
        "verdict": verdict,
        "overreach": bool(obj.get("overreach")),
        "overdesign": bool(obj.get("overdesign")),
        "reason": str(obj.get("reason") or "")[:200],
        "missing": str(obj.get("missing") or "")[:200],
    }


def _label_of(model: Any) -> str:
    """模型标签（台账用）：取模型自己的名字，取不到就说 unknown。"""
    for attr in ("model_name", "model"):
        val = getattr(model, attr, None)
        if val:
            return str(val)[:64]
    inner = getattr(model, "_model", None)
    for attr in ("model_name", "model"):
        val = getattr(inner, attr, None)
        if val:
            return str(val)[:64]
    return f"unknown:{type(model).__name__}"[:64]


async def judge_selfcheck(
    *,
    query: str,
    answer: str,
    model: Any,
    scope: Optional[dict],
    hub: Any = None,
    skills: Sequence[Any] | None = None,
) -> Optional[dict[str, Any]]:
    """主模型自评一轮交付（**永不抛异常**；判不出返回 None）。

    Args:
        query: 用户目标。
        answer: 本轮交付文本。
        model: 本轮在用的会话模型（agentscope ChatModelBase 兼容形状）。
        scope: 台账身份（``user_id/agent_id/chat_id/turn``）。
        hub: 判断中枢配置（None 时读环境变量）。
        skills: 技能摘要（判则技能可覆盖内置判则）。

    Returns:
        ``{"verdict","reason","tokens","latency_ms"}``；熄火/失败返回 None。
    """
    try:
        from .config import get_hub_config

        cfg = hub if hub is not None else get_hub_config()
        if cfg is None or not getattr(cfg, "selfcheck_enabled", False):
            return None
        if not cfg.post_enabled("acceptance"):
            return None
        ans = str(answer or "").strip()
        if len(ans) < int(getattr(cfg, "selfcheck_min_answer_chars", 80)):
            return None
        if model is None:
            return None

        from .gateway import _is_stream, _text_of, _usage_of

        kwargs = {
            "temperature": 0.0,
            "max_tokens": 400,
            "extra_body": {"chat_template_kwargs": {"enable_thinking": False}},
        }
        messages = [
            {"role": "system", "content": _SELFCHECK_SYS + JSON_ONLY},
            {
                "role": "user",
                "content": build_prompt(
                    query=query,
                    answer=ans,
                    skills=skills,
                    cap=int(getattr(cfg, "acceptance_max_chars", 4000)),
                ),
            },
        ]
        t0 = asyncio.get_running_loop().time()
        res = await asyncio.wait_for(
            model(messages, **kwargs),
            timeout=max(int(getattr(cfg, "selfcheck_timeout_ms", 20000)), 2000) / 1000.0,
        )
        if _is_stream(res):
            chunks = []
            async for c in res:
                chunks.append(c)
            res = chunks[-1] if chunks else None
            raw = _text_of(res) if res is not None else ""
        else:
            raw = _text_of(res)
        latency_ms = int((asyncio.get_running_loop().time() - t0) * 1000)
        tin, tout = _usage_of(res)

        try:
            parsed = parse_selfcheck(raw)
        except (ValueError, json.JSONDecodeError):
            # 自评判不出就留空：写一行垃圾自评比不写更坏（它会回填出假档位）。
            logger.debug("[自评] 解析失败 raw=%s", str(raw)[:120])
            return None

        label = _label_of(model)
        # 台账 value 与验收行同形（档位|越界|过度设计|理由|缺口），看板一把尺子
        # 就能读两边；截 256 字是台账契约的 value 上限。
        value = (
            f"{parsed['verdict']}|{parsed['overreach']}|{parsed['overdesign']}"
            f"|{parsed['reason']}|{parsed['missing']}"
        )[:256]
        cost = _cost_of_safe(label, tin, tout)
        write_ledger(
            source="selfcheck",
            purpose="selfcheck",
            action=f"selfcheck:{parsed['verdict']}",
            hit_layer="llm",
            model=label,
            latency_ms=latency_ms,
            tokens=tin + tout,
            cost=cost,
            value=value,
            outcome=parsed["verdict"],
            scope=scope,
        )
        # 回填档位：与判官验收走同一条通路（同一把尺子，两个来源）。
        # 必须是 await——`_backfill_plan_gate` 是协程，取函数不 await 等于
        # 什么都没做（协程对象被丢弃，档位继续卡 pending）。
        try:
            from .hub_acceptance import _backfill_plan_gate

            await _backfill_plan_gate(scope=scope, verdict=parsed["verdict"])
        except Exception:  # noqa: BLE001
            logger.debug("[自评] 档位回填失败", exc_info=True)
        return {
            "verdict": parsed["verdict"],
            "reason": parsed["reason"],
            "tokens": tin + tout,
            "latency_ms": latency_ms,
        }
    except asyncio.TimeoutError:
        logger.debug("[自评] 超时熄火（不拖主链）")
        return None
    except asyncio.CancelledError:
        raise
    except Exception:  # noqa: BLE001 - 自评绝不影响主链
        logger.debug("[自评] 判断失败（不影响主链）", exc_info=True)
        return None


def _cost_of_safe(model_label: str, tin: int, tout: int) -> float:
    """按模型计价；取不到价格表就返回 0（台账契约会标 usage_missing）。"""
    try:
        from .gateway import _cost_of

        return float(_cost_of(model_label, tin, tout))
    except Exception:  # noqa: BLE001
        return 0.0


def fire_selfcheck(
    *,
    query: str,
    answer: str,
    model: Any,
    scope: Optional[dict],
    hub: Any = None,
    skills: Sequence[Any] | None = None,
    on_done: Optional[Callable[[Any], Any]] = None,
) -> Optional[asyncio.Task]:
    """发射一轮自评（fire-and-forget；主链零占用）。

    Args:
        query/answer/model/scope/hub/skills: 见 :func:`judge_selfcheck`。
        on_done: 自评完成后的回调（同步或 async），收结论。

    Returns:
        任务对象；发射失败返回 None。
    """
    try:
        task = asyncio.create_task(
            judge_selfcheck(
                query=query,
                answer=answer,
                model=model,
                scope=scope,
                hub=hub,
                skills=skills,
            ),
            name="coapis_selfcheck",
        )
        _pending.add(task)

        def _done(tk: asyncio.Task) -> None:
            _pending.discard(tk)
            if tk.cancelled():
                return
            try:
                res = tk.result()
            except Exception:  # noqa: BLE001
                logger.debug("[自评] 任务异常", exc_info=True)
                return
            if res is None or on_done is None:
                return
            try:
                out = on_done(res)
                if asyncio.iscoroutine(out):
                    t2 = asyncio.create_task(out)
                    _pending.add(t2)
                    t2.add_done_callback(lambda x: _pending.discard(x))
            except Exception:  # noqa: BLE001
                logger.debug("[自评] 回调失败", exc_info=True)

        task.add_done_callback(_done)
        return task
    except Exception:  # noqa: BLE001
        logger.debug("[自评] 发射失败（不影响主链）", exc_info=True)
        return None
