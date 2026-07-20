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

"""Models package."""

from .scene import (
    SceneConfig,
    SceneAgentConfig,
    SceneInfo,
    Capabilities,
    EvolutionConfig,
    ModelConfig,
)
from .tag import (
    TagType,
    TagConfig,
    TagCreateRequest,
    TagUpdateRequest,
    TagListResponse,
    TagTreeItem,
)

__all__ = [
    # Scene models
    "SceneConfig",
    "SceneAgentConfig",
    "SceneInfo",
    "Capabilities",
    "EvolutionConfig",
    "ModelConfig",
    # Tag models
    "TagType",
    "TagConfig",
    "TagCreateRequest",
    "TagUpdateRequest",
    "TagListResponse",
    "TagTreeItem",
]
