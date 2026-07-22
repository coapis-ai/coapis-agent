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

"""Scene Agent Service - manages scene configuration and scene agents.

Scene Agent Architecture:
    - Scene Agent: Global shared agent providing business capabilities
    - User Agent: Personal isolated agent providing identity and memory
    - Runtime: Scene Agent + User Agent = Complete AI capability

This service handles:
    - Scene CRUD (create, read, update, delete)
    - Scene Agent lifecycle management
    - Scene index management (scenes.json)
"""

from __future__ import annotations

import json
import logging
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

from ..models.scene import (
    SceneConfig,
    SceneConfigCreate,
    SceneConfigUpdate,
    SceneAgentConfig,
    SceneInfo,
    Capabilities,
    EvolutionConfig,
    ModelConfig,
    SceneListResponse,
    ScenesFile,
    EnterSceneRequest,
    EnterSceneResponse,
)
from ..exceptions import SceneNotFoundError, SceneAgentError

logger = logging.getLogger(__name__)


class SceneAgentService:
    """Service for managing scene configuration and scene agents.
    
    Storage:
        - scenes.json: Scene index file
        - agents/scene-{scene_id}/: Scene agent directory
        - agents/scene-{scene_id}/agent.json: Scene agent configuration
        - agents/scene-{scene_id}/MEMORY.md: Shared evolution memory
    
    Scene Agent Naming Convention:
        - Scene ID: meeting-minutes
        - Scene Agent ID: scene-meeting-minutes
        - Scene Agent Directory: agents/scene-meeting-minutes/
    """
    
    def __init__(self, data_dir: Optional[Path] = None):
        """Initialize scene agent service.
        
        Args:
            data_dir: Data directory path (default: WORKING_DIR)
        """
        if data_dir is None:
            # Use WORKING_DIR from constant
            from ..constant import WORKING_DIR
            data_dir = Path(WORKING_DIR)
        
        self.data_dir = Path(data_dir)
        self.scenes_file = self.data_dir / "scenes.json"
        self.agents_dir = self.data_dir / "agents"
        
        # Ensure directories exist
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.agents_dir.mkdir(parents=True, exist_ok=True)
    
    # -------------------------------------------------------------------------
    # Scene Configuration Management
    # -------------------------------------------------------------------------
    
    def list_scenes(
        self,
        status: Optional[str] = None,
        category: Optional[str] = None,
        tag: Optional[str] = None,
    ) -> SceneListResponse:
        """List all scenes with optional filtering.
        
        Args:
            status: Filter by status (active/disabled/deleted)
            category: Filter by category
            tag: Filter by tag
        
        Returns:
            SceneListResponse with scene list
        """
        scenes_file = self._load_scenes_file()
        scenes = scenes_file.scenes
        
        # Apply filters
        if status:
            scenes = [s for s in scenes if s.status == status]
        if category:
            scenes = [s for s in scenes if s.category == category]
        if tag:
            scenes = [s for s in scenes if tag in s.tags]
        
        return SceneListResponse(scenes=scenes, total=len(scenes))
    
    def get_scene(self, scene_id: str) -> Optional[SceneConfig]:
        """Get scene configuration by ID.
        
        Args:
            scene_id: Scene ID (e.g., meeting-minutes)
        
        Returns:
            SceneConfig or None if not found
        """
        scenes_file = self._load_scenes_file()
        for scene in scenes_file.scenes:
            if scene.id == scene_id:
                return scene
        return None
    
    def create_scene(
        self,
        scene_create: SceneConfigCreate,
        created_by: Optional[str] = None,
    ) -> SceneConfig:
        """Create a new scene.
        
        This method:
        1. Creates scene configuration in scenes.json
        2. Creates scene agent directory and configuration
        
        Args:
            scene_create: Scene creation request
            created_by: Creator username
        
        Returns:
            Created SceneConfig
        
        Raises:
            ValueError: If scene ID already exists
        """
        # Check if scene ID already exists
        if self.get_scene(scene_create.id):
            raise ValueError(f"Scene ID already exists: {scene_create.id}")
        
        # Create scene configuration
        now = datetime.now(timezone.utc).isoformat()
        scene_config = SceneConfig(
            id=scene_create.id,
            name=scene_create.name,
            icon=scene_create.icon,
            description=scene_create.description,
            short_description=scene_create.short_description,
            primary_tag_id=scene_create.primary_tag_id,
            tag_ids=scene_create.tag_ids,
            skills=scene_create.skills,
            system_prompt=scene_create.system_prompt,
            welcome_message=scene_create.welcome_message,
            status=scene_create.status,
            created_at=now,
            updated_at=now,
            created_by=created_by,
        )
        
        # Add to scenes.json
        scenes_file = self._load_scenes_file()
        scenes_file.scenes.append(scene_config)
        self._save_scenes_file(scenes_file)
        
        # Create scene agent
        self._create_scene_agent(scene_config, created_by)
        
        logger.info(f"Created scene: {scene_config.id} by {created_by}")
        return scene_config
    
    def update_scene(
        self,
        scene_id: str,
        scene_update: SceneConfigUpdate,
    ) -> Optional[SceneConfig]:
        """Update scene configuration.
        
        Args:
            scene_id: Scene ID
            scene_update: Scene update request
        
        Returns:
            Updated SceneConfig or None if not found
        """
        scenes_file = self._load_scenes_file()
        
        for i, scene in enumerate(scenes_file.scenes):
            if scene.id == scene_id:
                # Update fields
                update_data = scene_update.model_dump(exclude_unset=True)
                for key, value in update_data.items():
                    if value is not None:
                        setattr(scene, key, value)
                
                # Update timestamp
                scene.updated_at = datetime.now(timezone.utc).isoformat()
                
                # Save
                scenes_file.scenes[i] = scene
                self._save_scenes_file(scenes_file)
                
                # Update scene agent
                self._update_scene_agent(scene)
                
                logger.info(f"Updated scene: {scene_id}")
                return scene
        
        return None
    
    def delete_scene(self, scene_id: str, hard_delete: bool = False) -> bool:
        """Delete scene (soft delete by default).
        
        Args:
            scene_id: Scene ID
            hard_delete: If True, permanently delete scene and agent
        
        Returns:
            True if deleted, False if not found
        """
        scenes_file = self._load_scenes_file()
        
        for i, scene in enumerate(scenes_file.scenes):
            if scene.id == scene_id:
                if hard_delete:
                    # Remove from scenes.json
                    scenes_file.scenes.pop(i)
                    self._save_scenes_file(scenes_file)
                    
                    # Delete scene agent directory
                    agent_dir = self.agents_dir / f"scene-{scene_id}"
                    if agent_dir.exists():
                        import shutil
                        shutil.rmtree(agent_dir)
                    
                    logger.info(f"Hard deleted scene: {scene_id}")
                else:
                    # Soft delete
                    scene.status = "deleted"
                    scene.updated_at = datetime.now(timezone.utc).isoformat()
                    scenes_file.scenes[i] = scene
                    self._save_scenes_file(scenes_file)
                    
                    logger.info(f"Soft deleted scene: {scene_id}")
                
                return True
        
        return False
    
    # -------------------------------------------------------------------------
    # Scene Agent Management
    # -------------------------------------------------------------------------
    
    def get_scene_agent(self, scene_id: str) -> Optional[SceneAgentConfig]:
        """Get scene agent configuration.
        
        Args:
            scene_id: Scene ID (e.g., meeting-minutes)
        
        Returns:
            SceneAgentConfig or None if not found
        """
        agent_file = self.agents_dir / f"scene-{scene_id}" / "agent.json"
        if not agent_file.exists():
            return None
        
        with open(agent_file, "r", encoding="utf-8") as f:
            data = json.load(f)
        
        return SceneAgentConfig(**data)
    
    def _create_scene_agent(
        self,
        scene_config: SceneConfig,
        created_by: Optional[str] = None,
    ) -> SceneAgentConfig:
        """Create scene agent configuration and directory.
        
        Args:
            scene_config: Scene configuration
            created_by: Creator username
        
        Returns:
            Created SceneAgentConfig
        """
        agent_id = f"scene-{scene_config.id}"
        agent_dir = self.agents_dir / agent_id
        agent_dir.mkdir(parents=True, exist_ok=True)
        
        # Create scene agent configuration
        now = datetime.now(timezone.utc).isoformat()
        agent_config = SceneAgentConfig(
            id=agent_id,
            name=scene_config.name,
            description=scene_config.description,
            scene=SceneInfo(
                id=scene_config.id,
                icon=scene_config.icon,
                category=scene_config.category,
                tags=scene_config.tags,
                status=scene_config.status,
            ),
            capabilities=Capabilities(
                system_prompt=scene_config.system_prompt,
                skills=scene_config.skills,
            ),
            evolution=EvolutionConfig(
                enabled=True,
                shared=True,
            ),
            model=ModelConfig(),  # Use user agent's model by default
            welcome_message=scene_config.welcome_message,
            created_at=now,
            updated_at=now,
            created_by=created_by or "system",
        )
        
        # Save agent.json
        agent_file = agent_dir / "agent.json"
        with open(agent_file, "w", encoding="utf-8") as f:
            json.dump(agent_config.model_dump(), f, indent=2, ensure_ascii=False)
        
        # Create AGENTS.md (scene-specific system prompt)
        # ⭐ 场景智能体的 AGENTS.md 只包含场景特定的内容
        # 通用内容（安全、协作等）在用户智能体的 AGENTS.md 中
        agents_md_file = agent_dir / "AGENTS.md"
        if scene_config.system_prompt:
            agents_md_file.write_text(scene_config.system_prompt, encoding="utf-8")
            logger.info(f"Created AGENTS.md for scene agent: {agent_id}")
        
        # Create MEMORY.md (shared evolution memory)
        memory_file = agent_dir / "MEMORY.md"
        if not memory_file.exists():
            memory_file.write_text(
                f"# {scene_config.name} - 共享进化记忆\n\n"
                f"此文件记录 {scene_config.name} 的共享进化经验。\n\n"
                f"---\n\n"
                f"## 进化记录\n\n",
                encoding="utf-8",
            )
        
        logger.info(f"Created scene agent: {agent_id}")
        return agent_config
    
    def _update_scene_agent(self, scene_config: SceneConfig) -> None:
        """Update scene agent configuration based on scene config changes.
        
        Args:
            scene_config: Updated scene configuration
        """
        agent_config = self.get_scene_agent(scene_config.id)
        if not agent_config:
            logger.warning(f"Scene agent not found for update: {scene_config.id}")
            return
        
        # Update scene agent fields
        agent_config.name = scene_config.name
        agent_config.description = scene_config.description
        agent_config.scene = SceneInfo(
            id=scene_config.id,
            icon=scene_config.icon,
            category=scene_config.category,
            tags=scene_config.tags,
            status=scene_config.status,
        )
        agent_config.capabilities = Capabilities(
            system_prompt=scene_config.system_prompt,
            skills=scene_config.skills,
        )
        agent_config.welcome_message = scene_config.welcome_message
        agent_config.updated_at = datetime.now(timezone.utc).isoformat()
        
        # Save
        agent_file = self.agents_dir / f"scene-{scene_config.id}" / "agent.json"
        with open(agent_file, "w", encoding="utf-8") as f:
            json.dump(agent_config.model_dump(), f, indent=2, ensure_ascii=False)
        
        # Update AGENTS.md (scene-specific system prompt)
        agents_md_file = self.agents_dir / f"scene-{scene_config.id}" / "AGENTS.md"
        if scene_config.system_prompt:
            agents_md_file.write_text(scene_config.system_prompt, encoding="utf-8")
            logger.info(f"Updated AGENTS.md for scene agent: scene-{scene_config.id}")
        
        logger.info(f"Updated scene agent: {agent_config.id}")
    
    # -------------------------------------------------------------------------
    # Scene Enter (for scene代入)
    # -------------------------------------------------------------------------
    
    def enter_scene(
        self,
        scene_id: str,
        user_id: str,
        request: Optional[EnterSceneRequest] = None,
    ) -> EnterSceneResponse:
        """Enter a scene - create chat session with scene context.
        
        Scene代入架构：
            - agent_id: 用户默认智能体 (user:{user_id})
            - scene_id: 场景标识，运行时注入场景能力
            - 进化记忆：用户记忆（隔离）+ 场景记忆（共享）
        
        This method:
        1. Validates scene exists
        2. Creates or retrieves scene agent config
        3. Creates chat session with scene context
        4. Returns scene info and welcome message
        
        Args:
            scene_id: Scene ID (e.g., meeting-minutes)
            user_id: User ID
            request: Optional enter scene request
        
        Returns:
            EnterSceneResponse with chat session info
        
        Raises:
            SceneNotFoundError: If scene not found
        """
        # Get scene configuration
        scene_config = self.get_scene(scene_id)
        if not scene_config:
            raise SceneNotFoundError(f"Scene not found: {scene_id}")
        
        if scene_config.status != "active":
            raise SceneAgentError(f"Scene is not active: {scene_id}")
        
        # Get or create scene agent config (for scene capabilities)
        scene_agent = self.get_scene_agent(scene_id)
        if not scene_agent:
            scene_agent = self._create_scene_agent(scene_config)
        
        # ⭐ Scene代入会话管理：固定ID格式，避免重复创建
        # chat_id: scene-{scene_id}-{user_id}
        # session_id: scene:{scene_id}:user:{user_id}
        chat_id = f"scene-{scene_id}-{user_id}"
        session_id = f"scene:{scene_id}:user:{user_id}"
        
        # User's default agent (not a composed agent)
        user_agent_id = f"user:{user_id}"
        
        return EnterSceneResponse(
            chat_id=chat_id,
            session_id=session_id,
            scene=scene_agent.scene,
            agent={
                "id": user_agent_id,
                "type": "user",
                "user_id": user_id,
            },
            welcome_message=scene_agent.welcome_message,
        )
    
    # -------------------------------------------------------------------------
    # File I/O Helpers
    # -------------------------------------------------------------------------
    
    def _load_scenes_file(self) -> ScenesFile:
        """Load scenes.json file.
        
        Returns:
            ScenesFile object
        """
        if not self.scenes_file.exists():
            return ScenesFile(version=1, scenes=[])
        
        with open(self.scenes_file, "r", encoding="utf-8") as f:
            data = json.load(f)
        
        return ScenesFile(**data)
    
    def _save_scenes_file(self, scenes_file: ScenesFile) -> None:
        """Save scenes.json file.
        
        Args:
            scenes_file: ScenesFile object to save
        """
        with open(self.scenes_file, "w", encoding="utf-8") as f:
            json.dump(scenes_file.model_dump(), f, indent=2, ensure_ascii=False)
    
    # -------------------------------------------------------------------------
    # Utility Methods
    # -------------------------------------------------------------------------
    
    def get_scene_categories(self) -> List[str]:
        """Get all unique scene categories.
        
        Returns:
            List of category names
        """
        scenes_file = self._load_scenes_file()
        categories = set()
        for scene in scenes_file.scenes:
            if scene.category:
                categories.add(scene.category)
        return sorted(list(categories))
    
    def get_categories_with_dimensions(self) -> Dict[str, Any]:
        """Get categories with dimension grouping.
        
        Reads from categories.json and returns structured data:
        {
            "dimensions": {
                "nature": {
                    "name": "通用分类",
                    "categories": [...]
                },
                "domain": {
                    "name": "按领域分类",
                    "categories": [...]
                }
            }
        }
        
        Returns:
            Dict with dimension-grouped categories
        """
        # Read categories.json
        categories_file = self.data_dir / "categories.json"
        
        if not categories_file.exists():
            logger.warning(f"categories.json not found at {categories_file}")
            return {"dimensions": {}}
        
        try:
            with open(categories_file, 'r', encoding='utf-8') as f:
                data = json.load(f)
            
            # Return dimensions structure
            return {
                "dimensions": data.get("dimensions", {})
            }
        except Exception as e:
            logger.error(f"Failed to load categories.json: {e}")
            return {"dimensions": {}}
    
    def get_scene_tags(self) -> List[str]:
        """Get all unique scene tags.
        
        Returns:
            List of tag names
        """
        scenes_file = self._load_scenes_file()
        tags = set()
        for scene in scenes_file.scenes:
            for tag in scene.tags:
                tags.add(tag)
        return sorted(list(tags))
    
    # ---------------------------------------------------------------------------
    # Scene Management Extensions (v0.10.1+)
    # ---------------------------------------------------------------------------
    
    def get_workbench_menu(self) -> List[Dict[str, Any]]:
        """Get workbench menu items (category tags with scene counts).
        
        Returns:
            List of menu items with:
            - id: tag ID
            - name: tag name
            - icon: tag icon
            - scene_count: number of active scenes
        """
        # Load tags from tag service
        from ..app.services.tag_service import TagService
        tag_service = TagService(data_dir=self.data_dir)
        
        # Get category tags (type="category")
        from ..models.tag import TagType
        category_tags = tag_service.list_tags(
            tag_type=TagType.CATEGORY,
            enabled=True,
            show_in_menu=True
        )
        
        # Load scenes
        scenes_file = self._load_scenes_file()
        active_scenes = [s for s in scenes_file.scenes if s.status == "active"]
        
        # Build menu items
        menu_items = []
        for tag in category_tags.tags:
            # Count scenes with this tag as primary_tag_id
            scene_count = sum(
                1 for s in active_scenes
                if s.primary_tag_id == tag.id
            )
            
            if scene_count > 0:  # Only show tags with scenes
                menu_items.append({
                    "id": tag.id,
                    "name": tag.name,
                    "icon": tag.icon,
                    "scene_count": scene_count,
                })
        
        # Sort by scene_count descending
        menu_items.sort(key=lambda x: -x["scene_count"])
        
        return menu_items
    
    def get_workbench_section(self, tag_id: str) -> Dict[str, Any]:
        """Get scenes for a workbench section (by primary tag).
        
        Args:
            tag_id: Primary tag ID
            
        Returns:
            Dict with:
            - tag: tag info (id, name, icon, description)
            - scenes: list of scenes (id, name, icon, short_description)
        """
        # Load tag info
        from ..app.services.tag_service import TagService
        tag_service = TagService(data_dir=self.data_dir)
        tag = tag_service.get_tag(tag_id)
        
        if not tag:
            raise SceneNotFoundError(f"Tag not found: {tag_id}")
        
        # Load scenes with this primary_tag_id
        scenes_file = self._load_scenes_file()
        active_scenes = [
            s for s in scenes_file.scenes
            if s.status == "active" and s.primary_tag_id == tag_id
        ]
        
        # Sort by usage_count descending
        active_scenes.sort(key=lambda x: -x.usage_count)
        
        # Build response
        return {
            "tag": {
                "id": tag.id,
                "name": tag.name,
                "icon": tag.icon,
                "description": tag.description or "",
            },
            "scenes": [
                {
                    "id": s.id,
                    "name": s.name,
                    "icon": s.icon,
                    "short_description": s.short_description,
                    "usage_count": s.usage_count,
                }
                for s in active_scenes
            ]
        }
    
    def increment_usage(self, scene_id: str) -> None:
        """Increment scene usage count.
        
        Args:
            scene_id: Scene ID
        """
        scenes_file = self._load_scenes_file()
        
        # Find scene
        for scene in scenes_file.scenes:
            if scene.id == scene_id:
                scene.usage_count += 1
                scene.updated_at = datetime.now(timezone.utc).isoformat()
                break
        else:
            raise SceneNotFoundError(f"Scene not found: {scene_id}")
        
        # Save
        self._save_scenes_file(scenes_file)
    
    def list_scenes_by_primary_tag(
        self,
        primary_tag_id: str,
        status: Optional[str] = "active"
    ) -> SceneListResponse:
        """List scenes by primary tag.
        
        Args:
            primary_tag_id: Primary tag ID
            status: Filter by status (default: active)
            
        Returns:
            SceneListResponse
        """
        scenes_file = self._load_scenes_file()
        scenes = scenes_file.scenes
        
        # Filter by primary_tag_id
        scenes = [s for s in scenes if s.primary_tag_id == primary_tag_id]
        
        # Filter by status
        if status:
            scenes = [s for s in scenes if s.status == status]
        
        # Sort by usage_count descending
        scenes = sorted(scenes, key=lambda x: -x.usage_count)
        
        return SceneListResponse(scenes=scenes, total=len(scenes))
    
    def get_hot_scenes(self, limit: int = 10) -> List[Dict[str, Any]]:
        """Get hot scenes by usage count.
        
        Args:
            limit: Maximum number of scenes to return
            
        Returns:
            List of scene dictionaries
        """
        scenes_file = self._load_scenes_file()
        scenes = scenes_file.scenes
        
        # Filter active scenes
        active_scenes = [s for s in scenes if s.status == "active"]
        
        # Sort by usage_count descending
        sorted_scenes = sorted(active_scenes, key=lambda x: -x.usage_count)
        
        # Take top N
        top_scenes = sorted_scenes[:limit]
        
        # Convert to dict for JSON serialization
        return [scene.model_dump(exclude_none=True) for scene in top_scenes]

