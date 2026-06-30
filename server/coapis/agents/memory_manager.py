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

"""MemoryManager - Manages agent memory with context fencing.

Inspired by external reference's memory_manager.py.
Supports built-in memory provider plus external plugin providers.
"""

import json
import logging
import re
from pathlib import Path
from typing import Dict, List, Optional, Any

logger = logging.getLogger(__name__)

# Context fencing patterns
_FENCE_TAG_RE = re.compile(r'</?\s*memory-context\s*>', re.IGNORECASE)
_INTERNAL_CONTEXT_RE = re.compile(
    r'<\s*memory-context\s*>[\s\S]*?</\s*memory-context\s*>',
    re.IGNORECASE,
)


class MemoryManager:
    """Manages agent memory across multiple sources.

    v0.5.1: Simplified to only handle USER.md and MEMORY.md.
    AGENTS.md and SOUL.md are managed by the configuration system directly.

    Memory types:
    - USER.md: User preferences, persona, details
    - MEMORY.md: Agent experience, lessons learned
    """

    def __init__(self, workspace_dir: Path):
        self.workspace_dir = workspace_dir
        self._memory_files = {
            "user": workspace_dir / "USER.md",
            "agent": workspace_dir / "MEMORY.md",
        }
        self._cache: Dict[str, str] = {}
        self._dirty: Dict[str, bool] = {}

    def get_context(self) -> str:
        """Get combined memory context for system prompt."""
        parts = []
        for name in ["user", "agent"]:
            content = self._load(name)
            if content and content.strip():
                parts.append(f"## {name.title()} Memory\n{content}")
        return "\n\n".join(parts) if parts else ""

    def prefetch(self, user_message: str) -> str:
        """Prefetch relevant memory based on user message.

        Args:
            user_message: Current user message

        Returns:
            Relevant memory context
        """
        # Simple keyword-based relevance (can be enhanced with semantic search)
        relevant = []
        for name in ["user", "agent"]:
            content = self._load(name)
            if content:
                relevant.append(content)
        return "\n\n".join(relevant) if relevant else ""

    def save(self, memory_type: str, content: str, append: bool = True):
        """Save memory content.

        Args:
            memory_type: Type of memory (user/agent/identity/soul)
            content: Content to save
            append: Whether to append to existing content
        """
        if memory_type not in self._memory_files:
            raise ValueError(f"Unknown memory type: {memory_type}")

        filepath = self._memory_files[memory_type]

        if append and filepath.exists():
            existing = filepath.read_text()
            if existing.strip():
                content = existing + "\n\n" + content

        filepath.write_text(content)
        self._cache[memory_type] = content
        self._dirty.pop(memory_type, None)
        logger.info(f"Memory saved: {memory_type} ({len(content)} chars)")

    def update(self, memory_type: str, old_text: str, new_text: str) -> bool:
        """Update memory by replacing text.

        Args:
            memory_type: Type of memory
            old_text: Text to replace
            new_text: Replacement text

        Returns:
            True if updated, False if old_text not found
        """
        content = self._load(memory_type)
        if old_text in content:
            content = content.replace(old_text, new_text)
            self.save(memory_type, content, append=False)
            return True
        return False

    def _load(self, memory_type: str) -> str:
        """Load memory content with caching."""
        if memory_type in self._cache:
            return self._cache[memory_type]

        filepath = self._memory_files.get(memory_type)
        if filepath and filepath.exists():
            content = filepath.read_text()
            self._cache[memory_type] = content
            return content
        return ""

    def sanitize(self, text: str) -> str:
        """Strip fence tags and injected context from memory output."""
        text = _INTERNAL_CONTEXT_RE.sub('', text)
        text = _FENCE_TAG_RE.sub('', text)
        return text

    def list_entries(self, memory_type: str) -> List[Dict[str, Any]]:
        """List memory entries (parsed from markdown)."""
        content = self._load(memory_type)
        entries = []
        current_entry = {}

        for line in content.split("\n"):
            if line.startswith("## "):
                if current_entry:
                    entries.append(current_entry)
                current_entry = {"section": line[3:].strip(), "content": ""}
            elif current_entry:
                current_entry["content"] += line + "\n"

        if current_entry:
            entries.append(current_entry)

        return entries

    def list_memory_tools(self) -> list:
        """Return memory-related tool functions for agent registration.

        This simplified MemoryManager does not expose additional memory tools.
        The BaseMemoryManager (in agents/memory/) provides full tool support.
        """
        return []

    async def close(self):
        """No-op. This simple file-based MemoryManager has no async resources
        to release.  Exists so callers (e.g. runner finally block) can
        uniformly call ``await memory_manager.close()`` without guarding."""
        pass
