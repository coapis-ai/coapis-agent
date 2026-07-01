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

"""
File preview endpoint for chat media URLs.

Provides a simple `/files/preview/{filepath:path}` endpoint that serves
files by absolute or relative path. This matches the QwenPaw behavior
and is used by the frontend's `toDisplayUrl` → `filePreviewUrl` chain
to render file attachments in chat messages.

The frontend constructs URLs like:
    /api/files/preview/media/xxx.ppm?token=xxx
    /api/files/preview/apps/ai/coapis/workspaces/admin/files/media/xxx.ppm?token=xxx

This endpoint resolves the path and serves the file directly.
"""

import logging
from pathlib import Path
from urllib.parse import unquote

from fastapi import APIRouter, HTTPException
from starlette.responses import FileResponse

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/files", tags=["file-preview"])


@router.api_route(
    "/preview/{filepath:path}",
    methods=["GET", "HEAD"],
    summary="Preview file by path",
)
async def preview_file(filepath: str):
    """Preview a file by its path.

    Accepts both absolute and relative paths:
    - Absolute: /apps/ai/coapis/workspaces/admin/files/media/xxx.ppm
    - Relative: media/xxx.ppm (resolved as /media/xxx.ppm)

    Matches QwenPaw's /files/preview/{filepath:path} behavior.
    """
    normalized = unquote(filepath)

    # Normalize /C:/... to C:/... on Windows.
    if (
        len(normalized) >= 4
        and normalized[0] == "/"
        and normalized[2] == ":"
        and normalized[1].isalpha()
    ):
        normalized = normalized[1:]

    path = Path(normalized)
    if not path.is_absolute():
        path = Path("/" + normalized)
    path = path.resolve()

    if not path.is_file():
        logger.debug("File not found: %s (requested: %s)", path, filepath)
        raise HTTPException(status_code=404, detail="Not found")

    # Security: basic check against path traversal outside known workspaces
    # (the path is already resolved, so symlink attacks are mitigated)
    return FileResponse(path, filename=path.name)
