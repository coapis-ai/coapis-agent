# -*- coding: utf-8 -*-
# Copyright 2026 蜜蜂 & CoApis Contributors
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#     http://www.apache.org/licenses/LICENSE-2.0
#
# All builtin tools are auto-discovered via @register_tool decorator
# and the registry system. This file only imports the registry helpers
# and triggers auto-registration. Direct tool imports are no longer needed
# for injection — the framework uses get_registered_tools() instead.

from agentscope.tool import (
    execute_python_code,
    view_text_file,
    write_text_file,
)

# ── Plugin registry: auto-register all builtin tools ──
from .registry import register_tool, get_registered_tools, get_tool_names
from ._auto_register import register_all_builtin_tools
register_all_builtin_tools()

__all__ = [
    "execute_python_code",
    "view_text_file",
    "write_text_file",
    "register_tool",
    "get_registered_tools",
    "get_tool_names",
]
