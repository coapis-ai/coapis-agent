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

"""Batch operations — safe batch file operations without shell commands.

Provides rename, move, copy, find-replace across multiple files
as a safe alternative to sed/awk/find via shell.
"""

from __future__ import annotations

import logging
import re
import shutil
from pathlib import Path
from typing import Any


logger = logging.getLogger(__name__)

_MAX_RESULTS = 100
_MAX_FILE_SIZE = 5 * 1024 * 1024  # 5MB per file


def _get_workspace() -> Path:
    """Get workspace directory (for reading files)."""
    try:
        from ...config.context import get_current_workspace_dir
        ws = get_current_workspace_dir()
        if ws:
            return Path(ws)
    except Exception:
        pass
    return Path.cwd()


def _get_files_dir() -> Path:
    """Get workspace/files/ directory (for writing output files)."""
    d = _get_workspace() / "files"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _resolve(path_str: str) -> Path | None:
    """Resolve a file path."""
    p = Path(path_str.strip())
    if p.is_absolute():
        return p if p.exists() else None
    ws = _get_workspace()
    resolved = ws / p
    return resolved if resolved.exists() else None


def _match_files(
    root: Path,
    pattern: str = "",
    glob: str = "",
    path_filter: str = "",
) -> list[Path]:
    """Find files matching criteria."""
    results = []
    try:
        if glob.strip():
            files = root.rglob(glob.strip())
        else:
            files = root.rglob("*")

        for f in files:
            if not f.is_file():
                continue
            if f.stat().st_size > _MAX_FILE_SIZE:
                continue
            # Skip common unwanted dirs
            parts = f.relative_to(root).parts
            if any(p.startswith(".") or p in ("node_modules", "__pycache__", "venv") for p in parts):
                continue
            # Text content pattern match
            if pattern.strip():
                try:
                    content = f.read_text(encoding="utf-8", errors="ignore")
                    if pattern.strip() not in content:
                        continue
                except Exception:
                    continue
            # Path filter (substring)
            if path_filter.strip():
                if path_filter.strip() not in str(f.relative_to(root)):
                    continue
            results.append(f)
            if len(results) >= _MAX_RESULTS:
                break
    except Exception as e:
        logger.warning(f"Error matching files: {e}")
    return results


async def batch_ops(
    action: str = "find",
    pattern: str = "",
    glob: str = "",
    path_filter: str = "",
    old_text: str = "",
    new_text: str = "",
    dest: str = "",
    dry_run: bool = True,
    limit: int = 50,
) -> dict[str, Any]:
    """批量文件操作。

    安全替代 sed/awk/shell 的批量文件操作工具。

    Args:
        action: 操作类型 (find/replace/move/copy/stats)
        pattern: 文本内容搜索模式（find/replace 时使用）
        glob: 文件名 glob 模式（如 *.py, *.ts）
        path_filter: 路径子串过滤
        old_text: 要替换的文本（replace 时必填）
        new_text: 替换后的文本（replace 时必填）
        dest: 目标路径（move/copy 时必填）
        dry_run: 预览模式，默认 True（不实际执行）
        limit: 最大匹配文件数，默认 50

    Returns:
        操作结果
    """
    root = _get_workspace()

    if action == "find":
        files = _match_files(root, pattern, glob, path_filter)
        results = []
        for f in files[:limit]:
            rel = str(f.relative_to(root))
            results.append({"path": rel, "size": f.stat().st_size})
        return {
            "files": results,
            "count": len(results),
            "total_found": len(files),
            "dry_run": dry_run,
        }

    elif action == "replace":
        if not old_text.strip():
            return {"error": "old_text 不能为空"}
        if not new_text.strip():
            return {"error": "new_text 不能为空"}

        files = _match_files(root, pattern, glob, path_filter)
        changes = []
        errors = []

        for f in files[:limit]:
            try:
                content = f.read_text(encoding="utf-8")
                if old_text not in content:
                    continue
                new_content = content.replace(old_text, new_text)
                count = content.count(old_text)
                rel = str(f.relative_to(root))
                changes.append({"path": rel, "replacements": count})

                if not dry_run:
                    f.write_text(new_content, encoding="utf-8")
            except Exception as e:
                errors.append({"path": str(f.relative_to(root)), "error": str(e)})

        return {
            "changes": changes,
            "change_count": len(changes),
            "total_replacements": sum(c["replacements"] for c in changes),
            "errors": errors,
            "dry_run": dry_run,
        }

    elif action == "move":
        if not dest.strip():
            return {"error": "dest 不能为空"}

        files = _match_files(root, pattern, glob, path_filter)
        dest_path = _get_files_dir() / dest.strip()
        results = []

        for f in files[:limit]:
            rel = str(f.relative_to(root))
            target = dest_path / f.name
            results.append({"from": rel, "to": str(target.relative_to(root))})

            if not dry_run:
                dest_path.mkdir(parents=True, exist_ok=True)
                try:
                    shutil.move(str(f), str(target))
                except Exception as e:
                    results[-1]["error"] = str(e)

        return {
            "moved": results,
            "count": len(results),
            "dry_run": dry_run,
        }

    elif action == "copy":
        if not dest.strip():
            return {"error": "dest 不能为空"}

        files = _match_files(root, pattern, glob, path_filter)
        dest_path = _get_files_dir() / dest.strip()
        results = []

        for f in files[:limit]:
            rel = str(f.relative_to(root))
            target = dest_path / f.name
            results.append({"from": rel, "to": str(target.relative_to(root))})

            if not dry_run:
                dest_path.mkdir(parents=True, exist_ok=True)
                try:
                    shutil.copy2(str(f), str(target))
                except Exception as e:
                    results[-1]["error"] = str(e)

        return {
            "copied": results,
            "count": len(results),
            "dry_run": dry_run,
        }

    elif action == "stats":
        files = _match_files(root, pattern, glob, path_filter)
        ext_counts: dict[str, int] = {}
        total_size = 0
        for f in files:
            ext = f.suffix.lower() or "(no ext)"
            ext_counts[ext] = ext_counts.get(ext, 0) + 1
            total_size += f.stat().st_size

        return {
            "total_files": len(files),
            "total_size": f"{total_size / 1024:.1f}KB",
            "by_extension": dict(sorted(ext_counts.items(), key=lambda x: -x[1])[:10]),
        }

    else:
        return {"error": f"未知操作: {action}，支持 find/replace/move/copy/stats"}
