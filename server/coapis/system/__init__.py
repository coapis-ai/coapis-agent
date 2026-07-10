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

"""CoApis System Initialization Module.

Provides unified initialization for:
- Directory structure
- Default configuration files
- Default data (users, permissions, roles)
- Version migration
"""
from .defaults import (
    SYSTEM_VERSION,
    INIT_SCHEMA_VERSION,
    DEFAULT_CONFIG,
    DEFAULT_PERMISSIONS,
    DEFAULT_ROLES,
    DEFAULT_ADMIN_USER,
)
from .initializer import (
    SystemInitializer,
    initialize_system,
    check_system_status,
)

__all__ = [
    "SYSTEM_VERSION",
    "INIT_SCHEMA_VERSION",
    "DEFAULT_CONFIG",
    "DEFAULT_PERMISSIONS",
    "DEFAULT_ROLES",
    "DEFAULT_ADMIN_USER",
    "SystemInitializer",
    "initialize_system",
    "check_system_status",
]
