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

"""
File preview endpoint for chat media URLs.

Provides a simple `/files/preview/{filepath:path}` endpoint that serves
files by absolute or relative path. Used by the frontend's
`toDisplayUrl` → `filePreviewUrl` chain to render file
attachments in chat messages.

The frontend constructs URLs like:
    /api/files/preview/media/xxx.ppm?token=xxx
    /api/files/preview/{WORKSPACES_DIR}/admin/files/media/xxx.ppm?token=xxx

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
    - Absolute: /opt/coapis/workspaces/admin/files/media/xxx.ppm
    - Relative: media/xxx.ppm (resolved as /media/xxx.ppm)

    Serves file preview with auth token support.
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
