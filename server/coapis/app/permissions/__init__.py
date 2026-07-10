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

"""Permissions module for CoApis.

Config-driven permission system (Phase 2).
Loads permissions from config/permissions.json, supports hot-reload.
"""

from .manager import PermissionManager
from .decorators import require_permission, require_role, require_module_access

__all__ = [
    "PermissionManager",
    "require_permission",
    "require_role",
    "require_module_access",
]
