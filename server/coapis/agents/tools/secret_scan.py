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

"""Secret scan — detect API keys, passwords, tokens and other sensitive data in code and files.

Uses regex patterns + entropy analysis to find leaked secrets.
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
    {"name": "Slack Webhook", "pattern": r"https://hooks\.slack\.com/services/T[A-Z0-9]+/B[A-Z0-9]+/[A-Za-z0-9]+", "severity": "high"},
    {"name": "OpenAI API Key", "pattern": r"sk-[A-Za-z0-9]{20,}T3BlbkFJ[A-Za-z0-9]{20,}", "severity": "critical"},
    {"name": "OpenAI API Key (new)", "pattern": r"sk-(?:proj-)?[A-Za-z0-9\-_]{40,}", "severity": "critical"},
    {"name": "Anthropic API Key", "pattern": r"sk-ant-[A-Za-z0-9\-_]{40,}", "severity": "critical"},
    {"name": "Google API Key", "pattern": r"AIza[0-9A-Za-z\-_]{35}", "severity": "critical"},
    {"name": "Google OAuth", "pattern": r"[0-9]+-[A-Za-z0-9_]{32}\.apps\.googleusercontent\.com", "severity": "high"},
    {"name": "Stripe Key", "pattern": r"[sr]k_(?:live|test)_[A-Za-z0-9]{24,}", "severity": "critical"},
    {"name": "Twilio API Key", "pattern": r"SK[0-9a-fA-F]{32}", "severity": "high"},
    {"name": "SendGrid API Key", "pattern": r"SG\.[A-Za-z0-9\-_]{22}\.[A-Za-z0-9\-_]{43}", "severity": "critical"},
    {"name": "Heroku API Key", "pattern": r"(?i)heroku[_\-]?api[_\-]?key[\s:=]+['\"]?([0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12})", "severity": "critical"},
    {"name": "Hardcoded IP:Port", "pattern": r"\b(?:10\.|172\.(?:1[6-9]|2[0-9]|3[01])\.|192\.168\.)\d{1,3}\.\d{1,3}:\d{1,5}\b", "severity": "medium"},
]

# File extensions to scan
SCAN_EXTENSIONS = {
    ".py", ".js", ".ts", ".jsx", ".tsx", ".java", ".go", ".rs", ".rb", ".php",
    ".env", ".env.*", ".cfg", ".conf", ".config", ".yaml", ".yml", ".toml",
    ".json", ".xml", ".ini", ".sh", ".bash", ".zsh", ".sql", ".md", ".txt",
    ".dockerfile", ".tf", ".hcl",
}

SKIP_DIRS = {
    ".git", "node_modules", "__pycache__", ".venv", "venv", "env",
    ".tox", ".mypy_cache", ".pytest_cache", "dist", "build", ".eggs",
}


def _shannon_entropy(data: str) -> float:
    """Calculate Shannon entropy of a string."""
    if not data:
        return 0.0
    freq = {}
    for c in data:
        freq[c] = freq.get(c, 0) + 1
    length = len(data)
    return -sum((count / length) * math.log2(count / length) for count in freq.values())


def _should_skip(path: Path) -> bool:
    """Check if path should be skipped."""
    for part in path.parts:
        if part in SKIP_DIRS:
            return True
    return False


def _scan_file(filepath: Path, custom_patterns: list[dict] | None = None) -> list[dict[str, Any]]:
    """Scan a single file for secrets."""
    findings = []
    patterns = SECRET_PATTERNS + (custom_patterns or [])

    try:
        content = filepath.read_text(encoding="utf-8", errors="ignore")
        lines = content.split("\n")
    except Exception:
        return findings

    for line_num, line in enumerate(lines, 1):
        # Skip comments (simple heuristic)
        stripped = line.strip()
        if stripped.startswith("#") or stripped.startswith("//") or stripped.startswith("*"):
            continue

        for pat in patterns:
            try:
                match = re.search(pat["pattern"], line)
                if match:
                    # Entropy check for generic patterns
                    if pat["name"] in ("Generic API Key", "Generic Secret"):
                        captured = match.group(2) if match.lastindex and match.lastindex >= 2 else match.group(1) if match.lastindex else ""
                        if _shannon_entropy(captured) < 3.0:
                            continue

                    findings.append({
                        "file": str(filepath),
                        "line": line_num,
                        "pattern": pat["name"],
                        "severity": pat["severity"],
                        "context": stripped[:120],
                    })
            except re.error:
                continue

    return findings


async def secret_scan(
    path: str = ".",
    extensions: str = "",
    exclude: str = "",
    max_file_size_kb: int = 1024,
    min_severity: str = "low",
) -> dict[str, Any]:
    """密钥泄露检测。

    扫描代码和文件中的敏感信息。

    Args:
        path: 扫描路径（文件或目录）
        extensions: 自定义扩展名过滤（逗号分隔）
        exclude: 排除路径模式（逗号分隔）
        max_file_size_kb: 最大文件大小 KB，默认 1024
        min_severity: 最低严重级别 (low/medium/high/critical)

    Returns:
        扫描结果和发现列表
    """
    target = Path(path).resolve()
    if not target.exists():
        return {"error": f"路径不存在: {path}"}

    ext_filter = None
    if extensions.strip():
        ext_filter = {e.strip() if e.strip().startswith(".") else f".{e.strip()}" for e in extensions.split(",")}

    exclude_patterns = []
    if exclude.strip():
        exclude_patterns = [e.strip() for e in exclude.split(",")]

    severity_order = {"low": 0, "medium": 1, "high": 2, "critical": 3}
    min_sev = severity_order.get(min_severity, 0)

    # Collect files
    files = []
    if target.is_file():
        files = [target]
    else:
        for f in target.rglob("*"):
            if not f.is_file():
                continue
            if _should_skip(f.relative_to(target)):
                continue
            if f.stat().st_size > max_file_size_kb * 1024:
                continue
            ext = f.suffix.lower()
            if ext_filter and ext not in ext_filter:
                continue
            skip = False
            for ep in exclude_patterns:
                if ep in str(f):
                    skip = True
                    break
            if not skip:
                files.append(f)

    # Scan
    all_findings = []
    for f in files:
        findings = _scan_file(f)
        all_findings.extend(findings)

    # Filter by severity
    filtered = [f for f in all_findings if severity_order.get(f["severity"], 0) >= min_sev]

    # Group by severity
    by_severity = {}
    for f in filtered:
        sev = f["severity"]
        by_severity.setdefault(sev, []).append(f)

    return {
        "scan_path": str(target),
        "files_scanned": len(files),
        "total_findings": len(filtered),
        "by_severity": {k: len(v) for k, v in by_severity.items()},
        "findings": filtered[:100],  # cap at 100
        "truncated": len(filtered) > 100,
        "critical_count": len(by_severity.get("critical", [])),
        "clean": len(filtered) == 0,
    }
