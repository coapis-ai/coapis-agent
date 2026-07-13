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

"""Project analyzer tool — scan workspace to understand project structure."""

from __future__ import annotations

import logging
import os
from collections import Counter
from pathlib import Path
from typing import Any

from .registry import register_tool

logger = logging.getLogger(__name__)

# Language detection by extension
_EXT_LANG_MAP = {
    ".py": "Python",
    ".js": "JavaScript",
    ".ts": "TypeScript",
    ".tsx": "TypeScript (React)",
    ".jsx": "JavaScript (React)",
    ".go": "Go",
    ".rs": "Rust",
    ".java": "Java",
    ".c": "C",
    ".cpp": "C++",
    ".h": "C/C++ Header",
    ".hpp": "C++ Header",
    ".rb": "Ruby",
    ".php": "PHP",
    ".swift": "Swift",
    ".kt": "Kotlin",
    ".scala": "Scala",
    ".sh": "Shell",
    ".bash": "Shell",
    ".sql": "SQL",
    ".r": "R",
    ".R": "R",
    ".lua": "Lua",
    ".dart": "Dart",
    ".vue": "Vue",
    ".svelte": "Svelte",
    ".css": "CSS",
    ".scss": "SCSS",
    ".less": "Less",
    ".html": "HTML",
    ".htm": "HTML",
    ".xml": "XML",
    ".json": "JSON",
    ".yaml": "YAML",
    ".yml": "YAML",
    ".toml": "TOML",
    ".ini": "INI",
    ".cfg": "Config",
    ".md": "Markdown",
    ".txt": "Text",
    ".dockerfile": "Dockerfile",
}

# Project type detection by marker files
_PROJECT_MARKERS = {
    "Python": ["pyproject.toml", "setup.py", "setup.cfg", "requirements.txt", "Pipfile", "poetry.lock"],
    "Node.js": ["package.json", "yarn.lock", "pnpm-lock.yaml", "package-lock.json"],
    "Go": ["go.mod", "go.sum"],
    "Rust": ["Cargo.toml", "Cargo.lock"],
    "Java": ["pom.xml", "build.gradle", "build.gradle.kts"],
    "Docker": ["Dockerfile", "docker-compose.yml", "docker-compose.yaml"],
    "FastAPI": ["pyproject.toml"],  # detected via dependencies
    "React": ["tsconfig.json", "vite.config.ts", "next.config.js", "next.config.ts"],
    "Vue": ["vue.config.js", "vite.config.ts"],
    "Flutter": ["pubspec.yaml"],
}

# Directories to always skip
_SKIP_DIRS = {
    ".git", ".svn", "node_modules", "__pycache__", ".tox", ".mypy_cache",
    ".pytest_cache", "dist", "build", ".eggs", "*.egg-info", ".venv", "venv",
    "env", ".env", ".next", ".nuxt", "target", "vendor", ".cache",
    "coverage", ".nyc_output", "__snapshots__", "fixtures",
}

# Max depth for tree output
_MAX_TREE_DEPTH = 3
# Max files to scan for language stats
_MAX_FILES = 5000


def _should_skip(name: str) -> bool:
    """Check if a directory name should be skipped."""
    for pattern in _SKIP_DIRS:
        if pattern.startswith("*"):
            if name.endswith(pattern[1:]):
                return True
        elif name == pattern:
            return True
    return False


def _get_workspace() -> Path:
    """Get workspace directory.
    
    优先返回 files 子目录（用户上传文件的位置），
    如果不存在则返回工作目录根目录。
    """
    try:
        from ...config.context import get_current_workspace_dir
        ws = get_current_workspace_dir()
        if ws:
            workspace = Path(ws)
            # 优先检查 files 子目录（MySpace 上传文件的位置）
            files_dir = workspace / "files"
            if files_dir.exists() and files_dir.is_dir():
                return files_dir
            return workspace
    except Exception:
        pass
    return Path.cwd()


def _detect_project_types(root: Path) -> list[str]:
    """Detect project types by marker files."""
    types = []
    for ptype, markers in _PROJECT_MARKERS.items():
        for marker in markers:
            if (root / marker).exists():
                if ptype not in types:
                    types.append(ptype)
                break

    # Special: detect FastAPI from pyproject.toml
    if "Python" in types:
        pyproject = root / "pyproject.toml"
        if pyproject.exists():
            try:
                content = pyproject.read_text(encoding="utf-8")
                if "fastapi" in content.lower():
                    if "FastAPI" not in types:
                        types.append("FastAPI")
            except Exception:
                pass

    return types


def _build_tree(root: Path, max_depth: int = _MAX_TREE_DEPTH, prefix: str = "") -> list[str]:
    """Build a directory tree string."""
    lines = []
    if max_depth <= 0:
        return lines

    try:
        entries = sorted(root.iterdir(), key=lambda e: (not e.is_dir(), e.name.lower()))
    except PermissionError:
        return lines

    dirs = [e for e in entries if e.is_dir() and not _should_skip(e.name)]
    files = [e for e in entries if e.is_file()]

    # Show important files first
    important_exts = {".py", ".js", ".ts", ".go", ".rs", ".java", ".md", ".toml", ".yaml", ".yml", ".json"}
    important_files = [f for f in files if f.suffix in important_exts or f.name in ("Dockerfile", "Makefile", "README.md")]
    other_files = [f for f in files if f not in important_files]

    all_items = dirs + important_files + other_files

    for i, item in enumerate(all_items):
        is_last = (i == len(all_items) - 1)
        connector = "└── " if is_last else "├── "
        child_prefix = prefix + ("    " if is_last else "│   ")

        if item.is_dir():
            # Count files in dir
            try:
                count = sum(1 for _ in item.iterdir())
            except Exception:
                count = "?"
            lines.append(f"{prefix}{connector}📁 {item.name}/ ({count})")
            if max_depth > 1:
                lines.extend(_build_tree(item, max_depth - 1, child_prefix))
        else:
            # File size
            try:
                size = item.stat().st_size
                if size > 1024 * 1024:
                    size_str = f"{size / 1024 / 1024:.1f}MB"
                elif size > 1024:
                    size_str = f"{size / 1024:.1f}KB"
                else:
                    size_str = f"{size}B"
            except Exception:
                size_str = "?"
            lines.append(f"{prefix}{connector}{item.name} ({size_str})")

    return lines


async def project_analyzer(
    action: str = "overview",
    path: str = "",
    depth: int = 3,
) -> dict[str, Any]:
    """项目结构分析。

    Args:
        action: 分析类型 (overview/tree/languages/types)
        path: 子目录路径（可选，默认整个 workspace）
        depth: 目录树深度，默认 3

    Returns:
        分析结果
    """
    workspace = _get_workspace()
    target = workspace / path.strip() if path.strip() else workspace

    if not target.exists():
        return {"error": f"路径不存在: {target}"}
    if not target.is_dir():
        return {"error": f"不是目录: {target}"}

    if action == "overview":
        # Full overview
        project_types = _detect_project_types(target)
        tree = _build_tree(target, max_depth=min(depth, _MAX_TREE_DEPTH))

        # Count files by extension
        ext_counter: Counter = Counter()
        file_count = 0
        total_size = 0
        try:
            for f in target.rglob("*"):
                if f.is_file() and not any(_should_skip(p) for p in f.parts):
                    file_count += 1
                    total_size += f.stat().st_size
                    ext = f.suffix.lower()
                    if ext:
                        ext_counter[ext] += 1
                    if file_count >= _MAX_FILES:
                        break
        except Exception:
            pass

        # Language stats
        lang_stats: Counter = Counter()
        for ext, count in ext_counter.items():
            lang = _EXT_LANG_MAP.get(ext, ext.lstrip(".").upper() or "Other")
            lang_stats[lang] += count

        top_langs = lang_stats.most_common(10)

        return {
            "project_types": project_types,
            "total_files": file_count,
            "total_size": f"{total_size / 1024:.1f}KB" if total_size < 1024 * 1024 else f"{total_size / 1024 / 1024:.1f}MB",
            "languages": [{"lang": lang, "count": count} for lang, count in top_langs],
            "tree": "\n".join(tree),
        }

    elif action == "tree":
        tree = _build_tree(target, max_depth=min(depth, _MAX_TREE_DEPTH))
        return {
            "path": str(target),
            "tree": "\n".join(tree),
        }

    elif action == "languages":
        ext_counter: Counter = Counter()
        file_count = 0
        try:
            for f in target.rglob("*"):
                if f.is_file() and not any(_should_skip(p) for p in f.parts):
                    file_count += 1
                    ext = f.suffix.lower()
                    if ext:
                        ext_counter[ext] += 1
                    if file_count >= _MAX_FILES:
                        break
        except Exception:
            pass

        lang_stats: Counter = Counter()
        for ext, count in ext_counter.items():
            lang = _EXT_LANG_MAP.get(ext, ext.lstrip(".").upper() or "Other")
            lang_stats[lang] += count

        return {
            "total_files": file_count,
            "languages": [{"lang": lang, "count": count} for lang, count in lang_stats.most_common(15)],
        }

    elif action == "types":
        project_types = _detect_project_types(target)
        return {
            "project_types": project_types if project_types else ["Unknown"],
        }

    else:
        return {"error": f"未知操作: {action}，支持 overview/tree/languages/types"}
