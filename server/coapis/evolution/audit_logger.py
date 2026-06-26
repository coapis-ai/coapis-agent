# -*- coding: utf-8 -*-
"""进化审计日志 — 记录所有进化变更，支持查询、统计、回滚。

存储位置: system/evolution/audit_log.jsonl
每条记录为一行 JSON，字段定义见 AuditEntry。
"""
from __future__ import annotations

import json
import logging
import os
import uuid
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

from ..utils.file_lock import safe_append_jsonl, safe_read_json

logger = logging.getLogger(__name__)

# ── 单例 ──────────────────────────────────────────────────────────────────

_global_logger: Optional["AuditLogger"] = None


def get_audit_logger() -> "AuditLogger":
    """返回全局 AuditLogger 单例。"""
    global _global_logger
    if _global_logger is None:
        _global_logger = AuditLogger()
    return _global_logger


# ── 数据模型 ──────────────────────────────────────────────────────────────

@dataclass
class AuditEntry:
    """单条审计日志。"""
    entry_id: str = field(default_factory=lambda: uuid.uuid4().hex[:12])
    timestamp: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    # 变更类型
    change_type: str = ""       # add | update | delete | promote | demote | rollback
    target_type: str = ""       # memory | skill | experience | config
    target_id: str = ""         # 目标标识（经验 id / 技能名 / 文件路径）
    # 风险与审核
    risk_level: str = "L0"      # L0 | L1 | L2
    review_method: str = "auto" # auto | llm | manual
    reviewer: str = "system"    # system | llm | admin
    decision: str = "approved"  # approved | rejected | modified
    reason: str = ""
    # 内容快照
    content_before: str = ""    # 变更前内容（用于回滚）
    content_after: str = ""     # 变更后内容
    # 关联信息
    source_user: str = ""
    source_agent: str = ""
    session_id: str = ""
    # 回滚标记
    rollback_available: bool = False
    rolled_back: bool = False
    rollback_entry_id: str = ""

    def to_dict(self) -> dict:
        return asdict(self)


# ── 日志器 ──────────────────────────────────────────────────────────────

class AuditLogger:
    """进化审计日志器。

    用法:
        al = get_audit_logger()
        al.log(AuditEntry(
            change_type="promote",
            target_type="experience",
            target_id="exp_abc",
            risk_level="L1",
            review_method="llm",
            decision="approved",
            reason="LLM 审核通过",
            content_before="B 桶待审核",
            content_after="A 桶已纳入",
        ))
    """

    def __init__(self, log_path: Path | None = None):
        if log_path is None:
            from ..constant import SYSTEM_EVOLUTION_DIR
            log_path = SYSTEM_EVOLUTION_DIR / "audit_log.jsonl"
        self._log_path = log_path
        self._log_path.parent.mkdir(parents=True, exist_ok=True)

    # ── 写入 ──

    def log(self, entry: AuditEntry) -> bool:
        """写入一条审计记录。"""
        record = entry.to_dict()
        ok = safe_append_jsonl(self._log_path, record)
        if ok:
            logger.info(
                "AuditLog: %s %s/%s risk=%s decision=%s",
                entry.change_type, entry.target_type, entry.target_id[:16],
                entry.risk_level, entry.decision,
            )
        return ok

    # ── 查询 ──

    def query(
        self,
        *,
        change_type: str | None = None,
        target_type: str | None = None,
        risk_level: str | None = None,
        review_method: str | None = None,
        limit: int = 50,
    ) -> list[dict]:
        """查询审计日志，支持筛选。返回最新的 limit 条。"""
        if not self._log_path.exists():
            return []
        results: list[dict] = []
        try:
            with open(self._log_path, "r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        rec = json.loads(line)
                    except json.JSONDecodeError:
                        continue
                    if change_type and rec.get("change_type") != change_type:
                        continue
                    if target_type and rec.get("target_type") != target_type:
                        continue
                    if risk_level and rec.get("risk_level") != risk_level:
                        continue
                    if review_method and rec.get("review_method") != review_method:
                        continue
                    results.append(rec)
        except OSError as e:
            logger.error("AuditLog query failed: %s", e)
        return results[-limit:]

    def get_entry(self, entry_id: str) -> Optional[dict]:
        """按 entry_id 查找单条记录。"""
        if not self._log_path.exists():
            return None
        try:
            with open(self._log_path, "r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        rec = json.loads(line)
                        if rec.get("entry_id") == entry_id:
                            return rec
                    except json.JSONDecodeError:
                        continue
        except OSError:
            pass
        return None

    # ── 统计 ──

    def stats(self) -> dict:
        """返回审计日志统计摘要。"""
        if not self._log_path.exists():
            return {"total": 0, "by_risk": {}, "by_decision": {}, "by_review_method": {}}
        total = 0
        by_risk: dict[str, int] = {}
        by_decision: dict[str, int] = {}
        by_method: dict[str, int] = {}
        try:
            with open(self._log_path, "r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        rec = json.loads(line)
                    except json.JSONDecodeError:
                        continue
                    total += 1
                    by_risk[rec.get("risk_level", "?")] = by_risk.get(rec.get("risk_level", "?"), 0) + 1
                    by_decision[rec.get("decision", "?")] = by_decision.get(rec.get("decision", "?"), 0) + 1
                    by_method[rec.get("review_method", "?")] = by_method.get(rec.get("review_method", "?"), 0) + 1
        except OSError:
            pass
        return {
            "total": total,
            "by_risk": by_risk,
            "by_decision": by_decision,
            "by_review_method": by_method,
        }
