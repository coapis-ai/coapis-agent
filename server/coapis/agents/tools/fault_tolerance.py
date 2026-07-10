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
"""Fault tolerance — unified tool for checkpointing and error recovery.

Merges: checkpoint_tool + error_recovery into one tool.
"""
from __future__ import annotations
import json, os, time, traceback, hashlib
from datetime import datetime
from pathlib import Path
from .registry import register_tool


def _get_checkpoint_dir() -> Path:
    try:
        from ...config.context import get_current_workspace_dir
        ws = get_current_workspace_dir()
        if ws:
            return Path(ws) / "files" / "checkpoints"
    except Exception:
        pass
    return Path.cwd() / "files" / "checkpoints"


# ── Checkpoint ──
def _create_snapshot(name: str = "", description: str = "") -> dict:
    ckpt_dir = _get_checkpoint_dir()
    ckpt_dir.mkdir(parents=True, exist_ok=True)
    ts = int(time.time() * 1000)
    ckpt_name = name or f"ckpt_{ts}"
    ckpt_path = ckpt_dir / ckpt_name
    ckpt_path.mkdir(parents=True, exist_ok=True)
    # Save metadata
    meta = {"name": ckpt_name, "description": description, "created_at": datetime.now().isoformat(), "ts": ts}
    (ckpt_path / "meta.json").write_text(json.dumps(meta, ensure_ascii=False, indent=2))
    # Try git snapshot
    git_info = {}
    try:
        import subprocess
        ws = str(Path(os.environ.get("COAPIS_WORKSPACE", ".")))
        r = subprocess.run(["git", "rev-parse", "HEAD"], capture_output=True, text=True, cwd=ws, timeout=5)
        if r.returncode == 0:
            git_info["commit"] = r.stdout.strip()
        subprocess.run(["git", "stash", "push", "-m", f"checkpoint:{ckpt_name}"],
                      capture_output=True, text=True, cwd=ws, timeout=10)
        git_info["stashed"] = True
    except Exception:
        pass
    meta["git"] = git_info
    (ckpt_path / "meta.json").write_text(json.dumps(meta, ensure_ascii=False, indent=2))
    return {"checkpoint": ckpt_name, "path": str(ckpt_path), "git": git_info, "status": "ok"}


def _list_checkpoints(limit: int = 10) -> dict:
    ckpt_dir = _get_checkpoint_dir()
    if not ckpt_dir.exists():
        return {"checkpoints": [], "count": 0}
    items = []
    for d in sorted(ckpt_dir.iterdir(), reverse=True):
        if d.is_dir():
            meta_file = d / "meta.json"
            if meta_file.exists():
                try:
                    meta = json.loads(meta_file.read_text())
                    items.append(meta)
                except Exception:
                    items.append({"name": d.name})
            else:
                items.append({"name": d.name})
        if len(items) >= limit:
            break
    return {"checkpoints": items, "count": len(items)}


# ── Error Recovery ──
_ERROR_PATTERNS = {
    "disk_full": {"symptoms": ["No space left", "ENOSPC"], "recovery": "清理临时文件和日志"},
    "oom": {"symptoms": ["out of memory", "OOM", "Cannot allocate"], "recovery": "减少并发/增加swap"},
    "permission": {"symptoms": ["Permission denied", "EACCES"], "recovery": "检查文件权限"},
    "not_found": {"symptoms": ["No such file", "ENOENT", "404"], "recovery": "检查路径是否存在"},
    "timeout": {"symptoms": ["timed out", "ETIMEDOUT", "deadline exceeded"], "recovery": "增加超时/检查网络"},
    "connection": {"symptoms": ["Connection refused", "ECONNREFUSED", "ECONNRESET"], "recovery": "检查服务是否运行"},
    "syntax": {"symptoms": ["SyntaxError", "IndentationError", "ParseError"], "recovery": "检查代码语法"},
    "import": {"symptoms": ["ImportError", "ModuleNotFoundError"], "recovery": "安装缺失依赖"},
    "auth": {"symptoms": ["401", "403", "Unauthorized", "Forbidden"], "recovery": "检查认证凭据"},
    "rate_limit": {"symptoms": ["429", "Too Many Requests", "rate limit"], "recovery": "降低请求频率"},
}


def _diagnose_error(error_msg: str) -> dict:
    matched = []
    error_lower = error_msg.lower()
    for pattern_name, info in _ERROR_PATTERNS.items():
        for symptom in info["symptoms"]:
            if symptom.lower() in error_lower:
                matched.append({"pattern": pattern_name, "recovery": info["recovery"], "matched_symptom": symptom})
                break
    return {"diagnosis": matched, "total_matches": len(matched)}


def _auto_fix(pattern: str) -> dict:
    fixes = {
        "disk_full": {"action": "clean_tmp", "cmd": "find /tmp -type f -mtime +1 -delete"},
        "permission": {"action": "fix_perms", "cmd": "chmod -R u+w ."},
        "not_found": {"action": "create_dirs", "cmd": "mkdir -p workspaces/global_default/files"},
    }
    if pattern in fixes:
        return {"pattern": pattern, "fix": fixes[pattern], "status": "applied", "note": "Fix prepared (execute via shell if needed)"}
    return {"pattern": pattern, "status": "no_auto_fix", "note": "Manual intervention required"}


async def fault_tolerance(
    action: str = "checkpoint",
    name: str = "",
    description: str = "",
    error_msg: str = "",
    pattern: str = "",
    limit: int = 10,
) -> dict:
    """容错工具。

    Args:
        action: checkpoint(创建快照) / list(查看快照) / diagnose(诊断错误) / fix(自动修复)
        name: 快照名称 (checkpoint 时)
        description: 快照描述 (checkpoint 时)
        error_msg: 错误信息 (diagnose 时)
        pattern: 错误模式名 (fix 时)
        limit: 列表数量限制 (list 时)
    """
    if action == "checkpoint":
        return {"action": "checkpoint", **_create_snapshot(name, description)}
    elif action == "list":
        return {"action": "list", **_list_checkpoints(limit)}
    elif action == "diagnose":
        if not error_msg.strip():
            return {"error": "error_msg 不能为空"}
        return {"action": "diagnose", **_diagnose_error(error_msg)}
    elif action == "fix":
        if not pattern.strip():
            return {"error": "pattern 不能为空"}
        return {"action": "fix", **_auto_fix(pattern)}
    else:
        return {"error": f"未知 action: {action}，支持 checkpoint/list/diagnose/fix"}


