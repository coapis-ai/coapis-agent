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
