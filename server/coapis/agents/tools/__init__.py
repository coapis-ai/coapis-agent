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
from agentscope.tool import (
    execute_python_code,
    view_text_file,
    write_text_file,
)

# ── Plugin registry: auto-register all builtin tools ──
from .registry import register_tool, get_registered_tools, get_tool_names, apply_tool_descriptions
from ._auto_register import register_all_builtin_tools
register_all_builtin_tools()

# ── Apply tool descriptions from data pack (language-aware) ──
try:
    apply_tool_descriptions("zh")
except Exception:
    pass

__all__ = [
    "execute_python_code",
    "view_text_file",
    "write_text_file",
    "register_tool",
    "get_registered_tools",
    "get_tool_names",
]
