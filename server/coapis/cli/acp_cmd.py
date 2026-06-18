# -*- coding: utf-8 -*-
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
