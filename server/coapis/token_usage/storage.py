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
