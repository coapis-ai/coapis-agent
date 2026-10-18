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

# 材料块标题（注入侧与展示侧共用同一 token）
KB_HINT_TOKEN = "[知识库引用材料]"

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
    )
    """,
    re.VERBOSE,
)

# 材料块内的编号指令行（"1. 不要复述…"）
_NUMBERED_INSTRUCTION_RE = re.compile(r"^\s*\d+\.\s*(?:不要|勿|请|若|材料|采纳)")


def _line_is_leak(line: str) -> bool:
    if _LEAK_LINE_RE.match(line):
        return True
    # 材料块内的编号指令行只在「已进入块」时判定，避免误杀正常编号列表
    return bool(_NUMBERED_INSTRUCTION_RE.match(line))


def strip_kb_hint_leak(text: str) -> str:
    """清理整段文本里被复述的材料块（用于完成态消息与落库内容）。"""
    if not text or KB_HINT_TOKEN not in text and "来源知识库" not in text:
        return text
    state = {"in_block": False}
    out = []
    for line in text.split("\n"):
        keep, state = _feed_line(line, state)
        if keep:
            out.append(line)
    cleaned = "\n".join(out).strip("\n")
    return cleaned


def _feed_line(line: str, state: dict) -> tuple[bool, dict]:
    """逐行状态机：命中材料行则进入抑制态，遇到正常内容行退出。

    返回 (是否保留, 新状态)。空行在抑制态内一并吞掉（材料块内的分隔行）。
    """
    in_block = state.get("in_block", False)
    if in_block:
        if not line.strip():
            return False, state
        if _line_is_leak(line):
            return False, state
        # 材料块结束：本行是正常内容
        state = dict(state, in_block=False)
    if _line_is_leak(line):
        return False, dict(state, in_block=True)
    return True, state


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
            keep, self._state = _feed_line(line, self._state)
            if keep:
                emit.append(line)
        return "\n".join(emit) + ("\n" if emit and "\n" in chunk else "")

    def flush(self) -> str:
        """收尾：处理缓冲区里最后一行（无换行结尾）。"""
        if not self._buf:
            return ""
        line, self._buf = self._buf, ""
        keep, self._state = _feed_line(line, self._state)
        return line if keep else ""
