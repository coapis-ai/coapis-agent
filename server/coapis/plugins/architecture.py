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

"""Plugin architecture definitions."""

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional
from pathlib import Path


@dataclass
class PluginEntryPoints:
    """Plugin entry points for frontend and backend."""

    frontend: Optional[str] = None
    backend: Optional[str] = None


@dataclass
class PluginManifest:
    """Plugin manifest definition."""

    id: str
    name: str
    version: str
    description: str = ""
    author: str = ""
    entry: PluginEntryPoints = field(default_factory=PluginEntryPoints)
    dependencies: List[str] = field(default_factory=list)
    min_version: str = "0.1.0"
    meta: Dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "PluginManifest":
        """Create manifest from dictionary.

        Args:
            data: Manifest data dictionary

        Returns:
            PluginManifest instance
        """
        entry_data = data.get("entry", {})
        legacy_entry_point = data.get("entry_point", "plugin.py")
        entry = PluginEntryPoints(
            frontend=entry_data.get("frontend"),
            backend=entry_data.get("backend") or legacy_entry_point,
        )

        return cls(
            id=data["id"],
            name=data["name"],
            version=data["version"],
            description=data.get("description", ""),
            author=data.get("author", ""),
            entry=entry,
            dependencies=data.get("dependencies", []),
            min_version=data.get("min_version", "0.1.0"),
            meta=data.get("meta", {}),
        )


@dataclass
class PluginRecord:
    """Plugin record for loaded plugins."""

    manifest: PluginManifest
    source_path: Path
    enabled: bool
    instance: Optional[Any] = None
    diagnostics: List[str] = field(default_factory=list)
