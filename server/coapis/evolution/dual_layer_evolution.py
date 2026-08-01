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

"""Dual Layer Evolution Engine.

This module implements the dual-layer evolution mechanism for scene agents:

Layer 1: Shared Evolution (Scene Agent)
    - Shared experiences across all users
    - Best practices and common patterns
    - Stored in agents/scene-{scene_id}/MEMORY.md

Layer 2: Personal Evolution (User Agent)
    - User-specific preferences and context
    - Personal memory and history
    - Stored in workspaces/{user_id}/MEMORY.md

Evolution Flow:
    User interacts with scene
        ↓
    Analyze interaction quality
        ↓
    Classify experience type:
        - Shared → Update scene agent MEMORY.md
        - Personal → Update user agent MEMORY.md
        ↓
    Dual-layer memory updated
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from ..models.scene import SceneAgentConfig, EvolutionConfig
from ..exceptions import SceneAgentError

logger = logging.getLogger(__name__)


class EvolutionType:
    """Evolution type classification."""
    
    SHARED = "shared"       # Shared across all users
    PERSONAL = "personal"   # User-specific
    BOTH = "both"           # Both shared and personal


class EvolutionEntry:
    """Single evolution entry."""
    
    def __init__(
        self,
        content: str,
        evolution_type: str,
        confidence: float = 0.7,
        metadata: Optional[Dict[str, Any]] = None,
    ):
        self.timestamp = datetime.now(timezone.utc).isoformat()
        self.content = content
        self.evolution_type = evolution_type
        self.confidence = confidence
        self.metadata = metadata or {}
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "timestamp": self.timestamp,
            "content": self.content,
            "type": self.evolution_type,
            "confidence": self.confidence,
            "metadata": self.metadata,
        }


class DualLayerEvolutionEngine:
    """Engine for managing dual-layer evolution.
    
    This engine analyzes conversations and updates both:
    1. Scene agent memory (shared evolution)
    2. User agent memory (personal evolution)
    
    Usage:
        engine = DualLayerEvolutionEngine(data_dir)
        engine.evolve(
            scene_id="meeting-minutes",
            user_id="alice",
            conversation=[...],
            metadata={...}
        )
    """
    
    def __init__(self, data_dir: Path):
        """Initialize dual-layer evolution engine.
        
        Args:
            data_dir: Data directory (e.g., server/data)
        """
        self.data_dir = Path(data_dir)
        self.agents_dir = self.data_dir / "agents"
        self.workspaces_dir = self.data_dir / "workspaces"
        
        # Ensure directories exist
        self.agents_dir.mkdir(parents=True, exist_ok=True)
        self.workspaces_dir.mkdir(parents=True, exist_ok=True)
    
    # -------------------------------------------------------------------------
    # Main Evolution API
    # -------------------------------------------------------------------------
    
    def evolve(
        self,
        scene_id: str,
        user_id: str,
        conversation: List[Dict[str, Any]],
        metadata: Optional[Dict[str, Any]] = None,
    ) -> Tuple[Optional[str], Optional[str]]:
        """Evolve both scene agent and user agent based on conversation.
        
        This method:
        1. Analyzes conversation quality
        2. Classifies evolution entries (shared/personal)
        3. Updates scene agent memory (shared)
        4. Updates user agent memory (personal)
        
        Args:
            scene_id: Scene ID (e.g., meeting-minutes)
            user_id: User ID
            conversation: Conversation messages
            metadata: Additional metadata
        
        Returns:
            Tuple of (shared_evolution, personal_evolution) or None if no evolution
        """
        # Analyze conversation for evolution opportunities
        evolution_entries = self._analyze_conversation(conversation, metadata)
        
        if not evolution_entries:
            logger.debug(f"No evolution opportunities found for scene {scene_id}")
            return None, None
        
        # Separate shared and personal entries
        shared_entries = [e for e in evolution_entries if e.evolution_type in [EvolutionType.SHARED, EvolutionType.BOTH]]
        personal_entries = [e for e in evolution_entries if e.evolution_type in [EvolutionType.PERSONAL, EvolutionType.BOTH]]
        
        # Update scene agent memory (shared)
        shared_evolution = None
        if shared_entries:
            shared_evolution = self._update_scene_memory(scene_id, shared_entries)
        
        # Update user agent memory (personal)
        personal_evolution = None
        if personal_entries:
            personal_evolution = self._update_user_memory(user_id, scene_id, personal_entries)
        
        logger.info(
            f"Evolved scene {scene_id} for user {user_id}: "
            f"{len(shared_entries)} shared, {len(personal_entries)} personal"
        )
        
        return shared_evolution, personal_evolution
    
    # -------------------------------------------------------------------------
    # Conversation Analysis
    # -------------------------------------------------------------------------
    
    def _analyze_conversation(
        self,
        conversation: List[Dict[str, Any]],
        metadata: Optional[Dict[str, Any]] = None,
    ) -> List[EvolutionEntry]:
        """Analyze conversation for evolution opportunities.
        
        This method identifies:
        - Best practices (shared)
        - Common patterns (shared)
        - User preferences (personal)
        - User context (personal)
        
        Args:
            conversation: Conversation messages
            metadata: Additional metadata
        
        Returns:
            List of EvolutionEntry
        """
        entries = []
        
        # Simple heuristic-based analysis
        # In production, this could use LLM to analyze conversation
        
        for msg in conversation:
            role = msg.get("role", "")
            content = msg.get("content", "")
            
            # Skip system messages
            if role == "system":
                continue
            
            # Analyze user messages for preferences
            if role == "user":
                preference = self._extract_user_preference(content)
                if preference:
                    entries.append(EvolutionEntry(
                        content=preference,
                        evolution_type=EvolutionType.PERSONAL,
                        confidence=0.8,
                        metadata={"source": "user_preference"},
                    ))
            
            # Analyze assistant messages for best practices
            if role == "assistant":
                best_practice = self._extract_best_practice(content)
                if best_practice:
                    entries.append(EvolutionEntry(
                        content=best_practice,
                        evolution_type=EvolutionType.SHARED,
                        confidence=0.7,
                        metadata={"source": "best_practice"},
                    ))
        
        return entries
    
    def _extract_user_preference(self, content: str) -> Optional[str]:
        """Extract user preference from message content.
        
        Simple heuristic: look for preference indicators.
        
        Args:
            content: Message content
        
        Returns:
            Extracted preference or None
        """
        # Simple heuristics
        preference_indicators = [
            "我喜欢", "我希望", "请记住", "下次",
            "我更喜欢", "我的习惯", "我通常",
        ]
        
        for indicator in preference_indicators:
            if indicator in content:
                # Extract sentence with preference
                sentences = content.split("。")
                for sentence in sentences:
                    if indicator in sentence:
                        return f"用户偏好: {sentence.strip()}"
        
        return None
    
    def _extract_best_practice(self, content: str) -> Optional[str]:
        """Extract best practice from assistant message.
        
        Simple heuristic: look for structured output patterns.
        
        Args:
            content: Message content
        
        Returns:
            Extracted best practice or None
        """
        # Simple heuristics
        if len(content) > 100:
            # Long, structured responses might contain best practices
            if "：" in content or ":" in content:
                # Contains structured format
                return f"最佳实践: 使用结构化输出格式"
        
        return None
    
    # -------------------------------------------------------------------------
    # Memory Updates
    # -------------------------------------------------------------------------
    
    def _update_scene_memory(
        self,
        scene_id: str,
        entries: List[EvolutionEntry],
    ) -> Optional[str]:
        """Update scene agent shared memory.
        
        Args:
            scene_id: Scene ID
            entries: Shared evolution entries
        
        Returns:
            Summary of evolution or None
        """
        scene_agent_dir = self.agents_dir / f"scene-{scene_id}"
        memory_file = scene_agent_dir / "MEMORY.md"
        
        if not scene_agent_dir.exists():
            logger.warning(f"Scene agent directory not found: {scene_agent_dir}")
            return None
        
        # Read existing memory
        existing_memory = ""
        if memory_file.exists():
            existing_memory = memory_file.read_text(encoding="utf-8")
        
        # Append new evolution entries
        new_entries = []
        for entry in entries:
            if entry.content not in existing_memory:
                new_entries.append(entry)
        
        if not new_entries:
            return None
        
        # Build evolution content
        evolution_content = self._build_evolution_content(new_entries, "共享进化")
        
        # Append to memory file
        with open(memory_file, "a", encoding="utf-8") as f:
            f.write(evolution_content)
        
        logger.info(f"Updated scene memory: {scene_id} with {len(new_entries)} entries")
        
        return f"新增 {len(new_entries)} 条共享进化"
    
    def _update_user_memory(
        self,
        user_id: str,
        scene_id: str,
        entries: List[EvolutionEntry],
    ) -> Optional[str]:
        """Update user agent personal memory.
        
        Args:
            user_id: User ID
            scene_id: Scene ID (for context)
            entries: Personal evolution entries
        
        Returns:
            Summary of evolution or None
        """
        user_workspace_dir = self.workspaces_dir / user_id
        memory_file = user_workspace_dir / "MEMORY.md"
        
        # Ensure user workspace exists
        user_workspace_dir.mkdir(parents=True, exist_ok=True)
        
        # Read existing memory
        existing_memory = ""
        if memory_file.exists():
            existing_memory = memory_file.read_text(encoding="utf-8")
        else:
            # Create initial memory file
            initial_content = f"# {user_id} 的个人记忆\n\n此文件记录用户在使用场景智能体时的个人偏好和上下文。\n\n---\n\n## 进化记录\n\n"
            memory_file.write_text(initial_content, encoding="utf-8")
        
        # Append new evolution entries
        new_entries = []
        for entry in entries:
            if entry.content not in existing_memory:
                new_entries.append(entry)
        
        if not new_entries:
            return None
        
        # Build evolution content
        evolution_content = self._build_evolution_content(
            new_entries,
            f"个人进化 (场景: {scene_id})"
        )
        
        # Append to memory file
        with open(memory_file, "a", encoding="utf-8") as f:
            f.write(evolution_content)
        
        logger.info(f"Updated user memory: {user_id} with {len(new_entries)} entries")
        
        return f"新增 {len(new_entries)} 条个人进化"
    
    def _build_evolution_content(
        self,
        entries: List[EvolutionEntry],
        section_title: str,
    ) -> str:
        """Build evolution content for memory file.
        
        Args:
            entries: Evolution entries
            section_title: Section title
        
        Returns:
            Formatted content
        """
        content_lines = [
            "",
            f"### {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M')}",
            "",
        ]
        
        for entry in entries:
            content_lines.append(f"- {entry.content}")
            if entry.metadata:
                content_lines.append(f"  - 来源: {entry.metadata.get('source', 'unknown')}")
            content_lines.append(f"  - 置信度: {entry.confidence:.2f}")
        
        content_lines.append("")
        
        return "\n".join(content_lines)
    
    # -------------------------------------------------------------------------
    # Utility Methods
    # -------------------------------------------------------------------------
    
    def get_scene_memory(self, scene_id: str) -> str:
        """Get scene agent shared memory content.
        
        Args:
            scene_id: Scene ID
        
        Returns:
            Memory content or empty string
        """
        memory_file = self.agents_dir / f"scene-{scene_id}" / "MEMORY.md"
        if not memory_file.exists():
            return ""
        return memory_file.read_text(encoding="utf-8")
    
    def get_user_memory(self, user_id: str) -> str:
        """Get user agent personal memory content.
        
        Args:
            user_id: User ID
        
        Returns:
            Memory content or empty string
        """
        memory_file = self.workspaces_dir / user_id / "MEMORY.md"
        if not memory_file.exists():
            return ""
        return memory_file.read_text(encoding="utf-8")
