# coding: utf-8
"""计划审查岗——计划生成之后、开始执行之前的那道「看一眼」。
================================================================

判断中枢五岗里唯一**不看难度、只看计划本身**的岗。判档岗（plan_gate）在计划
之前判「这活多重」；本岗在计划之后判「这份计划做得下去吗」。

它卡的是 CoApis 最常见的一类失败：**计划看着齐，跑起来才发现没有终点**——
读完文档没有「交付」这一步、每步只有「分析一下」这种没法验收的描述、
用户要三件事而计划自设成一步。这类问题执行完再判（验收岗）只能事后记账，
在这里判还能当场改。

一期只做建议权（v15 §6.1）：
  * 岗不阻塞主链。计划变更钩子里 fire-and-forget 发一个后台任务，主链照常往下跑；
  * 判出 revise / replan → 把该怎么改写进记忆，下一轮推理时生效；
  * 判出 pass 或判不出 → 什么都不发生，主链感觉不到本岗存在（设计要求：
    判断不可用时过程中自动忽略）；
  * 台账写一行 ``source=plan_review``。

尺子在 :mod:`rubric`（``rubric_for("plan_review")``），本岗不私设标准。
规则先判：确定的结论不占模型额度；规则没把握才问模型，模型没有就弃权——
不猜。
"""
from __future__ import annotations

import asyncio
import json
import logging
import re
from typing import Any, Callable, Dict, List, Optional

from .config import DecisionHubConfig, get_hub_config
from .gateway import PURPOSE_PLAN_REVIEW
from .rubric import JSON_ONLY, rubric_for

logger = logging.getLogger("coapis.decision")

#: 台账 gate_source / 配置开关 / 熔断 key 三处共用同一个名字（复用 POSTS 词表）
POST = PURPOSE_PLAN_REVIEW

#: 发射即忘的任务集合（防 GC 掐掉未完成任务）
_pending: set[asyncio.Task] = set()

# ══════════════════════ 词表（确定性部分先判）══════════════════════════
#: 出现即视为「这一步没法单独验收」
VAGUE_WORDS = (
    "分析一下", "研究研究", "看看情况", "了解一下", "处理一下", "看一下",
    "总结一下相关", "相关信息", "相关资料", "等等", "诸如此类",
    "尽量", "尽可能多", "若干", "一些内容",
)
#: 出现即视为「用户明确要一份落在文件/输出里的东西」
#: （只收没有歧义的说法——规则误判比漏判更糟，宽泛的判断留给模型）
DELIVER_WORDS = (
    "保存到", "存成", "生成文件", "写入文件", "输出为", "落成文件",
    "save to", "write to", "生成一份文件",
)
#: 出现即视为「这一步真的会动手做点什么」
DOING_WORDS = (
    "查", "搜", "读", "写", "建", "改", "算", "跑", "调用", "执行", "整理",
    "汇总", "分析", "生成", "实现", "测试", "验证", "保存", "导出", "核对",
    "search", "read", "write", "build", "run", "test", "collect", "fetch",
)
#: 出现即视为「这本来就是直接回答，不需要计划」
CHITCHAT_WORDS = (
    "你好", "你是谁", "谢谢", "好的", "再见", "hi", "hello", "thanks",
)

#: 提示词前缀（进记忆，下一轮生效）
HINT_TAG = "<coapis-plan-review>"


# ══════════════════════ 开关 ══════════════════════════════════════════
def should_review(hub: Optional[DecisionHubConfig] = None) -> bool:
    """计划审查岗是否启用（默认开；``{post}_enabled=false`` 可单独关）。"""
    cfg = hub or get_hub_config()
    return cfg.post_enabled(POST)


# ══════════════════════ 取计划快照（纯读，不改计划）════════════════════
def collect(nb: Any) -> Optional[Dict[str, Any]]:
    """把计划摊成一份可判的快照。没有计划返回 None（本岗不存在）。

    只读不改——本岗没有改写权（一期只有建议权）。字段名与
    ``coapis/plan/hints.py`` 摊计划的那份对齐，避免出现第二套口径。
    """
    plan = getattr(nb, "current_plan", None)
    if plan is None:
        getter = getattr(nb, "get_plan", None)
        plan = getter() if callable(getter) else getattr(nb, "plan", None)
    if plan is None:
        return None
    raw_steps = list(getattr(plan, "subtasks", None) or [])
    goal = str(
        getattr(plan, "description", "") or getattr(plan, "name", "") or ""
    )
    steps: List[Dict[str, Any]] = []
    for i, st in enumerate(raw_steps, 1):
        steps.append({
            "idx": i,
            "name": str(getattr(st, "name", "") or ""),
            "outcome": str(
                getattr(st, "expected_outcome", "")
                or getattr(st, "outcome", "")
                or getattr(st, "description", "")
                or ""
            ),
            "state": str(getattr(st, "state", "") or "todo"),
        })
    if not steps:
        return None
    return {
        "goal": goal,
        "steps": steps,
        "step_count": len(steps),
        "in_progress": any(st["state"] != "todo" for st in steps),
    }


# ══════════════════════ 规则先判 ══════════════════════════════════════
def _hit(text: str, words) -> bool:
    low = text.lower()
    return any(w.lower() in low for w in words)


def review_rules(snap: Dict[str, Any]):
    """确定性结论。返回 ``(action, why, hint)``；没把握返回 None。

    只判四类一眼能看出的毛病，语义是否「对症」留给模型。
    """
    steps = snap.get("steps") or []
    goal = snap.get("goal") or ""
    count = int(snap.get("step_count") or 0)
    if not steps:
        return None

    def step_text(st: Dict[str, Any]) -> str:
        return f'{st.get("name") or ""} {st.get("outcome") or ""}'

    # 1) 用户要的是多件事，计划却自设成一步
    if count == 1 and not snap.get("in_progress"):
        multi = any(m in goal for m in ("并", "以及", "同时", "然后", "最后",
                                         "再", "之后", "并且"))
        if multi:
            return (
                "replan",
                "计划只有 1 步，但目标里写着多件事",
                "目标里是几件事就写几步，别把多件事压成一步后直接 finish。",
            )

    # 2) 整份计划其实是「直接回答用户」
    if count >= 1 and _hit(goal, CHITCHAT_WORDS) and len(goal) <= 24:
        return (
            "replan",
            "目标只是寒暄/一句话问答，不需要多步计划",
            "这类请求直接回答用户即可，把计划撤掉，别拆步骤。",
        )

    # 3) 有步骤没法单独验收
    vague = [st for st in steps if not st.get("outcome") or _hit(step_text(st), VAGUE_WORDS)]
    if vague:
        idx = "、".join(str(st["idx"]) for st in vague[:3])
        return (
            "revise",
            f'步骤 {idx} 没有可验收的产出描述',
            f'把步骤 {idx} 的「expected_outcome」写成能检查的结果：'
            "做完之后能看到什么、放在哪里。",
        )

    # 4) 用户要一个能检查的产出，计划里却没有一步真的动手
    if _hit(goal, DELIVER_WORDS) and not any(
        _hit(step_text(st), DOING_WORDS) for st in steps
    ):
        return (
            "replan",
            "计划里没有真正动手执行的步骤，产出落不到任何步骤上",
            "补上真正会动手的步骤（查/写/算/调用工具），"
            "并把要做出的东西挂到某一步的 expected_outcome 上。",
        )

    return None


def forced_rule(snap: Optional[Dict[str, Any]]):
    """模型不可用时的收口：规则有把握就用规则，没把握就**不判**（不猜）。"""
    rules = review_rules(snap) if snap else None
    if not rules:
        return None
    return {
        "action": rules[0],
        "why": rules[1],
        "hint": rules[2],
        "decided_by": "rule",
    }


# ══════════════════════ 提示文本（进记忆）════════════════════════════
def review_hint(result: Dict[str, Any]) -> str:
    """把结论写成给主链看的建议。没有要改的（pass/弃权）就不说话。"""
    action = str(result.get("action") or "")
    if action not in ("revise", "replan"):
        return ""
    why = str(result.get("why") or "")
    hint = str(result.get("hint") or "")
    head = "这份计划建议就地修改" if action == "revise" else "这份计划建议重新规划"
    lines = [
        f"{HINT_TAG} {head}（{why}）",
        f"该怎么改：{hint}",
        "只改计划，别改用户的要求；改完继续往下做。",
        "</coapis-plan-review>",
    ]
    return "\n".join(lines)


# ══════════════════════ 解析模型结论 ═════════════════════════════════
#: 台账 action 列的取值域
ACTIONS = ("pass", "revise", "replan", "abstain")

_JSON_START = re.compile(r"[{[]")


def _load_obj(text: str) -> Optional[Dict[str, Any]]:
    """从模型回答里抠出 JSON 对象（容忍前后废话与代码围栏）。"""
    if not text:
        return None
    body = text.strip()
    if body.startswith("```"):
        body = re.sub(r"^```[a-zA-Z]*\n?", "", body)
        body = body.rstrip("`").strip()
    match = _JSON_START.search(body)
    if not match:
        return None
    try:
        obj = json.loads(body[match.start():])
    except Exception:  # noqa: BLE001 模型话多了，按解析失败处理
        return None
    return obj if isinstance(obj, dict) else None


def _parse(text: str) -> Optional[Dict[str, Any]]:
    obj = _load_obj(text)
    if not obj:
        return None
    action = str(obj.get("action") or "").strip().lower()
    if action not in ACTIONS[:3]:
        return None
    return {
        "action": action,
        "why": str(obj.get("why") or "")[:200],
        "hint": str(obj.get("hint") or "")[:300],
        "decided_by": "model",
    }


def _describe(result: Any) -> str:
    """台账 judge_decision 列的写法。"""
    if not isinstance(result, dict):
        return "abstain"
    return f'{result.get("action") or "abstain"} {result.get("why") or ""}'.strip()


# ══════════════════════ 主入口（发射即忘）════════════════════════════
async def review_plan(
    nb: Any,
    *,
    scope: Optional[Dict[str, Any]] = None,
    hub: Optional[DecisionHubConfig] = None,
    skills: Optional[List[str]] = None,
    on_verdict: Optional[Callable[[Dict[str, Any]], Any]] = None,
) -> Optional[Dict[str, Any]]:
    """判一份刚生成的计划。返回结论 dict；不判/判不出返回 None。

    参数：
        nb: PlanNotebook（只读）。
        scope: ``{user_id, agent_id, chat_id, turn}``，台账作用域与轮内预算口径。
        hub: 配置（默认读环境变量）。
        on_verdict: 判出 revise/replan 时的回调（同步或 async）。**必须带**——
            软超时后的迟到真判只有这个回执能送回主链（验收岗 0 行的教训）。
    """
    cfg = hub or get_hub_config()
    if not cfg.post_enabled(POST):
        return None
    snap = collect(nb)
    if not snap:
        return None
    rules = review_rules(snap)

    user = _ask(snap)
    try:
        from .gateway import get_judge_gateway

        reply = await get_judge_gateway().judge(
            purpose=POST,
            system=rubric_for(POST, skills) + JSON_ONLY,
            user=user,
            parse=_parse,
            rule_fast=lambda: (
                None if rules is None else
                {"action": rules[0], "why": rules[1], "hint": rules[2],
                 "decided_by": "rule"}
            ),
            rule_fallback=lambda: forced_rule(snap),
            describe=_describe,
            hub=cfg,
            scope=dict(scope or {}),
            on_late_verdict=on_verdict,
        )
    except Exception as exc:  # noqa: BLE001 判断不可用不许影响主链
        logger.debug("[plan-review] 跳过：%s", exc)
        return None

    result = reply.value
    if not isinstance(result, dict) or result.get("action") not in ("revise", "replan"):
        return None
    if on_verdict is not None:
        try:
            out = on_verdict(result)
            if hasattr(out, "await"):
                await out
        except Exception:  # noqa: BLE001
            logger.debug("[plan-review] 提示回调异常（吞掉）", exc_info=True)
    return result


def _ask(snap: Dict[str, Any]) -> str:
    """给模型的提问：只给计划和目标，不给工具结果（那是验收岗的活）。"""
    lines = [f"目标：{snap.get('goal') or '（未写明）'}", "步骤："]
    for st in snap.get("steps") or []:
        lines.append(
            f'{st["idx"]}. {st.get("name") or "(无名)"} '
            f'| 产出：{st.get("outcome") or "(未写)"} '
            f'| 状态：{st.get("state") or "todo"}'
        )
    lines.append("请判这份计划：pass / revise / replan。")
    return "\n".join(lines)


def fire_plan_review(
    nb: Any,
    *,
    scope: Optional[Dict[str, Any]] = None,
    hub: Optional[DecisionHubConfig] = None,
    skills: Any = None,
    on_verdict: Optional[Callable[[Dict[str, Any]], Any]] = None,
) -> Optional[asyncio.Task]:
    """发射一次计划审查（不 await）。被闸门挡掉时返回 ``None``。

    主链只管把计划交出来继续往下跑；结论由 ``on_verdict`` 送回。
    """
    cfg = hub or get_hub_config()
    if not cfg.post_enabled(POST):
        return None
    if collect(nb) is None:
        return None
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        return None
    task = loop.create_task(
        review_plan(nb, scope=dict(scope or {}), hub=cfg,
                    skills=skills, on_verdict=on_verdict),
        name="coapis-plan-review",
    )
    _pending.add(task)
    task.add_done_callback(_pending.discard)
    return task


__all__ = [
    "POST",
    "should_review",
    "collect",
    "review_rules",
    "review_hint",
    "review_plan",
    "fire_plan_review",
]
