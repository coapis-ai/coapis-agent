"""SkillEvolutionEngine — 从触发日志和工具日志聚合技能效能指标。

数据流：
  trigger_log.jsonl (TriggerEvent + TriggerOutcome)
  tool_usage.jsonl   (record_tool_call + record_trigger_outcome)
      ↓ 聚合
  SkillMetrics per skill → skill_metrics.json 缓存
      ↓ 暴露
  GET /api/skills/metrics

五维指标：
  precision     = skill_tool_used / total_triggers  (触发词精确度)
  reliability   = tool_success / total_outcomes      (工具执行可靠性)
  effectiveness = precision * reliability            (综合有效率)
  satisfaction  = 1 - user_followed_up_rate          (用户满意度：后续不重复提问)
  robustness    = 1 - error_rate                     (稳健性：错误频率)
"""

from __future__ import annotations

import json
import logging
import os
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

def _get_system_dir() -> Path:
    """Resolve system data directory — prefers COAPIS_WORKING_DIR, falls back to __file__ relative."""
    wd = os.environ.get("COAPIS_WORKING_DIR")
    if wd:
        p = Path(wd) / "system"
        if p.exists():
            return p
    return Path(__file__).resolve().parent.parent.parent.parent / "system"


def _get_trigger_log_path() -> Path:
    env = os.environ.get("COAPIS_TRIGGER_LOG")
    if env:
        return Path(env)
    # TriggerTracker writes to system/skill_evolution/trigger_log.jsonl (P0-1)
    evo_path = _get_system_dir() / "skill_evolution" / "trigger_log.jsonl"
    if evo_path.exists():
        return evo_path
    # Legacy fallback
    legacy = _get_system_dir() / "trigger_log.jsonl"
    if legacy.exists():
        return legacy
    # Default to new path
    return evo_path


def _get_tool_usage_path() -> Path:
    env = os.environ.get("COAPIS_USAGE_LOG")
    if env:
        return Path(env)
    return _get_system_dir() / "tool_usage.jsonl"


def _get_metrics_cache_path() -> Path:
    return _get_system_dir() / "skill_metrics.json"


@dataclass
class UserSkillMetrics:
    """单个用户的技能效能指标。"""

    user_id: str = ""

    precision: float = 0.0
    reliability: float = 0.0
    effectiveness: float = 0.0
    satisfaction: float = 0.0
    robustness: float = 0.0
    composite_score: float = 0.0

    total_triggers: int = 0
    skill_tool_used_count: int = 0
    tool_success_count: int = 0
    tool_error_count: int = 0
    user_followup_count: int = 0

    last_triggered_at: str = ""

    def to_dict(self) -> dict:
        return {
            "user_id": self.user_id,
            "precision": round(self.precision, 4),
            "reliability": round(self.reliability, 4),
            "effectiveness": round(self.effectiveness, 4),
            "satisfaction": round(self.satisfaction, 4),
            "robustness": round(self.robustness, 4),
            "composite_score": round(self.composite_score, 4),
            "total_triggers": self.total_triggers,
            "skill_tool_used_count": self.skill_tool_used_count,
            "tool_success_count": self.tool_success_count,
            "tool_error_count": self.tool_error_count,
            "user_followup_count": self.user_followup_count,
            "last_triggered_at": self.last_triggered_at,
        }


@dataclass
class SkillMetrics:
    """五维效能指标，一个技能一份。包含全局聚合和 per-user 维度。"""

    skill_name: str = ""

    # ── 五维指标（全局） ──
    precision: float = 0.0       # 触发精确度：触发后 LLM 实际使用了该技能工具
    reliability: float = 0.0     # 工具可靠性：工具执行成功率
    effectiveness: float = 0.0   # 综合有效率：precision × reliability
    satisfaction: float = 0.0    # 用户满意度：1 - 用户后续重复提问率
    robustness: float = 0.0      # 稳健性：1 - 错误率

    # ── 综合分 ──
    composite_score: float = 0.0  # 加权平均

    # ── 原始计数 ──
    total_triggers: int = 0
    skill_tool_used_count: int = 0
    tool_success_count: int = 0
    tool_error_count: int = 0
    user_followup_count: int = 0

    # ── 元信息 ──
    last_triggered_at: str = ""
    last_computed_at: str = ""
    top_keywords: list[str] = field(default_factory=list)

    # ── 用户维度 ──
    users: dict[str, UserSkillMetrics] = field(default_factory=dict)
    unique_user_count: int = 0

    def to_dict(self) -> dict:
        result = {
            "skill_name": self.skill_name,
            "precision": round(self.precision, 4),
            "reliability": round(self.reliability, 4),
            "effectiveness": round(self.effectiveness, 4),
            "satisfaction": round(self.satisfaction, 4),
            "robustness": round(self.robustness, 4),
            "composite_score": round(self.composite_score, 4),
            "total_triggers": self.total_triggers,
            "skill_tool_used_count": self.skill_tool_used_count,
            "tool_success_count": self.tool_success_count,
            "tool_error_count": self.tool_error_count,
            "user_followup_count": self.user_followup_count,
            "last_triggered_at": self.last_triggered_at,
            "last_computed_at": self.last_computed_at,
            "top_keywords": self.top_keywords[:10],
            "unique_user_count": self.unique_user_count,
        }
        # 用户维度指标（按 composite_score 降序）
        if self.users:
            user_list = sorted(
                self.users.values(),
                key=lambda u: u.composite_score,
                reverse=True,
            )
            result["users"] = [u.to_dict() for u in user_list[:50]]
        return result


class SkillEvolutionEngine:
    """效能评估引擎：聚合触发日志 → 五维指标 → 缓存 + API。"""

    # 综合分权重
    WEIGHTS = {
        "precision": 0.25,
        "reliability": 0.25,
        "effectiveness": 0.20,
        "satisfaction": 0.15,
        "robustness": 0.15,
    }

    # 时间衰减参数：lambda 越大衰减越快；90 天权重降至 ~0.1
    DECAY_LAMBDA: float = 0.025

    def __init__(self) -> None:
        self._metrics_cache: dict[str, SkillMetrics] = {}
        self._cache_ts: float = 0
        self._cache_ttl: float = 300  # 5 min
        self._lock = __import__("threading").Lock()

    @staticmethod
    def _time_decay_weight(timestamp: float, now: float) -> float:
        """计算时间衰减权重: w = e^(-λ × days)。

        Args:
            timestamp: 事件的 Unix 时间戳
            now: 当前时间戳

        Returns:
            0.0 ~ 1.0 的权重，越近期越高
        """
        if timestamp <= 0:
            return 0.0
        days = max(0.0, (now - timestamp) / 86400)
        import math
        return math.exp(-SkillEvolutionEngine.DECAY_LAMBDA * days)

    # ── Public API ──

    def get_all_metrics(
        self,
        force_refresh: bool = False,
        sort_by: str = "composite_score",
        limit: int = 100,
    ) -> list[dict]:
        """返回所有技能的效能指标，按 sort_by 降序排列。"""
        metrics = self._aggregate(force_refresh=force_refresh)
        result = [m.to_dict() for m in metrics.values()]
        result.sort(key=lambda x: x.get(sort_by, 0), reverse=True)
        return result[:limit]

    def get_skill_metric(self, skill_name: str) -> dict | None:
        """返回单个技能的效能指标。"""
        metrics = self._aggregate()
        m = metrics.get(skill_name)
        return m.to_dict() if m else None

    def get_funnel_data(self) -> dict:
        """返回触发漏斗数据：触发 → 使用 → 成功 → 满意。"""
        metrics = self._aggregate()
        total_triggers = sum(m.total_triggers for m in metrics.values())
        total_used = sum(m.skill_tool_used_count for m in metrics.values())
        total_success = sum(m.tool_success_count for m in metrics.values())
        total_no_followup = sum(
            m.total_triggers - m.user_followup_count for m in metrics.values()
        )
        return {
            "funnel": [
                {"stage": "触发", "count": total_triggers},
                {"stage": "使用技能工具", "count": total_used},
                {"stage": "工具执行成功", "count": total_success},
                {"stage": "用户满意（无重复提问）", "count": max(0, total_no_followup)},
            ],
            "rates": {
                "trigger_to_use": round(total_used / max(total_triggers, 1), 4),
                "use_to_success": round(total_success / max(total_used, 1), 4),
                "overall_satisfaction": round(
                    max(0, total_no_followup) / max(total_triggers, 1), 4
                ),
            },
        }

    def refresh(self) -> dict:
        """强制刷新并返回聚合统计摘要。"""
        metrics = self._aggregate(force_refresh=True)
        return {
            "skills_count": len(metrics),
            "total_triggers": sum(m.total_triggers for m in metrics.values()),
            "computed_at": datetime.now(timezone.utc).isoformat(),
        }

    # ── Self-Evolution: Trigger Word Optimization ──

    def _get_suggestions_dir(self) -> Path:
        """获取建议草稿存储目录。"""
        d = _get_system_dir() / "skill_evolution" / "suggestions"
        d.mkdir(parents=True, exist_ok=True)
        return d

    def analyze_trigger_issues(self, skill_name: str) -> dict:
        """分析技能的触发词问题：误触发 + 漏触发。

        Returns:
            {
                "skill_name": str,
                "precision": float,
                "total_triggers": int,
                "false_positive_keywords": [{"keyword": str, "count": int, "reason": str}],
                "false_negative_hints": [{"keyword": str, "source": str}],
                "recommendation": str,
            }
        """
        metrics = self._aggregate()
        m = metrics.get(skill_name)
        if not m:
            return {"skill_name": skill_name, "error": "no metrics found"}

        result = {
            "skill_name": skill_name,
            "precision": m.precision,
            "total_triggers": m.total_triggers,
            "false_positive_keywords": [],
            "false_negative_hints": [],
            "recommendation": "",
        }

        # ── 误触发分析（precision < 0.5）──
        if m.precision < 0.5 and m.total_triggers >= 3:
            # 从触发日志中找 false_positive 信号
            fp_signals = self._get_effectiveness_signals(skill_name, "false_positive")
            for sig in fp_signals:
                kw = sig.get("trigger_keyword", "")
                if kw and kw not in [k["keyword"] for k in result["false_positive_keywords"]]:
                    result["false_positive_keywords"].append({
                        "keyword": kw,
                        "count": sum(1 for s in fp_signals if s.get("trigger_keyword") == kw),
                        "reason": sig.get("context", "")[:100],
                    })

            # 从 top_keywords 中找高频但不精确的词
            trigger_log = self._read_trigger_log()
            for entry in trigger_log:
                ev = entry.get("event", entry.get("type", ""))
                if ev in ("trigger_event", "skill_trigger") and entry.get("skill_name") == skill_name:
                    for kw in entry.get("matched_keywords", []):
                        # 检查该关键词对应的 outcome 是否为 false
                        related_outcomes = [
                            o for o in self._read_trigger_log()
                            if o.get("event") == "trigger_outcome"
                            and o.get("trigger_id") == entry.get("trigger_id")
                        ]
                        if related_outcomes and not related_outcomes[0].get("skill_tool_used", False):
                            existing = [k for k in result["false_positive_keywords"] if k["keyword"] == kw]
                            if not existing:
                                result["false_positive_keywords"].append({
                                    "keyword": kw, "count": 1,
                                    "reason": "triggered but skill tool not used",
                                })
                            else:
                                existing[0]["count"] += 1

        # ── 漏触发分析 ──
        fp_signals = self._get_effectiveness_signals(skill_name, "false_negative")
        for sig in fp_signals:
            kw = sig.get("trigger_keyword", "")
            if kw:
                result["false_negative_hints"].append({
                    "keyword": kw,
                    "source": sig.get("context", "")[:100],
                })

        # ── 生成建议 ──
        if result["false_positive_keywords"]:
            result["recommendation"] += f"建议移除 {len(result['false_positive_keywords'])} 个误触发关键词。"
        if result["false_negative_hints"]:
            result["recommendation"] += f"建议添加 {len(result['false_negative_hints'])} 个漏触发关键词。"
        if not result["recommendation"]:
            result["recommendation"] = "当前触发词表现良好，无需优化。"

        return result

    def _get_effectiveness_signals(self, skill_name: str, signal_type: str = None) -> list[dict]:
        """从 effectiveness_signals.jsonl 读取信号。"""
        sig_path = _get_system_dir() / "skill_evolution" / "effectiveness_signals.jsonl"
        if not sig_path.exists():
            return []
        signals = []
        try:
            with open(sig_path, "r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        entry = json.loads(line)
                        if entry.get("skill_name") != skill_name:
                            continue
                        if signal_type and entry.get("signal_type") != signal_type:
                            continue
                        signals.append(entry)
                    except json.JSONDecodeError:
                        continue
        except Exception:
            pass
        return signals

    def _read_trigger_log(self) -> list[dict]:
        """读取触发日志全部条目。"""
        path = _get_trigger_log_path()
        if not path.exists():
            return []
        entries = []
        try:
            with open(path, "r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        entries.append(json.loads(line))
                    except json.JSONDecodeError:
                        continue
        except Exception:
            pass
        return entries

    def analyze_content_issues(self, skill_name: str) -> dict:
        """分析技能内容问题：执行失败原因。

        Returns:
            {
                "skill_name": str,
                "reliability": float,
                "tool_error_count": int,
                "common_errors": [{"error": str, "count": int}],
                "recommendation": str,
            }
        """
        metrics = self._aggregate()
        m = metrics.get(skill_name)
        if not m:
            return {"skill_name": skill_name, "error": "no metrics found"}

        result = {
            "skill_name": skill_name,
            "reliability": m.reliability,
            "tool_error_count": m.tool_error_count,
            "total_triggers": m.total_triggers,
            "common_errors": [],
            "recommendation": "",
        }

        if m.reliability < 0.8 and m.tool_error_count >= 2:
            # 从触发日志中提取错误信息
            trigger_log = self._read_trigger_log()
            error_msgs: dict[str, int] = {}
            for entry in trigger_log:
                ev = entry.get("event", entry.get("type", ""))
                if ev == "trigger_outcome" and entry.get("skill_name") == skill_name:
                    if not entry.get("tool_success", False):
                        err = entry.get("error_message", entry.get("error", "unknown error"))
                        err_short = str(err)[:150]
                        error_msgs[err_short] = error_msgs.get(err_short, 0) + 1

            result["common_errors"] = [
                {"error": err, "count": cnt}
                for err, cnt in sorted(error_msgs.items(), key=lambda x: x[1], reverse=True)[:5]
            ]

        # 生成建议
        if result["common_errors"]:
            result["recommendation"] = f"发现 {len(result['common_errors'])} 种常见错误，建议优化 SKILL.md 中的使用说明。"
        elif m.reliability < 0.5:
            result["recommendation"] = "可靠性较低，建议检查工具配置和 SKILL.md 描述。"
        else:
            result["recommendation"] = "技能内容表现良好，无需改进。"

        return result

    def generate_trigger_suggestion(
        self,
        skill_name: str,
        removes: list[str] = None,
        adds: list[str] = None,
    ) -> dict:
        """生成触发词优化建议草稿，保存到 suggestions/ 待审批。

        Args:
            skill_name: 技能名
            removes: 建议移除的关键词列表
            adds: 建议添加的关键词列表

        Returns:
            草稿信息 {id, skill_name, type, removes, adds, status, created_at}
        """
        removes = removes or []
        adds = adds or []

        if not removes and not adds:
            # 自动从分析结果生成
            analysis = self.analyze_trigger_issues(skill_name)
            removes = [k["keyword"] for k in analysis.get("false_positive_keywords", [])]
            adds = [k["keyword"] for k in analysis.get("false_negative_hints", [])]

        suggestion = {
            "id": f"trig_{skill_name}_{int(time.time())}",
            "skill_name": skill_name,
            "type": "trigger_optimization",
            "removes": removes,
            "adds": adds,
            "status": "pending",
            "created_at": datetime.now(timezone.utc).isoformat(),
            "reason": f"自动分析：precision={self._get_skill_precision(skill_name):.2f}",
        }

        # 保存到 suggestions/
        sug_dir = self._get_suggestions_dir()
        sug_file = sug_dir / f"{suggestion['id']}.json"
        with open(sug_file, "w", encoding="utf-8") as f:
            json.dump(suggestion, f, ensure_ascii=False, indent=2)

        logger.info("Generated trigger suggestion: %s", suggestion["id"])
        return suggestion

    def generate_content_suggestion(
        self,
        skill_name: str,
        improvements: list[str] = None,
    ) -> dict:
        """生成内容改进建议草稿，保存到 suggestions/ 待审批。

        Args:
            skill_name: 技能名
            improvements: 改进建议列表

        Returns:
            草稿信息
        """
        if not improvements:
            analysis = self.analyze_content_issues(skill_name)
            improvements = []
            for err in analysis.get("common_errors", [])[:3]:
                improvements.append(f"修复常见错误: {err['error'][:80]}")
            if analysis.get("recommendation"):
                improvements.append(analysis["recommendation"])

        suggestion = {
            "id": f"cont_{skill_name}_{int(time.time())}",
            "skill_name": skill_name,
            "type": "content_improvement",
            "improvements": improvements,
            "status": "pending",
            "created_at": datetime.now(timezone.utc).isoformat(),
            "reason": f"自动分析：reliability={self._get_skill_reliability(skill_name):.2f}",
        }

        sug_dir = self._get_suggestions_dir()
        sug_file = sug_dir / f"{suggestion['id']}.json"
        with open(sug_file, "w", encoding="utf-8") as f:
            json.dump(suggestion, f, ensure_ascii=False, indent=2)

        logger.info("Generated content suggestion: %s", suggestion["id"])
        return suggestion

    def list_suggestions(
        self,
        skill_name: str = None,
        status: str = None,
    ) -> list[dict]:
        """列出建议草稿。"""
        sug_dir = self._get_suggestions_dir()
        suggestions = []
        for f in sorted(sug_dir.glob("*.json")):
            try:
                with open(f, "r", encoding="utf-8") as fh:
                    sug = json.load(fh)
                if skill_name and sug.get("skill_name") != skill_name:
                    continue
                if status and sug.get("status") != status:
                    continue
                suggestions.append(sug)
            except Exception:
                continue
        return suggestions

    def approve_suggestion(self, suggestion_id: str) -> dict | None:
        """审批通过建议（标记为 approved）。"""
        return self._update_suggestion_status(suggestion_id, "approved")

    def reject_suggestion(self, suggestion_id: str) -> dict | None:
        """拒绝建议（标记为 rejected）。"""
        return self._update_suggestion_status(suggestion_id, "rejected")

    def _update_suggestion_status(self, suggestion_id: str, new_status: str) -> dict | None:
        """更新建议状态。"""
        sug_dir = self._get_suggestions_dir()
        sug_file = sug_dir / f"{suggestion_id}.json"
        if not sug_file.exists():
            return None
        try:
            with open(sug_file, "r", encoding="utf-8") as f:
                sug = json.load(f)
            sug["status"] = new_status
            sug["updated_at"] = datetime.now(timezone.utc).isoformat()
            with open(sug_file, "w", encoding="utf-8") as f:
                json.dump(sug, f, ensure_ascii=False, indent=2)
            return sug
        except Exception:
            return None

    def _get_skill_precision(self, skill_name: str) -> float:
        metrics = self._aggregate()
        m = metrics.get(skill_name)
        return m.precision if m else 0.0

    def _get_skill_reliability(self, skill_name: str) -> float:
        metrics = self._aggregate()
        m = metrics.get(skill_name)
        return m.reliability if m else 0.0

    # ── Promotion / Retirement Detection ──

    def _get_candidates_path(self) -> Path:
        return _get_system_dir() / "skill_evolution" / "promotion_candidates.json"

    def detect_promotion_candidates(self) -> list[dict]:
        """扫描触发日志，识别满足晋升条件的技能。

        晋升条件（全部满足）：
        1. ≥3 个不同用户使用过
        2. 综合效能分 ≥ 0.7
        3. 存在 ≥ 30 天（首次触发距今）
        """
        metrics = self._aggregate(force_refresh=True)
        trigger_log = self._read_trigger_log()

        # 按技能名统计用户和首次触发时间
        skill_users: dict[str, set] = {}
        skill_first_ts: dict[str, float] = {}
        for entry in trigger_log:
            ev = entry.get("event", entry.get("type", ""))
            if ev not in ("trigger_event", "skill_trigger", "trigger_outcome"):
                continue
            name = entry.get("skill_name", entry.get("skill", "unknown"))
            user = entry.get("user_id", entry.get("user", ""))
            ts = entry.get("timestamp", 0)
            if user:
                skill_users.setdefault(name, set()).add(user)
            if ts and (name not in skill_first_ts or ts < skill_first_ts[name]):
                skill_first_ts[name] = ts

        now = time.time()
        candidates = []
        for name, m in metrics.items():
            users = skill_users.get(name, set())
            first_ts = skill_first_ts.get(name, now)
            age_days = (now - first_ts) / 86400 if first_ts else 0
            user_count = len(users)

            if user_count >= 3 and m.composite_score >= 0.7 and age_days >= 30:
                candidates.append({
                    "skill_name": name,
                    "composite_score": round(m.composite_score, 4),
                    "user_count": user_count,
                    "users": sorted(users)[:20],
                    "age_days": round(age_days, 1),
                    "total_triggers": m.total_triggers,
                    "detected_at": datetime.now(timezone.utc).isoformat(),
                    "status": "pending",  # pending / approved / rejected
                })

        # 按 composite_score 降序
        candidates.sort(key=lambda x: x["composite_score"], reverse=True)

        # 持久化
        path = self._get_candidates_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        try:
            with open(path, "w", encoding="utf-8") as f:
                json.dump({"candidates": candidates, "updated_at": datetime.now(timezone.utc).isoformat()},
                          f, ensure_ascii=False, indent=2)
        except Exception as exc:
            logger.warning("Failed to save promotion_candidates.json: %s", exc)

        logger.info("Detected %d promotion candidates", len(candidates))
        return candidates

    def detect_retirement_candidates(self) -> list[dict]:
        """扫描触发日志，识别满足退役条件的技能。

        退役条件（任一满足）：
        1. 90 天零触发
        2. 连续 5 次工具执行失败
        """
        metrics = self._aggregate(force_refresh=True)
        trigger_log = self._read_trigger_log()

        # 按技能名统计最后触发时间和连续失败次数
        skill_last_ts: dict[str, float] = {}
        skill_consecutive_fail: dict[str, int] = {}
        # 按时间排序后扫描
        sorted_log = sorted(trigger_log, key=lambda e: e.get("timestamp", 0))
        for entry in sorted_log:
            ev = entry.get("event", entry.get("type", ""))
            name = entry.get("skill_name", entry.get("skill", "unknown"))
            ts = entry.get("timestamp", 0)

            if ev in ("trigger_event", "skill_trigger"):
                if ts:
                    skill_last_ts[name] = ts
            elif ev == "trigger_outcome":
                if ts:
                    skill_last_ts[name] = ts
                success = entry.get("tool_success", entry.get("success", True))
                if not success:
                    skill_consecutive_fail[name] = skill_consecutive_fail.get(name, 0) + 1
                else:
                    skill_consecutive_fail[name] = 0  # 重置连续失败计数

        now = time.time()
        candidates = []
        for name, m in metrics.items():
            last_ts = skill_last_ts.get(name, 0)
            days_since = (now - last_ts) / 86400 if last_ts else 999
            consec_fail = skill_consecutive_fail.get(name, 0)

            reasons = []
            if days_since >= 90:
                reasons.append(f"零触发 {round(days_since)} 天")
            if consec_fail >= 5:
                reasons.append(f"连续 {consec_fail} 次执行失败")

            if reasons:
                candidates.append({
                    "skill_name": name,
                    "composite_score": round(m.composite_score, 4),
                    "total_triggers": m.total_triggers,
                    "days_since_last_trigger": round(days_since, 1),
                    "consecutive_failures": consec_fail,
                    "reasons": reasons,
                    "detected_at": datetime.now(timezone.utc).isoformat(),
                    "status": "pending",  # pending / approved / rejected / restored
                })

        candidates.sort(key=lambda x: x["days_since_last_trigger"], reverse=True)
        logger.info("Detected %d retirement candidates", len(candidates))
        return candidates

    def approve_promotion(self, skill_name: str) -> dict | None:
        """审批通过晋升候选。"""
        path = self._get_candidates_path()
        if not path.exists():
            return None
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        for c in data.get("candidates", []):
            if c["skill_name"] == skill_name and c["status"] == "pending":
                c["status"] = "approved"
                c["approved_at"] = datetime.now(timezone.utc).isoformat()
                with open(path, "w", encoding="utf-8") as f:
                    json.dump(data, f, ensure_ascii=False, indent=2)
                return c
        return None

    def reject_promotion(self, skill_name: str) -> dict | None:
        """拒绝晋升候选。"""
        path = self._get_candidates_path()
        if not path.exists():
            return None
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        for c in data.get("candidates", []):
            if c["skill_name"] == skill_name and c["status"] == "pending":
                c["status"] = "rejected"
                c["rejected_at"] = datetime.now(timezone.utc).isoformat()
                with open(path, "w", encoding="utf-8") as f:
                    json.dump(data, f, ensure_ascii=False, indent=2)
                return c
        return None

    # ── Internal ──

    def _aggregate(self, force_refresh: bool = False) -> dict[str, SkillMetrics]:
        """从 JSONL 日志聚合所有技能的效能指标。带 5 分钟缓存。"""
        now = time.time()
        with self._lock:
            if (
                not force_refresh
                and self._metrics_cache
                and (now - self._cache_ts) < self._cache_ttl
            ):
                return self._metrics_cache

        # ── 读取触发日志 ──
        trigger_path = _get_trigger_log_path()
        events: list[dict] = []      # trigger events
        outcomes: list[dict] = []    # trigger outcomes
        if trigger_path.exists():
            try:
                with open(trigger_path, "r", encoding="utf-8") as f:
                    for line in f:
                        line = line.strip()
                        if not line:
                            continue
                        try:
                            entry = json.loads(line)
                        except json.JSONDecodeError:
                            continue
                        ev = entry.get("event", entry.get("type", ""))
                        if ev in ("trigger_event", "skill_trigger"):
                            events.append(entry)
                        elif ev == "trigger_outcome":
                            outcomes.append(entry)
            except Exception as exc:
                logger.warning("Failed to read trigger log: %s", exc)

        # ── 读取工具使用日志 ──
        usage_path = _get_tool_usage_path()
        usage_outcomes: list[dict] = []
        if usage_path.exists():
            try:
                with open(usage_path, "r", encoding="utf-8") as f:
                    for line in f:
                        line = line.strip()
                        if not line:
                            continue
                        try:
                            entry = json.loads(line)
                        except json.JSONDecodeError:
                            continue
                        if entry.get("event") == "trigger_outcome":
                            usage_outcomes.append(entry)
            except Exception as exc:
                logger.warning("Failed to read tool usage log: %s", exc)

        # 合并两个来源的 trigger_outcome（去重 by trigger_id）
        seen_ids = {o["trigger_id"] for o in outcomes if "trigger_id" in o}
        for uo in usage_outcomes:
            tid = uo.get("trigger_id", "")
            if tid and tid not in seen_ids:
                outcomes.append(uo)
                seen_ids.add(tid)

        # ── 按技能聚合 ──
        skill_data: dict[str, dict] = {}

        def _ensure(name: str) -> dict:
            if name not in skill_data:
                skill_data[name] = {
                    "triggers": [],
                    "outcomes": [],
                    "keywords": {},
                    "last_ts": 0,
                }
            return skill_data[name]

        for ev in events:
            name = ev.get("skill_name", ev.get("skill", "unknown"))
            sd = _ensure(name)
            sd["triggers"].append(ev)
            ts = ev.get("timestamp", 0)
            if ts > sd["last_ts"]:
                sd["last_ts"] = ts
            # 统计关键词频率
            for kw in ev.get("matched_keywords", []):
                sd["keywords"][kw] = sd["keywords"].get(kw, 0) + 1

        for oc in outcomes:
            name = oc.get("skill_name", oc.get("skill", "unknown"))
            sd = _ensure(name)
            sd["outcomes"].append(oc)

        # ── 计算五维指标 ──
        metrics: dict[str, SkillMetrics] = {}
        now_iso = datetime.now(timezone.utc).isoformat()

        for name, sd in skill_data.items():
            m = SkillMetrics(skill_name=name)
            m.total_triggers = len(sd["triggers"])
            m.last_computed_at = now_iso

            if sd["last_ts"] > 0:
                m.last_triggered_at = datetime.fromtimestamp(
                    sd["last_ts"], tz=timezone.utc
                ).isoformat()

            # 从关键词频率排序取 top 10
            sorted_kw = sorted(
                sd["keywords"].items(), key=lambda x: x[1], reverse=True
            )
            m.top_keywords = [k for k, _ in sorted_kw[:10]]

            outcomes_list = sd["outcomes"]
            n_outcomes = len(outcomes_list)

            if n_outcomes > 0:
                # ── 时间衰减加权统计 ──
                now_ts = time.time()
                decayed_used = 0.0
                decayed_success = 0.0
                decayed_followup = 0.0
                decayed_total = 0.0

                for o in outcomes_list:
                    o_ts = o.get("timestamp", now_ts)
                    w = self._time_decay_weight(o_ts, now_ts)
                    decayed_total += w
                    if o.get("skill_tool_used", False):
                        decayed_used += w
                    if o.get("tool_success", False):
                        decayed_success += w
                    if o.get("user_followed_up", False):
                        decayed_followup += w

                # 精确计数（用于 total_triggers 等原始统计）
                m.skill_tool_used_count = sum(
                    1 for o in outcomes_list if o.get("skill_tool_used", False)
                )
                m.tool_success_count = sum(
                    1 for o in outcomes_list if o.get("tool_success", False)
                )
                m.tool_error_count = n_outcomes - m.tool_success_count
                m.user_followup_count = sum(
                    1 for o in outcomes_list if o.get("user_followed_up", False)
                )

                # 衰减加权的五维指标（近期数据权重更高）
                if decayed_total > 0:
                    m.precision = decayed_used / decayed_total
                    m.reliability = decayed_success / decayed_total
                    m.satisfaction = 1 - (decayed_followup / decayed_total)
                    m.robustness = 1 - ((decayed_total - decayed_success) / decayed_total)
                else:
                    m.precision = m.skill_tool_used_count / n_outcomes
                    m.reliability = m.tool_success_count / n_outcomes
                    m.satisfaction = 1 - (m.user_followup_count / n_outcomes)
                    m.robustness = 1 - (m.tool_error_count / n_outcomes)

            # effectiveness = precision × reliability
            m.effectiveness = m.precision * m.reliability

            # composite_score = 加权平均
            m.composite_score = (
                self.WEIGHTS["precision"] * m.precision
                + self.WEIGHTS["reliability"] * m.reliability
                + self.WEIGHTS["effectiveness"] * m.effectiveness
                + self.WEIGHTS["satisfaction"] * m.satisfaction
                + self.WEIGHTS["robustness"] * m.robustness
            )

            # ── 按用户分组计算 per-user 指标 ──
            user_outcomes: dict[str, list[dict]] = {}
            for o in outcomes_list:
                uid = o.get("user", o.get("user_id", "unknown"))
                user_outcomes.setdefault(uid, []).append(o)

            m.unique_user_count = len(user_outcomes)
            for uid, u_outcomes in user_outcomes.items():
                if uid == "unknown" and len(user_outcomes) == 1:
                    # 只有一个 unknown 用户时跳过 per-user（无区分价值）
                    continue
                n_uo = len(u_outcomes)
                if n_uo == 0:
                    continue

                um = UserSkillMetrics(user_id=uid)
                um.total_triggers = n_uo

                um.skill_tool_used_count = sum(
                    1 for o in u_outcomes if o.get("skill_tool_used", False)
                )
                um.precision = um.skill_tool_used_count / n_uo if n_uo else 0.0

                um.tool_success_count = sum(
                    1 for o in u_outcomes if o.get("tool_success", False)
                )
                um.tool_error_count = n_uo - um.tool_success_count
                um.reliability = um.tool_success_count / n_uo if n_uo else 0.0

                um.user_followup_count = sum(
                    1 for o in u_outcomes if o.get("user_followed_up", False)
                )
                um.satisfaction = 1 - (um.user_followup_count / n_uo) if n_uo else 0.0

                um.robustness = 1 - (um.tool_error_count / n_uo) if n_uo else 0.0

                um.effectiveness = um.precision * um.reliability

                um.composite_score = (
                    self.WEIGHTS["precision"] * um.precision
                    + self.WEIGHTS["reliability"] * um.reliability
                    + self.WEIGHTS["effectiveness"] * um.effectiveness
                    + self.WEIGHTS["satisfaction"] * um.satisfaction
                    + self.WEIGHTS["robustness"] * um.robustness
                )

                # 取该用户最后一次触发时间
                last_ts = max(
                    (o.get("timestamp", 0) for o in u_outcomes), default=0
                )
                if last_ts > 0:
                    um.last_triggered_at = datetime.fromtimestamp(
                        last_ts, tz=timezone.utc
                    ).isoformat()

                m.users[uid] = um

            metrics[name] = m

        # ── 更新缓存 ──
        with self._lock:
            self._metrics_cache = metrics
            self._cache_ts = now

        # ── 持久化到 skill_metrics.json ──
        self._save_cache(metrics)

        logger.info(
            "SkillEvolutionEngine: aggregated %d skills from %d events, %d outcomes",
            len(metrics), len(events), len(outcomes),
        )
        return metrics

    def _save_cache(self, metrics: dict[str, SkillMetrics]) -> None:
        """将聚合结果持久化到 skill_metrics.json。"""
        try:
            path = _get_metrics_cache_path()
            path.parent.mkdir(parents=True, exist_ok=True)
            data = {
                "version": 1,
                "computed_at": datetime.now(timezone.utc).isoformat(),
                "skills_count": len(metrics),
                "weights": self.WEIGHTS,
                "metrics": {name: m.to_dict() for name, m in metrics.items()},
            }
            with open(path, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
        except Exception as exc:
            logger.warning("Failed to save skill_metrics.json: %s", exc)

    def load_cached(self) -> dict[str, SkillMetrics]:
        """从 skill_metrics.json 加载缓存（冷启动用）。"""
        path = _get_metrics_cache_path()
        if not path.exists():
            return {}
        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
            metrics = {}
            for name, d in data.get("metrics", {}).items():
                m = SkillMetrics(
                    skill_name=d.get("skill_name", name),
                    precision=d.get("precision", 0),
                    reliability=d.get("reliability", 0),
                    effectiveness=d.get("effectiveness", 0),
                    satisfaction=d.get("satisfaction", 0),
                    robustness=d.get("robustness", 0),
                    composite_score=d.get("composite_score", 0),
                    total_triggers=d.get("total_triggers", 0),
                    skill_tool_used_count=d.get("skill_tool_used_count", 0),
                    tool_success_count=d.get("tool_success_count", 0),
                    tool_error_count=d.get("tool_error_count", 0),
                    user_followup_count=d.get("user_followup_count", 0),
                    last_triggered_at=d.get("last_triggered_at", ""),
                    last_computed_at=d.get("last_computed_at", ""),
                    top_keywords=d.get("top_keywords", []),
                    unique_user_count=d.get("unique_user_count", 0),
                )
                # 恢复 per-user 指标
                for ud in d.get("users", []):
                    uid = ud.get("user_id", "")
                    if uid:
                        m.users[uid] = UserSkillMetrics(
                            user_id=uid,
                            precision=ud.get("precision", 0),
                            reliability=ud.get("reliability", 0),
                            effectiveness=ud.get("effectiveness", 0),
                            satisfaction=ud.get("satisfaction", 0),
                            robustness=ud.get("robustness", 0),
                            composite_score=ud.get("composite_score", 0),
                            total_triggers=ud.get("total_triggers", 0),
                            skill_tool_used_count=ud.get("skill_tool_used_count", 0),
                            tool_success_count=ud.get("tool_success_count", 0),
                            tool_error_count=ud.get("tool_error_count", 0),
                            user_followup_count=ud.get("user_followup_count", 0),
                            last_triggered_at=ud.get("last_triggered_at", ""),
                        )
                metrics[name] = m
            with self._lock:
                self._metrics_cache = metrics
                self._cache_ts = time.time()
            logger.info(
                "SkillEvolutionEngine: loaded %d skills from cache", len(metrics)
            )
            return metrics
        except Exception as exc:
            logger.warning("Failed to load skill_metrics.json cache: %s", exc)
            return {}

    def get_user_skill_metric(self, skill_name: str, user_id: str) -> dict | None:
        """返回指定用户在指定技能上的效能指标。"""
        metrics = self._aggregate()
        m = metrics.get(skill_name)
        if not m or user_id not in m.users:
            return None
        return m.users[user_id].to_dict()

    def get_user_overview(self, user_id: str) -> list[dict]:
        """返回指定用户在所有技能上的效能指标概览。"""
        metrics = self._aggregate()
        result = []
        for name, m in metrics.items():
            if user_id in m.users:
                um = m.users[user_id]
                result.append({
                    "skill_name": name,
                    **um.to_dict(),
                })
        result.sort(key=lambda x: x.get("composite_score", 0), reverse=True)
        return result


# ── Singleton ──
_engine_instance: SkillEvolutionEngine | None = None


def get_evolution_engine() -> SkillEvolutionEngine:
    """获取单例效能评估引擎。冷启动时自动加载缓存。"""
    global _engine_instance
    if _engine_instance is None:
        _engine_instance = SkillEvolutionEngine()
        _engine_instance.load_cached()
    return _engine_instance
