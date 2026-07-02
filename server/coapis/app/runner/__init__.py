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
