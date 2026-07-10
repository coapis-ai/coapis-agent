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

"""Base strategy class for recommendations."""

from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from typing import Any, Dict, List, Optional

from ..models import RecommendationItem

logger = logging.getLogger(__name__)


class BaseStrategy(ABC):
    """Base class for recommendation strategies.
    
    All strategies must implement:
    - get_candidates(): Generate recommendation candidates
    - score(): Score a candidate based on context
    """
    
    def __init__(self, name: str, weight: float = 1.0):
        """Initialize strategy.
        
        Args:
            name: Strategy name (e.g., "skill", "history")
            weight: Strategy weight for final scoring
        """
        self.name = name
        self.weight = weight
        self.enabled = True
    
    @abstractmethod
    def get_candidates(
        self,
        user_id: str,
        context: Optional[Dict[str, Any]] = None,
    ) -> List[RecommendationItem]:
        """Generate recommendation candidates.
        
        Args:
            user_id: User identifier
            context: Optional context (time, scene, etc.)
            
        Returns:
            List of recommendation items
        """
        pass
    
    @abstractmethod
    def score(
        self,
        item: RecommendationItem,
        context: Optional[Dict[str, Any]] = None,
    ) -> float:
        """Score a recommendation item.
        
        Args:
            item: Recommendation item to score
            context: Optional context
            
        Returns:
            Score between 0.0 and 1.0
        """
        pass
    
    def get_weight(self, context: Optional[Dict[str, Any]] = None) -> float:
        """Get strategy weight, optionally adjusted by context.
        
        Args:
            context: Optional context
            
        Returns:
            Strategy weight
        """
        return self.weight
    
    def filter_candidates(
        self,
        candidates: List[RecommendationItem],
        context: Optional[Dict[str, Any]] = None,
    ) -> List[RecommendationItem]:
        """Filter candidates based on strategy rules.
        
        Args:
            candidates: List of candidates to filter
            context: Optional context
            
        Returns:
            Filtered list of candidates
        """
        return candidates
    
    def __repr__(self) -> str:
        return f"<{self.__class__.__name__}(name={self.name}, weight={self.weight})>"
