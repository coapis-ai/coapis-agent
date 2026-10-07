# -*- coding: utf-8 -*-
"""Timeline digest — 被动桥接：记忆台账 → 聊天上下文（批次 1）。

将用户近期的记忆时间线信号渲染为紧凑文本块，追加到系统提示词中，
让智能体"被动感知"最近发生过的决策/事实/待办/纠偏，而不必主动检索。

设计原则（与方案文档一致）：
- 纯只读，零副作用；
- 优雅降级：无数据 / 任何异常 → 返回 ""，调用方视为"跳过注入"；
- 长度封顶（默认 600 字符），防止撑爆系统提示词；
- user_id 采用 username 字符串命名空间（与 crons/manager.py 写入侧一致）。
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List

logger = logging.getLogger(__name__)

DEFAULT_HOURS = 72          # D1 拍板：72 小时摘要窗口
DEFAULT_LIMIT = 30          # 最多纳入的信号条数
MAX_DIGEST_CHARS = 600      # D1 拍板：600 字符上限

_SIGNAL_LABELS: Dict[str, str] = {
    "decision": "决策",
    "fact": "事实",
    "todo": "待办",
    "correction": "纠偏",
}


def build_timeline_digest(
    *,
    user_id: Any,
    hours: int = DEFAULT_HOURS,
    limit: int = DEFAULT_LIMIT,
    max_chars: int = MAX_DIGEST_CHARS,
) -> str:
    """渲染用户近期记忆时间线的紧凑摘要。

    Args:
        user_id: username 字符串（兼容传入数字 ID 的情形，统一 str() 归一）。
        hours: 回溯窗口（小时）。
        limit: 最大条数。
        max_chars: 输出字符上限。

    Returns:
        形如 ``[近期记忆台账] …`` 的多行文本；无可注入内容时返回 ``""``。
    """
    if not user_id:
        return ""
    try:
        from .repository_factory import RepositoryFactory

        repo = RepositoryFactory.get_memory_timeline_repository()
        rows: List[Dict[str, Any]] = repo.recent(
            user_id=str(user_id), hours=int(hours), limit=int(limit)
        )
    except Exception as exc:  # pragma: no cover - 防御性降级
        logger.debug("Timeline digest unavailable: %s", exc)
        return ""

    if not rows:
        return ""

    lines = [
        f"[近期记忆台账] 近{hours}小时内 {len(rows)} 条信号"
        f"（可用 memory_search 主动检索更多）:"
    ]
    for row in rows:
        content = (row.get("content") or "").strip().replace("\n", " ")
        if not content:
            continue
        label = _SIGNAL_LABELS.get(
            row.get("signal_type") or "", row.get("signal_type") or ""
        )
        importance = row.get("importance")
        star = "★" if isinstance(importance, (int, float)) and importance >= 0.8 else ""
        prefix = f"[{label}] " if label else ""
        lines.append(f"- {prefix}{star}{content}")

    if len(lines) == 1:
        return ""

    block = "\n".join(lines)
    if len(block) > max_chars:
        block = block[:max_chars].rstrip() + "…"
    return block
