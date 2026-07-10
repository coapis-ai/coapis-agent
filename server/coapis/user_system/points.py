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

"""Points service — STUB (removed in simplification).

The points/level system has been removed to simplify user management.
This file is kept as a stub for backward compatibility with imports.
"""
from __future__ import annotations

import logging
from typing import Optional

logger = logging.getLogger(__name__)


def add_points(username: str, amount: int, source: str, description: Optional[str] = None) -> int:
    """No-op: points system removed."""
    return 0


def spend_points(username: str, amount: int, source: str, description: Optional[str] = None) -> bool:
    """No-op: points system removed."""
    return True


def manual_add_points(req) -> int:
    """No-op: points system removed."""
    return 0


def get_point_transactions(username: str, page: int = 1, page_size: int = 50, source: Optional[str] = None):
    """No-op: points system removed."""
    from .models import UserSettingsList
    return UserSettingsList(settings=[])
