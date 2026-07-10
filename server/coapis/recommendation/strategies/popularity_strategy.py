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

"""Popularity-based recommendation strategy.

Generates recommendations based on global usage statistics and trending topics.
"""

from __future__ import annotations

import logging
import os
import json
from pathlib import Path
from typing import Any, Dict, List, Optional
from datetime import datetime, timedelta

from .base import BaseStrategy
from ..models import RecommendationItem

logger = logging.getLogger(__name__)


class PopularityTracker:
    """Track global usage statistics for recommendations."""
    
    def __init__(self, data_dir: Optional[str] = None):
        self.data_dir = Path(data_dir or os.environ.get(
            "COAPIS_DATA", os.path.expanduser("~/.coapis/data")
        ))
        self.stats_file = self.data_dir / "recommendation_stats.json"
        self._ensure_data_dir()
    
    def _ensure_data_dir(self):
        """Ensure data directory exists."""
        self.data_dir.mkdir(parents=True, exist_ok=True)
    
    def load_stats(self) -> Dict[str, Any]:
        """Load usage statistics."""
        if self.stats_file.exists():
            try:
                return json.loads(self.stats_file.read_text(encoding="utf-8"))
            except Exception as e:
                logger.warning(f"Failed to load stats: {e}")
        
        return {
            "prompt_usage": {},
            "skill_usage": {},
            "feature_usage": {},
            "last_updated": None,
        }
    
    def save_stats(self, stats: Dict[str, Any]):
        """Save usage statistics."""
        try:
            stats["last_updated"] = datetime.now().isoformat()
            self.stats_file.write_text(
                json.dumps(stats, ensure_ascii=False, indent=2),
                encoding="utf-8"
            )
        except Exception as e:
            logger.error(f"Failed to save stats: {e}")
    
    def record_prompt_usage(self, prompt: str, user_id: str):
        """Record prompt usage."""
        stats = self.load_stats()
        
        if prompt not in stats["prompt_usage"]:
            stats["prompt_usage"][prompt] = {
                "count": 0,
                "users": [],
                "first_used": datetime.now().isoformat(),
                "last_used": None,
            }
        
        entry = stats["prompt_usage"][prompt]
        entry["count"] += 1
        if user_id not in entry["users"]:
            entry["users"].append(user_id)
        entry["last_used"] = datetime.now().isoformat()
        
        self.save_stats(stats)
    
    def record_skill_usage(self, skill_name: str, user_id: str):
        """Record skill usage."""
        stats = self.load_stats()
        
        if skill_name not in stats["skill_usage"]:
            stats["skill_usage"][skill_name] = {
                "count": 0,
                "users": [],
                "first_used": datetime.now().isoformat(),
            }
        
        entry = stats["skill_usage"][skill_name]
        entry["count"] += 1
        if user_id not in entry["users"]:
            entry["users"].append(user_id)
        
        self.save_stats(stats)
    
    def get_trending_prompts(self, limit: int = 5) -> List[Dict[str, Any]]:
        """Get trending prompts based on recent usage."""
        stats = self.load_stats()
        prompt_usage = stats.get("prompt_usage", {})
        
        # Sort by count and recency
        sorted_prompts = sorted(
            prompt_usage.items(),
            key=lambda x: (x[1]["count"], x[1].get("last_used", "")),
            reverse=True
        )
        
        trending = []
        for prompt, data in sorted_prompts[:limit]:
            trending.append({
                "prompt": prompt,
                "count": data["count"],
                "user_count": len(data.get("users", [])),
                "last_used": data.get("last_used"),
            })
        
        return trending
    
    def get_trending_skills(self, limit: int = 5) -> List[Dict[str, Any]]:
        """Get trending skills based on usage."""
        stats = self.load_stats()
        skill_usage = stats.get("skill_usage", {})
        
        sorted_skills = sorted(
            skill_usage.items(),
            key=lambda x: x[1]["count"],
            reverse=True
        )
        
        trending = []
        for skill, data in sorted_skills[:limit]:
            trending.append({
                "skill": skill,
                "count": data["count"],
                "user_count": len(data.get("users", [])),
            })
        
        return trending


class PopularityStrategy(BaseStrategy):
    """Strategy based on global popularity and trending topics."""
    
    def __init__(self, weight: float = 0.6, data_dir: Optional[str] = None):
        super().__init__(name="popularity", weight=weight)
        self.tracker = PopularityTracker(data_dir)
        
        # Curated trending recommendations
        self.trending_recommendations = [
            {
                "title": "智能文档分析",
                "description": "最受欢迎：AI 驱动的文档深度分析",
                "prompt": "帮我深度分析这个文档，提取关键信息、生成摘要、识别重要观点",
                "icon": "📄",
                "popularity_score": 0.95,
            },
            {
                "title": "代码审查助手",
                "description": "热门：自动化代码质量检查",
                "prompt": "帮我审查这段代码，检查质量、安全性、性能和最佳实践",
                "icon": "🔍",
                "popularity_score": 0.92,
            },
            {
                "title": "数据分析专家",
                "description": "趋势：智能数据可视化和洞察",
                "prompt": "帮我分析这些数据，找出趋势、异常和关键洞察，生成可视化图表",
                "icon": "📊",
                "popularity_score": 0.90,
            },
            {
                "title": "邮件智能处理",
                "description": "高效：自动整理和回复邮件",
                "prompt": "帮我处理收件箱，分类重要邮件，生成专业回复",
                "icon": "✉️",
                "popularity_score": 0.88,
            },
            {
                "title": "网页数据抓取",
                "description": "实用：自动化网页信息收集",
                "prompt": "帮我自动化抓取这个网页的信息，整理成结构化数据",
                "icon": "🌐",
                "popularity_score": 0.85,
            },
            {
                "title": "多语言翻译",
                "description": "必备：专业文档翻译和本地化",
                "prompt": "帮我翻译这个文档，保持专业术语准确，语言流畅自然",
                "icon": "🌍",
                "popularity_score": 0.82,
            },
            {
                "title": "会议纪要生成",
                "description": "职场：自动整理会议要点和待办",
                "prompt": "帮我整理这个会议的内容，提取关键决策和待办事项",
                "icon": "🎤",
                "popularity_score": 0.80,
            },
            {
                "title": "知识库构建",
                "description": "系统：建立个人知识管理体系",
                "prompt": "帮我整理这些笔记，建立分类清晰、易于检索的知识库",
                "icon": "🧠",
                "popularity_score": 0.78,
            },
        ]
    
    def get_candidates(
        self,
        user_id: str,
        context: Optional[Dict[str, Any]] = None,
    ) -> List[RecommendationItem]:
        """Generate recommendations based on popularity."""
        candidates = []
        
        # Add curated trending recommendations
        for rec in self.trending_recommendations:
            candidates.append(RecommendationItem(
                id=f"popularity:trending:{rec['title']}",
                title=rec["title"],
                description=rec["description"],
                prompt=rec["prompt"],
                category="popularity",
                icon=rec["icon"],
                score=rec["popularity_score"],
                metadata={"source": "curated"},
            ))
        
        # Add dynamically trending recommendations
        try:
            trending_prompts = self.tracker.get_trending_prompts(limit=3)
            for item in trending_prompts:
                candidates.append(RecommendationItem(
                    id=f"popularity:dynamic:{hash(item['prompt']) % 10000}",
                    title=f"热门：{item['prompt'][:30]}...",
                    description=f"已被 {item['user_count']} 位用户使用",
                    prompt=item["prompt"],
                    category="popularity",
                    icon="🔥",
                    score=0.0,
                    metadata={
                        "source": "dynamic",
                        "usage_count": item["count"],
                        "user_count": item["user_count"],
                    },
                ))
        except Exception as e:
            logger.warning(f"Failed to get dynamic trending: {e}")
        
        logger.debug(f"PopularityStrategy: Generated {len(candidates)} candidates for user {user_id}")
        return candidates
    
    def score(
        self,
        item: RecommendationItem,
        context: Optional[Dict[str, Any]] = None,
    ) -> float:
        """Score based on popularity."""
        # Use existing score for curated items
        if item.score > 0:
            return item.score
        
        # Score dynamic items based on usage
        metadata = item.metadata or {}
        usage_count = metadata.get("usage_count", 0)
        user_count = metadata.get("user_count", 0)
        
        # Normalize to 0.5 - 0.9 range
        if user_count > 100:
            return 0.9
        elif user_count > 50:
            return 0.8
        elif user_count > 20:
            return 0.7
        elif user_count > 5:
            return 0.6
        else:
            return 0.5
    
    def get_weight(self, context: Optional[Dict[str, Any]] = None) -> float:
        """Adjust weight based on context."""
        # For new users, popularity (social proof) is more valuable
        if context and context.get("is_new_user", False):
            return self.weight * 1.3
        return self.weight
