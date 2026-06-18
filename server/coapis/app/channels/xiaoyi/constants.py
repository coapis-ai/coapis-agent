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

"""XiaoYi channel constants."""

# Default WebSocket URL
DEFAULT_WS_URL = "wss://hag.cloud.huawei.com/openclaw/v1/ws/link"

# Heartbeat interval (seconds)
HEARTBEAT_INTERVAL = 30

# Reconnect delays (seconds)
RECONNECT_DELAYS = [1, 2, 5, 10, 30, 60]
MAX_RECONNECT_ATTEMPTS = 50

# Connection timeout (seconds)
CONNECTION_TIMEOUT = 30

# Task timeout (milliseconds)
DEFAULT_TASK_TIMEOUT_MS = 3600000  # 1 hour

# Maximum text chunk size (characters)
# Larger messages will be split to avoid WebSocket disconnection
TEXT_CHUNK_LIMIT = 4000
