# -*- coding: utf-8 -*-
# Copyright 2026 以太吃虾 & CoApis Contributors
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

"""Dependency audit — scan project dependencies for known vulnerabilities.

Supports npm/yarn/pnpm (package-lock.json), pip/poetry (requirements.txt/pyproject.toml),
and Go (go.sum). Integrates with error_recovery for fix suggestions and memory_manager
for scan history.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import time
from pathlib import Path
from typing import Any


logger = logging.getLogger(__name__)


async def _run_cmd(cmd: list[str], cwd: str | None = None, timeout: int = 30) -> dict[str, Any]:
    start = time.time()
    try:
        proc = await asyncio.create_subprocess_exec(
            *cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
            cwd=cwd,
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


def _detect_project_type(project_path: str) -> list[str]:
    """Detect project types from directory contents."""
    types = []
    p = Path(project_path)
    if (p / "package-lock.json").exists() or (p / "yarn.lock").exists() or (p / "pnpm-lock.yaml").exists():
        types.append("npm")
    if (p / "requirements.txt").exists() or (p / "setup.py").exists() or (p / "Pipfile.lock").exists():
        types.append("pip")
    if (p / "pyproject.toml").exists():
        types.append("pip")
    if (p / "go.sum").exists():
        types.append("go")
    if (p / "Cargo.lock").exists():
        types.append("cargo")
    return list(set(types))


async def _audit_npm(project_path: str) -> dict[str, Any]:
    """Run npm audit."""
    r = await _run_cmd(["npm", "audit", "--json"], cwd=project_path, timeout=60)
    if r["returncode"] == -1 and "ENOENT" in r["stderr"]:
        return {"status": "not_installed", "message": "npm 未安装"}

    vulns = []
    try:
        data = json.loads(r["stdout"])
        vuln_data = data.get("vulnerabilities", {})
        for name, info in vuln_data.items():
            severity = info.get("severity", "unknown")
            via = info.get("via", [])
            fix_available = info.get("fixAvailable", False)
            vulns.append({
                "package": name,
                "severity": severity,
                "fix_available": fix_available,
                "is_direct": info.get("isDirect", False),
                "via": [v if isinstance(v, str) else v.get("title", "") for v in via[:3]],
            })
        return {
            "status": "ok",
            "total_vulns": data.get("metadata", {}).get("vulnerabilities", {}).get("total", len(vulns)),
            "critical": data.get("metadata", {}).get("vulnerabilities", {}).get("critical", 0),
            "high": data.get("metadata", {}).get("vulnerabilities", {}).get("high", 0),
            "moderate": data.get("metadata", {}).get("vulnerabilities", {}).get("moderate", 0),
            "vulns": vulns,
        }
    except (json.JSONDecodeError, KeyError):
        return {"status": "parse_error", "raw": r["stdout"][:500]}


async def _audit_pip(project_path: str) -> dict[str, Any]:
    """Run pip-audit or safety check."""
    # Try pip-audit first
    r = await _run_cmd(["pip-audit", "--format", "json"], cwd=project_path, timeout=60)
    if r["returncode"] != -1 or "No such file" not in r["stderr"]:
        try:
            data = json.loads(r["stdout"])
            vulns = []
            for v in data.get("dependencies", []):
                if v.get("vulns"):
                    for vuln in v["vulns"]:
                        vulns.append({
                            "package": v["name"],
                            "version": v["version"],
                            "vuln_id": vuln.get("id", ""),
                            "fix_versions": vuln.get("fix_versions", []),
                            "description": vuln.get("description", "")[:200],
                        })
            return {"status": "ok", "total_vulns": len(vulns), "vulns": vulns}
        except (json.JSONDecodeError, KeyError):
            pass

    # Fallback: check requirements.txt with pip check
    req_file = Path(project_path) / "requirements.txt"
    if req_file.exists():
        r2 = await _run_cmd(["pip", "check"], cwd=project_path, timeout=30)
        broken = [l for l in r2["stdout"].split("\n") if "has requirement" in l.lower() or "incompatible" in l.lower()]
        return {"status": "ok", "total_vulns": len(broken), "vulns": [{"package": b, "severity": "medium"} for b in broken]}

    return {"status": "no_lockfile", "message": "未找到 requirements.txt 或 pip-audit"}


async def _audit_go(project_path: str) -> dict[str, Any]:
    """Run govulncheck."""
    r = await _run_cmd(["govulncheck", "-json", "./..."], cwd=project_path, timeout=60)
    if r["returncode"] == -1 and "ENOENT" in r["stderr"]:
        return {"status": "not_installed", "message": "govulncheck 未安装"}
    try:
        vulns = []
        for line in r["stdout"].split("\n"):
            if not line.strip():
                continue
            entry = json.loads(line)
            if entry.get("osv"):
                osv = entry["osv"]
                vulns.append({
                    "vuln_id": osv.get("id", ""),
                    "summary": osv.get("summary", "")[:200],
                    "severity": osv.get("database_specific", {}).get("severity", "unknown"),
                })
        return {"status": "ok", "total_vulns": len(vulns), "vulns": vulns}
    except (json.JSONDecodeError, KeyError):
        return {"status": "parse_error", "raw": r["stdout"][:500]}


async def dependency_audit(
    action: str = "scan",
    project_path: str = ".",
    fix: bool = False,
    record_history: bool = True,
) -> dict[str, Any]:
    """依赖漏洞扫描。

    扫描项目依赖包的已知漏洞，支持 npm/pip/go。

    Args:
        action: 操作类型 (scan/history)
        project_path: 项目路径
        fix: 是否尝试自动修复
        record_history: 是否记录扫描历史到 memory_manager

    Returns:
        扫描结果和漏洞列表
    """
    if action == "scan":
        project = Path(project_path).resolve()
        if not project.exists():
            return {"error": f"项目路径不存在: {project_path}"}

        types = _detect_project_type(str(project))
        if not types:
            return {"error": "未检测到已知项目类型（需要 package-lock.json / requirements.txt / go.sum）"}

        results = {}
        total_vulns = 0
        total_critical = 0

        for ptype in types:
            if ptype == "npm":
                results["npm"] = await _audit_npm(str(project))
            elif ptype == "pip":
                results["pip"] = await _audit_pip(str(project))
            elif ptype == "go":
                results["go"] = await _audit_go(str(project))

            type_result = results.get(ptype, {})
            total_vulns += type_result.get("total_vulns", 0)
            total_critical += type_result.get("critical", 0)

        # Generate fix suggestions (heuristic)
        fix_suggestions = []
        if total_vulns > 0:
            for ptype, res in results.items():
                for vuln in res.get("vulns", [])[:5]:
                    fix_suggestions.append({
                        "package": vuln.get("package", ""),
                        "suggestion": f"更新 {vuln.get('package', '')} 到最新版本",
                    })

        # Record scan history
        if record_history and total_vulns > 0:
            try:
                from .memory_manager import memory_manager
                await memory_manager(
                    action="add",
                    key=f"dep_audit_{int(time.time())}",
                    value=json.dumps({
                        "path": str(project),
                        "types": types,
                        "total_vulns": total_vulns,
                        "critical": total_critical,
                        "timestamp": time.strftime("%Y-%m-%d %H:%M:%S"),
                    }, ensure_ascii=False),
                    tags="security,dependency_audit",
                )
            except Exception:
                pass

        # Auto fix
        fix_results = {}
        if fix and total_vulns > 0:
            if "npm" in types and results.get("npm", {}).get("total_vulns", 0) > 0:
                r = await _run_cmd(["npm", "audit", "fix"], cwd=str(project), timeout=120)
                fix_results["npm"] = r["returncode"] == 0

        return {
            "project_path": str(project),
            "project_types": types,
            "total_vulns": total_vulns,
            "critical": total_critical,
            "results": results,
            "fix_suggestions": fix_suggestions,
            "fix_results": fix_results,
            "clean": total_vulns == 0,
        }

    elif action == "history":
        try:
            from .memory_manager import memory_manager
            r = await memory_manager(action="search", key="dep_audit_", limit=10)
            return {"action": "history", "entries": r.get("results", []), "count": r.get("count", 0)}
        except Exception:
            return {"action": "history", "entries": [], "count": 0}

    else:
        return {"error": f"未知操作: {action}，支持 scan/history"}
