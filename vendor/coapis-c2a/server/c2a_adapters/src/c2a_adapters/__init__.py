"""
C2A (Chat-to-Action) Interactive Message Protocol - Channel Adapters SDK

This package provides adapters to transform C2A messages into platform-specific rich card formats.
"""

from .wecom import WecomTemplateCardAdapter
from .dingtalk import DingTalkActionCardAdapter
from .slack import SlackBlockKitAdapter
from .feishu import FeishuInteractiveMessageAdapter

__all__ = [
    "WecomTemplateCardAdapter",
    "DingTalkActionCardAdapter",
    "SlackBlockKitAdapter",
    "FeishuInteractiveMessageAdapter",
]
