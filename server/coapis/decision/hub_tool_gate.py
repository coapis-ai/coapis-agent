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

# ─── v27 · 拍板 D2：确定性护栏扩充 ─────────────────────────────────────────
# Why: dev 七天台账实证——在线判官真判 22%、真判中位 4.2s、峰值 16.9s，撞在
#   15s 硬熔断上；而工具闸 7 天 101 行全部来自「规则命中」。结论很清楚：这一层
#   真正拦得住东西的是**规则**，不是模型。所以把护栏做成确定性的：零延迟、零
#   token、100% 可复现、可单测；模型只在规则没把握时补位（一期只提示不拦）。

#: 破坏性命令模式 ``(人话标签, 正则)``——命中即提示「先确认」，一期不拦。
#: 取值原则：只收「删了回不来」的动作。普通 ``rm file``、``ls``、``git status``
#: 一律不报，报多了提示就变成噪音（台账实测 60% 的行是 no_model 空转）。
_DANGER_RULES: tuple[tuple[str, str], ...] = (
    ("rm 递归/强制删除", r"\brm\b[^\n]*\s-\w*[rf]"),
    ("mkfs 格式化", r"\bmkfs(\.|\s)"),
    ("dd 直写设备", r"\bdd\b[^\n]*\bof="),
    ("fork 炸弹", r":\(\)\s*\{[^}]*\}\s*;\s*:"),
    ("删表/清表", r"\b(drop\s+(table|database)|truncate\s+table)\b"),
    ("git 强推覆盖远端", r"\bgit\b[^\n]*\bpush\b[^\n]*(--force\b|-f\b)"),
    ("git 硬重置", r"\bgit\b[^\n]*\breset\b[^\n]*--hard"),
    ("git 清空工作区", r"\bgit\b[^\n]*\bclean\b[^\n]*-[a-z]*f"),
    ("compose down 连数据卷删", r"docker\s+compose\s+down[^\n]*-v"),
    ("管道执行远程脚本", r"\b(curl|wget)\b[^\n]*\|\s*(ba|z)?sh\b"),
    ("关机/重启", r"\b(shutdown|reboot|poweroff)\b"),
    ("批量杀进程", r"\b(pkill|killall)\b"),
    ("递归改权限/777", r"\bchmod\b[^\n]*(-R\b|\b777\b)"),
    ("重定向写系统目录", r">\s*/(etc|boot|usr|bin|sbin|sys|proc|dev)/"),
)

#: 敏感写入路径 ``(人话标签, 正则)``——只收密钥/系统/容器编排这类越界目标。
#: 业务代码里的 ``token``/``secret`` 字样不算（那是正常开发，报了就是噪音）。
_SENSITIVE_RULES: tuple[tuple[str, str], ...] = (
    ("环境变量文件", r"(/|\")\.env(\.[\w.-]+)?\b"),
    ("密钥/证书文件", r"\.(pem|key|p12|pfx|jks)\b"),
    ("SSH 私钥/授权表", r"(id_rsa|id_ed25519|authorized_keys|\.ssh/)"),
    ("版本库内部对象", r"\.git/"),
    ("系统配置目录", r"(^|[\s\"'(])/etc/"),
    ("容器编排文件", r"docker-compose[\w.-]*\.ya?ml\b"),
)

#: 连续几次只读探查算「只读空转」（含本次）。低于这个数属正常调查，不报。
_READ_SPIN_HITS = 8

#: 本轮第几次动作后开始提醒收敛（工具闸单轮上限 12 次，见 react_agent）
_STEP_BUDGET_HINT = 10


def _match_rule(text: str, rules: tuple[tuple[str, str], ...]) -> str:
    """在参数摘要里找第一条命中的护栏模式，返回人话标签（没命中给空串）。"""
    for label, pattern in rules:
        try:
            if re.search(pattern, text, re.I):
                return label
        except re.error:  # pragma: no cover - 模式写错时的自保
            logger.debug("[工具闸] 护栏正则异常: %s", pattern, exc_info=True)
    return ""


def danger_label(digest: str) -> str:
    """破坏性命令识别（纯函数，给单测用）。

    Args:
        digest: 工具参数摘要（:func:`args_digest` 的形状）。

    Returns:
        命中的人话标签（如 ``"rm 递归/强制删除"``）；没命中给空串。
    """
    return _match_rule(str(digest or ""), _DANGER_RULES)


def sensitive_label(tool_name: str, digest: str) -> str:
    """敏感写入目标识别（纯函数，给单测用）。

    Args:
        tool_name: 工具名（只有 ``write_file``/``edit_file`` 会检）。
        digest: 参数摘要。

    Returns:
        命中的人话标签；没命中给空串。
    """
    if tool_name not in ("write_file", "edit_file"):
        return ""
    return _match_rule(str(digest or ""), _SENSITIVE_RULES)


def read_spin_hits(tool_name: str, recent: Sequence[tuple[str, str]]) -> int:
    """连续只读次数（含本次），算「只读空转」用（纯函数，给单测用）。

    Args:
        tool_name: 本次工具名。
        recent: 最近 ``(工具名, 摘要)`` 序列（时间顺序）。

    Returns:
        从本次往前数、连续落在 :data:`CHEAP_TOOLS` 里的次数。本次不是只读
        工具就是 0（说明已经在动手了，不算空转）。
    """
    if tool_name not in CHEAP_TOOLS:
        return 0
    hits = 1
    for name, _dig in reversed(list(recent or [])):
        if name in CHEAP_TOOLS:
            hits += 1
        else:
            break
    return hits

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

    六条规则，按把握从大到小排（v27 D2 扩充后全部零模型、零延迟、可单测）：
    ① 原地打转（同工具同参数连续第 3 次）② 破坏性命令（:data:`_DANGER_RULES`）
    ③ 越界写入敏感目标（:data:`_SENSITIVE_RULES`）④ 无目标动破坏性动作
    ⑤ 只读空转（连续 :data:`_READ_SPIN_HITS` 次只读）⑥ 预算护栏（本轮
    :data:`_STEP_BUDGET_HINT` 次动作后提醒收敛）。全部只提示不拦。

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
    # v27 D2：确定性护栏。顺序按「把握从大到小」——破坏性动作与越界写入是
    # 一眼能判的事，不该花 4 秒问一个真判率 22% 的模型。
    danger = danger_label(digest)
    if danger:
        return {
            "verdict": "reroute",
            "why": f"破坏性动作「{danger}」：先讲清目标与影响，确认后再动手",
            "tool": "",
        }
    sensitive = sensitive_label(tool_name, digest)
    if sensitive:
        return {
            "verdict": "reroute",
            "why": f"写入敏感目标「{sensitive}」：越界改动前先确认归属与影响",
            "tool": "",
        }
    if tool_name in _LOUD_TOOLS and not str(goal or "").strip():
        return {
            "verdict": "reroute",
            "why": "没有明确目标就动破坏性动作",
            "tool": "",
        }
    spin = read_spin_hits(tool_name, recent)
    if spin >= _READ_SPIN_HITS:
        return {
            "verdict": "reroute",
            "why": f"连续 {spin} 次只读探查没有产出：收敛到动手改或给出结论",
            "tool": "",
        }
    steps = len(list(recent or [])) + 1
    if steps >= _STEP_BUDGET_HINT:
        return {
            "verdict": "reroute",
            "why": f"本轮已 {steps} 次动作（单轮上限 12），预算将尽：先交付结论再补细节",
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
