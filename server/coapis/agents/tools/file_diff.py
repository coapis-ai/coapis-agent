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

"""File diff tool — compare two files or a file against its last checkpoint."""

from __future__ import annotations

import difflib
import logging
from pathlib import Path
from typing import Any

from .registry import register_tool

logger = logging.getLogger(__name__)

_MAX_OUTPUT = 8000  # Truncate output beyond this many chars


def _resolve(path_str: str) -> Path | None:
    """Resolve a file path relative to workspace."""
    p = Path(path_str.strip())
    if p.is_absolute() and p.exists():
        return p
    try:
        from ...config.context import get_current_workspace_dir
        ws = get_current_workspace_dir()
        if ws:
            resolved = Path(ws) / p
            if resolved.exists():
                return resolved
    except Exception:
        pass
    # Fallback: try cwd
    import os
    resolved = Path(os.getcwd()) / p
    if resolved.exists():
        return resolved
    return None


def _read_lines(path: Path) -> list[str]:
    """Read file as lines."""
    try:
        return path.read_text(encoding="utf-8", errors="replace").splitlines(keepends=True)
    except Exception:
        return []


def _format_unified_diff(
    lines_a: list[str],
    lines_b: list[str],
    name_a: str,
    name_b: str,
    context_lines: int = 3,
) -> str:
    """Generate unified diff output."""
    diff = difflib.unified_diff(
        lines_a,
        lines_b,
        fromfile=name_a,
        tofile=name_b,
        n=context_lines,
    )
    return "".join(diff)


def _format_side_by_side(
    lines_a: list[str],
    lines_b: list[str],
    width: int = 80,
) -> str:
    """Generate side-by-side diff (truncated for readability)."""
    half = width // 2 - 2
    output = []
    matcher = difflib.SequenceMatcher(None, lines_a, lines_b)
    for tag, i1, i2, j1, j2 in matcher.get_opcodes():
        if tag == "equal":
            for line in lines_a[i1:i2]:
                output.append(f"  {line.rstrip()[:width-2]}")
        elif tag == "replace":
            for a, b in zip(lines_a[i1:i2], lines_b[j1:j2]):
                output.append(f"- {a.rstrip()[:half]}")
                output.append(f"+ {b.rstrip()[:half]}")
            # Handle unequal lengths
            for line in lines_a[i2 - (i2-i1) + min(i2-i1, j2-j1):i2]:
                output.append(f"- {line.rstrip()[:half]}")
            for line in lines_b[j2 - (j2-j1) + min(i2-i1, j2-j1):j2]:
                output.append(f"+ {line.rstrip()[:half]}")
        elif tag == "delete":
            for line in lines_a[i1:i2]:
                output.append(f"- {line.rstrip()[:half]}")
        elif tag == "insert":
            for line in lines_b[j1:j2]:
                output.append(f"+ {line.rstrip()[:half]}")
    return "\n".join(output)


async def file_diff(
    file_a: str = "",
    file_b: str = "",
    context: int = 3,
    mode: str = "unified",
) -> dict[str, Any]:
    """文件差异对比。

    支持两种模式：
    - unified: 标准 unified diff 格式（适合 patch/review）
    - side_by_side: 并排对比格式（适合可视化对比）

    Args:
        file_a: 第一个文件路径（基准文件）
        file_b: 第二个文件路径（对比文件）
        context: 上下文行数，默认 3
        mode: 对比模式 (unified/side_by_side)，默认 unified

    Returns:
        差异结果
    """
    if not file_a.strip() or not file_b.strip():
        return {"error": "需要提供两个文件路径 (file_a 和 file_b)"}

    path_a = _resolve(file_a)
    path_b = _resolve(file_b)

    if not path_a:
        return {"error": f"文件不存在: {file_a.strip()}"}
    if not path_b:
        return {"error": f"文件不存在: {file_b.strip()}"}

    lines_a = _read_lines(path_a)
    lines_b = _read_lines(path_b)

    # Generate diff
    name_a = path_a.name
    name_b = path_b.name

    if mode == "side_by_side":
        diff_text = _format_side_by_side(lines_a, lines_b)
    else:
        diff_text = _format_unified_diff(lines_a, lines_b, name_a, name_b, context)

    if not diff_text.strip():
        return {
            "message": "两个文件内容完全相同",
            "file_a": str(path_a),
            "file_b": str(path_b),
            "lines_a": len(lines_a),
            "lines_b": len(lines_b),
            "diff": "",
        }

    # Truncate if too long
    truncated = False
    if len(diff_text) > _MAX_OUTPUT:
        diff_text = diff_text[:_MAX_OUTPUT]
        truncated = True

    # Stats
    added = sum(1 for line in diff_text.split("\n") if line.startswith("+") and not line.startswith("+++"))
    removed = sum(1 for line in diff_text.split("\n") if line.startswith("-") and not line.startswith("---"))

    return {
        "message": f"📝 差异对比: {name_a} vs {name_b}",
        "diff": diff_text,
        "file_a": str(path_a),
        "file_b": str(path_b),
        "lines_a": len(lines_a),
        "lines_b": len(lines_b),
        "added": added,
        "removed": removed,
        "truncated": truncated,
        "mode": mode,
    }
