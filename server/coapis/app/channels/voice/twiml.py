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

"""TwiML generation helpers for the Voice channel."""
from __future__ import annotations

import xml.etree.ElementTree as ET


def build_conversation_relay_twiml(
    ws_url: str,
    *,
    welcome_greeting: str = "Hi! How can I help you?",
    tts_provider: str = "google",
    tts_voice: str = "en-US-Journey-D",
    stt_provider: str = "deepgram",
    language: str = "en-US",
    interruptible: bool = True,
) -> str:
    """Build TwiML ``<Response>`` that connects to ConversationRelay.

    Returns an XML string suitable as an HTTP response to Twilio's
    incoming call webhook.
    """
    response_el = ET.Element("Response")
    connect_el = ET.SubElement(response_el, "Connect")
    ET.SubElement(
        connect_el,
        "ConversationRelay",
        url=ws_url,
        welcomeGreeting=welcome_greeting,
        ttsProvider=tts_provider,
        voice=tts_voice,
        transcriptionProvider=stt_provider,
        language=language,
        interruptible=str(interruptible).lower(),
    )
    xml_body = ET.tostring(response_el, encoding="unicode")
    return f'<?xml version="1.0" encoding="UTF-8"?>{xml_body}'


def build_busy_twiml(
    message: str = "On another call. Please try again later.",
) -> str:
    """Build TwiML that speaks a busy message.

    Twilio automatically ends the call after all verbs complete.
    """
    response_el = ET.Element("Response")
    say_el = ET.SubElement(response_el, "Say")
    say_el.text = message
    xml_body = ET.tostring(response_el, encoding="unicode")
    return f'<?xml version="1.0" encoding="UTF-8"?>{xml_body}'


def build_error_twiml(
    message: str = "An error occurred. Please try again later.",
) -> str:
    """Build TwiML that speaks an error message.

    Twilio automatically ends the call after all verbs complete.
    """
    return build_busy_twiml(message)
