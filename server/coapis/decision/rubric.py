# -*- coding: utf-8 -*-
"""判则：判官要知道「什么算好」的标准（v14 §3.1）。

Why: 台账实证的头号缺陷是**判则不在 prompt**——判级请求里只有一句格式
指令（"回答一个词"），判官在猜标准，所以 88 行台账里 judgment 与 outcome
全是空，命中率无从计算。标准必须是随请求一起走的文本，判官照着判，
台账才可能记录「判了什么、判对没有」。

How: 三个岗位各一份内置判则（判档 / 验收 / 事中改道），全文随请求走。
工作区可用技能覆盖：技能名以 ``判则-`` 或 ``rubric-`` 开头的，其描述
追加在内置判则之后（上限 1200 字，防 prompt 被撑爆）。这样判则可被
检索、可被复用，且**零检索基建**——复用智能体已经拿在手里的技能摘要，
不新建任何索引。

规则先行（L0）能覆盖的判据写在 ``rule_level`` 里；判则文本是判官的
标准，不是规则的实现，两者刻意分开：规则改了要同步判则，判则改了
不影响规则。
"""
from __future__ import annotations

from typing import Any, Iterable, Sequence

#: 判档的取值域（台账 judgment 列就存这三个词）
LEVELS = ("simple", "medium", "complex")

#: 判档判则（环0 · 档位2 的 L2 判官用）
RUBRIC_LEVEL = """判档判则——按「要动几个知识单元、结果是否可逆、有无外部副作用」定档：
- simple：一句话能答完的事实/解释/换算，不需要读文件、不需要改任何东西。
  特征：答案唯一、不涉密、无副作用。
- medium：需要读 1~3 个已知对象（某文件/某记录/某配置），或做一处可逆修改，
  步骤可预先列出且不超过 5 步。
- complex：需要跨多个对象检索/对比/归纳，或要产出文档/方案/报告，
  或涉及不可逆动作（删除、发布、对外发送、改生产），或步骤数与所需
  信息在开头无法确定。
拿不准时**往低判**：档位升高只会增加成本，判低由事中改道兜底。
只答一个词：simple 或 medium 或 complex。"""

#: 验收判则（环4/5 · 需求满足度 + 越界 + 过度设计）
RUBRIC_ACCEPTANCE = """验收判则——对照「用户要的东西」看「这轮实际交付的东西」：
- satisfied：需求点都有着落，交付物就是用户要的那个（形态对了：要表格给表格、
  要文件给了文件路径、要结论给了结论）。
- partial：主需求有着落但有明确缺口（少一项、少一个维度、只给了方案没给落地）。
- failed：答非所问/空转/只说了要做什么没做/关键需求没碰。
同时判两件红线：
- overreach（越界）= 做了用户没要求的事，尤其动了用户没让动的文件、数据、
  外部系统、生产环境。
- overdesign（过度设计）= 交付里明显超出需求的部分：为「以后可能用到」加的
  抽象层/配置项/兼容分支、需求只要 1 步却铺了 5 步。
不要奖励长度，不要奖励计划；只看交付物与需求的对应关系。"""

#: 事中改道判则（环1 · 目标漂移三问）
RUBRIC_ADVICE = """改道判则——回答三问，给一个动作：
1. 目标变了没：用户在这几轮里有没有改变/追加要求，或推翻了先前的要求？
2. 达成了没：按现在的进度，按当前做法走下去能不能交付用户要的东西？
3. 手段偏了没：这几轮的动作是不是在解决用户的问题，还是在解决自己的问题
   （反复读同一个文件、反复试同一个失败路子、把范围扩到用户没提的东西）？
动作取值：
- continue：三问都没问题，继续按当前做法走。
- change：目标变了或手段偏了——指出**具体**要改成什么（一句话，可执行）。
- stop：继续做就是越界（要动用户没让动的东西），或已达成需求在重复劳动。
判 change/stop 必须给出证据（引用动作序号），不许凭感觉。
拿不准就 continue——改道提示每轮都在花钱。"""

#: 输出契约：判官必须吐 JSON，解析失败按弃权（台账记 abstain）
JSON_ONLY = "只输出一个 JSON 对象，不要 markdown 代码围栏，不要解释性文字。"

_RUBRIC_PREFIXES = ("判则", "rubric")
_OVERLAY_CAP = 1200


def rubric_for(purpose: str, skills: Sequence[Any] | None = None) -> str:
    """取某岗位的判则全文（内置 + 工作区技能覆盖）。

    Args:
        purpose: ``level`` / ``acceptance`` / ``advisor``。
        skills: 智能体手里已有的技能摘要（``SkillSummary`` 或任何带
            ``name``/``description`` 属性的对象，也接受 ``(name, desc)``
            元组与 ``dict``）。为 None 时只用内置判则。

    Returns:
        判则文本。技能覆盖以 ``【工作区判则·<技能名>】`` 分节追加，
        总长上限 ``_OVERLAY_CAP``，防 prompt 被撑爆。
    """
    base = {
        "level": RUBRIC_LEVEL,
        "acceptance": RUBRIC_ACCEPTANCE,
        "advisor": RUBRIC_ADVICE,
    }.get(purpose, "")
    if not skills:
        return base
    parts: list[str] = []
    used = 0
    for item in skills:
        name, desc = _name_desc(item)
        if not name:
            continue
        if not name.startswith(_RUBRIC_PREFIXES):
            continue
        if not desc:
            continue
        block = f"【工作区判则·{name}】{desc.strip()}"
        room = _OVERLAY_CAP - used
        if room <= 0:
            break
        block = block[:room]
        parts.append(block)
        used += len(block)
    if not parts:
        return base
    return base + "\n" + "\n".join(parts)


def _name_desc(item: Any) -> tuple[str, str]:
    """从任意形态的技能摘要里取 (name, description)。"""
    if isinstance(item, (tuple, list)) and len(item) >= 2:
        return str(item[0]), str(item[1])
    name = getattr(item, "name", None)
    desc = getattr(item, "description", None)
    if name is None and isinstance(item, dict):
        name = item.get("name")
        desc = item.get("description")
    return (str(name) if name else ""), (str(desc) if desc else "")


def rubric_names() -> Iterable[str]:
    """内置判则名（给台账/自检用）。"""
    return ("level", "acceptance", "advisor")


#: 判官系统提示模板——判则必须**随请求走**，不靠"它大概记得"（v14 §4.5）
RUBRIC_SYSTEM = (
    "你是 CoApis 判断中枢的判官。判断依据只有下面这份判则："
    "逐条对着判，不要发挥、不要解释、不要安慰、不要脑补用户没说的东西。\n\n"
    "{rubric}\n\n{json_only}"
)

#: 判则技能的名字前缀（技能目录名以这些开头即视为判则技能）
_RUBRIC_PREFIXES = ("判则-", "判则_", "rubric-", "rubric_")


def scan_skill_rubrics(skills_dir: Any) -> list[tuple[str, str]]:
    """扫工作区技能目录里的**判则技能**（目录名以 ``判则-``/``rubric-`` 开头）。

    判则做成技能是 v14 §4.5 的"零新基建"路子：技能本来就可检索、可复用、
    可按用户启停，判则挂进去就自动随请求走、自动被用户看见。
    目录读不到返回空——判则有内置兜底，不该因为技能目录炸掉一次判断。
    """
    out: list[tuple[str, str]] = []
    try:
        root = Path(str(skills_dir))
        if not root.is_dir():
            return out
        for child in sorted(root.iterdir()):
            md = child / "SKILL.md"
            if not md.is_file():
                continue
            lname = child.name.lower()
            if not any(p in lname for p in _RUBRIC_PREFIXES):
                continue
            try:
                out.append((child.name, md.read_text(encoding="utf-8")))
            except OSError:  # pragma: no cover - 单文件读不动就跳过
                continue
    except Exception:  # pragma: no cover - 技能目录异常不影响判断
        return []
    return out


def system_for(
    purpose: str,
    skills: Sequence[Any] | None = None,
    json_only: str = JSON_ONLY,
) -> str:
    """某岗位的**系统提示词** = 判则全文 + "只出 JSON" 尾巴。

    "判则随请求走"的落点：任何岗位的 LLM 判断都从这里取 system，判则因此
    只有一处定义、每轮都进 prompt、台账能回溯到同一把尺子。
    """
    return RUBRIC_SYSTEM.format(
        rubric=rubric_for(purpose, skills), json_only=json_only,
    )
