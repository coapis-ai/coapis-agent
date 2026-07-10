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

"""File I/O for token usage data with atomic writes.
"""

import json
import logging
import os
from pathlib import Path

import aiofiles

logger = logging.getLogger(__name__)


async def load_data(path: Path) -> dict:
    """Load token usage data from *path*."""
    if not path.exists():
        return {}

    try:
        async with aiofiles.open(path, mode="r", encoding="utf-8") as f:
            raw = await f.read()
        data = json.loads(raw) if raw.strip() else {}
    except (json.JSONDecodeError, OSError) as exc:
        logger.warning(
            "token_usage: failed to read %s: %s — starting with empty data",
            path,
            exc,
        )
        return {}

    return data


def save_data_sync(path: Path, data: dict) -> None:
    """Persist *data* to *path* using an atomic write (tmp → replace).

    This is intentionally synchronous so it can be called from the buffer
    flush task without blocking the event loop via ``asyncio.to_thread``.
    """
    tmp_path = path.with_suffix(".tmp")
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        payload = json.dumps(data, ensure_ascii=False, indent=2)
        with open(tmp_path, mode="w", encoding="utf-8") as f:
            f.write(payload)
        os.replace(tmp_path, path)
    except OSError as exc:
        logger.warning(
            "token_usage: failed to write %s: %s",
            path,
            exc,
        )
        # Clean up orphaned tmp file if it was created.
        try:
            if tmp_path.exists():
                tmp_path.unlink()
        except OSError:
            pass


__all__ = [
    "load_data",
    "save_data_sync",
]
