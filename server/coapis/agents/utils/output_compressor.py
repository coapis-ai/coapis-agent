# -*- coding: utf-8 -*-
# Copyright 2026 蜜蜂 & CoApis Contributors
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

"""Tool output compression utilities.

Provides tiered truncation for tool outputs to reduce context bloat
in the ReAct reasoning loop. Each tool can use the appropriate
compressor for its output type.
"""

from __future__ import annotations


# ── Default thresholds ──
_SHELL_MAX_CHARS = 4000       # Shell output: head 3000 + tail 1000
_SHELL_HEAD_CHARS = 3000
_FILE_MAX_LINES = 200         # read_file default max lines
_GREP_MAX_LINES = 200         # grep_search result max lines
_GREP_MAX_CHARS = 8000        # grep_search result max chars
_GENERIC_MAX_CHARS = 3000     # Generic tool output max chars


def compress_shell_output(text: str, max_chars: int = _SHELL_MAX_CHARS) -> str:
    """Compress shell command output with head+tail preservation.

    Strategy:
    - Short output (<= max_chars): return as-is
    - Long output: keep head (most recent/relevant) + tail (conclusion)
      with an omission notice showing how many chars were skipped.

    Args:
        text: Raw shell output string.
        max_chars: Maximum characters before truncation.

    Returns:
        Compressed output string.
    """
    if not text or len(text) <= max_chars:
        return text

    head = text[:_SHELL_HEAD_CHARS]
    tail = text[-(max_chars - _SHELL_HEAD_CHARS):]
    skipped = len(text) - max_chars

    return (
        f"{head}\n\n"
        f"[...省略 {skipped} 字符，原始长度 {len(text)} 字符...]\n\n"
        f"{tail}"
    )


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
