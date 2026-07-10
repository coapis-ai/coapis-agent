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

"""Runner module with chat manager for coordinating repository.

All heavy imports (agentscope, model factories, etc.) are lazy so that
CLI commands like ``coapis daemon`` can load ``daemon_commands`` without
pulling in the full runtime.
"""

_LAZY_IMPORTS = {
    "AgentRunner": (".runner", "AgentRunner"),
    "router": (".api", "router"),
    "ChatManager": (".manager", "ChatManager"),
    "ChatSpec": (".models", "ChatSpec"),
    "ChatHistory": (".models", "ChatHistory"),
    "ChatsFile": (".models", "ChatsFile"),
    "BaseChatRepository": (".repo", "BaseChatRepository"),
    "JsonChatRepository": (".repo", "JsonChatRepository"),
}

__all__ = list(_LAZY_IMPORTS)


def __getattr__(name: str):
    if name in _LAZY_IMPORTS:
        module_path, attr = _LAZY_IMPORTS[name]
        import importlib
        mod = importlib.import_module(module_path, __name__)
        return getattr(mod, attr)
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
