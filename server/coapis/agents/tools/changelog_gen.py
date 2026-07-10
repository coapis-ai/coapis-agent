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
from __future__ import annotations
import asyncio, json, logging, re, time
from pathlib import Path
from typing import Any
from .registry import register_tool

logger = logging.getLogger(__name__)


async def _run_cmd(cmd: list[str], cwd: str | None = None, timeout: int = 15) -> dict[str, Any]:
    start = time.time()
    try:
        proc = await asyncio.create_subprocess_exec(
            *cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE, cwd=cwd
        )
        stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=timeout)
        return {"returncode": proc.returncode, "stdout": stdout.decode(errors="replace"),
                "stderr": stderr.decode(errors="replace"), "elapsed": round(time.time() - start, 2)}
    except Exception as e:
        return {"returncode": -1, "stdout": "", "stderr": str(e), "elapsed": 0}


def _parse_commits(log_text: str) -> list[dict[str, Any]]:
    """Parse git log into structured commits."""
    commits = []
    current = None
    for line in log_text.split("\n"):
        # Commit header: hash | author | date | subject
        m = re.match(r"^([a-f0-9]+)\|(.+?)\|(\d{4}-\d{2}-\d{2})\|(.+)$", line)
        if m:
            if current:
                commits.append(current)
            current = {
                "hash": m.group(1),
                "author": m.group(2).strip(),
                "date": m.group(3),
                "subject": m.group(4).strip(),
                "body": "",
            }
            continue
        # Body line
        if current and line.strip():
            current["body"] += line.strip() + " "
    if current:
        commits.append(current)
    return commits


def _categorize(subject: str) -> str:
    """Categorize commit by subject prefix."""
    s = subject.lower()
    if s.startswith("feat") or s.startswith("add") or s.startswith("新增"):
        return "✨ Features"
    elif s.startswith("fix") or s.startswith("bug") or s.startswith("修复"):
        return "🐛 Bug Fixes"
    elif s.startswith("refactor") or s.startswith("perf") or s.startswith("optimize"):
        return "⚡ Performance"
    elif s.startswith("docs") or s.startswith("doc"):
        return "📝 Documentation"
    elif s.startswith("test"):
        return "🧪 Tests"
    elif s.startswith("chore") or s.startswith("ci") or s.startswith("build"):
        return "🔧 Maintenance"
    elif "v0." in s and ":" in s:
        return "✨ Features"
    else:
        return "📦 Other"


def _generate_markdown(commits: list[dict[str, Any]], title: str = "") -> str:
    """Generate CHANGELOG markdown from commits."""
    if not title:
        title = time.strftime("v0.%m.%d (unreleased)")
    lines = [f"## [{title}]\n"]
    categories: dict[str, list[str]] = {}
    for c in commits:
        cat = _categorize(c["subject"])
        categories.setdefault(cat, []).append(f"- {c['subject']} (`{c['hash'][:7]}`)")

    cat_order = ["✨ Features", "🐛 Bug Fixes", "⚡ Performance", "📝 Documentation",
                 "🧪 Tests", "🔧 Maintenance", "📦 Other"]
    for cat in cat_order:
        if cat in categories:
            lines.append(f"### {cat}\n")
            lines.extend(categories[cat])
            lines.append("")

    if title and "date" in (commits[0] if commits else {}):
        lines.append(f"\n---\n*Generated on {time.strftime('%Y-%m-%d')}*\n")

    return "\n".join(lines)


async def changelog_gen(
    action: str = "generate",
    project_path: str = ".",
    since_tag: str = "",
    title: str = "",
    format: str = "markdown",
    count: int = 50,
    output: str = "",
) -> dict[str, Any]:
    """自动生成 CHANGELOG。

    Args:
        action: 操作类型 (generate/diff_between_tags/summary)
        project_path: 项目路径
        since_tag: 起始标签（如 v0.7.14）
        title: 版本标题
        format: 输出格式 (markdown/json)
        count: 最大提交数
        output: 输出文件路径

    Returns:
        生成的 CHANGELOG
    """
    # Build git log command
    cmd = ["git", "log", f"--max-count={count}", "--pretty=format:%H|%an|%ad|%s", "--date=short"]

    if since_tag.strip():
        cmd = ["git", "log", f"{since_tag.strip()}..HEAD", "--pretty=format:%H|%an|%ad|%s", "--date=short",
               f"--max-count={count}"]

    r = await _run_cmd(cmd, cwd=project_path)
    if r["returncode"] != 0:
        return {"error": f"git log 失败: {r['stderr'][:200]}"}

    commits = _parse_commits(r["stdout"])

    if not commits:
        return {"action": action, "message": "没有找到提交记录", "commits": 0}

    # Get latest tag for title
    if not title.strip():
        tag_r = await _run_cmd(["git", "describe", "--tags", "--abbrev=0"], cwd=project_path)
        latest_tag = tag_r["stdout"].strip() if tag_r["returncode"] == 0 else ""
        if latest_tag:
            title = f"{latest_tag} (next)"
        else:
            title = time.strftime("v0.%Y.%m.%d (unreleased)")

    if action == "generate":
        if format == "json":
            result = {"action": "generate", "title": title, "commits": commits, "count": len(commits)}
        else:
            md = _generate_markdown(commits, title)
            result = {"action": "generate", "title": title, "changelog": md,
                      "count": len(commits), "categories": {}}
            # Count by category
            for c in commits:
                cat = _categorize(c["subject"])
                result["categories"][cat] = result["categories"].get(cat, 0) + 1

        # Write to file if output specified
        if output.strip() and "changelog" in result:
            try:
                Path(output).write_text(result["changelog"], encoding="utf-8")
                result["written_to"] = output
            except Exception as e:
                result["write_error"] = str(e)

        return result

    elif action == "diff_between_tags":
        if not since_tag.strip():
            return {"error": "since_tag 不能为空"}
        # Get tags
        tags_r = await _run_cmd(["git", "tag", "-l", "--sort=-version:refname"], cwd=project_path)
        tags = [t.strip() for t in tags_r["stdout"].split("\n") if t.strip()]
        from_idx = -1
        for i, t in enumerate(tags):
            if t == since_tag:
                from_idx = i
                break
        if from_idx < 0 or from_idx + 1 >= len(tags):
            return {"error": f"未找到标签 {since_tag} 或其后续标签"}
        from_tag = tags[from_idx + 1]
        cmd2 = ["git", "log", f"{since_tag}..{from_tag}", "--pretty=format:%H|%an|%ad|%s", "--date=short"]
        r2 = await _run_cmd(cmd2, cwd=project_path)
        commits2 = _parse_commits(r2["stdout"])
        return {"action": "diff_between_tags", "from": since_tag, "to": from_tag,
                "count": len(commits2), "commits": commits2}

    elif action == "summary":
        cats = {}
        for c in commits:
            cat = _categorize(c["subject"])
            cats.setdefault(cat, []).append(c["subject"])
        return {"action": "summary", "total": len(commits), "categories": {k: len(v) for k, v in cats.items()},
                "authors": list(set(c["author"] for c in commits)),
                "date_range": f"{commits[-1]['date']} → {commits[0]['date']}" if len(commits) > 1 else commits[0]["date"]}

    else:
        return {"error": f"未知操作: {action}，支持 generate/diff_between_tags/summary"}
