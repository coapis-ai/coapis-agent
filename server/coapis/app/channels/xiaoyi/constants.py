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
