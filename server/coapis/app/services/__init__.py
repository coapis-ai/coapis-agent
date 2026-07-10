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

"""CoApis Services Layer.

This package contains service-level abstractions that encapsulate
external system interactions (Seafile, etc.) and provide a unified
interface for the rest of the application.
"""

from .seafile_client import SeafileClient, SeafileConfig, SeafileError
from .file_service import (
    FileService,
    FileServiceFactory,
    LocalFileBackend,
    SeafileFileBackend,
    FileInfo,
)
from .user_sync_service import (
    UserSyncService,
    UserSyncConfig,
    SyncResult,
)

__all__ = [
    "SeafileClient",
    "SeafileConfig",
    "SeafileError",
    "FileService",
    "FileServiceFactory",
    "LocalFileBackend",
    "SeafileFileBackend",
    "FileInfo",
    "UserSyncService",
    "UserSyncConfig",
    "SyncResult",
]
