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

"""Shared constants and path helpers used across backup sub-modules."""
from __future__ import annotations

import re
from pathlib import Path

from ...constant import BACKUP_DIR

META_FILE = "meta.json"

# Zip internal path prefixes – defined once to avoid scattered hardcoding.
# PREFIX_CONFIG is intentionally hardcoded to "data/config.json" and NOT
# derived from the COAPIS_CONFIG_FILE env-var so that backup archives are
# portable across installations regardless of runtime configuration.
PREFIX_WORKSPACES = "data/workspaces/"
PREFIX_SECRETS = "data/secrets/"
PREFIX_SKILL_POOL = "data/skill_pool/"
PREFIX_CONFIG = "data/config.json"

# Allowed characters for a backup ID. Accepts both the new human-readable
# format (coapis-{ver}-{ts}-{short8}) and legacy UUID strings.
# Forbids path-traversal characters: '/', '\', '..', NUL, etc.
BACKUP_ID_RE = re.compile(r"^[a-zA-Z0-9._-]{1,200}$")


def validate_backup_id(backup_id: str) -> None:
    """Raise ``ValueError`` if *backup_id* contains unsafe characters."""
    if not BACKUP_ID_RE.match(backup_id):
        raise ValueError(
            f"Invalid backup id {backup_id!r}: "
            f"must match {BACKUP_ID_RE.pattern}",
        )


def zip_path(backup_id: str) -> Path:
    return BACKUP_DIR / f"{backup_id}.zip"
