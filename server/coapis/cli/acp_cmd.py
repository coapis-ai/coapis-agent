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

"""``coapis acp`` — run CoApis as an ACP agent over stdio."""
from __future__ import annotations

import asyncio
import logging

import click


@click.command("acp")
@click.option(
    "--agent",
    default=None,
    help="Agent ID to use (defaults to active agent)",
)
@click.option(
    "--workspace",
    default=None,
    type=click.Path(exists=False),
    help="Workspace directory override",
)
@click.option(
    "--debug",
    is_flag=True,
    default=False,
    help="Enable debug logging to stderr",
)
def acp_cmd(
    agent: str | None,
    workspace: str | None,
    debug: bool,
) -> None:
    """Start CoApis as an ACP agent (stdio)."""
    from pathlib import Path

    level = logging.DEBUG if debug else logging.WARNING
    logging.basicConfig(
        level=level,
        format="%(levelname)s %(name)s: %(message)s",
    )

    workspace_dir = Path(workspace) if workspace else None

    from ..agents.acp.server import run_coapis_agent

    asyncio.run(
        run_coapis_agent(
            agent_id=agent,
            workspace_dir=workspace_dir,
        ),
    )
