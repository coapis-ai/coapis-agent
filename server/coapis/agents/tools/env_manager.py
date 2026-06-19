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

"""Environment manager — read/set/list env vars and manage .env files.

Provides safe environment variable access and .env file parsing.
"""

from __future__ import annotations

import logging
import os
import re
from pathlib import Path
from typing import Any

from .registry import register_tool

logger = logging.getLogger(__name__)

_MAX_ENV_ENTRIES = 200
_SENSITIVE_PATTERNS = re.compile(
    r"(?i)(password|secret|token|api.?key|private.?key|credential|auth)",
)


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


def _is_sensitive(key: str) -> bool:
    """Check if a key might contain sensitive data."""
    return bool(_SENSITIVE_PATTERNS.search(key))


def _mask_value(value: str) -> str:
    """Mask sensitive values."""
    if len(value) <= 4:
        return "****"
    return value[:2] + "****" + value[-2:]


def _parse_env_file(path: Path) -> list[dict[str, str]]:
    """Parse a .env file into list of key-value dicts."""
    entries = []
    if not path.exists():
        return entries
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip()
        value = value.strip()
        # Remove surrounding quotes
        if len(value) >= 2 and value[0] == value[-1] and value[0] in ('"', "'"):
            value = value[1:-1]
        entries.append({"key": key, "value": value})
    return entries


@register_tool(
    name="env_manager",
    description="环境变量管理：读取/设置/列出环境变量，管理 .env 文件。",
    category="builtin",
    tags=["env", "config", "system"],
    scene="security"
)
async def env_manager(
    action: str = "list",
    key: str = "",
    value: str = "",
    file_path: str = ".env",
    show_sensitive: bool = False,
) -> dict[str, Any]:
    """环境变量管理。

    Args:
        action: 操作类型 (list/get/set/unset/dotenv_read/dotenv_write/dotenv_append)
        key: 环境变量名
        value: 环境变量值
        file_path: .env 文件路径，默认 .env
        show_sensitive: 是否显示敏感值（默认隐藏）

    Returns:
        操作结果
    """
    ws = _get_workspace()

    if action == "list":
        env_vars = []
        for k, v in sorted(os.environ.items()):
            entry = {"key": k, "value": v}
            if _is_sensitive(k) and not show_sensitive:
                entry["value"] = _mask_value(v)
                entry["sensitive"] = True
            env_vars.append(entry)
            if len(env_vars) >= _MAX_ENV_ENTRIES:
                break
        return {
            "action": "list",
            "entries": env_vars,
            "count": len(env_vars),
            "total": len(os.environ),
        }

    elif action == "get":
        if not key.strip():
            return {"error": "key 不能为空"}
        val = os.environ.get(key.strip())
        if val is None:
            return {"error": f"环境变量 '{key}' 不存在"}
        if _is_sensitive(key) and not show_sensitive:
            val = _mask_value(val)
        return {"action": "get", "key": key.strip(), "value": val}

    elif action == "set":
        if not key.strip():
            return {"error": "key 不能为空"}
        os.environ[key.strip()] = value
        return {"action": "set", "key": key.strip(), "set": True}

    elif action == "unset":
        if not key.strip():
            return {"error": "key 不能为空"}
        existed = key.strip() in os.environ
        os.environ.pop(key.strip(), None)
        return {"action": "unset", "key": key.strip(), "existed": existed}

    elif action == "dotenv_read":
        env_path = ws / file_path.strip()
        if not env_path.exists():
            return {"error": f"文件不存在: {file_path}"}
        entries = _parse_env_file(env_path)
        # Mask sensitive
        if not show_sensitive:
            for e in entries:
                if _is_sensitive(e["key"]):
                    e["value"] = _mask_value(e["value"])
                    e["sensitive"] = True
        return {
            "action": "dotenv_read",
            "file": str(env_path),
            "entries": entries,
            "count": len(entries),
        }

    elif action == "dotenv_write":
        if not key.strip():
            return {"error": "key 不能为空"}
        env_path = _get_files_dir() / file_path.strip()

        # Read existing entries
        entries = _parse_env_file(env_path) if env_path.exists() else []
        # Update or add
        updated = False
        for e in entries:
            if e["key"] == key.strip():
                e["value"] = value
                updated = True
                break
        if not updated:
            entries.append({"key": key.strip(), "value": value})

        # Write back
        lines = [f'{e["key"]}={e["value"]}' for e in entries]
        env_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
        return {
            "action": "dotenv_write",
            "file": str(env_path),
            "key": key.strip(),
            "updated": updated,
            "total_entries": len(entries),
        }

    elif action == "dotenv_append":
        if not key.strip():
            return {"error": "key 不能为空"}
        env_path = _get_files_dir() / file_path.strip()
        line = f'{key.strip()}={value}\n'
        with open(str(env_path), "a", encoding="utf-8") as f:
            f.write(line)
        return {
            "action": "dotenv_append",
            "file": str(env_path),
            "key": key.strip(),
        }

    else:
        return {"error": f"未知操作: {action}，支持 list/get/set/unset/dotenv_read/dotenv_write/dotenv_append"}
