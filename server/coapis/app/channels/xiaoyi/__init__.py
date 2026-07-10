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

"""XiaoYi channel module.

XiaoYi (小艺) is Huawei's voice assistant platform.
This module implements A2A (Agent-to-Agent) protocol support.
"""

from .channel import XiaoYiChannel
from .auth import generate_auth_headers
from .constants import DEFAULT_WS_URL

__all__ = [
    "XiaoYiChannel",
    "generate_auth_headers",
    "DEFAULT_WS_URL",
]
