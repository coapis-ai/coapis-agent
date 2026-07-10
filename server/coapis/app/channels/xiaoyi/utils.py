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

"""XiaoYi channel utilities for file handling."""

import mimetypes
from pathlib import Path
from typing import Optional

import aiohttp


async def download_file(
    url: str,
    media_dir: Path,
    filename: str,
) -> Optional[str]:
    """Download file from URL to media_dir, return local path."""
    media_dir.mkdir(parents=True, exist_ok=True)

    async with aiohttp.ClientSession() as session:
        try:
            async with session.get(url) as resp:
                if resp.status >= 400:
                    return None

                data = await resp.read()
                content_type = (
                    resp.headers.get("Content-Type", "").split(";")[0].strip()
                )

                # Determine extension
                ext = ""
                if content_type:
                    ext = mimetypes.guess_extension(content_type) or ""
                if not ext:
                    ext = Path(filename).suffix or ".bin"

                # Build safe filename
                safe_name = "".join(
                    c for c in filename if c.isalnum() or c in "-_."
                )
                if not safe_name:
                    safe_name = "file"

                # Ensure unique extension
                if not Path(safe_name).suffix and ext:
                    safe_name = f"{Path(safe_name).stem}{ext}"

                path = media_dir / safe_name
                path.write_bytes(data)
                return str(path)

        except Exception:
            return None
