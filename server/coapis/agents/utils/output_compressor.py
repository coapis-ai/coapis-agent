# -*- coding: utf-8 -*-
# Copyright 2026 蜜蜂 & CoApis Contributors
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU Affero General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU Affero General Public License for more details.
#
# You should have received a copy of the GNU Affero General Public License
# along with this program.  If not, see <https://www.gnu.org/licenses/>.

"""Tool output compression utilities.

Provides tiered truncation for tool outputs to reduce context bloat
in the ReAct reasoning loop. Each tool can use the appropriate
compressor for its output type.

P3 智能压缩：超长输出不再简单 head+tail 截断，而是提取语义关键行
（ERROR/WARN/统计/结论）+ 头尾，让模型看到最有信息量的部分。
"""

from __future__ import annotations

import re


# ── Default thresholds ──
_SHELL_MAX_CHARS = 4000       # Shell output: head 3000 + tail 1000
_SHELL_HEAD_CHARS = 3000
_FILE_MAX_LINES = 200         # read_file default max lines
_GREP_MAX_LINES = 200         # grep_search result max lines
_GREP_MAX_CHARS = 8000        # grep_search result max chars
_GENERIC_MAX_CHARS = 3000     # Generic tool output max chars

# P3: 语义关键行模式（可扩展正则）
_KEY_LINE_PATTERNS = re.compile(
    r"(?:^|\n)"
    r"("
    r"(?:ERROR|FATAL|CRITICAL|SEVERE|error|fatal|critical)"
    r"|(?:WARNING|WARN|warning|warn)"
    r"|(?:FAILED|failed|FAILURE|failure|FAIL|fail)"
    r"|(?:Traceback|Exception|exception)"
    r"|(?:\d+\s*(?:error|warning|fail)\w*)"
    r"|(?:passed|failed|skipped)\s+\d+"
    r"|(?:Total|Summary|Result|result:)"
    r"|(?:Build|Test|Compile|Deploy)\s+(?:success|failed|complete|finished)"
    r")",
    re.IGNORECASE,
)
_KEY_LINE_MAX = 1500       # chars of extracted key lines
_KEY_LINE_MAX_LINES = 30   # max key lines to extract


def _extract_key_lines(text: str) -> str:
    """P3: Extract semantically important lines from long output.

    Scans for ERROR/WARN/FAIL/Traceback/statistics/conclusion lines
    so the model sees the most informative content, not just head+tail.
    """
    lines = text.split("\n")
    key_lines: list[str] = []
    for line in lines:
        if _KEY_LINE_PATTERNS.search(line):
            key_lines.append(line.strip())
            if len(key_lines) >= _KEY_LINE_MAX_LINES:
                break
    if not key_lines:
        return ""
    result = "\n".join(key_lines)
    return result[:_KEY_LINE_MAX]


def compress_shell_output(text: str, max_chars: int = _SHELL_MAX_CHARS) -> str:
    """Compress shell command output with key-line extraction + head+tail.

    Strategy (P3 智能压缩):
    - Short output (<= max_chars): return as-is
    - Long output: extract key lines (ERROR/WARN/stats/conclusions)
      + head + tail, with omission notice.

    Args:
        text: Raw shell output string.
        max_chars: Maximum characters before truncation.

    Returns:
        Compressed output string.
    """
    if not text or len(text) <= max_chars:
        return text

    # P3: 提取语义关键行
    key_lines = _extract_key_lines(text)

    # 分配预算：关键行 + 头 + 尾
    key_budget = len(key_lines) + 1 if key_lines else 0
    remaining = max_chars - key_budget
    head_budget = max(500, int(remaining * 0.65))
    tail_budget = max(200, remaining - head_budget)

    head = text[:head_budget]
    tail = text[-tail_budget:]
    skipped = len(text) - head_budget - tail_budget

    parts = [head]
    if key_lines:
        parts.append(f"\n\n[关键行]\n{key_lines}\n")
    parts.append(
        f"\n[...省略 {skipped} 字符，原始长度 {len(text)} 字符...]\n\n{tail}"
    )
    return "".join(parts)


def compress_file_content(
    text: str,
    max_lines: int = _FILE_MAX_LINES,
) -> str:
    """Compress file content with line-based truncation.

    Strategy:
    - Short file (<= max_lines): return as-is
    - Long file: keep first 80% + last 20% lines with omission notice.

    Args:
        text: File content string.
        max_lines: Maximum lines before truncation.

    Returns:
        Compressed file content.
    """
    if not text:
        return text

    lines = text.split('\n')
    if len(lines) <= max_lines:
        return text

    head_count = int(max_lines * 0.8)
    tail_count = max_lines - head_count

    head = '\n'.join(lines[:head_count])
    tail = '\n'.join(lines[-tail_count:])
    skipped_lines = len(lines) - max_lines

    return (
        f"{head}\n\n"
        f"[...省略 {skipped_lines} 行，原始共 {len(lines)} 行...]\n\n"
        f"{tail}"
    )


def compress_grep_results(
    text: str,
    max_lines: int = _GREP_MAX_LINES,
    max_chars: int = _GREP_MAX_CHARS,
) -> str:
    """Compress grep/search results.

    Strategy:
    - Apply both line limit and char limit.
    - Keep first N lines (most relevant matches).
    - Add omission notice with total match count if available.

    Args:
        text: Grep output string.
        max_lines: Maximum result lines.
        max_chars: Maximum characters.

    Returns:
        Compressed grep output.
    """
    if not text:
        return text

    # First apply char limit
    if len(text) > max_chars:
        text = text[:max_chars]
        text += f"\n\n[...输出超过 {max_chars} 字符，已截断...]"

    # Then apply line limit
    lines = text.split('\n')
    if len(lines) > max_lines:
        head = '\n'.join(lines[:max_lines])
        skipped = len(lines) - max_lines
        text = (
            f"{head}\n\n"
            f"[...省略 {skipped} 行结果，共 {len(lines)} 行匹配...]"
        )

    return text


def compress_generic_output(
    text: str,
    max_chars: int = _GENERIC_MAX_CHARS,
) -> str:
    """Compress generic tool output.

    Strategy:
    - Short output: return as-is.
    - Long output: keep head + omission notice.

    Args:
        text: Tool output string.
        max_chars: Maximum characters.

    Returns:
        Compressed output.
    """
    if not text or len(text) <= max_chars:
        return text

    head = text[:max_chars - 200]
    skipped = len(text) - (max_chars - 200)

    return f"{head}\n\n[...截断，原始长度 {len(text)} 字符，省略 {skipped} 字符...]"
