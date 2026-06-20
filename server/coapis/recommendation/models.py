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

"""Data models for the recommendation system."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Dict, List, Optional


@dataclass
class RecommendationItem:
    """A single recommendation item."""
    
    id: str
    title: str
    description: str
    prompt: str  # The message to send when clicked
    category: str  # skill, history, context, popularity
    icon: str = "💡"
    score: float = 0.0
    metadata: Dict[str, Any] = field(default_factory=dict)
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for API response."""
        return {
            "id": self.id,
            "title": self.title,
            "description": self.description,
            "prompt": self.prompt,
            "category": self.category,
            "icon": self.icon,
            "score": round(self.score, 3),
            "metadata": self.metadata,
        }


@dataclass
class RecommendationResponse:
    """API response for recommendations."""
    
    recommendations: List[RecommendationItem]
    meta: Dict[str, Any] = field(default_factory=dict)
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for API response."""
        return {
            "recommendations": [item.to_dict() for item in self.recommendations],
            "meta": {
                "count": len(self.recommendations),
                "generated_at": datetime.now().isoformat(),
                **self.meta,
            },
        }


@dataclass
class SceneConfig:
    """Configuration for a recommendation scene."""
    
    max_items: int = 6
    strategies: List[str] = field(default_factory=lambda: ["skill", "history", "context"])
    layout: str = "grid"  # grid, list, carousel
    show_icon: bool = True
    show_description: bool = True
    strategy_weights: Dict[str, float] = field(default_factory=dict)
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> SceneConfig:
        """Create from dictionary."""
        return cls(
            max_items=data.get("max_items", 6),
            strategies=data.get("strategies", ["skill", "history", "context"]),
            layout=data.get("layout", "grid"),
            show_icon=data.get("show_icon", True),
            show_description=data.get("show_description", True),
            strategy_weights=data.get("strategy_weights", {}),
        )


@dataclass
class UserPreferences:
    """User's recommendation preferences."""
    
    user_id: str
    dismissed: List[str] = field(default_factory=list)  # Dismissed recommendation IDs
    clicked: List[str] = field(default_factory=list)  # Clicked recommendation IDs
    preferred_categories: List[str] = field(default_factory=list)
    last_updated: Optional[str] = None
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary."""
        return {
            "user_id": self.user_id,
            "dismissed": self.dismissed,
            "clicked": self.clicked,
            "preferred_categories": self.preferred_categories,
            "last_updated": self.last_updated,
        }
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> UserPreferences:
        """Create from dictionary."""
        return cls(
            user_id=data.get("user_id", ""),
            dismissed=data.get("dismissed", []),
            clicked=data.get("clicked", []),
            preferred_categories=data.get("preferred_categories", []),
            last_updated=data.get("last_updated"),
        )
