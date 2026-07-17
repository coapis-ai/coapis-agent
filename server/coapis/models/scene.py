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

"""Scene data models.

This module defines data models for scene management and scene agents.

Scene Agent Architecture:
    - Scene Agent: Global shared agent providing business capabilities
    - User Agent: Personal isolated agent providing identity and memory
    - Runtime: Scene Agent + User Agent = Complete AI capability
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, List, Optional
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field


# ---------------------------------------------------------------------------
# Scene Configuration Models
# ---------------------------------------------------------------------------

class SceneInfo(BaseModel):
    """Scene basic information.
    
    This is a subset of scene configuration used in scene agent config.
    """
    
    model_config = ConfigDict(extra="forbid")
    
    id: str = Field(..., description="Scene ID (e.g., meeting-minutes)")
    icon: str = Field(default="📝", description="Scene icon emoji")
    category: str = Field(default="", description="Scene category (e.g., 办公)")
    tags: List[str] = Field(default_factory=list, description="Scene tags")
    status: str = Field(default="active", description="Scene status: active / disabled / deleted")


class Capabilities(BaseModel):
    """Scene agent capabilities configuration.
    
    Defines what the scene agent can do.
    """
    
    model_config = ConfigDict(extra="forbid")
    
    system_prompt: str = Field(default="", description="System prompt for the scene agent")
    skills: List[str] = Field(default_factory=list, description="Associated skill IDs")
    tools: List[str] = Field(
        default_factory=lambda: ["read_file", "write_file", "search_files"],
        description="Available tools for the scene agent",
    )
    knowledge_bases: List[str] = Field(default_factory=list, description="Knowledge base IDs")


class EvolutionConfig(BaseModel):
    """Evolution configuration for scene agent.
    
    Defines how the scene agent evolves.
    """
    
    model_config = ConfigDict(extra="forbid")
    
    enabled: bool = Field(default=True, description="Whether evolution is enabled")
    shared: bool = Field(default=True, description="Whether evolution results are shared")
    min_confidence: float = Field(default=0.7, description="Minimum confidence threshold")
    require_validation: bool = Field(default=False, description="Whether validation is required")


class ModelConfig(BaseModel):
    """Model configuration for scene agent.
    
    If provider and model are null, the user agent's model will be used.
    """
    
    model_config = ConfigDict(extra="forbid")
    
    provider: Optional[str] = Field(default=None, description="Model provider (null = use user agent's model)")
    model: Optional[str] = Field(default=None, description="Model name (null = use user agent's model)")


class SceneConfig(BaseModel):
    """Scene configuration.
    
    This is the main configuration for a scene, stored in scenes.json.
    Used for scene list display and scene agent initialization.
    """
    
    model_config = ConfigDict(extra="forbid")
    
    id: str = Field(..., description="Scene ID (e.g., meeting-minutes)")
    name: str = Field(..., description="Scene name")
    icon: str = Field(default="📝", description="Scene icon emoji")
    description: str = Field(default="", description="Scene description")
    category: str = Field(default="", description="Scene category (e.g., 办公)")
    tags: List[str] = Field(default_factory=list, description="Scene tags")
    skills: List[str] = Field(default_factory=list, description="Associated skill IDs")
    system_prompt: str = Field(default="", description="System prompt for the scene agent")
    welcome_message: str = Field(default="", description="Welcome message for users")
    
    status: str = Field(default="active", description="Scene status: active / disabled / deleted")
    created_at: str = Field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat(),
        description="Creation timestamp",
    )
    updated_at: str = Field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat(),
        description="Last update timestamp",
    )
    created_by: Optional[str] = Field(default=None, description="Creator username")


class SceneConfigCreate(BaseModel):
    """Request to create a new scene.
    
    Used in POST /api/admin/scenes
    """
    
    model_config = ConfigDict(extra="forbid")
    
    id: str = Field(..., description="Scene ID (e.g., meeting-minutes)")
    name: str = Field(..., description="Scene name")
    icon: str = Field(default="📝", description="Scene icon emoji")
    description: str = Field(default="", description="Scene description")
    category: str = Field(default="", description="Scene category")
    tags: List[str] = Field(default_factory=list, description="Scene tags")
    skills: List[str] = Field(default_factory=list, description="Associated skill IDs")
    system_prompt: str = Field(default="", description="System prompt")
    welcome_message: str = Field(default="", description="Welcome message")


class SceneConfigUpdate(BaseModel):
    """Request to update a scene.
    
    Used in PATCH /api/admin/scenes/{scene_id}
    Only non-null fields will be updated.
    """
    
    model_config = ConfigDict(extra="forbid")
    
    name: Optional[str] = None
    icon: Optional[str] = None
    description: Optional[str] = None
    category: Optional[str] = None
    tags: Optional[List[str]] = None
    skills: Optional[List[str]] = None
    system_prompt: Optional[str] = None
    welcome_message: Optional[str] = None
    status: Optional[str] = None


# ---------------------------------------------------------------------------
# Scene Agent Configuration Models
# ---------------------------------------------------------------------------

class SceneAgentConfig(BaseModel):
    """Scene agent configuration.
    
    This is the configuration for a scene agent, stored in agents/scene-{scene_id}/agent.json.
    
    Scene Agent Architecture:
        - Scene Agent: Global shared agent providing business capabilities
        - User Agent: Personal isolated agent providing identity and memory
        - Runtime: Scene Agent + User Agent = Complete AI capability
    
    Storage Location:
        data/agents/scene-{scene_id}/agent.json
    
    Naming Convention:
        - id: scene-{scene_id} (e.g., scene-meeting-minutes)
        - type: scene-agent (fixed)
        - owner: system (fixed)
    """
    
    model_config = ConfigDict(extra="allow")  # Allow extra fields for compatibility
    
    # Basic information
    id: str = Field(..., description="Scene agent ID (e.g., scene-meeting-minutes)")
    name: str = Field(..., description="Scene agent name")
    type: str = Field(default="scene-agent", description="Agent type (fixed: scene-agent)")
    description: str = Field(default="", description="Scene agent description")
    workspace_dir: str = Field(default=".", description="Workspace directory")
    owner: str = Field(default="system", description="Owner (fixed: system)")
    template_id: str = Field(default="scene-template", description="Template ID")
    
    # Scene information
    scene: SceneInfo = Field(..., description="Scene information")
    
    # Capabilities (from scene config)
    capabilities: Capabilities = Field(
        default_factory=Capabilities,
        description="Scene agent capabilities",
    )
    
    # Evolution configuration
    evolution: EvolutionConfig = Field(
        default_factory=EvolutionConfig,
        description="Evolution configuration",
    )
    
    # Model configuration (null = use user agent's model)
    model: ModelConfig = Field(
        default_factory=ModelConfig,
        description="Model configuration",
    )
    
    # Welcome message
    welcome_message: str = Field(default="", description="Welcome message")
    
    # Timestamps
    created_at: str = Field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat(),
        description="Creation timestamp",
    )
    updated_at: str = Field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat(),
        description="Last update timestamp",
    )
    created_by: str = Field(default="system", description="Creator")


# ---------------------------------------------------------------------------
# Scene List Response Models
# ---------------------------------------------------------------------------

class SceneListResponse(BaseModel):
    """Scene list response.
    
    Used in GET /api/scenes
    """
    
    model_config = ConfigDict(extra="forbid")
    
    scenes: List[SceneConfig] = Field(default_factory=list, description="Scene list")
    total: int = Field(default=0, description="Total number of scenes")


class ScenesFile(BaseModel):
    """Scenes registry file for JSON repository.
    
    Stored in data/scenes.json
    """
    
    model_config = ConfigDict(extra="forbid")
    
    version: int = Field(default=1, description="File version")
    scenes: List[SceneConfig] = Field(default_factory=list, description="Scene list")


# ---------------------------------------------------------------------------
# Scene Enter Models
# ---------------------------------------------------------------------------

class EnterSceneRequest(BaseModel):
    """Request to enter a scene.
    
    Used in POST /api/scenes/{scene_id}/enter
    """
    
    model_config = ConfigDict(extra="forbid")
    
    session_name: Optional[str] = Field(default=None, description="Optional session name")


class EnterSceneResponse(BaseModel):
    """Response for entering a scene.
    
    Contains chat session information and scene details.
    """
    
    model_config = ConfigDict(extra="forbid")
    
    chat_id: str = Field(..., description="Chat session ID")
    session_id: str = Field(..., description="Session ID")
    
    scene: SceneInfo = Field(..., description="Scene information")
    
    agent: Dict[str, Any] = Field(
        default_factory=lambda: {"id": "", "type": "composed"},
        description="Composed agent information",
    )
    
    welcome_message: str = Field(default="", description="Welcome message")
