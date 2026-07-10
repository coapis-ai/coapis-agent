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

"""Recommendation module - Dynamic recommendation engine for CoApis.

Provides:
- Skill-based recommendations
- History-based recommendations
- Context-aware recommendations
- Popularity-based recommendations

Usage:
    from coapis.recommendation import get_recommendations
    
    recommendations = get_recommendations(user_id="user123", scene="chat_welcome")
"""

from .engine import RecommendationEngine, get_recommendations
from .models import RecommendationItem, RecommendationResponse
from .router import router

__all__ = [
    "RecommendationEngine",
    "get_recommendations",
    "RecommendationItem",
    "RecommendationResponse",
    "router",
]
