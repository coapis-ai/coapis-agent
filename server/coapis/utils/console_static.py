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

"""Resolve the web console static assets directory (shared by app and CLI)."""
from __future__ import annotations

import os
from pathlib import Path

from ..constant import EnvVarLoader

# Primary env key (``COAPIS_CONSOLE_STATIC_DIR`` is accepted as a legacy
# fallback via :class:`~coapis.constant.EnvVarLoader`).
CONSOLE_STATIC_ENV = "COAPIS_CONSOLE_STATIC_DIR"


def resolve_console_static_dir() -> str:
    """Return the directory expected to contain ``index.html`` for the console.

    Resolution order matches :mod:`coapis.app._app`: env override, package
    ``coapis/console``, repo ``console/dist``, then cwd fallbacks.
    """
    static_dir = EnvVarLoader.get_str("COAPIS_CONSOLE_STATIC_DIR")
    if static_dir:
        return static_dir

    pkg_dir = Path(__file__).resolve().parent.parent
    candidate = pkg_dir / "console"
    if candidate.is_dir() and (candidate / "index.html").is_file():
        return str(candidate)

    repo_dir = pkg_dir.parent.parent
    candidate = repo_dir / "console" / "dist"
    if candidate.is_dir() and (candidate / "index.html").is_file():
        return str(candidate)

    cwd = Path(os.getcwd())
    for subdir in ("console/dist", "console_dist"):
        candidate = cwd / subdir
        if candidate.is_dir() and (candidate / "index.html").is_file():
            return str(candidate)

    return str(cwd / "console" / "dist")


def find_coapis_source_repo_root() -> Path | None:
    """Return the git checkout root if this Python
    is running from CoApis source.

    Looks upward from :mod:`coapis` for ``console/package.json``,
    ``console/package-lock.json``, and ``src/coapis/``
    (bundled static target).
    Returns ``None`` for a normal pip/wheel install.
    """
    try:
        import coapis  # noqa: PLC0415 — avoid import cycle at module load
    except Exception:  # pylint: disable=broad-exception-caught
        return None
    cur = Path(coapis.__file__).resolve().parent
    for _ in range(20):
        con = cur / "console"
        if (
            (con / "package.json").is_file()
            and (con / "package-lock.json").is_file()
            and (cur / "src" / "coapis").is_dir()
        ):
            return cur
        if cur.parent == cur:
            break
        cur = cur.parent
    return None
