# -*- coding: utf-8 -*-
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

"""coapis uninstall — remove the CoApis environment and CLI wrapper."""
from __future__ import annotations

import shutil
import re
from pathlib import Path

import click

from ..constant import WORKING_DIR


# Directories created by the installer (relative to WORKING_DIR).
_INSTALLER_DIRS = ("venv", "bin")

# Shell profiles to clean up.
_SHELL_PROFILES = (
    Path.home() / ".zshrc",
    Path.home() / ".bashrc",
    Path.home() / ".bash_profile",
)


def _remove_path_entry(profile: Path) -> bool:
    """
    Remove CoApis PATH lines from a shell profile. Returns True if changed.
    """
    if not profile.is_file():
        return False

    text = profile.read_text()
    # Remove the "# CoApis" comment line and the export PATH line
    cleaned = re.sub(
        r"\n?# CoApis\nexport PATH=\"\$HOME/\.coapis/bin:\$PATH\"\n?",
        "\n",
        text,
    )
    if cleaned == text:
        return False

    profile.write_text(cleaned)
    return True


@click.command("uninstall")
@click.option(
    "--purge",
    is_flag=True,
    help="Also remove all data (config, chats, models, etc.)",
)
@click.option("--yes", is_flag=True, help="Do not prompt for confirmation")
def uninstall_cmd(purge: bool, yes: bool) -> None:
    """Remove CoApis environment, CLI wrapper, and shell PATH entries."""
    wd = WORKING_DIR

    if purge:
        click.echo(f"This will remove ALL CoApis data in {wd}")
    else:
        click.echo(
            "This will remove the CoApis Python environment and CLI wrapper.",
        )
        click.echo(f"Your configuration and data in {wd} will be preserved.")

    if not yes:
        ok = click.confirm("Continue?", default=False)
        if not ok:
            click.echo("Cancelled.")
            return

    # Remove installer-managed directories
    for dirname in _INSTALLER_DIRS:
        d = wd / dirname
        if d.exists():
            shutil.rmtree(d)
            click.echo(f"  Removed {d}")

    # Purge everything if requested
    if purge and wd.exists():
        shutil.rmtree(wd)
        click.echo(f"  Removed {wd}")

    # Clean shell profiles
    for profile in _SHELL_PROFILES:
        if _remove_path_entry(profile):
            click.echo(f"  Cleaned {profile}")

    click.echo("")
    click.echo("CoApis uninstalled. Please restart your terminal.")
