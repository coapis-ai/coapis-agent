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

"""DingTalk channel helpers (media suffix guess, etc.)."""

from pathlib import Path
from typing import Optional

# Magic bytes -> suffix for .file fallback (DingTalk URLs often return .file).
# AMR-NB voice: "#!AMR\n"
DINGTALK_MAGIC_SUFFIX: list[tuple[bytes, str]] = [
    (b"%PDF", ".pdf"),
    (b"PK\x03\x04", ".zip"),
    (b"PK\x05\x06", ".zip"),
    (b"\x89PNG\r\n\x1a\n", ".png"),
    (b"\xff\xd8\xff", ".jpg"),
    (b"GIF87a", ".gif"),
    (b"GIF89a", ".gif"),
    (b"\xd0\xcf\x11\xe0", ".doc"),
    (b"RIFF", ".webp"),
    (b"#!AMR\n", ".amr"),
]


def guess_suffix_from_file_content(path: Path) -> Optional[str]:
    """Guess suffix from file magic bytes. Returns e.g. '.pdf' or None."""
    try:
        with open(path, "rb") as f:
            head = f.read(32)
        for magic, suffix in DINGTALK_MAGIC_SUFFIX:
            if head.startswith(magic):
                return suffix
        return None
    except Exception:
        return None
