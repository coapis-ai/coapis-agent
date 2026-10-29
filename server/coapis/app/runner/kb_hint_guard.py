# -*- coding: utf-8 -*-
"""知识库引用材料「复述泄漏」过滤器。

背景：聊天勾选知识库后，检索材料以 system 消息注入给智能体。部分模型
（尤其本地小模型）会把这段材料原样复述进可见回答，用户看到
「[知识库引用材料] 1. 《紫晶.md》…」这类内部提示语，体验与信息密度都被破坏。

对策（两层）：
1. 注入侧（企业版插件）在材料块里显式下达「禁止复述本块说明」的指令；
2. 本模块在输出侧兜底：流式逐行识别并抑制被复述的材料块，
   完成态消息里也做一次清理，保证可见输出与落库历史都不含提示语。

判定口径：只认材料块特有的行形（方括号标题 / 「来源知识库：」/
「N. 《标题》：」/ 「【N】来源：」/「硬性要求：」），
普通回答里的编号列表不会被误杀（缺少《》与冒号即不匹配）。
"""
from __future__ import annotations

import re
from contextvars import ContextVar

# 材料块标题（注入侧与展示侧共用同一 token）
KB_HINT_TOKEN = "[知识库引用材料]"

# 本轮是否开启「模型自述行」剔除。默认关闭 —— 没有注入知识库材料时，
# 回答里出现"我需要……"多半是正常表述，不该被吃掉。
#
# 载体必须是可变对象：开关由 query_handler（异步生成器）置位，由外层
# stream_query 消费。协程在创建时捕获自己的 context 副本，生成器内部
# 的 contextvar.set 不会向外传播 —— 直接传 bool 外层永远看不到。放进
# dict 里就地改写，外层读同一个 dict 对象即可见。
kb_self_talk: ContextVar[bool] = ContextVar("kb_self_talk", default=False)
kb_turn_state: ContextVar[dict | None] = ContextVar("kb_turn_state", default=None)


def begin_kb_turn() -> dict:
    """流开始时建立本轮开关载体，返回该载体供外层轮询。"""
    holder: dict = {"self_talk": False}
    kb_turn_state.set(holder)
    return holder


def enable_self_talk() -> None:
    """拿到本轮引用材料后置位；就地改写载体，外层可见。"""
    holder = kb_turn_state.get()
    if holder is not None:
        holder["self_talk"] = True


def self_talk_enabled() -> bool:
    """当前是否应剔除自述行。"""
    holder = kb_turn_state.get()
    if holder is not None:
        return bool(holder.get("self_talk"))
    return kb_self_talk.get()

# 单行「疑似被复述的材料行」特征
_LEAK_LINE_RE = re.compile(
    r"""^\s*
    (?:
        \[知识库引用材料\]
      | 以下(?:片段|内容|材料)?(?:是)?(?:从|来自)?[^。\n]{0,40}知识库
      | 硬性要求\s*[:：]?
      | 来源知识库\s*[:：]
      | 请(?:严格|仅|务必)?[^。\n]{0,40}知识库
      | \d+\.\s*《[^》]+》\s*[:：]
      | 【\d+】\s*来源\s*[:：]
      | (?:不要|勿)复述[^。\n]{0,40}(?:本块|材料|说明)
      | 若片段与当前问题无关
      | 回答末尾标注来源
      | (?:根据|依据|按照|从)[^。\n]{0,12}(?:你|您)?(?:勾选|选中|勾选过|选取|选择)
        [^。\n]{0,20}知识库
      | (?:你|您)(?:的)?(?:勾选|选中|选取|选择)的[^。\n]{0,20}知识库
      | 相关度[^。\n]{0,12}\d+\s*%
      | (?:匹配|命中)度[^。\n]{0,12}\d+\s*%
      | 检索(?:到|到之|所得)[^。\n]{0,20}材料
    )
    """,
    re.VERBOSE,
)

# 材料块内的编号指令行（"1. 不要复述…"）
_NUMBERED_INSTRUCTION_RE = re.compile(r"^\s*\d+\.\s*(?:不要|勿|请|若|材料|采纳)")


# 模型自述行：把"我打算怎么回答"的思考过程写进正文，用户读到的是
# "我应该简洁明了地回答这个问题。""用户问的是……""让我基于知识库
# 内容回答" —— 这类句子不携带任何信息，纯占位，且让回答显得啰嗦割裂。
#
# 口径收紧在「主语是模型自己 + 动词是回答/整理类」：
#   * "你应该提前预订" —— 主语是"你"，是给用户的建议，保留；
#   * "我们要考虑季节因素" —— 主语是"我们"且无回答类动词，保留；
#   * "我需要回答全域土地整治任务" —— 命中，剔除。
_SELF_TALK_RE = re.compile(
    r"""^\s*
    (?:
        (?:现在|接下来|首先|那么|好[，,]\s*)?\s*我(?:来|需要|应该|要|得|会|打算|先)
          \s*(?:回答|回复|说明|介绍|讲|梳理|整理|分析|判断|确认|查看|检索|基于
               |组织|给出|总结|列举|作答)
      | 我(?:应该|需要|得|要)(?:简洁|简明|直接|详细|认真|如实|简单|清楚)
      | 让(?:我|我们)[^。！？\n]{0,24}?(?:回答|梳理|整理|分析|看看|讲讲|说明|介绍|作答)
      | 用户(?:问|提到|说的|需要|想(?:了解|知道)|的(?:问题|需求|意思))
      | 这(?:个|道|条)(?:问题|提问|需求)(?:我|这里|中)
      | 我(?:刚刚|刚才|刚刚已经|已经|之前)(?:已经)?(?:回答|回复|说过|讲过|提到)
      | 根据(?:你|您)?(?:的)?知识库
      | (?:从|在)知识库(?:中|里|内)
      | 知识库(?:中|里|内)的(?:材料|资料|内容|信息)
    )
    """,
    re.VERBOSE,
)


# 句子边界：中文句末标点。模型常把自述与正文写在同一行（不换行），
# 整行丢弃会连带正文一起丢，因此自述按句剔除，提示词泄漏按行剔除。
_SENT_SPLIT_RE = re.compile(r"(?<=[。！？；])")


def _strip_self_talk(line: str) -> str:
    """逐句剔除自述句，保留同行里的正文。"""
    parts = _SENT_SPLIT_RE.split(line)
    kept = [p for p in parts if p.strip() and not _SELF_TALK_RE.match(p.strip())]
    return "".join(kept)


def _line_is_leak(line: str, self_talk: bool | None = None) -> bool:
    if _LEAK_LINE_RE.match(line):
        return True
    # None = 跟随本轮开关（contextvar）；显式传值用于单测与非流式路径
    talk = self_talk_enabled() if self_talk is None else self_talk
    if talk and _SELF_TALK_RE.match(line):
        return True
    # 材料块内的编号指令行只在「已进入块」时判定，避免误杀正常编号列表
    return bool(_NUMBERED_INSTRUCTION_RE.match(line))


def strip_kb_hint_leak(text: str, self_talk: bool | None = None) -> str:
    """清理整段文本里被复述的材料块（用于完成态消息与落库内容）。"""
    if not text:
        return text
    talk = self_talk_enabled() if self_talk is None else self_talk
    if not talk and KB_HINT_TOKEN not in text and "来源知识库" not in text:
        return text
    state = {"in_block": False}
    out = []
    for line in text.split("\n"):
        kept, state = _feed_line(line, state, talk)
        if kept is not None:
            out.append(kept)
    cleaned = "\n".join(out).strip("\n")
    return cleaned


def _feed_line(line: str, state: dict, self_talk: bool | None = None) -> tuple[str | None, dict]:
    """逐行状态机：命中材料行则进入抑制态，遇到正常内容行退出。

    返回 (清洗后应展示的文本或 None, 新状态)。

    提示词泄漏按整行吞；模型自述按句剔除 —— 模型常把自述与正文写在
    同一行（不换行），整行丢弃会连带正文一起丢。
    """
    talk = kb_self_talk.get() if self_talk is None else self_talk

    def _clean(text: str) -> str | None:
        if not talk or not _SELF_TALK_RE.search(text):
            return text
        cleaned = _strip_self_talk(text)
        return cleaned if cleaned.strip() else None

    if state.get("in_block", False):
        if not line.strip():
            return None, state
        if _line_is_leak(line, False):
            return None, state
        # 材料块结束：本行是正常内容（自述句按句剔除后放行）
        return _clean(line), dict(state, in_block=False)
    if _line_is_leak(line, False):
        return None, dict(state, in_block=True)
    return _clean(line), state


class StreamLeakFilter:
    """流式文本过滤器（跨 delta 维护行缓冲与抑制态）。"""

    __slots__ = ("_state", "_buf")

    def __init__(self) -> None:
        self._state = {"in_block": False}
        self._buf = ""

    def feed(self, chunk: str) -> str:
        """喂入一个 delta 文本，返回可安全展示的片段。"""
        if not chunk:
            return ""
        self._buf += chunk
        emit = []
        while True:
            idx = self._buf.find("\n")
            if idx < 0:
                break
            line, self._buf = self._buf[:idx], self._buf[idx + 1:]
            kept, self._state = _feed_line(line, self._state)
            if kept is not None:
                emit.append(kept)
        return "\n".join(emit) + ("\n" if emit and "\n" in chunk else "")

    def flush(self) -> str:
        """收尾：处理缓冲区里最后一行（无换行结尾）。"""
        if not self._buf:
            return ""
        line, self._buf = self._buf, ""
        kept, self._state = _feed_line(line, self._state)
        return kept or ""
