# -*- coding: utf-8 -*-
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

"""CLI daemon subcommands: status, restart, reload-config, version, logs.

Shares execution with in-chat /daemon <sub> via daemon_commands.
"""
from __future__ import annotations

import asyncio
from pathlib import Path

import click

from ..app.runner.daemon_commands import (
    DaemonContext,
    run_daemon_logs,
    run_daemon_reload_config,
    run_daemon_restart,
    run_daemon_status,
    run_daemon_version,
)
from ..constant import WORKING_DIR
from ..config import load_config


def _get_agent_workspace(agent_id: str) -> Path:
    """Get agent workspace directory."""
    try:
        config = load_config()
        if agent_id in config.agents.profiles:
            ref = config.agents.profiles[agent_id]
            workspace_dir = Path(ref.workspace_dir).expanduser()
            return workspace_dir
    except Exception:
        pass
    return WORKING_DIR


def _context(agent_id: str) -> DaemonContext:
    working_dir = _get_agent_workspace(agent_id)
    return DaemonContext(
        working_dir=working_dir,
        memory_manager=None,
        manager=None,  # CLI has no access to MultiAgentManager
        agent_id=agent_id,
    )


@click.group("daemon")
def daemon_group() -> None:
    """Daemon commands: status, restart, reload-config, version, logs."""


@daemon_group.command("status")
@click.option(
    "--agent-id",
    default="default",
    help="Agent ID (defaults to 'default')",
)
def status_cmd(agent_id: str) -> None:
    """Show daemon status (config, working dir, memory manager)."""
    ctx = _context(agent_id)
    click.echo(f"Agent: {agent_id}\n")
    click.echo(run_daemon_status(ctx))


@daemon_group.command("restart")
@click.option(
    "--agent-id",
    default="default",
    help="Agent ID (defaults to 'default')",
)
def restart_cmd(agent_id: str) -> None:
    """Print restart instructions (CLI has no process to restart)."""
    ctx = _context(agent_id)
    click.echo(f"Agent: {agent_id}\n")
    click.echo(asyncio.run(run_daemon_restart(ctx)))


@daemon_group.command("reload-config")
@click.option(
    "--agent-id",
    default="default",
    help="Agent ID (defaults to 'default')",
)
def reload_config_cmd(agent_id: str) -> None:
    """Reload config (re-read from file)."""
    ctx = _context(agent_id)
    click.echo(f"Agent: {agent_id}\n")
    click.echo(run_daemon_reload_config(ctx))


@daemon_group.command("version")
@click.option(
    "--agent-id",
    default="default",
    help="Agent ID (defaults to 'default')",
)
def version_cmd(agent_id: str) -> None:
    """Show version and paths."""
    ctx = _context(agent_id)
    click.echo(f"Agent: {agent_id}\n")
    click.echo(run_daemon_version(ctx))


@daemon_group.command("logs")
@click.option(
    "-n",
    "--lines",
    default=100,
    type=int,
    help="Number of last lines to show (default 100).",
)
def logs_cmd(lines: int) -> None:
    """Tail last N lines of WORKING_DIR/coapis.log."""
    lines = min(max(1, lines), 2000)
    click.echo(run_daemon_logs(lines=lines))
