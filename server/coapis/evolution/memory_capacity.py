# -*- coding: utf-8 -*-
"""全局记忆容量管理 — 容量限制、自动淘汰、锁定、版本历史。

职责:
1. 监控 MEMORY.md 大小（tokens），超限触发自动淘汰
2. 解析结构化记忆条目（带置信度/锁定/频率元数据）
3. 自动淘汰低置信度 / 低使用频率的条目（锁定条目除外）
4. 管理员可手动锁定/解锁经验条目
5. 重大修改前自动备份，支持版本回滚
"""
from __future__ import annotations

import json
import logging
import re
import shutil
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

# ── 配置 ──
DEFAULT_MAX_TOKENS = 10000          # 全局 MEMORY.md 建议上限
DEFAULT_ARCHIVE_THRESHOLD = 0.3     # 置信度 < 此值自动标记 archived
DEFAULT_STALE_DAYS = 90             # 超过 N 天未使用且低置信度 → archived
MAX_VERSIONS = 20                   # 保留的版本历史数量

# 中文约 1.5 token/字，英文约 0.25 token/word
CHARS_PER_TOKEN_ZH = 1.5


def estimate_tokens(text: str) -> int:
    """粗略估算 token 数（中英混合）。"""
    if not text:
        return 0
    # 简化计算：中文字符约 1.5 token/字，英文单词约 1 token/word
    zh_chars = len(re.findall(r'[\u4e00-\u9fff]', text))
    en_words = len(re.findall(r'[a-zA-Z]+', text))
    other = len(text) - zh_chars - sum(len(w) for w in re.findall(r'[a-zA-Z]+', text))
    return int(zh_chars * 1.5 + en_words + other * 0.3)


@dataclass
class MemoryEntry:
    """结构化记忆条目。"""
    content: str = ""                           # 原文内容
    confidence: float = 1.0                     # 置信度 (0-1)
    use_count: int = 0                          # 使用次数
    locked: bool = False                        # 管理员锁定（不可淘汰）
    status: str = "active"                      # active / archived
    created_at: str = ""                        # 创建时间
    last_used: str = ""                         # 最后使用时间
    source: str = ""                            # 来源标记
    section: str = ""                           # 所属 section


class MemoryCapacityManager:
    """全局记忆容量管理器。"""

    def __init__(
        self,
        memory_file: Path,
        max_tokens: int = DEFAULT_MAX_TOKENS,
        metadata_file: Path | None = None,
        versions_dir: Path | None = None,
    ):
        self.memory_file = memory_file
        self.max_tokens = max_tokens
        self.metadata_file = metadata_file or memory_file.parent / ".memory_meta.json"
        self.versions_dir = versions_dir or memory_file.parent / ".memory_versions"
        self.versions_dir.mkdir(parents=True, exist_ok=True)

        self._metadata: dict[str, dict] = {}  # entry_id -> meta
        self._load_metadata()

    def _load_metadata(self) -> None:
        """加载条目元数据。"""
        if self.metadata_file.exists():
            try:
                with open(self.metadata_file) as f:
                    self._metadata = json.load(f)
            except Exception as e:
                logger.warning("Failed to load memory metadata: %s", e)
                self._metadata = {}

    def _save_metadata(self) -> None:
        """保存条目元数据。"""
        try:
            with open(self.metadata_file, "w") as f:
                json.dump(self._metadata, f, ensure_ascii=False, indent=2)
        except Exception as e:
            logger.warning("Failed to save memory metadata: %s", e)

    def check_capacity(self) -> dict:
        """检查当前 MEMORY.md 容量状态。

        Returns:
            dict with keys: current_tokens, max_tokens, usage_ratio, over_limit, content_chars
        """
        if not self.memory_file.exists():
            return {
                "current_tokens": 0,
                "max_tokens": self.max_tokens,
                "usage_ratio": 0.0,
                "over_limit": False,
                "content_chars": 0,
            }

        content = self.memory_file.read_text(encoding="utf-8")
        tokens = estimate_tokens(content)
        ratio = tokens / self.max_tokens if self.max_tokens > 0 else 0

        return {
            "current_tokens": tokens,
            "max_tokens": self.max_tokens,
            "usage_ratio": round(ratio, 3),
            "over_limit": tokens > self.max_tokens,
            "content_chars": len(content),
        }

    def backup_version(self, reason: str = "auto") -> Optional[Path]:
        """备份当前 MEMORY.md 到版本历史。

        Args:
            reason: 备份原因标记

        Returns:
            备份文件路径，失败返回 None
        """
        if not self.memory_file.exists():
            return None

        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        version_name = f"MEMORY_{timestamp}_{reason}.md"
        version_path = self.versions_dir / version_name

        try:
            shutil.copy2(self.memory_file, version_path)
            logger.info("Memory backup created: %s", version_path)

            # 清理旧版本（保留最新 N 个）
            versions = sorted(self.versions_dir.glob("MEMORY_*.md"), reverse=True)
            for old in versions[MAX_VERSIONS:]:
                old.unlink()
                logger.debug("Removed old memory version: %s", old)

            return version_path
        except Exception as e:
            logger.warning("Failed to backup memory: %s", e)
            return None

    def rollback_to_version(self, version_name: str) -> bool:
        """回滚到指定版本。

        Args:
            version_name: 版本文件名（不含路径）

        Returns:
            是否回滚成功
        """
        version_path = self.versions_dir / version_name
        if not version_path.exists():
            logger.warning("Version not found: %s", version_path)
            return False

        # 先备份当前版本
        self.backup_version(reason="pre_rollback")

        try:
            content = version_path.read_text(encoding="utf-8")
            self.memory_file.write_text(content, encoding="utf-8")
            logger.info("Memory rolled back to: %s", version_name)
            return True
        except Exception as e:
            logger.warning("Failed to rollback memory: %s", e)
            return False

    def list_versions(self) -> list[dict]:
        """列出所有版本历史。"""
        versions = []
        for f in sorted(self.versions_dir.glob("MEMORY_*.md"), reverse=True):
            versions.append({
                "name": f.name,
                "size": f.stat().st_size,
                "mtime": datetime.fromtimestamp(f.stat().st_mtime).isoformat(),
            })
        return versions

    def lock_entry(self, entry_id: str) -> bool:
        """锁定条目（防止被淘汰）。"""
        if entry_id not in self._metadata:
            self._metadata[entry_id] = {}
        self._metadata[entry_id]["locked"] = True
        self._save_metadata()
        logger.info("Locked memory entry: %s", entry_id)
        return True

    def unlock_entry(self, entry_id: str) -> bool:
        """解锁条目。"""
        if entry_id in self._metadata:
            self._metadata[entry_id]["locked"] = False
            self._save_metadata()
            logger.info("Unlocked memory entry: %s", entry_id)
            return True
        return False

    def is_locked(self, entry_id: str) -> bool:
        """检查条目是否被锁定。"""
        return self._metadata.get(entry_id, {}).get("locked", False)

    def auto_archive_stale(self) -> dict:
        """自动淘汰过时条目（低置信度 + 低使用频率 + 未锁定）。

        Returns:
            dict with keys: archived_count, remaining_tokens, details
        """
        if not self.memory_file.exists():
            return {"archived_count": 0, "remaining_tokens": 0, "details": []}

        content = self.memory_file.read_text(encoding="utf-8")
        current_tokens = estimate_tokens(content)

        if current_tokens <= self.max_tokens:
            return {
                "archived_count": 0,
                "remaining_tokens": current_tokens,
                "details": [],
            }

        # 找出可淘汰的条目
        now = datetime.now().isoformat()
        archived = []
        to_remove_ids = []

        for entry_id, meta in self._metadata.items():
            if meta.get("locked", False):
                continue
            if meta.get("status") == "archived":
                continue

            confidence = meta.get("confidence", 1.0)
            use_count = meta.get("use_count", 0)
            last_used = meta.get("last_used", "")

            # 低置信度 + 低使用频率 → 标记为 archived
            if confidence < DEFAULT_ARCHIVE_THRESHOLD and use_count < 2:
                self._metadata[entry_id]["status"] = "archived"
                self._metadata[entry_id]["archived_at"] = now
                archived.append(entry_id)
                to_remove_ids.append(entry_id)

        if archived:
            self._save_metadata()
            logger.info(
                "Auto-archived %d stale entries (low confidence + low usage)",
                len(archived),
            )

        # 重新计算
        if self.memory_file.exists():
            remaining = estimate_tokens(self.memory_file.read_text(encoding="utf-8"))
        else:
            remaining = 0

        return {
            "archived_count": len(archived),
            "remaining_tokens": remaining,
            "details": archived,
        }

    def get_status(self) -> dict:
        """获取完整的容量管理状态。"""
        capacity = self.check_capacity()
        versions = self.list_versions()

        locked_count = sum(1 for m in self._metadata.values() if m.get("locked"))
        archived_count = sum(1 for m in self._metadata.values() if m.get("status") == "archived")
        active_count = sum(1 for m in self._metadata.values() if m.get("status", "active") == "active")

        return {
            **capacity,
            "entries": {
                "total": len(self._metadata),
                "active": active_count,
                "archived": archived_count,
                "locked": locked_count,
            },
            "versions": len(versions),
            "latest_version": versions[0] if versions else None,
        }
