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
