# -*- coding: utf-8 -*-
"""Channel dependency registry.

Each channel declares its optional PyPI packages. When a channel is
enabled but the import fails, the ChannelManager will attempt to
install the missing packages on-demand.

Format: { channel_key: [package_spec, ...] }

package_spec can be:
  - "package_name" — latest version
  - "package_name>=1.0.0" — version constraint
  - "package_name[extra]>=1.0.0" — extras + constraint
"""

# ── Channel → required PyPI packages ──

CHANNEL_DEPENDENCIES: dict[str, list[str]] = {
    # ── Enterprise messaging ──
    "wecom": ["wecom-aibot-python-sdk>=1.0.0"],
    "dingtalk": [
        "dingtalk-stream",
        "alibabacloud_dingtalk",
        "alibabacloud_tea_openapi",
        "alibabacloud_tea_util",
    ],
    "feishu": ["lark-oapi>=1.2.0"],
    "weixin": ["wechatpy>=1.8.18"],

    # ── Open protocols ──
    "discord": ["discord.py>=2.3.0"],
    "telegram": ["python-telegram-bot>=21.0"],
    "matrix": ["matrix-nio>=0.22.0"],
    "mattermost": ["mattermostdriver>=8.0.0"],
    "qq": ["napcat-api>=2.0.0"],
    "onebot": ["pygobot>=1.0.0"],

    # ── Voice / SIP ──
    "voice": ["twilio>=9.0.0"],
    "sip": ["pyvoip>=0.5.0"],

    # ── MQTT / IoT ──
    "mqtt": ["paho-mqtt>=2.0.0"],

    # ── iMessage (macOS only) ──
    "imessage": ["pyatv>=0.10.0"],

    # ── Huawei Cloud XiaoYi ──
    "xiaoyi": [],

    # ── Console ──
    "console": [],
}

# ── Common transitive dependencies shared across many channels ──
# These are safe to install unconditionally if missing.
SHARED_DEPENDENCIES: list[str] = [
    "aiohttp>=3.9.0",
    "httpx>=0.27.0",
]


def get_channel_dependencies(channel_key: str) -> list[str]:
    """Return the list of PyPI packages required by a channel.

    Args:
        channel_key: Channel key (e.g. 'wecom', 'discord').

    Returns:
        List of package specifiers (e.g. ['wecom-aibot-python-sdk>=1.0.0']).
        Returns empty list if channel has no optional dependencies.
    """
    return CHANNEL_DEPENDENCIES.get(channel_key, [])
