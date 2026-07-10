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

"""Twilio API wrapper for the Voice channel."""
from __future__ import annotations

import asyncio
import logging
from functools import partial

logger = logging.getLogger(__name__)


class TwilioManager:
    """Async wrapper around the synchronous ``twilio`` Python SDK."""

    def __init__(self, account_sid: str, auth_token: str) -> None:
        self._account_sid = account_sid
        self._auth_token = auth_token
        self._client = None  # lazy init

    def _get_client(self):
        if self._client is None:
            from twilio.rest import Client

            self._client = Client(self._account_sid, self._auth_token)
        return self._client

    async def _run_sync(self, fn, *args, **kwargs):
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(None, partial(fn, *args, **kwargs))

    async def configure_voice_webhook(
        self,
        phone_number_sid: str,
        webhook_url: str,
        status_callback_url: str = "",
    ) -> None:
        """Update the voice webhook URL on an existing phone number."""
        client = self._get_client()

        def _configure():
            kwargs = {
                "voice_url": webhook_url,
                "voice_method": "POST",
            }
            if status_callback_url:
                kwargs["status_callback"] = status_callback_url
                kwargs["status_callback_method"] = "POST"
            client.incoming_phone_numbers(phone_number_sid).update(
                **kwargs,
            )

        await asyncio.wait_for(self._run_sync(_configure), timeout=30)
        logger.info(
            "Twilio webhook configured: sid=%s url=%s",
            phone_number_sid,
            webhook_url,
        )
