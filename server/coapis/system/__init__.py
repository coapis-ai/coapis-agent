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
