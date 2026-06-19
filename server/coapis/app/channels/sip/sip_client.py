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

"""SIP outbound call management."""
from __future__ import annotations

import logging

logger = logging.getLogger(__name__)

FAILED_HANGUP_CAUSES = {
    "NO_ANSWER",
    "USER_BUSY",
    "CALL_REJECTED",
    "NO_USER_RESPONSE",
    "NETWORK_OUT_OF_ORDER",
    "DESTINATION_OUT_OF_ORDER",
    "NORMAL_TEMPORARY_FAILURE",
    "SUBSCRIBER_ABSENT",
    "UNALLOCATED_NUMBER",
    "INVALID_NUMBER_FORMAT",
    "RECOVERY_ON_TIMER_EXPIRE",
}


class CallFailedError(Exception):
    def __init__(
        self,
        cause: str,
        message: str = "",
    ) -> None:
        self.cause = cause
        super().__init__(
            message or f"Call failed: {cause}",
        )
