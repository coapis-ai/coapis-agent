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

"""SkillScanner - Scans directories for skills and validates them.

Used by SkillManager for discovery. Can also be used standalone
for skill validation and analysis.
"""

import json
import logging
import re
from pathlib import Path
from typing import Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)


class SkillScanner:
    """Scans and validates skill directories."""

    # Required files
    REQUIRED_FILES = {"SKILL.md"}
    # Optional files
    OPTIONAL_FILES = {"_meta.json", "scripts", "references", "hooks"}

    def __init__(self):
        self._errors: List[str] = []
        self._warnings: List[str] = []

    def scan_directory(self, path: Path) -> Optional[Dict]:
        """Scan a directory for skill structure.

        Args:
            path: Directory to scan

        Returns:
            Skill metadata dict or None if not a valid skill
        """
        self._errors = []
        self._warnings = []

        if not path.is_dir():
            return None

        # Check for required files
        skill_md = path / "SKILL.md"
        if not skill_md.exists():
            return None

        # Parse skill info
        name, description = self._parse_frontmatter(skill_md.read_text())
        if not name:
            self._errors.append("Missing or invalid skill name in SKILL.md")
            return None

        # Check for potential issues
        self._check_structure(path)
        self._check_meta(path)

        return {
            "name": name,
            "description": description,
            "path": str(path),
            "has_scripts": (path / "scripts").is_dir(),
            "has_references": (path / "references").is_dir(),
            "has_hooks": (path / "hooks").is_dir(),
            "errors": self._errors,
            "warnings": self._warnings,
        }

    def scan_directory_tree(self, root: Path) -> List[Dict]:
        """Scan a directory tree for all skills.

        Args:
            root: Root directory to scan

        Returns:
            List of skill metadata dicts
        """
        skills = []
        for item in root.iterdir():
            if item.is_dir():
                skill = self.scan_directory(item)
                if skill:
                    skills.append(skill)
        return skills

    def _parse_frontmatter(self, content: str) -> Tuple[str, str]:
        """Parse YAML frontmatter from SKILL.md."""
        name = ""
        description = ""

        if content.startswith("---"):
            parts = content.split("---", 2)
            if len(parts) >= 2:
                yaml_block = parts[1]
                for line in yaml_block.split("\n"):
                    if line.startswith("name:"):
                        name = line.split(":", 1)[1].strip().strip('"').strip("'")
                    elif line.startswith("description:"):
                        description = line.split(":", 1)[1].strip().strip('"').strip("'")

        return name, description

    def _check_structure(self, path: Path):
        """Check skill directory structure."""
        # Check for required files
        for req_file in self.REQUIRED_FILES:
            if not (path / req_file).exists():
                self._errors.append(f"Missing required file: {req_file}")

        # Check for optional files
        for opt_file in self.OPTIONAL_FILES:
            if (path / opt_file).exists():
                if opt_file == "_meta.json":
                    self._check_meta(path)

    def _check_meta(self, path: Path):
        """Validate _meta.json if present."""
        meta_file = path / "_meta.json"
        if meta_file.exists():
            try:
                meta = json.loads(meta_file.read_text())
                if not isinstance(meta, dict):
                    self._errors.append("_meta.json must be a JSON object")
            except json.JSONDecodeError:
                self._errors.append("Invalid JSON in _meta.json")

    def validate_skill(self, path: Path) -> Tuple[bool, List[str], List[str]]:
        """Validate a skill directory.

        Args:
            path: Skill directory to validate

        Returns:
            Tuple of (is_valid, errors, warnings)
        """
        result = self.scan_directory(path)
        if result:
            return (
                len(result["errors"]) == 0,
                result["errors"],
                result["warnings"],
            )
        return False, ["Not a valid skill directory"], []
