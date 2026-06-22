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

"""Recommendation engine - Core logic for generating recommendations.

Orchestrates multiple strategies to produce final recommendations.
"""

from __future__ import annotations

import logging
import os
from typing import Any, Dict, List, Optional

from .models import (
    RecommendationItem,
    RecommendationResponse,
    SceneConfig,
)
from .strategies import (
    BaseStrategy,
    SkillStrategy,
    HistoryStrategy,
    ContextStrategy,
    PopularityStrategy,
)
from .store import get_store

logger = logging.getLogger(__name__)

# Default scene configurations
DEFAULT_SCENE_CONFIGS: Dict[str, SceneConfig] = {
    "chat_welcome": SceneConfig(
        max_items=6,
        strategies=["skill", "history", "context"],
        layout="grid",
        strategy_weights={"skill": 1.0, "history": 1.2, "context": 0.8},
    ),
    "sidebar": SceneConfig(
        max_items=3,
        strategies=["skill", "history"],
        layout="list",
        strategy_weights={"skill": 1.0, "history": 1.0},
    ),
    "skill_market": SceneConfig(
        max_items=10,
        strategies=["skill", "popularity"],
        layout="grid",
        strategy_weights={"skill": 1.0, "popularity": 0.8},
    ),
    "dashboard": SceneConfig(
        max_items=8,
        strategies=["history", "context", "popularity"],
        layout="carousel",
        strategy_weights={"history": 1.0, "context": 0.8, "popularity": 0.6},
    ),
}


class RecommendationEngine:
    """Main recommendation engine.
    
    Orchestrates strategies to produce final recommendations:
    1. Generate candidates from each strategy
    2. Score candidates using strategy weights
    3. Deduplicate and rank
    4. Return top N items
    """
    
    def __init__(self, workspace_dir: Optional[str] = None):
        """Initialize engine with all strategies.
        
        Args:
            workspace_dir: User workspace directory
        """
        self.workspace_dir = workspace_dir or os.environ.get(
            "COAPIS_WORKSPACE", os.path.expanduser("~/.coapis")
        )
        
        self.strategies: Dict[str, BaseStrategy] = {
            "skill": SkillStrategy(weight=1.0),
            "history": HistoryStrategy(weight=1.2, workspace_dir=self.workspace_dir),
            "context": ContextStrategy(weight=0.8),
            "popularity": PopularityStrategy(weight=0.6),
        }
        self.scene_configs = DEFAULT_SCENE_CONFIGS.copy()
    
    def get_recommendations(
        self,
        user_id: str,
        scene: str = "chat_welcome",
        limit: Optional[int] = None,
        context: Optional[Dict[str, Any]] = None,
    ) -> RecommendationResponse:
        """Get recommendations for a user and scene.
        
        Args:
            user_id: User identifier
            scene: Scene identifier (chat_welcome, sidebar, etc.)
            limit: Maximum number of recommendations
            context: Additional context
            
        Returns:
            RecommendationResponse with ranked items
        """
        store = get_store()
        
        # Get scene config
        scene_config = self.scene_configs.get(scene, self.scene_configs["chat_welcome"])
        
        # Override limit if provided
        max_items = limit or scene_config.max_items
        
        # Merge context with scene info
        full_context = {
            **(context or {}),
            "scene": scene,
            "user_id": user_id,
        }
        
        # Get user preferences (for filtering)
        user_prefs = store.get_user_preferences(user_id)
        hidden_categories = user_prefs.get("hidden_categories", [])
        dismissed_ids = user_prefs.get("dismissed_recommendations", [])
        
        # Collect candidates from all enabled strategies
        all_candidates: List[RecommendationItem] = []
        
        for strategy_name in scene_config.strategies:
            strategy = self.strategies.get(strategy_name)
            if not strategy or not strategy.enabled:
                continue
            
            try:
                candidates = strategy.get_candidates(user_id, full_context)
                all_candidates.extend(candidates)
                logger.debug(
                    f"Strategy {strategy_name} produced {len(candidates)} candidates"
                )
            except Exception as e:
                logger.error(f"Strategy {strategy_name} failed: {e}")
        
        # Deduplicate by ID
        seen_ids = set()
        unique_candidates = []
        for item in all_candidates:
            if item.id not in seen_ids:
                seen_ids.add(item.id)
                unique_candidates.append(item)
        
        # Filter out hidden categories and dismissed recommendations
        filtered_candidates = [
            item for item in unique_candidates
            if item.category not in hidden_categories
            and item.id not in dismissed_ids
        ]
        
        # Score candidates
        scored_items = self._score_candidates(
            filtered_candidates,
            full_context,
            scene_config.strategy_weights,
        )
        
        # Sort by score (descending)
        scored_items.sort(key=lambda x: x.score, reverse=True)
        
        # Apply limit
        final_items = scored_items[:max_items]
        
        # Build response
        meta = {
            "scene": scene,
            "strategies_used": scene_config.strategies,
            "total_candidates": len(all_candidates),
            "unique_candidates": len(unique_candidates),
            "filtered_candidates": len(filtered_candidates),
        }
        
        return RecommendationResponse(
            recommendations=final_items,
            meta=meta,
        )
    
    def _score_candidates(
        self,
        candidates: List[RecommendationItem],
        context: Dict[str, Any],
        strategy_weights: Dict[str, float],
    ) -> List[RecommendationItem]:
        """Score all candidates using strategies.
        
        Args:
            candidates: List of candidates to score
            context: Context for scoring
            strategy_weights: Weights for each strategy
            
        Returns:
            List of scored items
        """
        for item in candidates:
            total_score = 0.0
            total_weight = 0.0
            
            # Get score from each strategy
            for strategy_name, strategy in self.strategies.items():
                if not strategy.enabled:
                    continue
                
                try:
                    # Get strategy-specific score
                    strategy_score = strategy.score(item, context)
                    
                    # Get strategy weight (context-adjusted)
                    base_weight = strategy_weights.get(strategy_name, strategy.weight)
                    context_weight = strategy.get_weight(context)
                    effective_weight = base_weight * (context_weight / strategy.weight if strategy.weight > 0 else 1)
                    
                    # Weighted score
                    total_score += strategy_score * effective_weight
                    total_weight += effective_weight
                    
                except Exception as e:
                    logger.warning(f"Strategy {strategy_name} scoring failed: {e}")
            
            # Normalize score
            if total_weight > 0:
                item.score = total_score / total_weight
            else:
                item.score = 0.0
        
        return candidates
    
    def get_scene_config(self, scene: str) -> SceneConfig:
        """Get configuration for a scene."""
        return self.scene_configs.get(scene, self.scene_configs["chat_welcome"])
    
    def register_strategy(self, name: str, strategy: BaseStrategy) -> None:
        """Register a custom strategy."""
        self.strategies[name] = strategy
        logger.info(f"Registered strategy: {name}")
    
    def update_scene_config(self, scene: str, config: SceneConfig) -> None:
        """Update scene configuration."""
        self.scene_configs[scene] = config
        logger.info(f"Updated scene config: {scene}")


# Global engine instance
_engine: Optional[RecommendationEngine] = None


def get_engine() -> RecommendationEngine:
    """Get or create the global recommendation engine."""
    global _engine
    if _engine is None:
        _engine = RecommendationEngine()
    return _engine


def get_recommendations(
    user_id: str,
    scene: str = "chat_welcome",
    limit: Optional[int] = None,
    context: Optional[Dict[str, Any]] = None,
) -> RecommendationResponse:
    """Convenience function to get recommendations.
    
    Args:
        user_id: User identifier
        scene: Scene identifier
        limit: Maximum items
        context: Additional context
        
    Returns:
        RecommendationResponse
    """
    engine = get_engine()
    return engine.get_recommendations(user_id, scene, limit, context)
