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

"""Skill-based recommendation strategy.

Generates recommendations based on user's installed skills.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any, Dict, List, Optional

from .base import BaseStrategy
from ..models import RecommendationItem

logger = logging.getLogger(__name__)

# Skill to recommendation mapping
SKILL_RECOMMENDATIONS = {
    "xlsx": {
        "title": "帮我分析这份数据",
        "description": "读取 Excel/CSV，生成图表和分析报告",
        "prompt": "帮我分析这份销售数据，找出增长趋势并生成图表",
        "icon": "📊",
    },
    "docx": {
        "title": "帮我处理 Word 文档",
        "description": "创建、编辑、格式化 Word 文档",
        "prompt": "帮我创建一份专业的项目报告",
        "icon": "📝",
    },
    "pdf": {
        "title": "帮我处理 PDF 文件",
        "description": "读取、合并、拆分 PDF 文件",
        "prompt": "帮我提取这份 PDF 的关键信息",
        "icon": "📄",
    },
    "pptx": {
        "title": "帮我制作 PPT",
        "description": "创建专业的演示文稿",
        "prompt": "帮我制作一份产品介绍 PPT",
        "icon": "📊",
    },
    "browser_use": {
        "title": "帮我浏览网页",
        "description": "自动化浏览器操作，获取网页信息",
        "prompt": "帮我打开这个网页并提取关键信息",
        "icon": "🌐",
    },
    "web-search": {
        "title": "帮我搜索信息",
        "description": "搜索互联网并总结结果",
        "prompt": "帮我搜索最新的 AI 行业动态",
        "icon": "🔍",
    },
    "himalaya": {
        "title": "帮我处理邮件",
        "description": "读取、发送、管理邮件",
        "prompt": "帮我查看收件箱并回复重要邮件",
        "icon": "📧",
    },
    "code": {
        "title": "帮我写代码",
        "description": "编写、调试、优化代码",
        "prompt": "帮我写一个 Python 脚本处理数据",
        "icon": "💻",
    },
    "file_reader": {
        "title": "帮我读取文件",
        "description": "读取各种格式的文件内容",
        "prompt": "帮我读取这个文件并总结内容",
        "icon": "📂",
    },
    "guidance": {
        "title": "教我如何使用",
        "description": "平台使用指南和帮助",
        "prompt": "教我如何使用 CoApis 的核心功能",
        "icon": "❓",
    },
}

# Default recommendations for new users or when no skills installed
DEFAULT_RECOMMENDATIONS = [
    {
        "id": "default:document",
        "title": "帮我处理文档",
        "description": "支持 PDF、Word、Excel、PPT 等格式",
        "prompt": "帮我处理这份文档",
        "icon": "📄",
    },
    {
        "id": "default:search",
        "title": "帮我搜索信息",
        "description": "搜索互联网并总结结果",
        "prompt": "帮我搜索最新的技术趋势",
        "icon": "🔍",
    },
    {
        "id": "default:data",
        "title": "帮我分析数据",
        "description": "读取数据文件，生成图表和报告",
        "prompt": "帮我分析这份数据并生成可视化图表",
        "icon": "📊",
    },
    {
        "id": "default:code",
        "title": "帮我写代码",
        "description": "编写、调试、优化代码",
        "prompt": "帮我写一个脚本自动化这个任务",
        "icon": "💻",
    },
]


class SkillStrategy(BaseStrategy):
    """Strategy based on user's installed skills."""
    
    def __init__(self, weight: float = 1.0):
        super().__init__(name="skill", weight=weight)
    
    def get_candidates(
        self,
        user_id: str,
        context: Optional[Dict[str, Any]] = None,
    ) -> List[RecommendationItem]:
        """Generate recommendations based on installed skills."""
        candidates = []
        
        # Get user's workspace directory
        from ...constant import WORKSPACES_DIR
        workspace_dir = WORKSPACES_DIR / user_id
        
        # Load installed skills
        skill_file = workspace_dir / "skill.json"
        if not skill_file.exists():
            logger.debug(f"No skill.json found for user {user_id}, using defaults")
            return self._get_default_recommendations()
        
        try:
            with open(skill_file, "r", encoding="utf-8") as f:
                skill_data = json.load(f)
        except (json.JSONDecodeError, IOError) as e:
            logger.warning(f"Failed to load skill.json for {user_id}: {e}")
            return self._get_default_recommendations()
        
        # Extract installed skill names
        installed_skills = set()
        skills_list = skill_data.get("skills", [])
        for skill in skills_list:
            if isinstance(skill, dict):
                skill_name = skill.get("name", "")
                if skill_name:
                    installed_skills.add(skill_name)
            elif isinstance(skill, str):
                installed_skills.add(skill)
        
        if not installed_skills:
            logger.debug(f"No skills installed for user {user_id}")
            return self._get_default_recommendations()
        
        # Generate recommendations for installed skills
        for skill_name in installed_skills:
            if skill_name in SKILL_RECOMMENDATIONS:
                rec_config = SKILL_RECOMMENDATIONS[skill_name]
                item = RecommendationItem(
                    id=f"skill:{skill_name}",
                    title=rec_config["title"],
                    description=rec_config["description"],
                    prompt=rec_config["prompt"],
                    category="skill",
                    icon=rec_config["icon"],
                    metadata={"skill_name": skill_name},
                )
                candidates.append(item)
        
        # If no matching recommendations, use defaults
        if not candidates:
            return self._get_default_recommendations()
        
        return candidates
    
    def score(
        self,
        item: RecommendationItem,
        context: Optional[Dict[str, Any]] = None,
    ) -> float:
        """Score based on skill relevance."""
        # Base score for skill-based recommendations
        score = 0.7
        
        # Boost if skill is in core skills list
        core_skills = ["xlsx", "docx", "pdf", "browser_use", "web-search"]
        skill_name = item.metadata.get("skill_name", "")
        if skill_name in core_skills:
            score += 0.2
        
        # Boost if context indicates specific need
        if context:
            scene = context.get("scene", "")
            if scene == "chat_welcome":
                score += 0.1  # Slightly boost for welcome page
        
        return min(score, 1.0)
    
    def _get_default_recommendations(self) -> List[RecommendationItem]:
        """Get default recommendations for new users."""
        candidates = []
        for rec in DEFAULT_RECOMMENDATIONS:
            item = RecommendationItem(
                id=rec["id"],
                title=rec["title"],
                description=rec["description"],
                prompt=rec["prompt"],
                category="skill",
                icon=rec["icon"],
                metadata={"is_default": True},
            )
            candidates.append(item)
        return candidates
