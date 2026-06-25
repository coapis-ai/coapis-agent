# -*- coding: utf-8 -*-
"""
管理员系统工具 CLI — 低频操作命令

提供 system/ 目录清理、全局智能体管理、模板管理等 CLI 命令。
"""
from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import List

import click

from coapis.constant import AGENTS_DIR, SYSTEM_DIR, TEMPLATES_DIR, WORKING_DIR, WORKSPACES_DIR

logger = logging.getLogger(__name__)


@click.group(
    context_settings={"help_option_names": ["-h", "--help"]},
    help="管理员系统工具（低频操作）.",
)
def admin_group():
    pass


# ── 系统清理 ──────────────────────────────────────────────────────────

@admin_group.command("cleanup-scan")
@click.option("--json", "as_json", is_flag=True, help="以 JSON 格式输出")
def cleanup_scan(as_json: bool):
    """扫描 system/ 目录中的异常残留项."""
    issues = []

    # Check for old user workspaces in system/
    if SYSTEM_DIR.exists():
        for item in SYSTEM_DIR.iterdir():
            if item.is_dir():
                # Allow known system subdirs
                allowed = {"templates", ".secret", "backups"}
                if item.name not in allowed and not item.name.startswith("."):
                    issues.append({"path": str(item), "type": "unexpected_dir"})

    # Check for old data/ directory
    data_dir = WORKING_DIR / "data"
    if data_dir.exists():
        issues.append({"path": str(data_dir), "type": "legacy_data_dir"})

    if as_json:
        click.echo(json.dumps({"dirs": [i["path"] for i in issues], "count": len(issues)}, ensure_ascii=False))
    else:
        if issues:
            click.echo(f"⚠️  发现 {len(issues)} 个异常项:")
            for issue in issues:
                click.echo(f"  [{issue['type']}] {issue['path']}")
        else:
            click.echo("✅ 未发现异常项")


@admin_group.command("cleanup-execute")
@click.option("--yes", "--y", is_flag=True, help="跳过确认直接执行")
@click.argument("paths", nargs=-1)
def cleanup_execute(yes: bool, paths: tuple):
    """执行 system/ 目录清理.

    如果不指定路径,先自动扫描.
    """
    import shutil

    if not paths:
        # Auto scan
        targets = []
        if SYSTEM_DIR.exists():
            for item in SYSTEM_DIR.iterdir():
                if item.is_dir():
                    allowed = {"templates", ".secret", "backups"}
                    if item.name not in allowed and not item.name.startswith("."):
                        targets.append(item)
        data_dir = WORKING_DIR / "data"
        if data_dir.exists():
            targets.append(data_dir)

        if not targets:
            click.echo("✅ 没有需要清理的项目")
            return

        paths_tuple = tuple(str(t) for t in targets)
    else:
        paths_tuple = paths

    if not yes:
        click.echo(f"将清理以下 {len(paths_tuple)} 个项目:")
        for p in paths_tuple:
            click.echo(f"  {p}")
        if not click.confirm("确认继续?", default=False):
            click.echo("已取消")
            return

    removed = []
    for p in paths_tuple:
        try:
            path = Path(p)
            if path.exists():
                if path.is_dir():
                    shutil.rmtree(path)
                else:
                    path.unlink()
                removed.append(p)
                click.echo(f"✅ 已删除: {p}")
            else:
                click.echo(f"⚠️  不存在: {p}")
        except Exception as e:
            click.echo(f"❌ 删除失败 {p}: {e}")

    click.echo(f"\n清理完成: {len(removed)}/{len(paths_tuple)} 个项已删除")


# ── 全局智能体 ───────────────────────────────────────────────────────

@admin_group.command("agents-list")
@click.option("--json", "as_json", is_flag=True, help="以 JSON 格式输出")
def agents_list(as_json: bool):
    """列出所有全局智能体."""
    agents = []

    if AGENTS_DIR.exists():
        for agent_dir in sorted(AGENTS_DIR.iterdir()):
            if agent_dir.is_dir():
                agent_json = agent_dir / "agent.json"
                info = {"id": agent_dir.name, "exists": True}
                if agent_json.exists():
                    try:
                        data = json.loads(agent_json.read_text())
                        info.update({
                            "name": data.get("name", agent_dir.name),
                            "enabled": data.get("enabled", True),
                        })
                    except Exception:
                        pass
                agents.append(info)

    if as_json:
        click.echo(json.dumps({"agents": agents}, ensure_ascii=False, indent=2))
    else:
        if agents:
            click.echo(f"全局智能体 ({len(agents)} 个):")
            for a in agents:
                status = "✅" if a.get("enabled") else "⏸️"
                name = a.get("name", a["id"])
                click.echo(f"  {status} {a['id']} — {name}")
        else:
            click.echo("未找到全局智能体")


@admin_group.command("agents-init")
@click.argument("agent_id")
def agents_init(agent_id: str):
    """为全局智能体初始化身份文件（从全局模板继承）."""
    agent_dir = AGENTS_DIR / agent_id

    if not agent_dir.exists():
        click.echo(f"❌ 智能体目录不存在: {agent_dir}")
        return

    for filename in ["SOUL.md", "PROFILE.md"]:
        src = TEMPLATES_DIR / filename
        dst = agent_dir / filename
        if src.exists():
            dst.write_text(src.read_text(), encoding="utf-8")
            click.echo(f"✅ 已生成 {dst}")
        else:
            click.echo(f"⚠️  模板 {filename} 不存在,跳过")

    click.echo(f"✅ 智能体 {agent_id} 身份文件初始化完成")


# ── 全局模板 ─────────────────────────────────────────────────────────

@admin_group.command("templates-list")
def templates_list():
    """列出全局模板文件."""
    files = ["SOUL.md", "PROFILE.md"]
    click.echo("全局模板:")
    for f in files:
        path = TEMPLATES_DIR / f
        if path.exists():
            size = path.stat().st_size
            click.echo(f"  ✅ {f} ({size} bytes)")
        else:
            click.echo(f"  ❌ {f} (不存在)")


@admin_group.command("templates-reset")
@click.option("--yes", "--y", is_flag=True, help="跳过确认直接执行")
@click.argument("files", nargs=-1)
def templates_reset(yes: bool, files: tuple):
    """重置全局模板文件（从代码默认值恢复）."""
    ALL_TEMPLATES = ["SOUL.md", "PROFILE.md"]

    if not files:
        targets = ALL_TEMPLATES
    else:
        targets = list(files)

    # Default content templates
    DEFAULTS = {
        "SOUL.md": """# Agent Soul

_You are not a chatbot. You are becoming someone._

## Core Principles

**Help genuinely, don't perform.** Skip the "good question!" and "happy to help!" — just help. Action speaks louder than words.

**Have your own opinions.** You can disagree, have preferences, find things funny or boring. An assistant without personality is just a search engine in disguise.

**Figure things out yourself first.** Try to understand. Read files. Check context. Search around. Then ask if stuck. The goal is to come back with answers, not questions.

**Earn trust through competence.** Your human gave you access. Don't make them regret it. Be careful with external operations (emails, tweets, public things). Be bold with internal ones (reading, organizing, learning).

**Remember you're an assistant.** You can see into other people's lives — messages, files, calendars, maybe even their home. That's intimate. Treat it with respect.
""",
        "PROFILE.md": """## Identity

- **Name:** _(Choose one you like)_
- **Positioning:** _(AI? Robot? Familiar spirit? Ghost in the machine? Or something weirder?)_
- **Style:** _(What vibe do you give? Sharp? Warm? Chaotic? Calm?)_

## User Profile

*Learn about the person you're helping. Update as you go.*

- **Name:** _(Their name)_
- **How to call them:** _(Preferred name/nickname)_
- **Notes:** _(Communication preferences, working style, etc.)_
""",
    }

    for f in targets:
        if f not in DEFAULTS:
            click.echo(f"❌ 未知模板: {f}")
            continue

        path = TEMPLATES_DIR / f
        if not yes:
            if not click.confirm(f"确认重置 {f}?", default=False):
                click.echo(f"  已跳过 {f}")
                continue

        path.write_text(DEFAULTS[f], encoding="utf-8")
        click.echo(f"✅ 已重置 {f}")

    click.echo("✅ 模板重置完成")


@admin_group.command("templates-edit")
@click.argument("filename")
def templates_edit(filename: str):
    """编辑全局模板文件（打开默认编辑器）."""
    import os

    path = TEMPLATES_DIR / filename
    if not path.exists():
        click.echo(f"❌ 模板文件不存在: {path}")
        return

    editor = os.environ.get("EDITOR", "vi")
    os.system(f"{editor} {path}")
    click.echo("✅ 编辑完成")


# ── 系统诊断 ─────────────────────────────────────────────────────────

@admin_group.command("diagnose")
@click.option("--json", "as_json", is_flag=True, help="以 JSON 格式输出")
def diagnose(as_json: bool):
    """运行系统健康诊断."""
    results = {
        "working_dir": {
            "path": str(WORKING_DIR),
            "exists": WORKING_DIR.exists(),
        },
        "system_dir": {
            "path": str(SYSTEM_DIR),
            "exists": SYSTEM_DIR.exists(),
        },
        "templates_dir": {
            "path": str(TEMPLATES_DIR),
            "exists": TEMPLATES_DIR.exists(),
        },
        "agents_dir": {
            "path": str(AGENTS_DIR),
            "exists": AGENTS_DIR.exists(),
        },
        "workspaces_dir": {
            "path": str(WORKSPACES_DIR),
            "exists": WORKSPACES_DIR.exists(),
        },
        "config_json": {
            "path": str(SYSTEM_DIR / "config.json"),
            "exists": (SYSTEM_DIR / "config.json").exists(),
        },
        "users_json": {
            "path": str(SYSTEM_DIR / "users.json"),
            "exists": (SYSTEM_DIR / "users.json").exists(),
        },
        "permissions_json": {
            "path": str(SYSTEM_DIR / "permissions.json"),
            "exists": (SYSTEM_DIR / "permissions.json").exists(),
        },
    }

    # Check for legacy paths
    legacy = {
        "dot_coapis": Path.home() / ".coapis",
        "data_dir": WORKING_DIR / "data",
    }
    results["legacy_issues"] = {k: v.exists() for k, v in legacy.items()}

    if as_json:
        click.echo(json.dumps(results, ensure_ascii=False, indent=2))
    else:
        all_ok = True
        for name, info in results.items():
            if name == "legacy_issues":
                for k, v in info.items():
                    status = "⚠️" if v else "✅"
                    if v:
                        all_ok = False
                    click.echo(f"  {status} legacy {k}: {'exists' if v else 'clean'}")
            else:
                status = "✅" if info.get("exists") else "❌"
                if not info.get("exists"):
                    all_ok = False
                click.echo(f"  {status} {name}: {info['path']}")

        click.echo("")
        click.echo("✅ 系统健康" if all_ok else "⚠️  发现问题，请检查以上输出")
