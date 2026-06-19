# -*- coding: utf-8 -*-
# Copyright 2026 蜜蜂 & CoApis Contributors
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#     http://www.apache.org/licenses/LICENSE-2.0

"""Security scan — unified tool for secret detection and dependency auditing.

Merges secret_scan + dependency_audit into a single tool via action parameter.
Capabilities: detect leaked API keys/tokens/passwords, audit project dependencies.
"""

from __future__ import annotations

import asyncio
import json
import logging
import math
import os
import re
import time
from pathlib import Path
from typing import Any

from .registry import register_tool

logger = logging.getLogger(__name__)

# ── Secret patterns ──
SECRET_PATTERNS = [
    {"name": "AWS Access Key", "pattern": r"AKIA[0-9A-Z]{16}", "severity": "critical"},
    {"name": "AWS Secret Key", "pattern": r"(?i)aws[_\-]?secret[_\-]?access[_\-]?key[\s:=]+['\"]?([A-Za-z0-9/+=]{40})", "severity": "critical"},
    {"name": "GitHub Token", "pattern": r"gh[pousr]_[A-Za-z0-9_]{36,255}", "severity": "critical"},
    {"name": "GitHub Fine-grained PAT", "pattern": r"github_pat_[A-Za-z0-9_]{22,255}", "severity": "critical"},
    {"name": "GitLab Token", "pattern": r"glpat-[A-Za-z0-9\-_]{20,}", "severity": "critical"},
    {"name": "Private Key (PEM)", "pattern": r"-----BEGIN (RSA |EC |DSA |OPENSSH )?PRIVATE KEY-----", "severity": "critical"},
    {"name": "Generic API Key", "pattern": r"(?i)(api[_\-]?key|apikey)[\s:=]+['\"]([A-Za-z0-9\-_]{20,})['\"]", "severity": "high"},
    {"name": "Generic Secret", "pattern": r"(?i)(secret|password|passwd|pwd)[\s:=]+['\"]([^'\"]{8,})['\"]", "severity": "high"},
    {"name": "Bearer Token", "pattern": r"(?i)bearer\s+[A-Za-z0-9\-_\.]{20,}", "severity": "high"},
    {"name": "Basic Auth", "pattern": r"(?i)basic\s+[A-Za-z0-9+/]{10,}={0,2}", "severity": "medium"},
    {"name": "MySQL Connection String", "pattern": r"(?i)mysql://[^:\s]+:[^@\s]+@[^\s]+", "severity": "critical"},
    {"name": "PostgreSQL Connection String", "pattern": r"(?i)postgres(ql)?://[^:\s]+:[^@\s]+@[^\s]+", "severity": "critical"},
    {"name": "MongoDB Connection String", "pattern": r"(?i)mongodb(\+srv)?://[^:\s]+:[^@\s]+@[^\s]+", "severity": "critical"},
    {"name": "Redis Connection String", "pattern": r"(?i)redis://[^:\s]*:[^@\s]+@[^\s]+", "severity": "high"},
    {"name": "Slack Token", "pattern": r"xox[baprs]-[0-9]{10,}-[A-Za-z0-9\-]+", "severity": "critical"},
    {"name": "OpenAI API Key", "pattern": r"sk-[A-Za-z0-9]{20}T3BlbkFJ[A-Za-z0-9]{20}", "severity": "critical"},
    {"name": "OpenAI API Key (new)", "pattern": r"sk-proj-[A-Za-z0-9\-_]{40,}", "severity": "critical"},
    {"name": "Anthropic API Key", "pattern": r"sk-ant-[A-Za-z0-9\-_]{40,}", "severity": "critical"},
    {"name": "Google API Key", "pattern": r"AIza[0-9A-Za-z\-_]{35}", "severity": "high"},
    {"name": "Stripe API Key", "pattern": r"[rs]k_(live|test)_[0-9a-zA-Z]{24,}", "severity": "critical"},
    {"name": "JWT Token", "pattern": r"eyJ[A-Za-z0-9\-_]+\.eyJ[A-Za-z0-9\-_]+\.[A-Za-z0-9\-_.+/=]+", "severity": "medium"},
]

# ── Skip patterns ──
_SKIP_DIRS = {".git", "node_modules", "__pycache__", "venv", ".venv", "dist", "build", ".tox", ".mypy_cache"}
_SKIP_EXTENSIONS = {".png", ".jpg", ".jpeg", ".gif", ".ico", ".woff", ".woff2", ".ttf", ".eot", ".pyc", ".pyo", ".so", ".dylib", ".dll", ".exe", ".bin", ".dat", ".db", ".sqlite"}

_MAX_SCAN_SIZE = 100 * 1024  # 100KB per file for secret scan


def _get_workspace() -> Path:
    try:
        from ...config.context import get_current_workspace_dir
        ws = get_current_workspace_dir()
        if ws:
            return Path(ws)
    except Exception:
        pass
    return Path.cwd()


def _shannon_entropy(s: str) -> float:
    if not s:
        return 0.0
    freq: dict[str, int] = {}
    for c in s:
        freq[c] = freq.get(c, 0) + 1
    length = len(s)
    return -sum((count / length) * math.log2(count / length) for count in freq.values())


async def _run_cmd(cmd: list[str], cwd: str | None = None, timeout: int = 30) -> dict[str, Any]:
    start = time.time()
    try:
        proc = await asyncio.create_subprocess_exec(
            *cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE, cwd=cwd,
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
    r = await _run_cmd(["npm", "audit", "--json"], cwd=project_path, timeout=60)
    if r["returncode"] == -1 and "ENOENT" in r["stderr"]:
        return {"status": "not_installed", "message": "npm 未安装"}
    vulns = []
    try:
        data = json.loads(r["stdout"])
        for name, info in data.get("vulnerabilities", {}).items():
            severity = info.get("severity", "unknown")
            via = [v if isinstance(v, str) else v.get("title", "") for v in info.get("via", [])]
            fix = info.get("fixAvailable", False)
            vulns.append({"package": name, "severity": severity, "via": via, "fix_available": fix})
    except Exception:
        pass
    return {"type": "npm", "vulnerabilities": vulns, "count": len(vulns)}


async def _audit_pip(project_path: str) -> dict[str, Any]:
    r = await _run_cmd(["pip-audit", "--format", "json"], cwd=project_path, timeout=60)
    if r["returncode"] == -1 and ("not found" in r["stderr"].lower() or "command not found" in r["stderr"].lower()):
        r2 = await _run_cmd(["python3", "-m", "pip_audit", "--format", "json"], cwd=project_path, timeout=60)
        if r2["returncode"] == -1:
            return {"status": "not_installed", "message": "pip-audit 未安装，请运行: pip install pip-audit"}
        r = r2
    vulns = []
    try:
        data = json.loads(r["stdout"])
        for dep in data.get("dependencies", []):
            for v in dep.get("vulns", []):
                vulns.append({
                    "package": dep.get("name", ""),
                    "version": dep.get("version", ""),
                    "vuln_id": v.get("id", ""),
                    "description": v.get("description", "")[:200],
                    "fix_versions": v.get("fix_versions", []),
                })
    except Exception:
        pass
    return {"type": "pip", "vulnerabilities": vulns, "count": len(vulns)}


async def _audit_go(project_path: str) -> dict[str, Any]:
    r = await _run_cmd(["govulncheck", "./..."], cwd=project_path, timeout=120)
    vulns = []
    try:
        for line in r["stdout"].split("\n"):
            if "Vulnerability" in line:
                vulns.append({"description": line.strip()})
    except Exception:
        pass
    return {"type": "go", "vulnerabilities": vulns, "count": len(vulns)}


@register_tool(
    name="security_scan",
    description="安全扫描：检测泄露的密钥/Token/密码 + 审计项目依赖漏洞（npm/pip/go）。secret_scan + dependency_audit 合并。",
    category="builtin",
    tags=["security", "scan", "secrets", "audit", "vulnerability"],
    scene="security",
)
async def security_scan(
    action: str = "scan_secrets",
    # Secret scan params
    path: str = "",
    # Dependency audit params
    project_path: str = "",
    # Common params
    severity_filter: str = "",
    limit: int = 50,
    **kwargs: Any,
) -> dict[str, Any]:
    """安全扫描统一工具。

    Args:
        action: 操作类型:
            - scan_secrets: 扫描代码中的泄露密钥
            - audit_deps: 审计项目依赖漏洞
            - audit_all: 自动检测项目类型并审计
            - list_patterns: 列出已知密钥模式
        path: 扫描路径（scan_secrets 时使用）
        project_path: 项目路径（audit_deps 时使用）
        severity_filter: 严重级别过滤
        limit: 最大返回数

    Returns:
        扫描结果
    """
    if action == "list_patterns":
        patterns = []
        for p in SECRET_PATTERNS:
            patterns.append({"name": p["name"], "severity": p["severity"], "regex": p["pattern"][:80] + "..."})
        return {"action": "list_patterns", "count": len(patterns), "patterns": patterns}

    elif action == "scan_secrets":
        scan_path = path.strip() or str(_get_workspace())
        scan_dir = Path(scan_path)
        if not scan_dir.exists():
            return {"error": f"路径不存在: {scan_path}"}

        findings = []
        files_scanned = 0
        files_skipped = 0

        for root, dirs, files in os.walk(scan_dir):
            dirs[:] = [d for d in dirs if d not in _SKIP_DIRS]
            for fname in files:
                ext = Path(fname).suffix.lower()
                if ext in _SKIP_EXTENSIONS:
                    files_skipped += 1
                    continue
                fpath = Path(root) / fname
                if fpath.stat().st_size > _MAX_SCAN_SIZE:
                    files_skipped += 1
                    continue
                try:
                    content = fpath.read_text(encoding="utf-8", errors="ignore")
                    files_scanned += 1
                    for pattern_def in SECRET_PATTERNS:
                        if severity_filter and pattern_def["severity"] != severity_filter:
                            continue
                        for m in re.finditer(pattern_def["pattern"], content):
                            entropy = _shannon_entropy(m.group(0)[:40])
                            if entropy < 2.5:
                                continue
                            line_num = content[:m.start()].count("\n") + 1
                            findings.append({
                                "file": str(fpath.relative_to(scan_dir)),
                                "line": line_num,
                                "secret_type": pattern_def["name"],
                                "severity": pattern_def["severity"],
                                "match_preview": m.group(0)[:10] + "...",
                                "entropy": round(entropy, 2),
                            })
                except Exception:
                    files_skipped += 1

        severity_order = {"critical": 0, "high": 1, "medium": 2, "low": 3}
        findings.sort(key=lambda x: severity_order.get(x["severity"], 99))

        return {
            "action": "scan_secrets",
            "files_scanned": files_scanned,
            "files_skipped": files_skipped,
            "findings_count": len(findings),
            "findings": findings[:limit],
            "summary": {
                "critical": sum(1 for f in findings if f["severity"] == "critical"),
                "high": sum(1 for f in findings if f["severity"] == "high"),
                "medium": sum(1 for f in findings if f["severity"] == "medium"),
            },
        }

    elif action in ("audit_deps", "audit_all"):
        audit_path = project_path.strip() or str(_get_workspace())
        project_types = _detect_project_type(audit_path)

        if not project_types:
            return {"error": "未检测到支持的项目类型（需要 package-lock.json / requirements.txt / go.sum 等）"}

        results = {}
        for ptype in project_types:
            if ptype == "npm":
                results["npm"] = await _audit_npm(audit_path)
            elif ptype == "pip":
                results["pip"] = await _audit_pip(audit_path)
            elif ptype == "go":
                results["go"] = await _audit_go(audit_path)

        total_vulns = sum(r.get("count", 0) for r in results.values())
        return {
            "action": action,
            "project_path": audit_path,
            "project_types": project_types,
            "results": results,
            "total_vulnerabilities": total_vulns,
        }

    else:
        return {"error": f"未知操作: {action}。支持: scan_secrets/audit_deps/audit_all/list_patterns"}


# ── Aliases for backward compatibility ──
secret_scan = security_scan
dependency_audit = security_scan
