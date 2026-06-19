# -*- coding: utf-8 -*-
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
