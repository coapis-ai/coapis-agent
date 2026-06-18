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

from __future__ import annotations

import shutil
from pathlib import Path

import click

from ..constant import WORKING_DIR
from ..utils.telemetry import TELEMETRY_MARKER_FILE


def _iter_children(p: Path) -> list[Path]:
    if not p.exists():
        return []
    return sorted(list(p.iterdir()), key=lambda x: x.name)


# pylint: disable=too-many-branches
@click.command("clean")
@click.option("--yes", is_flag=True, help="Do not prompt for confirmation")
@click.option(
    "--dry-run",
    is_flag=True,
    help="List what would be deleted, but do not delete",
)
def clean_cmd(yes: bool, dry_run: bool) -> None:
    """Clear CoApis WORKING_DIR (~/.coapis by default)."""
    wd = WORKING_DIR

    if not wd.exists():
        click.echo(f"WORKING_DIR does not exist: {wd}")
        return

    children = _iter_children(wd)
    # Filter out the telemetry marker file
    telemetry_marker = wd / TELEMETRY_MARKER_FILE
    children = [c for c in children if c != telemetry_marker]

    if not children:
        if telemetry_marker.exists():
            click.echo(
                "WORKING_DIR has no removable files",
            )
        else:
            click.echo(f"WORKING_DIR is already empty: {wd}")
        return

    click.echo(f"WORKING_DIR: {wd}")
    click.echo("Will remove:")
    for c in children:
        click.echo(f"  - {c}")
    if telemetry_marker.exists():
        click.echo(f"Will keep: {TELEMETRY_MARKER_FILE}")

    if dry_run:
        click.echo("dry-run: nothing deleted.")
        return

    if not yes:
        ok = click.confirm(f"Delete ALL contents under {wd}?", default=False)
        if not ok:
            click.echo("Cancelled.")
            return

    # delete contents, keep the directory itself
    for c in children:
        try:
            if c.is_dir() and not c.is_symlink():
                shutil.rmtree(c)
            else:
                c.unlink()
        except FileNotFoundError:
            pass

    click.echo("Done.")
