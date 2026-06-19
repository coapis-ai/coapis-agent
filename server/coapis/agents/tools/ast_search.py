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

"""AST code search tool — syntax-level code pattern matching via ast-grep.

Unlike ``grep_search`` (text matching), ``ast_search`` understands code
structure: find all function definitions, match specific AST patterns,
locate call sites with particular arguments, etc.

Requires ``ast-grep`` CLI installed (``pip install ast-grep`` or system package).
"""

from __future__ import annotations

import json
import logging
import subprocess
from pathlib import Path
from typing import Any

from .registry import register_tool

logger = logging.getLogger(__name__)

# Supported languages (ast-grep short names)
SUPPORTED_LANGUAGES = frozenset({
    "python", "javascript", "typescript", "jsx", "tsx",
    "go", "rust", "java", "c", "cpp", "ruby",
    "swift", "kotlin", "scala", "php",
    "html", "css", "json", "yaml",
})

# Map common extensions to ast-grep language names
_EXT_TO_LANG = {
    ".py": "python",
    ".js": "javascript",
    ".jsx": "jsx",
    ".ts": "typescript",
    ".tsx": "tsx",
    ".go": "go",
    ".rs": "rust",
    ".java": "java",
    ".c": "c",
    ".cpp": "cpp",
    ".cc": "cpp",
    ".cxx": "cpp",
    ".h": "c",
    ".hpp": "cpp",
    ".rb": "ruby",
    ".swift": "swift",
    ".kt": "kotlin",
    ".scala": "scala",
    ".php": "php",
}


def _detect_language(file_path: str) -> str | None:
    """Detect language from file extension."""
    suffix = Path(file_path).suffix.lower()
    return _EXT_TO_LANG.get(suffix)


def _check_ast_grep() -> bool:
    """Check if ast-grep CLI is available."""
    try:
        result = subprocess.run(
            ["ast-grep", "--version"],
            capture_output=True, timeout=5,
        )
        return result.returncode == 0
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return False


@register_tool(
    name="ast_search",
    description="基于 AST 的语法级代码搜索。比 grep 更精准，能理解代码结构（函数定义、调用、参数等）。需要 ast-grep CLI。",
    category="builtin",
    tags=["code", "search", "ast"],
    scene="coding"
)
async def ast_search(
    pattern: str = "",
    language: str = "",
    path: str = "",
    max_matches: int = 30,
) -> dict[str, Any]:
    """基于 AST 的语法级代码搜索。

    使用 ast-grep 的模式匹配语法：
    - $NAME 捕获单个节点（变量名、函数名等）
    - $$$NAME 捕获多个节点（参数列表、语句块等）

    Python 示例：
    - "def $NAME($$$ARGS): $$$BODY"  — 查找所有函数定义
    - "import $NAME"                 — 查找所有 import 语句
    - "$OBJ.method($$$ARGS)"        — 查找特定方法调用

    Args:
        pattern: ast-grep 搜索模式
        language: 语言（python/javascript/go 等，留空自动检测）
        path: 搜索目录或文件（默认当前工作区）
        max_matches: 最大匹配数，默认 30

    Returns:
        匹配结果列表
    """
    if not pattern.strip():
        return {"error": "搜索模式不能为空"}

    if not _check_ast_grep():
        return {"error": "ast-grep CLI 未安装。请运行 pip install ast-grep 或参考 https://ast-grep.github.io 安装。"}

    # Resolve search path
    search_path = path.strip() if path.strip() else "."
    search_p = Path(search_path)
    if not search_p.exists():
        return {"error": f"搜索路径不存在: {search_path}"}

    # Build command
    cmd = ["ast-grep", "run", "-p", pattern.strip(), "--json"]
    if language.strip():
        lang = language.strip().lower()
        if lang not in SUPPORTED_LANGUAGES:
            return {
                "error": f"不支持的语言: {lang}。支持: {', '.join(sorted(SUPPORTED_LANGUAGES))}",
            }
        cmd.extend(["-l", lang])

    # Note: ast-grep run does not support --max-count; we trim results after parsing

    cmd.append(str(search_p))

    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=30,
        )
    except subprocess.TimeoutExpired:
        return {"error": "搜索超时（30秒），请缩小搜索范围"}
    except Exception as e:
        return {"error": f"执行 ast-grep 失败: {e}"}

    # Parse results — ast-grep --json outputs a JSON array
    matches = []
    if result.stdout.strip():
        try:
            data = json.loads(result.stdout.strip())
            if not isinstance(data, list):
                data = [data]
            for item in data:
                match_info = {
                    "file": item.get("file", ""),
                    "line": item.get("range", {}).get("start", {}).get("line", 0),
                    "text": item.get("text", "").strip(),
                }
                # Extract captured variables
                variables = item.get("variables", {})
                if variables:
                    match_info["captures"] = variables
                matches.append(match_info)
        except json.JSONDecodeError:
            matches = [{"text": line.strip()} for line in result.stdout.strip().split("\n") if line.strip()]

    # Trim to max_matches after parsing
    if max_matches > 0 and len(matches) > max_matches:
        matches = matches[:max_matches]

    if not matches:
        note = ""
        if result.stderr.strip():
            note = f" ({result.stderr.strip()[:200]})"
        return {
            "results": [],
            "count": 0,
            "pattern": pattern,
            "language": language or "auto",
            "path": search_path,
            "note": f"未找到匹配{note}" if not note else f"未找到匹配{note}",
        }

    return {
        "results": matches,
        "count": len(matches),
        "pattern": pattern,
        "language": language or "auto",
        "path": search_path,
    }
