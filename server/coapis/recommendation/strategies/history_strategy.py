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

"""History-based recommendation strategy.

Generates recommendations based on user's past behavior and usage patterns.
"""

from __future__ import annotations

import logging
import os
import json
from pathlib import Path
from typing import Any, Dict, List, Optional
from collections import Counter
from datetime import datetime, timedelta

from .base import BaseStrategy
from ..models import RecommendationItem

logger = logging.getLogger(__name__)


class HistoryAnalyzer:
    """Analyze user's chat history to extract patterns."""
    
    # Question type keywords
    QUESTION_TYPES = {
        "document": ["文档", "doc", "pdf", "word", "读取", "分析", "提取", "翻译"],
        "search": ["搜索", "search", "查找", "查询", "搜", "找", "google"],
        "code": ["代码", "code", "编程", "python", "javascript", "脚本", "开发"],
        "data": ["数据", "data", "excel", "csv", "表格", "统计", "图表"],
        "email": ["邮件", "email", "mail", "发送", "回复", "收件"],
        "browser": ["浏览器", "browser", "网页", "登录", "自动化", "爬取"],
        "memory": ["记住", "remember", "保存", "记录", "笔记"],
    }
    
    def __init__(self, workspace_dir: str):
        self.workspace_dir = Path(workspace_dir)
        self.memory_dir = self.workspace_dir / "memory"
    
    def analyze_user_patterns(self, user_id: str) -> Dict[str, Any]:
        """Analyze user's chat history and extract patterns."""
        patterns = {
            "question_types": Counter(),
            "topic_keywords": Counter(),
            "skill_usage": Counter(),
            "time_preferences": [],
            "recent_queries": [],
        }
        
        # Read memory files
        memory_files = self._get_memory_files(user_id)
        
        for file_path in memory_files:
            try:
                content = file_path.read_text(encoding="utf-8")
                self._extract_patterns(content, patterns)
            except Exception as e:
                logger.warning(f"Failed to read {file_path}: {e}")
        
        # Read MEMORY.md if exists
        memory_md = self.workspace_dir / "MEMORY.md"
        if memory_md.exists():
            try:
                content = memory_md.read_text(encoding="utf-8")
                self._extract_patterns(content, patterns)
            except Exception as e:
                logger.warning(f"Failed to read MEMORY.md: {e}")
        
        return patterns
    
    def _get_memory_files(self, user_id: str) -> List[Path]:
        """Get all memory files for a user."""
        files = []
        
        # Check memory directory
        if self.memory_dir.exists():
            for file_path in self.memory_dir.glob("*.md"):
                files.append(file_path)
        
        # Check workspaces directory
        workspace_path = self.workspace_dir / "workspaces" / user_id
        if workspace_path.exists():
            for file_path in workspace_path.rglob("*.md"):
                files.append(file_path)
        
        return files
    
    def _extract_patterns(self, content: str, patterns: Dict[str, Any]) -> None:
        """Extract patterns from text content."""
        content_lower = content.lower()
        
        # Detect question types
        for q_type, keywords in self.QUESTION_TYPES.items():
            for keyword in keywords:
                if keyword in content_lower:
                    patterns["question_types"][q_type] += 1
        
        # Extract keywords (simple word frequency)
        words = content_lower.split()
        for word in words:
            if len(word) > 2:  # Skip very short words
                patterns["topic_keywords"][word] += 1
    
    def get_top_patterns(self, patterns: Dict[str, Any], n: int = 5) -> Dict[str, Any]:
        """Get top N patterns."""
        return {
            "question_types": dict(patterns["question_types"].most_common(n)),
            "topic_keywords": dict(patterns["topic_keywords"].most_common(n * 2)),
            "skill_usage": dict(patterns["skill_usage"].most_common(n)),
        }


class HistoryStrategy(BaseStrategy):
    """Strategy based on user's history and usage patterns."""
    
    def __init__(self, weight: float = 1.2, workspace_dir: Optional[str] = None):
        """Initialize history strategy.
        
        Args:
            weight: Strategy weight
            workspace_dir: User workspace directory
        """
        super().__init__(name="history", weight=weight)
        self.workspace_dir = workspace_dir or os.environ.get(
            "COAPIS_WORKSPACE", os.path.expanduser("~/.coapis")
        )
        self.analyzer = HistoryAnalyzer(self.workspace_dir)
        
        # History-based recommendations
        self.history_recommendations = {
            "document": [
                {
                    "title": "文档深度分析",
                    "description": "分析文档结构、提取关键信息、生成摘要",
                    "prompt": "帮我深度分析这个文档，提取关键信息并生成摘要",
                    "icon": "📄",
                },
                {
                    "title": "文档对比",
                    "description": "对比两个文档的差异，找出重要变更",
                    "prompt": "帮我对比这两个文档，找出主要差异",
                    "icon": "🔀",
                },
            ],
            "search": [
                {
                    "title": "深度研究",
                    "description": "多源搜索、信息聚合、生成研究报告",
                    "prompt": "帮我深入研究这个主题，从多个来源收集信息并生成报告",
                    "icon": "🔍",
                },
                {
                    "title": "竞品分析",
                    "description": "搜索竞品信息，生成对比分析报告",
                    "prompt": "帮我做竞品分析，搜索相关产品信息并生成对比报告",
                    "icon": "📊",
                },
            ],
            "code": [
                {
                    "title": "代码审查",
                    "description": "审查代码质量，找出潜在问题",
                    "prompt": "帮我审查这段代码，检查代码质量和潜在问题",
                    "icon": "🔍",
                },
                {
                    "title": "代码优化",
                    "description": "分析代码性能，提供优化建议",
                    "prompt": "帮我分析这段代码的性能，提供优化建议",
                    "icon": "⚡",
                },
            ],
            "data": [
                {
                    "title": "数据可视化",
                    "description": "分析数据趋势，生成可视化图表",
                    "prompt": "帮我分析这些数据，生成可视化图表展示趋势",
                    "icon": "📈",
                },
                {
                    "title": "数据清洗",
                    "description": "清理脏数据，标准化数据格式",
                    "prompt": "帮我清洗这些数据，处理缺失值和异常值",
                    "icon": "🧹",
                },
            ],
            "email": [
                {
                    "title": "邮件撰写",
                    "description": "根据场景生成专业邮件内容",
                    "prompt": "帮我写一封专业的邮件，说明这个情况",
                    "icon": "✉️",
                },
                {
                    "title": "邮件整理",
                    "description": "整理收件箱，分类重要邮件",
                    "prompt": "帮我整理收件箱，找出重要邮件并分类",
                    "icon": "📬",
                },
            ],
            "browser": [
                {
                    "title": "网页数据抓取",
                    "description": "自动化抓取网页数据并整理",
                    "prompt": "帮我自动化抓取这个网页的数据并整理成表格",
                    "icon": "🌐",
                },
                {
                    "title": "表单自动填写",
                    "description": "自动化填写网页表单",
                    "prompt": "帮我自动化填写这个网页表单",
                    "icon": "📝",
                },
            ],
            "memory": [
                {
                    "title": "知识整理",
                    "description": "整理笔记，建立知识体系",
                    "prompt": "帮我整理这些笔记，建立清晰的知识体系",
                    "icon": "🧠",
                },
                {
                    "title": "经验总结",
                    "description": "总结经验教训，形成可复用的知识",
                    "prompt": "帮我总结这次经验，提炼可复用的知识点",
                    "icon": "💡",
                },
            ],
        }
    
    def get_candidates(
        self,
        user_id: str,
        context: Optional[Dict[str, Any]] = None,
    ) -> List[RecommendationItem]:
        """Generate recommendations based on user's history."""
        candidates = []
        
        try:
            # Analyze user patterns
            patterns = self.analyzer.analyze_user_patterns(user_id)
            top_patterns = self.analyzer.get_top_patterns(patterns, n=3)
            
            # Generate recommendations based on detected patterns
            for q_type, count in top_patterns["question_types"].items():
                if q_type in self.history_recommendations:
                    for rec in self.history_recommendations[q_type]:
                        candidates.append(RecommendationItem(
                            id=f"history:{q_type}:{rec['title']}",
                            title=rec["title"],
                            description=rec["description"],
                            prompt=rec["prompt"],
                            category="history",
                            icon=rec["icon"],
                            score=0.0,
                            metadata={"question_type": q_type, "frequency": count},
                        ))
            
            logger.debug(f"HistoryStrategy: Generated {len(candidates)} candidates for user {user_id}")
            
        except Exception as e:
            logger.error(f"HistoryStrategy failed: {e}")
        
        return candidates
    
    def score(
        self,
        item: RecommendationItem,
        context: Optional[Dict[str, Any]] = None,
    ) -> float:
        """Score based on history relevance."""
        # Score based on frequency of the question type
        frequency = item.metadata.get("frequency", 0) if item.metadata else 0
        
        # Normalize frequency to score (0.5 - 1.0)
        if frequency > 10:
            return 0.9
        elif frequency > 5:
            return 0.8
        elif frequency > 2:
            return 0.7
        elif frequency > 0:
            return 0.6
        else:
            return 0.5
    
    def get_weight(self, context: Optional[Dict[str, Any]] = None) -> float:
        """Adjust weight based on user's history depth."""
        # For users with more history, this strategy is more useful
        if context and context.get("has_history", False):
            return self.weight * 1.2
        return self.weight
