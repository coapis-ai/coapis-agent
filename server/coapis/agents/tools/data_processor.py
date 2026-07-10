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

"""Data processor — CSV/JSON data reading, filtering, transformation, and statistics.

Provides structured data operations without shell commands or external libraries.
"""

from __future__ import annotations

import csv
import io
import json
import logging
from pathlib import Path
from typing import Any


logger = logging.getLogger(__name__)

_MAX_ROWS = 1000
_MAX_FILE_SIZE = 10 * 1024 * 1024  # 10MB


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
    """Resolve a file path within workspace."""
    p = Path(path_str.strip())
    if p.is_absolute():
        return p if p.exists() and p.is_file() else None
    ws = _get_workspace()
    resolved = ws / p
    return resolved if resolved.exists() and resolved.is_file() else None


def _read_csv(path: Path, encoding: str = "utf-8") -> list[dict[str, str]]:
    """Read CSV file into list of dicts."""
    content = path.read_text(encoding=encoding, errors="replace")
    reader = csv.DictReader(io.StringIO(content))
    return [dict(row) for i, row in enumerate(reader) if i < _MAX_ROWS]


def _read_json(path: Path) -> list[dict[str, Any]] | dict[str, Any]:
    """Read JSON file."""
    content = path.read_text(encoding="utf-8")
    data = json.loads(content)
    if isinstance(data, list):
        return data[:_MAX_ROWS]
    return data


def _write_csv(rows: list[dict], path: Path) -> int:
    """Write list of dicts to CSV."""
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
    """Write data to JSON."""
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2, default=str), encoding="utf-8")


def _filter_rows(rows: list[dict], field: str, op: str, value: str) -> list[dict]:
    """Filter rows by field value."""
    result = []
    for row in rows:
        cell = row.get(field, "")
        try:
            # Try numeric comparison
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
            # String comparison
            if op == "eq" and cell == value:
                result.append(row)
            elif op == "contains" and value.lower() in cell.lower():
                result.append(row)
            elif op == "neq" and cell != value:
                result.append(row)
    return result


def _compute_stats(rows: list[dict]) -> dict[str, Any]:
    """Compute basic statistics for numeric columns."""
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


async def data_processor(
    action: str = "read",
    file_path: str = "",
    field: str = "",
    op: str = "eq",
    value: str = "",
    output_path: str = "",
    limit: int = 50,
    encoding: str = "utf-8",
) -> dict[str, Any]:
    """数据处理器。

    支持 CSV/JSON 文件的读取、过滤、转换和统计。

    Args:
        action: 操作类型 (read/filter/stats/convert/summary)
        file_path: 文件路径（CSV 或 JSON）
        field: 过滤字段名
        op: 过滤操作符 (eq/neq/gt/lt/gte/lte/contains)
        value: 过滤值
        output_path: 输出文件路径（用于 convert）
        limit: 最大返回行数，默认 50
        encoding: 文件编码，默认 utf-8

    Returns:
        操作结果
    """
    if action in ("read", "filter", "stats", "convert", "summary") and not file_path.strip():
        return {"error": "file_path 不能为空"}

    if action == "read":
        path = _resolve(file_path)
        if not path:
            return {"error": f"文件不存在: {file_path}"}
        if path.stat().st_size > _MAX_FILE_SIZE:
            return {"error": f"文件过大 ({path.stat().st_size / 1024 / 1024:.1f}MB)，最大 10MB"}

        if path.suffix.lower() == ".csv":
            rows = _read_csv(path, encoding)
            return {
                "type": "csv",
                "columns": list(rows[0].keys()) if rows else [],
                "row_count": len(rows),
                "rows": rows[:limit],
            }
        elif path.suffix.lower() == ".json":
            data = _read_json(path)
            if isinstance(data, list):
                return {
                    "type": "json_array",
                    "columns": list(data[0].keys()) if data else [],
                    "row_count": len(data),
                    "rows": data[:limit],
                }
            else:
                return {"type": "json_object", "data": data}
        else:
            return {"error": f"不支持的文件类型: {path.suffix}"}

    elif action == "filter":
        if not field.strip():
            return {"error": "field 不能为空"}
        path = _resolve(file_path)
        if not path:
            return {"error": f"文件不存在: {file_path}"}

        if path.suffix.lower() == ".csv":
            rows = _read_csv(path, encoding)
        elif path.suffix.lower() == ".json":
            data = _read_json(path)
            rows = data if isinstance(data, list) else []
        else:
            return {"error": f"不支持的文件类型: {path.suffix}"}

        filtered = _filter_rows(rows, field, op, value)
        return {
            "field": field,
            "op": op,
            "value": value,
            "total_rows": len(rows),
            "filtered_count": len(filtered),
            "rows": filtered[:limit],
        }

    elif action == "stats":
        path = _resolve(file_path)
        if not path:
            return {"error": f"文件不存在: {file_path}"}

        if path.suffix.lower() == ".csv":
            rows = _read_csv(path, encoding)
        elif path.suffix.lower() == ".json":
            data = _read_json(path)
            rows = data if isinstance(data, list) else []
        else:
            return {"error": f"不支持的文件类型: {path.suffix}"}

        stats = _compute_stats(rows)
        return {"row_count": len(rows), "columns": len(stats), "stats": stats}

    elif action == "convert":
        path = _resolve(file_path)
        if not path:
            return {"error": f"文件不存在: {file_path}"}

        dest = _get_files_dir() / output_path.strip()
        if not output_path.strip():
            return {"error": "output_path 不能为空"}

        if path.suffix.lower() == ".csv":
            rows = _read_csv(path, encoding)
            if dest.suffix.lower() == ".json":
                _write_json(rows, dest)
                return {"message": f"✅ 转换完成: {len(rows)} 行", "from": "csv", "to": "json", "output": output_path}
            else:
                return {"error": "CSV 只能转换为 JSON"}
        elif path.suffix.lower() == ".json":
            data = _read_json(path)
            if dest.suffix.lower() == ".csv":
                if isinstance(data, list) and data:
                    _write_csv(data, dest)
                    return {"message": f"✅ 转换完成: {len(data)} 行", "from": "json", "to": "csv", "output": output_path}
                else:
                    return {"error": "JSON 数组为空或格式不支持转 CSV"}
            elif dest.suffix.lower() == ".json":
                _write_json(data, dest)
                return {"message": "✅ 复制完成", "format": "json", "output": output_path}
            else:
                return {"error": "不支持的目标格式"}
        else:
            return {"error": f"不支持的文件类型: {path.suffix}"}

    elif action == "summary":
        path = _resolve(file_path)
        if not path:
            return {"error": f"文件不存在: {file_path}"}

        if path.suffix.lower() == ".csv":
            rows = _read_csv(path, encoding)
            cols = list(rows[0].keys()) if rows else []
            sample = rows[:3]
            return {
                "type": "csv",
                "columns": cols,
                "row_count": len(rows),
                "sample": sample,
                "stats": _compute_stats(rows),
            }
        elif path.suffix.lower() == ".json":
            data = _read_json(path)
            if isinstance(data, list):
                return {
                    "type": "json_array",
                    "columns": list(data[0].keys()) if data else [],
                    "row_count": len(data),
                    "sample": data[:3],
                    "stats": _compute_stats(data),
                }
            else:
                return {"type": "json_object", "keys": list(data.keys())[:20], "data": data}
        else:
            return {"error": f"不支持的文件类型: {path.suffix}"}

    else:
        return {"error": f"未知操作: {action}，支持 read/filter/stats/convert/summary"}
