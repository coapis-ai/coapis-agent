# -*- coding: utf-8 -*-
# Copyright 2026 以太吃虾 & CoApis Contributors
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

"""跨 Agent 进化引擎 — AB 桶管理 + AI 关键字提取 + 搜索聚合 + 评审晋升。

与 Agent 内部进化（EvolutionEngine）的区别:
- EvolutionEngine: Agent 内部经验提取 → 个人记忆（Level-3 内部）
- CrossAgentEvolution: 跨 Agent 经验聚合 → AI 评审 → 晋升到全局基础层

核心流程:
1. 经验上报 → B 桶（待审核）
2. AI 提取关键字 → 搜索相似经验
3. 相似经验聚合 → AI 评审
4. 评审通过 → A 桶（已纳入）+ 写入全局基础层
"""
from __future__ import annotations

import asyncio
import json
import logging
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Optional

from ..utils.file_lock import safe_read_json, safe_write_json

logger = logging.getLogger(__name__)


# =========================================================================
# 配置
# =========================================================================

@dataclass
class CrossAgentEvolutionConfig:
    """进化引擎配置（全部可配置）。"""
    enabled: bool = True
    promotion_threshold: int = 3          # 多少条相似经验触发评审
    cold_start_threshold: int = 2         # 冷启动期（经验数<50）降低阈值
    review_interval_minutes: int = 30     # 后台评审间隔（分钟）
    bucket_a_capacity: int = 200          # A 桶最大容量
    bucket_b_capacity: int = 2000         # B 桶最大容量
    archive_ttl_days: int = 180           # 归档保留天数
    min_confidence: float = 0.6           # 经验上报最低置信度
    max_keywords: int = 5                 # 每条经验最多提取关键字数
    similarity_threshold: float = 0.5     # Jaccard 相似度阈值


# =========================================================================
# 数据模型
# =========================================================================

@dataclass
class ExperienceEntry:
    """经验条目（直接存 JSON，不预设 KV 归类）。"""
    id: str = field(default_factory=lambda: str(uuid.uuid4()))
    content: str = ""                      # 经验原文
    category: str = "general"              # 分类
    source_user: str = ""                  # 来源用户
    source_agent: str = ""                 # 来源 Agent ID
    agent_level: str = "global"            # 来源 Agent 类型（global/user）
    confidence: float = 0.5                # 置信度
    created_at: str = field(default_factory=lambda: datetime.now().isoformat())
    bucket: str = "B"                      # 所在桶（A=已纳入，B=待审核）
    status: str = "pending"                # pending/reviewed/promoted/archived/rejected
    keywords: list[str] = field(default_factory=list)  # AI 提取的关键字
    review_result: Optional[str] = None    # AI 评审结果
    is_generalizable: Optional[bool] = None  # 是否可泛化（适用于所有用户）
    needs_admin_confirm: bool = False      # 是否需要管理员确认
    admin_confirmed: bool = False          # 管理员是否已确认
    admin_confirmed_by: Optional[str] = None  # 确认人
    admin_confirmed_at: Optional[str] = None  # 确认时间
    # Promotion/Demotion tracking fields
    promoted_at: Optional[str] = None      # 晋升时间
    promoted_by: Optional[str] = None      # 晋升操作人
    promotion_comment: Optional[str] = None  # 晋升备注
    demotion_comment: Optional[str] = None   # 降级备注
    affected_users: list[str] = field(default_factory=list)  # 影响的用户列表
    affected_agents: list[str] = field(default_factory=list)  # 影响的 Agent 列表
    embedding: list[float] = field(default_factory=list)      # 语义向量 (embedding)

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "content": self.content,
            "category": self.category,
            "source_user": self.source_user,
            "source_agent": self.source_agent,
            "agent_level": self.agent_level,
            "confidence": self.confidence,
            "created_at": self.created_at,
            "bucket": self.bucket,
            "status": self.status,
            "keywords": self.keywords,
            "review_result": self.review_result,
            "is_generalizable": self.is_generalizable,
            "needs_admin_confirm": self.needs_admin_confirm,
            "admin_confirmed": self.admin_confirmed,
            "admin_confirmed_by": self.admin_confirmed_by,
            "admin_confirmed_at": self.admin_confirmed_at,
            "promoted_at": self.promoted_at,
            "promoted_by": self.promoted_by,
            "promotion_comment": self.promotion_comment,
            "demotion_comment": self.demotion_comment,
            "affected_users": self.affected_users,
            "affected_agents": self.affected_agents,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "ExperienceEntry":
        return cls(**{k: v for k, v in data.items() if k in cls.__dataclass_fields__})


# =========================================================================
# 核心引擎
# =========================================================================

class CrossAgentEvolution:
    """
    跨 Agent 进化引擎（后台服务）。

    职责:
    1. AB 桶管理（JSON 文件存储，容量限制）
    2. AI 关键字提取
    3. 搜索模式聚合（关键词匹配，Jaccard 相似度）
    4. AI 评审（LLM 判断是否晋升）
    5. 晋升到全局基础层
    """

    def __init__(
        self,
        data_dir: str | Path,
        model: Any = None,                # LLM client (AsyncOpenAI)
        config: CrossAgentEvolutionConfig | None = None,
        foundation_manager: Any = None,   # 全局基础层管理器
    ):
        self.data_dir = Path(data_dir)
        self.data_dir.mkdir(parents=True, exist_ok=True)
        
        self.model = model
        self.config = config or CrossAgentEvolutionConfig()
        self.foundation_manager = foundation_manager
        
        # 桶数据（内存缓存，定期持久化）
        self._bucket_a: list[ExperienceEntry] = []
        self._bucket_b: list[ExperienceEntry] = []
        self._foundation: list[ExperienceEntry] = []  # 全局基础层（独立存储）
        self._review_log: list[dict] = []
        
        # 异步锁（防止并发桶操作导致数据不一致）
        self._lock: asyncio.Lock = asyncio.Lock()
        
        # 持久化文件路径
        self._bucket_a_file = self.data_dir / "bucket_a.json"
        self._bucket_b_file = self.data_dir / "bucket_b.json"
        self._foundation_file = self.data_dir / "foundation.json"
        self._review_log_file = self.data_dir / "review_log.json"
        self._archive_dir = self.data_dir / "archive"
        self._archive_dir.mkdir(parents=True, exist_ok=True)
        
        # 加载已有数据
        self._load_buckets()
        self._load_foundation()
        
        # 定时评审任务
        self._review_task: Optional[asyncio.Task] = None
        
        logger.info(
            "CrossAgentEvolution: initialized (A=%d, B=%d, enabled=%s)",
            len(self._bucket_a), len(self._bucket_b), self.config.enabled,
        )

    # ------------------------------------------------------------------
    # Property accessors for external use (routes, APIs)
    # ------------------------------------------------------------------

    @property
    def bucket_a(self) -> list[ExperienceEntry]:
        """Bucket A entries (public accessor)."""
        return self._bucket_a

    @property
    def bucket_b(self) -> list[ExperienceEntry]:
        """Bucket B entries (public accessor)."""
        return self._bucket_b

    @property
    def bucket_a_count(self) -> int:
        return len(self._bucket_a)

    @property
    def bucket_b_count(self) -> int:
        return len(self._bucket_b)

    @property
    def review_log(self) -> list[dict]:
        return self._review_log

    @property
    def foundation(self) -> list[ExperienceEntry]:
        """Foundation layer entries (public accessor)."""
        return self._foundation

    @property
    def foundation_count(self) -> int:
        return len(self._foundation)

    # ------------------------------------------------------------------
    # 经验上报
    # ------------------------------------------------------------------

    def report_experience(
        self,
        content: str,
        category: str = "general",
        source_user: str = "",
        agent_level: str = "global",
        confidence: float = 0.5,
    ) -> ExperienceEntry:
        """
        上报经验到 B 桶（待审核）。

        Args:
            content: 经验原文
            category: 分类（skill/preference/behavior/domain）
            source_user: 来源用户
            agent_level: 来源 Agent 类型（global/user）
            confidence: 置信度

        Returns:
            创建的 ExperienceEntry
        """
        if not self.config.enabled:
            logger.debug("CrossAgentEvolution: disabled, skipping report")
            return ExperienceEntry()

        # 低质量自动降级：置信度 < 0.3 直接标记 archived（优先于 min_confidence 过滤）
        if confidence < 0.3:
            entry = ExperienceEntry(
                content=content, category=category, source_user=source_user,
                agent_level=agent_level, confidence=confidence,
                bucket="B", status="archived",
            )
            logger.info(
                "CrossAgentEvolution: auto-archived low quality (id=%s, conf=%.2f)",
                entry.id[:8], confidence,
            )
            return entry

        if confidence < self.config.min_confidence:
            logger.debug(
                "CrossAgentEvolution: confidence %.2f < %.2f, skipping",
                confidence, self.config.min_confidence,
            )
            return ExperienceEntry()
        
        entry = ExperienceEntry(
            content=content,
            category=category,
            source_user=source_user,
            agent_level=agent_level,
            confidence=confidence,
            bucket="B",
            status="pending",
        )
        
        # 检查 B 桶容量
        if len(self._bucket_b) >= self.config.bucket_b_capacity:
            self._evict_oldest_from_bucket_b()
        
        self._bucket_b.append(entry)
        self._save_bucket_b()
        
        logger.info(
            "CrossAgentEvolution: reported experience (id=%s, user=%s, bucket=%s)",
            entry.id[:8], source_user, entry.bucket,
        )
        
        return entry

    def report_trigger_enhancement(
        self,
        skill_name: str,
        trigger_keyword: str,
        signal_type: str,
        source_user: str = "",
        confidence: float = 0.7,
    ) -> ExperienceEntry:
        """上报触发词优化信号到跨 Agent 进化系统。

        当 ≥3 个用户独立提出相同的触发词优化（添加/移除），该优化可晋升为全局。

        Args:
            skill_name: 目标技能名
            trigger_keyword: 触发词关键词
            signal_type: "false_positive" (建议移除) 或 "false_negative" (建议添加)
            source_user: 来源用户
            confidence: 置信度
        """
        content = json.dumps({
            "skill_name": skill_name,
            "trigger_keyword": trigger_keyword,
            "signal_type": signal_type,
        }, ensure_ascii=False)

        entry = ExperienceEntry(
            content=content,
            category="trigger_enhancement",
            source_user=source_user,
            confidence=confidence,
            bucket="B",
            status="pending",
        )
        entry.keywords = [skill_name, trigger_keyword, signal_type]

        if len(self._bucket_b) >= self.config.bucket_b_capacity:
            self._evict_oldest_from_bucket_b()

        self._bucket_b.append(entry)
        self._save_bucket_b()

        logger.info(
            "CrossAgentEvolution: reported trigger enhancement (id=%s, skill=%s, kw=%s, type=%s, user=%s)",
            entry.id[:8], skill_name, trigger_keyword, signal_type, source_user,
        )
        return entry

    def report_skill_improvement(
        self,
        skill_name: str,
        improvement_type: str,
        description: str,
        source_user: str = "",
        confidence: float = 0.7,
    ) -> ExperienceEntry:
        """上报技能改进经验到跨 Agent 进化系统。

        Args:
            skill_name: 技能名
            improvement_type: 改进类型 (content_improvement / trigger_enhanced / version_bumped)
            description: 改进描述
            source_user: 来源用户
            confidence: 置信度
        """
        content = json.dumps({
            "skill_name": skill_name,
            "improvement_type": improvement_type,
            "description": description,
        }, ensure_ascii=False)

        entry = ExperienceEntry(
            content=content,
            category="skill_improvement",
            source_user=source_user,
            confidence=confidence,
            bucket="B",
            status="pending",
        )
        entry.keywords = [skill_name, improvement_type]

        if len(self._bucket_b) >= self.config.bucket_b_capacity:
            self._evict_oldest_from_bucket_b()

        self._bucket_b.append(entry)
        self._save_bucket_b()

        logger.info(
            "CrossAgentEvolution: reported skill improvement (id=%s, skill=%s, type=%s)",
            entry.id[:8], skill_name, improvement_type,
        )
        return entry

    def aggregate_trigger_enhancements(
        self,
        skill_name: str,
        signal_type: str = None,
    ) -> list[dict]:
        """聚合跨用户的触发词优化信号。

        当 ≥3 个不同用户独立提出相同的触发词优化时，返回可晋升的优化列表。

        Returns:
            [{"keyword": str, "signal_type": str, "user_count": int, "users": [str], "promotable": bool}]
        """
        keyword_signals: dict[str, dict] = {}

        # 扫描 B 桶中所有 trigger_enhancement 类型的经验
        for entry in self._bucket_b + self._bucket_a:
            if entry.category != "trigger_enhancement":
                continue
            try:
                data = json.loads(entry.content)
            except (json.JSONDecodeError, TypeError):
                continue

            if data.get("skill_name") != skill_name:
                continue
            if signal_type and data.get("signal_type") != signal_type:
                continue

            kw = data.get("trigger_keyword", "")
            sig_type = data.get("signal_type", "")
            key = f"{kw}:{sig_type}"

            if key not in keyword_signals:
                keyword_signals[key] = {
                    "keyword": kw,
                    "signal_type": sig_type,
                    "users": set(),
                    "count": 0,
                }
            keyword_signals[key]["users"].add(entry.source_user or "anonymous")
            keyword_signals[key]["count"] += 1

        # 转换为可序列化格式
        threshold = self.config.promotion_threshold
        results = []
        for key, info in keyword_signals.items():
            results.append({
                "keyword": info["keyword"],
                "signal_type": info["signal_type"],
                "user_count": len(info["users"]),
                "users": sorted(info["users"]),
                "total_reports": info["count"],
                "promotable": len(info["users"]) >= threshold,
            })

        results.sort(key=lambda x: x["user_count"], reverse=True)
        return results

    # ------------------------------------------------------------------
    # AI 关键字提取
    # ------------------------------------------------------------------

    async def _extract_keywords(self, entry: ExperienceEntry) -> list[str]:
        """使用 AI 提取经验关键字，失败时回退到规则提取。"""
        # 优先尝试 AI 提取
        if self.model:
            try:
                prompt = (
                    f"请为以下经验提取 {self.config.max_keywords} 个关键字，用于后续搜索相似经验。\n"
                    f"\n"
                    f"经验: {entry.content}\n"
                    f"分类: {entry.category}\n"
                    f"\n"
                    f"要求:\n"
                    f"- 使用中文或英文关键词\n"
                    f"- 选择最能代表经验本质的词\n"
                    f"- 避免过于通用的词（如'问题''方法'）\n"
                    f"\n"
                    f"返回纯 JSON 数组格式: [\"keyword1\", \"keyword2\", ...]"
                )
                
                response = await self.model.chat.completions.create(
                    model=self.model._current_model or "default",
                    messages=[{"role": "user", "content": prompt}],
                    temperature=0.1,
                    max_tokens=100,
                )
                
                text = response.choices[0].message.content.strip()
                # 兼容 reasoning 字段（Qwen3 reasoning-parser）
                if not text and hasattr(response.choices[0].message, "reasoning"):
                    text = response.choices[0].message.reasoning or ""
                
                # 提取 JSON 数组
                start = text.find("[")
                end = text.rfind("]") + 1
                if start >= 0 and end > start:
                    keywords = json.loads(text[start:end])
                    if keywords:
                        return keywords[:self.config.max_keywords]
                
                logger.warning("CrossAgentEvolution: keyword extraction failed to parse JSON, falling back to rule-based")
            except Exception as e:
                logger.warning("CrossAgentEvolution: AI keyword extraction error: %s, falling back to rule-based", e)
        
        # 回退：规则关键字提取（基于常见中文/英文分词）
        return self._rule_based_keywords(entry)

    def _rule_based_keywords(self, entry: ExperienceEntry) -> list[str]:
        """规则关键字提取（不依赖 LLM）。"""
        import re
        import jieba
        
        text = entry.content
        # 移除标点符号
        text = re.sub(r'[^\w\s]', '', text)
        
        try:
            # 使用 jieba 分词
            words = list(jieba.cut(text))
            # 过滤停用词和单字符
            STOP_WORDS = {
                '的', '了', '在', '是', '我', '有', '和', '就', '不', '人', '都', '一',
                '一个', '上', '也', '很', '到', '说', '要', '去', '你', '会', '着', '个',
                'that', 'the', 'a', 'an', 'is', 'are', 'was', 'were', 'be', 'been',
                'being', 'have', 'has', 'had', 'do', 'does', 'did', 'will', 'would',
                'could', 'should', 'may', 'might', 'can', 'shall', 'to', 'of', 'in',
                'for', 'on', 'with', 'at', 'by', 'from', 'as', 'into', 'through',
                'during', 'before', 'after', 'above', 'below', 'between', 'under',
            }
            keywords = [w for w in words if len(w) > 1 and w.lower() not in STOP_WORDS]
            return list(set(keywords))[:self.config.max_keywords]
        except ImportError:
            # jieba 未安装，使用简单分词
            words = re.findall(r'\w{2,}', text)
            return list(set(words))[:self.config.max_keywords]

    # ------------------------------------------------------------------
    # 搜索模式聚合（语义相似度 + Jaccard 降级）
    # ------------------------------------------------------------------

    def _generate_text_embedding(self, text: str) -> list[float]:
        """基于字符 n-gram 频率生成文本向量（轻量级，无需外部 API）。

        用 bigram/unigram 频率映射到固定维度，通过哈希分散。
        当 ReMeLight embedding 可用时，可通过 override 方法替换为真实向量。
        """
        import hashlib
        import math

        if not text:
            return []

        # 提取 token（中文按字+bigram，英文按字符）
        chars = []
        for ch in text:
            if ch.strip():
                chars.append(ch.lower())

        if not chars:
            return []

        dim = 128
        vec = [0.0] * dim

        # unigram 频率
        for ch in chars:
            h = hashlib.md5(ch.encode("utf-8")).digest()
            idx = h[0] % dim
            vec[idx] += 1.0

        # bigram 频率（更强的语义信号）
        for i in range(len(chars) - 1):
            bg = chars[i] + chars[i + 1]
            h = hashlib.md5(bg.encode("utf-8")).digest()
            idx = h[0] % dim
            vec[idx] += 2.0  # bigram 权重更高

        # trigram
        for i in range(len(chars) - 2):
            tg = chars[i] + chars[i + 1] + chars[i + 2]
            h = hashlib.md5(tg.encode("utf-8")).digest()
            idx = h[0] % dim
            vec[idx] += 3.0

        # L2 归一化
        norm = math.sqrt(sum(v * v for v in vec))
        if norm > 0:
            vec = [v / norm for v in vec]

        return vec

    @staticmethod
    def _cosine_similarity(vec1: list[float], vec2: list[float]) -> float:
        """计算两个向量的余弦相似度。"""
        if not vec1 or not vec2 or len(vec1) != len(vec2):
            return 0.0
        dot = sum(a * b for a, b in zip(vec1, vec2))
        norm1 = sum(a * a for a in vec1) ** 0.5
        norm2 = sum(b * b for b in vec2) ** 0.5
        if norm1 == 0 or norm2 == 0:
            return 0.0
        return dot / (norm1 * norm2)

    def _jaccard_similarity(self, keywords1: list[str], keywords2: list[str]) -> float:
        """计算两个关键字列表的 Jaccard 相似度（降级方案）。"""
        if not keywords1 or not keywords2:
            return 0.0
        set1 = set(keywords1)
        set2 = set(keywords2)
        intersection = set1 & set2
        union = set1 | set2
        return len(intersection) / len(union) if union else 0.0

    def _find_similar_experiences(
        self,
        entry: ExperienceEntry,
        bucket: list[ExperienceEntry] | None = None,
    ) -> list[ExperienceEntry]:
        """通过语义相似度找到相似经验（降级到 Jaccard）。"""
        search_bucket = bucket or self._bucket_b
        similar = []

        # 确保当前 entry 有 embedding
        if not entry.embedding:
            entry.embedding = self._generate_text_embedding(entry.content)

        use_embedding = bool(entry.embedding)

        for other in search_bucket:
            if other.id == entry.id:
                continue
            if other.status != "pending":
                continue

            if use_embedding and other.embedding:
                # 语义相似度
                if not other.embedding:
                    other.embedding = self._generate_text_embedding(other.content)
                similarity = self._cosine_similarity(entry.embedding, other.embedding)
            elif entry.keywords and other.keywords:
                # 降级到 Jaccard
                similarity = self._jaccard_similarity(entry.keywords, other.keywords)
            else:
                continue

            if similarity >= self.config.similarity_threshold:
                similar.append(other)

        return similar

    # ------------------------------------------------------------------
    # AI 评审
    # ------------------------------------------------------------------

    async def _review_experiences(
        self,
        entry: ExperienceEntry,
        similar: list[ExperienceEntry],
    ) -> dict:
        """
        使用 AI 评审经验是否值得晋升。

        Returns:
            {"same_pattern": bool, "should_promote": bool, "principle": str, "reason": str}
        """
        if not self.model:
            logger.warning("CrossAgentEvolution: no model available, skipping review")
            return {"same_pattern": False, "should_promote": False, "principle": "", "reason": "no model"}
        
        # 构建评审 Prompt
        experiences_text = ""
        for i, exp in enumerate([entry] + similar[:4], 1):
            experiences_text += (
                f"经验{i}: {exp.content}\n"
                f"用户: {exp.source_user}\n"
                f"分类: {exp.category}\n\n"
            )
        
        threshold = (
            self.config.cold_start_threshold
            if len(self._bucket_b) < 50
            else self.config.promotion_threshold
        )
        
        prompt = (
            f"你是 CoApis 系统的知识评审员。\n"
            f"\n"
            f"以下 {len([entry] + similar)} 条经验都涉及相似模式:\n"
            f"\n"
            f"{experiences_text}"
            f"请判断:\n"
            f"1. 这些经验是否指向同一个真实模式？（是/否）\n"
            f"2. 这个模式是否值得成为全局基础原则？\n"
            f"   标准: 对绝大多数用户都有价值，且具备普适性\n"
            f"3. 这个模式是否可泛化（适用于所有用户，而非特定用户场景）？\n"
            f"4. 如果应该，请提炼核心原则（一句话，简洁准确）\n"
            f"5. 给出理由\n"
            f"\n"
            f"返回JSON: {{\n"
            f'  "same_pattern": "yes/no",\n'
            f'  "should_promote": "yes/no",\n'
            f'  "is_generalizable": "yes/no",\n'
            f'  "principle": "...",\n'
            f'  "reason": "..."}}'
        )
        
        try:
            response = await self.model.chat.completions.create(
                model=self.model._current_model or "default",
                messages=[{"role": "user", "content": prompt}],
                temperature=0.1,
                max_tokens=300,
            )
            
            text = response.choices[0].message.content.strip()
            # 提取 JSON
            start = text.find("{")
            end = text.rfind("}") + 1
            if start >= 0 and end > start:
                result = json.loads(text[start:end])
                return {
                    "same_pattern": result.get("same_pattern", "no") == "yes",
                    "should_promote": result.get("should_promote", "no") == "yes",
                    "is_generalizable": result.get("is_generalizable", "no") == "yes",
                    "principle": result.get("principle", ""),
                    "reason": result.get("reason", ""),
                }
            
            logger.warning("CrossAgentEvolution: review failed to parse JSON")
            return {"same_pattern": False, "should_promote": False, "principle": "", "reason": "parse error"}
            
        except Exception as e:
            logger.error("CrossAgentEvolution: review error: %s", e)
            return {"same_pattern": False, "should_promote": False, "principle": "", "reason": str(e)}

    # ------------------------------------------------------------------
    # 定时评审周期
    # ------------------------------------------------------------------

    async def run_review_cycle(self) -> list[dict]:
        """
        执行一次评审周期。

        Returns:
            评审结果列表
        """
        if not self.config.enabled:
            return []
        
        pending = [e for e in self._bucket_b if e.status == "pending"]
        results = []
        
        logger.info(
            "CrossAgentEvolution: review cycle started (%d pending)",
            len(pending),
        )
        
        reviewed_ids = set()
        
        for entry in pending:
            if entry.id in reviewed_ids:
                continue
            
            # 1. 提取关键字
            if not entry.keywords:
                entry.keywords = await self._extract_keywords(entry)
            
            # 2. 搜索相似经验
            similar = self._find_similar_experiences(entry)
            
            # 3. 判断是否达到评审阈值
            threshold = (
                self.config.cold_start_threshold
                if len(self._bucket_b) < 50
                else self.config.promotion_threshold
            )
            
            if len(similar) + 1 < threshold:
                continue  # 相似经验不足，跳过
            
            # 4. AI 评审
            review_result = await self._review_experiences(entry, similar)
            
            # 5. 处理评审结果
            entry.review_result = json.dumps(review_result, ensure_ascii=False)
            is_generalizable = review_result.get("is_generalizable", False)
            entry.is_generalizable = is_generalizable
            
            if review_result.get("should_promote"):
                if not is_generalizable:
                    # 不可泛化 → 标记为需管理员确认，暂不写入全局
                    entry.bucket = "A"
                    entry.status = "pending_admin_confirm"
                    entry.needs_admin_confirm = True
                    self._bucket_b.remove(entry)
                    self._bucket_a.append(entry)
                    logger.info(
                        "CrossAgentEvolution: non-generalizable, needs admin confirm (id=%s)",
                        entry.id[:8],
                    )
                else:
                    # 可泛化 → 晋升到 A 桶，标记需管理员确认后才写入全局
                    entry.bucket = "A"
                    entry.status = "pending_admin_confirm"
                    entry.needs_admin_confirm = True
                    self._bucket_b.remove(entry)
                    self._bucket_a.append(entry)
                    
                    logger.info(
                        "CrossAgentEvolution: promoted (needs admin confirm) (id=%s, principle=%s, generalizable=%s)",
                        entry.id[:8], review_result.get("principle", ""), is_generalizable,
                    )
                
                # 标记相似条目为已评审
                for s in similar:
                    s.status = "reviewed"
                    reviewed_ids.add(s.id)
            else:
                # 归档
                entry.status = "archived"
                self._archive_entry(entry)
                
                logger.info(
                    "CrossAgentEvolution: archived experience (id=%s, reason=%s)",
                    entry.id[:8], review_result.get("reason", ""),
                )
            
            # 记录评审日志
            self._review_log.append({
                "timestamp": datetime.now().isoformat(),
                "entry_id": entry.id,
                "result": review_result,
                "similar_count": len(similar),
            })
            
            results.append({
                "entry_id": entry.id,
                "promoted": review_result.get("should_promote", False),
                "principle": review_result.get("principle", ""),
                "reason": review_result.get("reason", ""),
            })
        
        # 持久化
        self._save_bucket_a()
        self._save_bucket_b()
        self._save_review_log()
        
        logger.info(
            "CrossAgentEvolution: review cycle completed (%d promoted, %d archived)",
            sum(1 for r in results if r["promoted"]),
            sum(1 for r in results if not r["promoted"]),
        )
        
        return results

    # ------------------------------------------------------------------
    # 定时任务管理
    # ------------------------------------------------------------------

    async def _periodic_review_loop(self):
        """后台定时评审循环。"""
        while self.config.enabled:
            await asyncio.sleep(self.config.review_interval_minutes * 60)
            try:
                await self.run_review_cycle()
            except Exception as e:
                logger.error("CrossAgentEvolution: periodic review error: %s", e)

    def start_periodic_review(self) -> None:
        """启动后台定时评审任务。"""
        if self._review_task and not self._review_task.done():
            logger.warning("CrossAgentEvolution: periodic review already running")
            return
        
        self._review_task = asyncio.create_task(self._periodic_review_loop())
        logger.info("CrossAgentEvolution: periodic review started")

    def stop_periodic_review(self) -> None:
        """停止后台定时评审任务。"""
        if self._review_task:
            self._review_task.cancel()
            self._review_task = None
            logger.info("CrossAgentEvolution: periodic review stopped")

    # ------------------------------------------------------------------
    # 晋升/降级
    # ------------------------------------------------------------------

    def promote_to_foundation(
        self,
        experience_id: str,
        promoted_by: str = "",
        comment: str = "",
    ) -> ExperienceEntry | None:
        """从 Bucket A 晋升经验到全局基础层。"""
        exp = next((e for e in self._bucket_a if e.id == experience_id), None)
        if not exp:
            logger.warning("CrossAgentEvolution: promote failed - not found in A (id=%s)", experience_id[:8])
            return None

        # 设置晋升元数据
        exp.status = "promoted"
        exp.promoted_at = datetime.now().isoformat()
        exp.promoted_by = promoted_by
        exp.promotion_comment = comment
        exp.bucket = "foundation"

        # 从 A 桶移除并加入基础层
        self._bucket_a.remove(exp)
        self._foundation.append(exp)

        # 持久化
        self._save_bucket_a()
        self._save_foundation()

        logger.info(
            "CrossAgentEvolution: promoted to foundation (id=%s, by=%s)",
            exp.id[:8], promoted_by,
        )
        return exp

    def demote_from_foundation(
        self,
        experience_id: str,
        comment: str = "",
    ) -> ExperienceEntry | None:
        """从全局基础层降级回 Bucket A。"""
        exp = next((e for e in self._foundation if e.id == experience_id), None)
        if not exp:
            logger.warning("CrossAgentEvolution: demote failed - not found in foundation (id=%s)", experience_id[:8])
            return None

        # 设置降级元数据
        exp.status = "reviewed"
        exp.demotion_comment = comment
        exp.bucket = "A"

        # 从基础层移除并加入 A 桶
        self._foundation.remove(exp)
        self._bucket_a.append(exp)

        # 持久化
        self._save_foundation()
        self._save_bucket_a()

        logger.info(
            "CrossAgentEvolution: demoted from foundation (id=%s)",
            exp.id[:8],
        )
        return exp

    # ------------------------------------------------------------------
    # 容量管理
    # ------------------------------------------------------------------

    def _evict_oldest_from_bucket_b(self) -> ExperienceEntry | None:
        """B 桶满时淘汰最早的未审核条目。"""
        if not self._bucket_b:
            return None
        
        # 按创建时间排序，淘汰最早的
        self._bucket_b.sort(key=lambda e: e.created_at)
        evicted = self._bucket_b.pop(0)
        evicted.status = "archived"
        self._archive_entry(evicted)
        
        logger.info(
            "CrossAgentEvolution: evicted oldest from B bucket (id=%s)",
            evicted.id[:8],
        )
        
        return evicted

    def _evict_lowest_from_bucket_a(self) -> ExperienceEntry | None:
        """A 桶满时淘汰最低置信度的条目。"""
        if not self._bucket_a:
            return None
        
        # 按置信度排序，淘汰最低的
        self._bucket_a.sort(key=lambda e: e.confidence)
        evicted = self._bucket_a.pop(0)
        evicted.bucket = "B"
        evicted.status = "pending"
        self._bucket_b.append(evicted)
        
        logger.info(
            "CrossAgentEvolution: evicted lowest from A bucket (id=%s, confidence=%.2f)",
            evicted.id[:8], evicted.confidence,
        )
        
        return evicted

    # ------------------------------------------------------------------
    # 归档管理
    # ------------------------------------------------------------------

    def admin_confirm(self, entry_id: str, confirmed_by: str = "admin") -> bool:
        """管理员确认经验写入全局基础层。

        Args:
            entry_id: 经验条目 ID
            confirmed_by: 确认人

        Returns:
            是否确认成功
        """
        entry = None
        for e in self._bucket_a:
            if e.id == entry_id:
                entry = e
                break

        if not entry:
            logger.warning("admin_confirm: entry %s not found in bucket A", entry_id)
            return False

        entry.admin_confirmed = True
        entry.admin_confirmed_by = confirmed_by
        entry.admin_confirmed_at = datetime.now().isoformat()
        entry.needs_admin_confirm = False
        entry.status = "promoted"

        # 写入全局基础层
        if self.foundation_manager:
            try:
                principle = ""
                if entry.review_result:
                    try:
                        rr = json.loads(entry.review_result)
                        principle = rr.get("principle", entry.content)
                    except (json.JSONDecodeError, TypeError):
                        principle = entry.content
                else:
                    principle = entry.content

                self.foundation_manager.add_principle(
                    principle=principle,
                    source_entry=entry,
                    source_users=[entry.source_user] if entry.source_user else [],
                    category=entry.category,
                    review_reason=f"Admin confirmed by {confirmed_by}",
                )
                logger.info(
                    "admin_confirm: entry %s written to global foundation by %s",
                    entry_id[:8], confirmed_by,
                )
            except Exception as e:
                logger.warning("admin_confirm: failed to write to foundation: %s", e)

        self._save_buckets()
        return True

    def admin_reject(self, entry_id: str, rejected_by: str = "admin", reason: str = "") -> bool:
        """管理员拒绝经验晋升。"""
        entry = None
        for e in self._bucket_a:
            if e.id == entry_id:
                entry = e
                break

        if not entry:
            return False

        entry.status = "rejected"
        entry.admin_confirmed = False
        entry.admin_confirmed_by = rejected_by
        entry.admin_confirmed_at = datetime.now().isoformat()
        entry.demotion_comment = reason or f"Rejected by {rejected_by}"
        self._bucket_a.remove(entry)
        self._archive_entry(entry)
        self._save_buckets()
        logger.info("admin_reject: entry %s rejected by %s", entry_id[:8], rejected_by)
        return True

    def get_pending_confirmations(self) -> list[ExperienceEntry]:
        """获取待管理员确认的经验条目。"""
        return [e for e in self._bucket_a if e.needs_admin_confirm]

    def _archive_entry(self, entry: ExperienceEntry) -> None:
        """归档经验条目。"""
        archive_file = self._archive_dir / f"archived_{datetime.now().strftime('%Y%m')}.json"
        
        entries = []
        if archive_file.exists():
            with open(archive_file, "r", encoding="utf-8") as f:
                entries = json.load(f)
        
        entries.append(entry.to_dict())
        
        with open(archive_file, "w", encoding="utf-8") as f:
            json.dump(entries, f, ensure_ascii=False, indent=2)

    def cleanup_expired_archives(self) -> int:
        """清理过期归档（超过 archive_ttl_days 天）。"""
        cutoff = datetime.now() - timedelta(days=self.config.archive_ttl_days)
        cleaned = 0
        
        for archive_file in self._archive_dir.glob("archived_*.json"):
            # 从文件名提取月份
            month_str = archive_file.stem.replace("archived_", "")
            if len(month_str) == 6:
                archive_date = datetime.strptime(month_str, "%Y%m")
                if archive_date < cutoff:
                    archive_file.unlink()
                    cleaned += 1
        
        if cleaned:
            logger.info("CrossAgentEvolution: cleaned %d expired archives", cleaned)
        
        return cleaned

    # ------------------------------------------------------------------
    # 持久化
    # ------------------------------------------------------------------

    def _load_buckets(self) -> None:
        """从文件加载桶数据。"""
        data_a = safe_read_json(self._bucket_a_file, default=[])
        if data_a:
            self._bucket_a = [ExperienceEntry.from_dict(d) for d in data_a]
        
        data_b = safe_read_json(self._bucket_b_file, default=[])
        if data_b:
            self._bucket_b = [ExperienceEntry.from_dict(d) for d in data_b]
        
        self._review_log = safe_read_json(self._review_log_file, default=[])

    def _load_foundation(self) -> None:
        """从文件加载基础层数据。"""
        data = safe_read_json(self._foundation_file, default=[])
        if data:
            self._foundation = [ExperienceEntry.from_dict(d) for d in data]
            logger.info("CrossAgentEvolution: loaded %d foundation entries", len(self._foundation))

    def _save_foundation(self) -> None:
        """保存基础层到文件。"""
        safe_write_json(self._foundation_file, [e.to_dict() for e in self._foundation])

    def _save_bucket_a(self) -> None:
        """保存 A 桶到文件。"""
        safe_write_json(self._bucket_a_file, [e.to_dict() for e in self._bucket_a])

    def _save_bucket_b(self) -> None:
        """保存 B 桶到文件。"""
        safe_write_json(self._bucket_b_file, [e.to_dict() for e in self._bucket_b])

    def _save_review_log(self) -> None:
        """保存评审日志到文件。"""
        safe_write_json(self._review_log_file, self._review_log)

    # ------------------------------------------------------------------
    # 查询接口
    # ------------------------------------------------------------------

    def get_bucket_stats(self) -> dict:
        """获取桶统计信息。"""
        return {
            "bucket_a": {
                "total": len(self._bucket_a),
                "capacity": self.config.bucket_a_capacity,
                "by_category": self._count_by_category(self._bucket_a),
                "by_status": self._count_by_status(self._bucket_a),
            },
            "bucket_b": {
                "total": len(self._bucket_b),
                "capacity": self.config.bucket_b_capacity,
                "pending": sum(1 for e in self._bucket_b if e.status == "pending"),
                "by_category": self._count_by_category(self._bucket_b),
                "by_status": self._count_by_status(self._bucket_b),
            },
            "foundation": {
                "total": len(self._foundation),
                "by_category": self._count_by_category(self._foundation),
                "by_status": self._count_by_status(self._foundation),
            },
            "review_log": {
                "total": len(self._review_log),
            },
        }

    def _count_by_category(self, entries: list[ExperienceEntry]) -> dict:
        result = {}
        for e in entries:
            result[e.category] = result.get(e.category, 0) + 1
        return result

    def _count_by_status(self, entries: list[ExperienceEntry]) -> dict:
        result = {}
        for e in entries:
            result[e.status] = result.get(e.status, 0) + 1
        return result

    def get_entries(self, bucket: str = "B", status: str | None = None) -> list[ExperienceEntry]:
        """获取桶中的经验条目。"""
        entries = self._bucket_a if bucket == "A" else self._bucket_b
        if status:
            entries = [e for e in entries if e.status == status]
        return entries


# =========================================================================
# 全局单例工厂
# =========================================================================

_global_instance: CrossAgentEvolution | None = None


def get_global_cross_agent_evolution() -> CrossAgentEvolution | None:
    """获取全局共享的 CrossAgentEvolution 实例（单例）。"""
    return _global_instance


def init_global_cross_agent_evolution(
    model: Any = None,
    config: CrossAgentEvolutionConfig | None = None,
    foundation_manager: Any = None,
) -> CrossAgentEvolution:
    """初始化全局共享的 CrossAgentEvolution。

    数据目录统一使用 system/evolution/cross_evolution/，
    所有全局 agent 共享同一个实例（AB 桶数据不再分散）。
    """
    global _global_instance
    if _global_instance is not None:
        # 更新 model 和 foundation_manager（启动后才可用）
        if model is not None:
            _global_instance.model = model
        if foundation_manager is not None:
            _global_instance.foundation_manager = foundation_manager
        return _global_instance

    from ..constant import SYSTEM_DIR
    data_dir = SYSTEM_DIR / "evolution" / "cross_evolution"
    data_dir.mkdir(parents=True, exist_ok=True)

    if config is None:
        config = CrossAgentEvolutionConfig()
        config_file = SYSTEM_DIR / "config" / "evolution_config.json"
        if config_file.exists():
            try:
                import json as _json
                with open(config_file) as _f:
                    config_data = _json.load(_f)
                config = CrossAgentEvolutionConfig(**config_data)
                logger.info("Loaded CrossAgentEvolution config from %s", config_file)
            except Exception as e:
                logger.warning("Failed to load CrossAgentEvolution config: %s", e)

    _global_instance = CrossAgentEvolution(
        data_dir=data_dir,
        model=model,
        config=config,
        foundation_manager=foundation_manager,
    )
    logger.info(
        "Global CrossAgentEvolution initialized at %s (A=%d, B=%d)",
        data_dir, _global_instance.bucket_a_count, _global_instance.bucket_b_count,
    )
    return _global_instance
