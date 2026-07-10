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

"""
Agent tools schema: type definitions for agent tool responses.
"""
from typing import Literal, Optional
from typing_extensions import TypedDict, Required

from agentscope.message import Base64Source, URLSource


class FileBlock(TypedDict, total=False):
    """File block for sending files to users."""

    type: Required[Literal["file"]]
    """The type of the block"""

    source: Required[Base64Source | URLSource]
    """The source of the file"""

    filename: Optional[str]
    """The filename of the file"""
