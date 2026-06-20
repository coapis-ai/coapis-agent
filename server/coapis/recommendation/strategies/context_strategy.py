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

"""Context-aware recommendation strategy.

Generates recommendations based on real-time context (time, date, user state).
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional

from .base import BaseStrategy
from ..models import RecommendationItem

logger = logging.getLogger(__name__)


class ContextStrategy(BaseStrategy):
    """Strategy based on real-time context."""
    
    def __init__(self, weight: float = 0.8):
        super().__init__(name="context", weight=weight)
        
        # Time-based recommendations
        self.time_recommendations = {
            "morning": [
                {
                    "title": "早间规划",
                    "description": "规划今日工作，安排优先级",
                    "prompt": "帮我规划今天的工作，安排优先级和时间表",
                    "icon": "🌅",
                },
                {
                    "title": "邮件检查",
                    "description": "检查收件箱，处理重要邮件",
                    "prompt": "帮我检查收件箱，找出重要邮件并处理",
                    "icon": "📬",
                },
            ],
            "afternoon": [
                {
                    "title": "工作总结",
                    "description": "总结上午工作，调整下午计划",
                    "prompt": "帮我总结上午的工作，调整下午的计划",
                    "icon": "📋",
                },
                {
                    "title": "会议准备",
                    "description": "准备会议材料，整理要点",
                    "prompt": "帮我准备会议材料，整理关键要点",
                    "icon": "🎤",
                },
            ],
            "evening": [
                {
                    "title": "日报撰写",
                    "description": "总结今日工作，生成日报",
                    "prompt": "帮我总结今天的工作，生成日报",
                    "icon": "📝",
                },
                {
                    "title": "明日规划",
                    "description": "规划明日任务，设置提醒",
                    "prompt": "帮我规划明天的任务，设置重要提醒",
                    "icon": "📅",
                },
            ],
            "night": [
                {
                    "title": "知识整理",
                    "description": "整理今日学习笔记",
                    "prompt": "帮我整理今天的学习笔记，保存重要知识点",
                    "icon": "🧠",
                },
                {
                    "title": "经验复盘",
                    "description": "复盘今日工作，总结经验",
                    "prompt": "帮我复盘今天的工作，总结经验教训",
                    "icon": "💡",
                },
            ],
        }
        
        # Day-of-week recommendations
        self.weekday_recommendations = {
            0: [  # Monday
                {
                    "title": "周计划制定",
                    "description": "制定本周工作计划",
                    "prompt": "帮我制定本周的工作计划，安排重要任务",
                    "icon": "📅",
                },
            ],
            4: [  # Friday
                {
                    "title": "周报总结",
                    "description": "总结本周工作，生成周报",
                    "prompt": "帮我总结本周的工作，生成周报",
                    "icon": "📊",
                },
                {
                    "title": "下周规划",
                    "description": "提前规划下周任务",
                    "prompt": "帮我提前规划下周的重要任务",
                    "icon": "📋",
                },
            ],
        }
        
        # Special date recommendations
        self.special_date_recommendations = {
            "month_start": {
                "title": "月度总结",
                "description": "总结上月工作，规划本月目标",
                "prompt": "帮我总结上个月的工作，规划这个月的目标",
                "icon": "📈",
            },
            "month_end": {
                "title": "月度复盘",
                "description": "复盘本月工作，准备月度汇报",
                "prompt": "帮我复盘这个月的工作，准备月度汇报材料",
                "icon": "📊",
            },
            "quarter_start": {
                "title": "季度规划",
                "description": "制定季度目标和计划",
                "prompt": "帮我制定这个季度的工作目标和计划",
                "icon": "🎯",
            },
        }
    
    def get_candidates(
        self,
        user_id: str,
        context: Optional[Dict[str, Any]] = None,
    ) -> List[RecommendationItem]:
        """Generate recommendations based on context."""
        candidates = []
        now = datetime.now()
        
        # Time-based recommendations
        hour = now.hour
        if 5 <= hour < 12:
            time_period = "morning"
        elif 12 <= hour < 17:
            time_period = "afternoon"
        elif 17 <= hour < 21:
            time_period = "evening"
        else:
            time_period = "night"
        
        for rec in self.time_recommendations.get(time_period, []):
            candidates.append(RecommendationItem(
                id=f"context:time:{time_period}:{rec['title']}",
                title=rec["title"],
                description=rec["description"],
                prompt=rec["prompt"],
                category="context",
                icon=rec["icon"],
                score=0.0,
                metadata={"time_period": time_period, "hour": hour},
            ))
        
        # Day-of-week recommendations
        weekday = now.weekday()
        for rec in self.weekday_recommendations.get(weekday, []):
            candidates.append(RecommendationItem(
                id=f"context:weekday:{weekday}:{rec['title']}",
                title=rec["title"],
                description=rec["description"],
                prompt=rec["prompt"],
                category="context",
                icon=rec["icon"],
                score=0.0,
                metadata={"weekday": weekday, "day_name": now.strftime("%A")},
            ))
        
        # Special date recommendations
        day = now.day
        if day == 1:
            rec = self.special_date_recommendations.get("month_start")
            if rec:
                candidates.append(RecommendationItem(
                    id=f"context:special:month_start",
                    title=rec["title"],
                    description=rec["description"],
                    prompt=rec["prompt"],
                    category="context",
                    icon=rec["icon"],
                    score=0.0,
                    metadata={"special_date": "month_start"},
                ))
        elif day >= 28:
            rec = self.special_date_recommendations.get("month_end")
            if rec:
                candidates.append(RecommendationItem(
                    id=f"context:special:month_end",
                    title=rec["title"],
                    description=rec["description"],
                    prompt=rec["prompt"],
                    category="context",
                    icon=rec["icon"],
                    score=0.0,
                    metadata={"special_date": "month_end"},
                ))
        
        # Check for new user context
        if context and context.get("is_new_user", False):
            candidates.append(RecommendationItem(
                id="context:new_user:welcome",
                title="功能探索",
                description="了解 CoApis 的核心功能和使用方法",
                prompt="请介绍 CoApis 的核心功能，帮我快速上手",
                category="context",
                icon="🚀",
                score=0.0,
                metadata={"is_new_user": True},
            ))
        
        logger.debug(f"ContextStrategy: Generated {len(candidates)} candidates for user {user_id}")
        return candidates
    
    def score(
        self,
        item: RecommendationItem,
        context: Optional[Dict[str, Any]] = None,
    ) -> float:
        """Score based on context relevance."""
        metadata = item.metadata or {}
        
        # New user gets highest score for welcome
        if metadata.get("is_new_user", False):
            return 0.95
        
        # Special dates get high score
        if metadata.get("special_date"):
            return 0.85
        
        # Time-based scoring
        time_period = metadata.get("time_period")
        if time_period:
            # Morning planning is more valuable
            if time_period == "morning":
                return 0.8
            # Evening summary is also valuable
            elif time_period == "evening":
                return 0.75
            else:
                return 0.65
        
        # Weekday scoring
        if "weekday" in metadata:
            weekday = metadata["weekday"]
            # Monday planning and Friday summary are valuable
            if weekday in [0, 4]:
                return 0.8
            else:
                return 0.6
        
        return 0.5
    
    def get_weight(self, context: Optional[Dict[str, Any]] = None) -> float:
        """Adjust weight based on context."""
        # For new users, context is more important
        if context and context.get("is_new_user", False):
            return self.weight * 1.5
        return self.weight
