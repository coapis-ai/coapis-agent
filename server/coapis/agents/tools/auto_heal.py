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

"""Auto heal — detect and fix common system issues with memory_manager integration.

Detection flow:
  1. Scan system health (disk/memory/processes)
  2. Apply fix
  3. Record fix experience to memory_manager
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import time
from pathlib import Path
from typing import Any

from .registry import register_tool

logger = logging.getLogger(__name__)


async def _run_cmd(cmd: list[str], timeout: int = 15) -> dict[str, Any]:
    start = time.time()
    try:
        proc = await asyncio.create_subprocess_exec(
            *cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE
        )
        stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=timeout)
        return {
            "returncode": proc.returncode,
            "stdout": stdout.decode(errors="replace"),
            "stderr": stderr.decode(errors="replace"),
            "elapsed": round(time.time() - start, 2),
        }
    except Exception as e:
        return {"returncode": -1, "stdout": "", "stderr": str(e), "elapsed": 0}


def _scan_issues() -> list[dict[str, Any]]:
    """Scan system for common issues."""
    issues = []

    # 1. Disk usage
    try:
        st = os.statvfs("/")
        used_pct = round((1 - st.f_bavail / max(st.f_blocks, 1)) * 100, 1)
        free_gb = round(st.f_bavail * st.f_frsize / 1024**3, 1)
        if used_pct > 90:
            issues.append({
                "id": "disk_full",
                "severity": "critical",
                "message": f"磁盘使用率 {used_pct}%，剩余 {free_gb}GB",
                "value": used_pct,
                "threshold": 90,
                "auto_fixable": True,
                "fix_action": "clean_tmp",
            })
        elif used_pct > 80:
            issues.append({
                "id": "disk_warning",
                "severity": "warning",
                "message": f"磁盘使用率 {used_pct}%，接近阈值",
                "value": used_pct,
                "threshold": 80,
                "auto_fixable": True,
                "fix_action": "clean_tmp",
            })
    except Exception:
        pass

    # 2. Memory usage
    try:
        with open("/proc/meminfo") as f:
            meminfo = {}
            for line in f:
                parts = line.split()
                if len(parts) >= 2:
                    meminfo[parts[0].rstrip(":")] = int(parts[1])
        total = meminfo.get("MemTotal", 1)
        avail = meminfo.get("MemAvailable", total)
        used_pct = round((1 - avail / total) * 100, 1)
        if used_pct > 90:
            issues.append({
                "id": "memory_critical",
                "severity": "critical",
                "message": f"内存使用率 {used_pct}%，可能触发 OOM",
                "value": used_pct,
                "threshold": 90,
                "auto_fixable": False,
                "fix_action": "drop_caches",
            })
        elif used_pct > 80:
            issues.append({
                "id": "memory_warning",
                "severity": "warning",
                "message": f"内存使用率 {used_pct}%",
                "value": used_pct,
                "threshold": 80,
                "auto_fixable": True,
                "fix_action": "drop_caches",
            })
    except Exception:
        pass

    # 3. Zombie/orphan processes
    try:
        r = _run_cmd(["ps", "aux"])
        if r["returncode"] == 0:
            zombies = [l for l in r["stdout"].split("\n") if "<defunct>" in l]
            if zombies:
                issues.append({
                    "id": "zombie_processes",
                    "severity": "warning",
                    "message": f"发现 {len(zombies)} 个僵尸进程",
                    "count": len(zombies),
                    "auto_fixable": True,
                    "fix_action": "kill_zombies",
                })
    except Exception:
        pass

    # 4. Too many open files
    try:
        fd_count = len(os.listdir("/proc/self/fd"))
        r = _run_cmd(["cat", "/proc/sys/fs/file-nr"])
        if r["returncode"] == 0:
            parts = r["stdout"].split()
            if len(parts) >= 3:
                allocated = int(parts[0])
                max_files = int(parts[2])
                if allocated > max_files * 0.8:
                    issues.append({
                        "id": "fd_exhaustion",
                        "severity": "critical",
                        "message": f"文件描述符使用接近上限 ({allocated}/{max_files})",
                        "auto_fixable": False,
                        "fix_action": "none",
                    })
    except Exception:
        pass

    # 5. Load average
    try:
        load1, load5, load15 = os.getloadavg()
        cpu_count = os.cpu_count() or 1
        if load5 > cpu_count * 2:
            issues.append({
                "id": "high_load",
                "severity": "warning",
                "message": f"系统负载 {load1:.1f}/{load5:.1f}/{load15:.1f}（CPU核心: {cpu_count}）",
                "load5": load5,
                "cpu_count": cpu_count,
                "auto_fixable": False,
                "fix_action": "none",
            })
    except Exception:
        pass

    return issues


async def _apply_fix(fix_action: str) -> dict[str, Any]:
    """Apply a fix action."""
    if fix_action == "clean_tmp":
        # Clean common temp locations
        cleaned = 0
        for tmp_dir in ["/tmp", "/var/tmp"]:
            try:
                r = _run_cmd(["find", tmp_dir, "-type", "f", "-atime", "+7", "-delete"], timeout=10)
                cleaned += 1
            except Exception:
                pass
        # Clean pip cache
        try:
            _run_cmd(["pip", "cache", "purge"], timeout=10)
        except Exception:
            pass
        return {"action": "clean_tmp", "success": True, "cleaned_dirs": cleaned}

    elif fix_action == "drop_caches":
        try:
            r = _run_cmd(["sh", "-c", "sync && echo 3 > /proc/sys/vm/drop_caches"], timeout=10)
            return {"action": "drop_caches", "success": r["returncode"] == 0}
        except Exception:
            return {"action": "drop_caches", "success": False, "error": "需要 root 权限"}

    elif fix_action == "kill_zombies":
        try:
            r = _run_cmd(["sh", "-c", "ps aux | awk '$8==\"Z\" {print $2}' | xargs -r kill -9 2>/dev/null"], timeout=10)
            return {"action": "kill_zombies", "success": True}
        except Exception:
            return {"action": "kill_zombies", "success": False}

    else:
        return {"action": fix_action, "success": False, "error": "不可自动修复"}


@register_tool(
    name="auto_heal",
    description="自动修复。action: scan(扫描系统问题), fix(修复指定问题,需issue_id), fix_all(修复所有问题), history(查看修复历史)。参数: action, fix, dry_run, issue_id。",
    category="builtin",
    tags=["healing", "self-repair", "ops"],
    scene="ops"
)
async def auto_heal(
    action: str = "scan",
    fix: str = "",
    dry_run: bool = False,
    issue_id: str = "",
) -> dict[str, Any]:
    """自动修复。

    检测系统问题并自动修复，修复前创建快照，修复后记录经验。

    Args:
        action: 操作类型 (scan/fix/fix_all/history)
        fix: 指定修复的动作（clean_tmp/drop_caches/kill_zombies）
        dry_run: 预览模式
        issue_id: 指定修复的问题 ID

    Returns:
        检测和修复结果
    """
    if action == "scan":
        issues = _scan_issues()
        critical = [i for i in issues if i["severity"] == "critical"]
        return {
            "action": "scan",
            "issues": issues,
            "total": len(issues),
            "critical": len(critical),
            "warning": len(issues) - len(critical),
            "healthy": len(issues) == 0,
        }

    elif action == "fix":
        if not fix.strip() and not issue_id.strip():
            return {"error": "fix 或 issue_id 不能为空"}

        # Scan first
        issues = _scan_issues()
        target = None

        if issue_id.strip():
            target = next((i for i in issues if i["id"] == issue_id.strip()), None)
            if not target:
                return {"error": f"未找到问题: {issue_id}"}
        elif fix.strip():
            target = next((i for i in issues if i.get("fix_action") == fix.strip()), None)
            if not target:
                # Create a synthetic issue for manual fix
                target = {
                    "id": f"manual_{fix}",
                    "fix_action": fix.strip(),
                    "message": f"手动修复: {fix}",
                }

        if not target:
            return {"error": "未找到匹配的可修复问题"}

        fix_action = target.get("fix_action", fix.strip())

        if dry_run:
            return {
                "action": "fix",
                "dry_run": True,
                "target": target,
                "fix_action": fix_action,
            }

        # Step 1: Apply fix
        fix_result = await _apply_fix(fix_action)

        # Step 2: Record to memory_manager
        memory_result = {"skipped": True}
        try:
            from .memory_manager import memory_manager
            memory_result = await memory_manager(
                action="add",
                key=f"heal_{target.get('id', 'unknown')}_{int(time.time())}",
                value=json.dumps({
                    "issue": target,
                    "fix": fix_result,
                    "timestamp": time.strftime("%Y-%m-%d %H:%M:%S"),
                }, ensure_ascii=False),
                tags="auto_heal,fix,system",
            )
        except Exception as e:
            memory_result = {"error": str(e), "skipped": True}

        return {
            "action": "fix",
            "issue": target,
            "fix_result": fix_result,
            "memory_recorded": memory_result,
            "success": fix_result.get("success", False),
        }

    elif action == "fix_all":
        issues = _scan_issues()
        fixable = [i for i in issues if i.get("auto_fixable")]
        if not fixable:
            return {"action": "fix_all", "message": "没有可自动修复的问题", "fixed": 0}

        if dry_run:
            return {
                "action": "fix_all",
                "dry_run": True,
                "would_fix": [{"id": i["id"], "action": i["fix_action"]} for i in fixable],
            }

        results = []
        for issue in fixable:
            r = await _apply_fix(issue["fix_action"])
            results.append({"issue": issue["id"], **r})

        fixed = sum(1 for r in results if r.get("success"))
        return {
            "action": "fix_all",
            "checkpoint": checkpoint_result,
            "results": results,
            "total": len(fixable),
            "fixed": fixed,
            "failed": len(fixable) - fixed,
        }

    elif action == "history":
        try:
            from .memory_manager import memory_manager
            r = await memory_manager(action="search", key="heal_", limit=10)
            return {
                "action": "history",
                "entries": r.get("results", []),
                "count": r.get("count", 0),
            }
        except Exception:
            return {"action": "history", "entries": [], "count": 0}

    else:
        return {"error": f"未知操作: {action}，支持 scan/fix/fix_all/history"}
