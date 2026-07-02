# -*- coding: utf-8 -*-
# Copyright 2026 蜜蜂 & CoApis Contributors
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#     http://www.apache.org/licenses/LICENSE-2.0

"""Data operations — unified tool for structured data processing and batch file ops.

Merges data_processor + batch_ops into a single tool via action parameter.
Capabilities: CSV/JSON read/filter/stats/convert, batch find/replace/move/copy.
"""

from __future__ import annotations

import csv
import io
import json
import logging
import re
import shutil
from pathlib import Path
from typing import Any

from .registry import register_tool

logger = logging.getLogger(__name__)

_MAX_ROWS = 1000
_MAX_FILE_SIZE = 10 * 1024 * 1024  # 10MB
_MAX_BATCH_RESULTS = 100


def _get_workspace() -> Path:
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
    p = Path(path_str.strip())
    if p.is_absolute():
        return p if p.exists() and p.is_file() else None
    ws = _get_workspace()
    resolved = ws / p
    return resolved if resolved.exists() and resolved.is_file() else None


# ── CSV/JSON helpers ──

def _read_csv(path: Path, encoding: str = "utf-8") -> list[dict[str, str]]:
    content = path.read_text(encoding=encoding, errors="replace")
    reader = csv.DictReader(io.StringIO(content))
    return [dict(row) for i, row in enumerate(reader) if i < _MAX_ROWS]


def _read_json(path: Path) -> list[dict[str, Any]] | dict[str, Any]:
    content = path.read_text(encoding="utf-8")
    data = json.loads(content)
    if isinstance(data, list):
        return data[:_MAX_ROWS]
    return data


def _write_csv(rows: list[dict], path: Path) -> int:
    if not rows:
        return 0
    fieldnames = list(rows[0].keys())
    with open(path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            writer.writerow(row)
    return len(rows)


def _write_json(data: Any, path: Path) -> None:
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2, default=str), encoding="utf-8")


def _filter_rows(rows: list[dict], field: str, op: str, value: str) -> list[dict]:
    result = []
    for row in rows:
        cell = row.get(field, "")
        try:
            cell_num = float(cell) if cell else 0
            val_num = float(value) if value else 0
            if op == "eq" and cell_num == val_num:
                result.append(row)
            elif op == "gt" and cell_num > val_num:
                result.append(row)
            elif op == "lt" and cell_num < val_num:
                result.append(row)
            elif op == "gte" and cell_num >= val_num:
                result.append(row)
            elif op == "lte" and cell_num <= val_num:
                result.append(row)
        except (ValueError, TypeError):
            if op == "eq" and cell == value:
                result.append(row)
            elif op == "contains" and value.lower() in cell.lower():
                result.append(row)
            elif op == "neq" and cell != value:
                result.append(row)
    return result


def _compute_stats(rows: list[dict]) -> dict[str, Any]:
    stats: dict[str, Any] = {}
    if not rows:
        return stats
    for key in rows[0].keys():
        values = []
        for row in rows:
            val = row.get(key, "")
            try:
                values.append(float(val))
            except (ValueError, TypeError):
                continue
        if not values:
            stats[key] = {"type": "text", "unique": len(set(row.get(key, "") for row in rows))}
            continue
        stats[key] = {
            "type": "numeric",
            "count": len(values),
            "min": min(values),
            "max": max(values),
            "mean": round(sum(values) / len(values), 2),
            "sum": round(sum(values), 2),
            "unique": len(set(values)),
        }
    return stats


def _load_data(file_path: str, encoding: str = "utf-8") -> tuple[list[dict] | dict | None, str | None]:
    """Load data from file, return (data, error)."""
    path = _resolve(file_path)
    if not path:
        return None, f"文件不存在: {file_path}"
    if path.stat().st_size > _MAX_FILE_SIZE:
        return None, f"文件过大 ({path.stat().st_size / 1024 / 1024:.1f}MB)，最大 10MB"
    if path.suffix.lower() == ".csv":
        return _read_csv(path, encoding), None
    elif path.suffix.lower() == ".json":
        return _read_json(path), None
    else:
        return None, f"不支持的文件类型: {path.suffix}"


# ── Batch file helpers ──

def _match_files(
    root: Path,
    pattern: str = "",
    glob_pattern: str = "",
    path_filter: str = "",
) -> list[Path]:
    results = []
    try:
        if glob_pattern.strip():
            files = root.rglob(glob_pattern.strip())
        else:
            files = root.rglob("*")
        for f in files:
            if not f.is_file():
                continue
            if f.stat().st_size > _MAX_FILE_SIZE:
                continue
            parts = f.relative_to(root).parts
            if any(p.startswith(".") or p in ("node_modules", "__pycache__", "venv") for p in parts):
                continue
            if pattern.strip():
                try:
                    content = f.read_text(encoding="utf-8", errors="ignore")
                    if pattern.strip() not in content:
                        continue
                except Exception:
                    continue
            if path_filter.strip():
                if path_filter.strip() not in str(f.relative_to(root)):
                    continue
            results.append(f)
            if len(results) >= _MAX_BATCH_RESULTS:
                break
    except Exception as e:
        logger.warning(f"Error matching files: {e}")
    return results


async def data_ops(
    action: str = "read",
    # Data processor params
    file_path: str = "",
    field: str = "",
    op: str = "eq",
    value: str = "",
    output_path: str = "",
    encoding: str = "utf-8",
    # Batch ops params
    pattern: str = "",
    glob: str = "",
    path_filter: str = "",
    old_text: str = "",
    new_text: str = "",
    dest: str = "",
    dry_run: bool = True,
    limit: int = 50,
    **kwargs: Any,
) -> dict[str, Any]:
    """数据操作统一工具。

    Args:
        action: 操作类型:
            数据处理: read/filter/stats/convert/summary
            批量文件: batch_find/batch_replace/batch_move/batch_copy/batch_stats
        file_path: 数据文件路径
        field: 过滤字段名
        op: 过滤操作符 (eq/neq/gt/lt/gte/lte/contains)
        value: 过滤值
        output_path: 输出文件路径（convert 时使用）
        encoding: 文件编码
        pattern: 文本内容搜索模式
        glob: 文件名 glob 模式
        path_filter: 路径子串过滤
        old_text: 要替换的文本
        new_text: 替换后的文本
        dest: 目标路径
        dry_run: 预览模式
        limit: 最大返回数

    Returns:
        操作结果
    """
    # ── Data processor actions ──
    if action in ("read", "filter", "stats", "convert", "summary"):
        if not file_path.strip():
            return {"error": "file_path 不能为空"}

        if action == "read":
            data, err = _load_data(file_path, encoding)
            if err:
                return {"error": err}
            if isinstance(data, list):
                return {
                    "type": "csv" if file_path.strip().endswith(".csv") else "json_array",
                    "columns": list(data[0].keys()) if data else [],
                    "row_count": len(data),
                    "rows": data[:limit],
                }
            else:
                return {"type": "json_object", "data": data}

        elif action == "filter":
            if not field.strip():
                return {"error": "field 不能为空"}
            data, err = _load_data(file_path, encoding)
            if err:
                return {"error": err}
            rows = data if isinstance(data, list) else []
            filtered = _filter_rows(rows, field, op, value)
            return {
                "field": field, "op": op, "value": value,
                "total_rows": len(rows), "filtered_count": len(filtered),
                "rows": filtered[:limit],
            }

        elif action == "stats":
            data, err = _load_data(file_path, encoding)
            if err:
                return {"error": err}
            rows = data if isinstance(data, list) else []
            stats = _compute_stats(rows)
            return {"row_count": len(rows), "columns": len(stats), "stats": stats}

        elif action == "convert":
            data, err = _load_data(file_path, encoding)
            if err:
                return {"error": err}
            if not output_path.strip():
                return {"error": "output_path 不能为空"}
            dest_p = _get_files_dir() / output_path.strip()
            src_ext = file_path.strip().rsplit(".", 1)[-1].lower() if "." in file_path else ""
            dst_ext = dest_p.suffix.lower()
            if src_ext == "csv" and dst_ext == ".json":
                rows = data if isinstance(data, list) else []
                _write_json(rows, dest_p)
                return {"message": f"✅ 转换完成: {len(rows)} 行", "from": "csv", "to": "json", "output": output_path}
            elif src_ext == "json" and dst_ext == ".csv":
                if isinstance(data, list) and data:
                    _write_csv(data, dest_p)
                    return {"message": f"✅ 转换完成: {len(data)} 行", "from": "json", "to": "csv", "output": output_path}
                else:
                    return {"error": "JSON 数组为空或格式不支持转 CSV"}
            else:
                return {"error": f"不支持的转换: {src_ext} -> {dst_ext}"}

        elif action == "summary":
            data, err = _load_data(file_path, encoding)
            if err:
                return {"error": err}
            if isinstance(data, list):
                return {
                    "columns": list(data[0].keys()) if data else [],
                    "row_count": len(data),
                    "sample": data[:3],
                    "stats": _compute_stats(data),
                }
            else:
                return {"type": "json_object", "keys": list(data.keys())[:20], "data": data}

    # ── Batch ops actions ──
    elif action in ("batch_find", "batch_replace", "batch_move", "batch_copy", "batch_stats"):
        root = _get_workspace()

        if action == "batch_find":
            files = _match_files(root, pattern, glob, path_filter)
            results = [{"path": str(f.relative_to(root)), "size": f.stat().st_size} for f in files[:limit]]
            return {"files": results, "count": len(results), "total_found": len(files), "dry_run": dry_run}

        elif action == "batch_replace":
            if not old_text.strip():
                return {"error": "old_text 不能为空"}
            if not new_text.strip():
                return {"error": "new_text 不能为空"}
            files = _match_files(root, pattern, glob, path_filter)
            changes, errors = [], []
            for f in files[:limit]:
                try:
                    content = f.read_text(encoding="utf-8")
                    if old_text not in content:
                        continue
                    count = content.count(old_text)
                    rel = str(f.relative_to(root))
                    changes.append({"path": rel, "replacements": count})
                    if not dry_run:
                        f.write_text(content.replace(old_text, new_text), encoding="utf-8")
                except Exception as e:
                    errors.append({"path": str(f.relative_to(root)), "error": str(e)})
            return {
                "changes": changes, "change_count": len(changes),
                "total_replacements": sum(c["replacements"] for c in changes),
                "errors": errors, "dry_run": dry_run,
            }

        elif action == "batch_move":
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
            return {"moved": results, "count": len(results), "dry_run": dry_run}

        elif action == "batch_copy":
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
            return {"copied": results, "count": len(results), "dry_run": dry_run}

        elif action == "batch_stats":
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
        return {"error": f"未知操作: {action}。数据: read/filter/stats/convert/summary; 批量: batch_find/batch_replace/batch_move/batch_copy/batch_stats"}


# ── Aliases for backward compatibility ──
data_processor = data_ops
batch_ops = data_ops
