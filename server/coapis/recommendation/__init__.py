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
