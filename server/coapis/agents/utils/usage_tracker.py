"""Tool & Skill usage tracker — writes structured JSONL logs.

Each line: {"ts", "event", "user", "agent", ...}
Events: "tool_call", "skill_trigger"
"""

import json
import hashlib
import time
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

# Lazy logger to avoid circular imports
import logging

logger = logging.getLogger(__name__)

# Default log directory — override via COAPIS_USAGE_LOG env var
def _get_system_dir() -> Path:
    """Resolve system data dir — prefers COAPIS_WORKING_DIR, falls back to __file__ relative."""
    wd = os.environ.get("COAPIS_WORKING_DIR")
    if wd:
        p = Path(wd) / "system"
        if p.exists():
            return p
    return Path(__file__).resolve().parent.parent.parent.parent / "system"


def _get_log_path() -> Path:
    """Return the JSONL log file path, creating parent dir if needed."""
    env = os.environ.get("COAPIS_USAGE_LOG")
    if env:
        p = Path(env)
    else:
        p = _get_system_dir() / "tool_usage.jsonl"
    p.parent.mkdir(parents=True, exist_ok=True)
    return p


def _hash_params(params: dict[str, Any]) -> str:
    """Short hash of tool call parameters for grouping."""
    if not params:
        return "none"
    raw = json.dumps(params, sort_keys=True, default=str)[:512]
    return hashlib.md5(raw.encode()).hexdigest()[:12]


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def record_tool_call(
    *,
    tool_name: str,
    params: dict[str, Any] | None = None,
    duration_ms: float = 0,
    success: bool = True,
    error: str | None = None,
    user: str = "unknown",
    agent: str = "default",
    output_len: int = 0,
) -> None:
    """Append one tool-call record to the JSONL log."""
    entry = {
        "ts": _now_iso(),
        "event": "tool_call",
        "tool": tool_name,
        "params_hash": _hash_params(params or {}),
        "duration_ms": round(duration_ms, 1),
        "success": success,
        "user": user,
        "agent": agent,
        "output_len": output_len,
    }
    if error:
        entry["error"] = error[:500]
    _append(entry)


def record_skill_trigger(
    *,
    skill_name: str,
    matched_keywords: list[str],
    user: str = "unknown",
    agent: str = "default",
    strategy: str = "",
    score: int = 0,
    candidates: int = 0,
    origin: str = "",
    injected_bytes: int = 0,
) -> None:
    """Append one skill-trigger record to the JSONL log.

    v19 P2-2：技能岗台账原先只有"装了哪个技能 + 命中词"，回答不了
    "凭什么装的"——关键词 Tier1、Tier3 语义命中、判官 LLM、还是用户点名，
    在账上长得一模一样，于是"真判率 42%"这种数字根本没法复核。
    新增四个可复现字段（都可选，老调用点零改动）：
      strategy  命中策略：keyword / tier3 / llm / user_picked / forced
      score     命中得分（规则层打分，判官层为 0）
      candidates 本轮候选技能数（量"在多大范围里选的"）
      origin    来源单列：user_picked 表示**用户点名**，不算判断命中
      injected_bytes 场景核心注入体积（P1-3 字节闸的可观测口径）
    """
    entry = {
        "ts": _now_iso(),
        "event": "skill_trigger",
        "skill": skill_name,
        "keywords": matched_keywords[:10],
        "user": user,
        "agent": agent,
    }
    if strategy:
        entry["strategy"] = strategy
    if score:
        entry["score"] = int(score)
    if candidates:
        entry["candidates"] = int(candidates)
    if origin:
        entry["origin"] = origin
    if injected_bytes:
        entry["injected_bytes"] = int(injected_bytes)
    _append(entry)


def record_trigger_outcome(
    *,
    trigger_id: str,
    skill_name: str,
    tools_used: list[str],
    skill_tool_used: bool = False,
    tool_success: bool = True,
    duration_ms: float = 0,
    user: str = "unknown",
    agent: str = "default",
) -> None:
    """Append one trigger-outcome record to the JSONL log.

    Links a skill trigger event to its execution result via trigger_id.
    """
    entry = {
        "ts": _now_iso(),
        "event": "trigger_outcome",
        "trigger_id": trigger_id,
        "skill": skill_name,
        "tools_used": tools_used[:20],
        "skill_tool_used": skill_tool_used,
        "tool_success": tool_success,
        "duration_ms": round(duration_ms, 1),
        "user": user,
        "agent": agent,
    }
    _append(entry)


def _append(entry: dict) -> None:
    """Write a single JSON line to the log file."""
    try:
        path = _get_log_path()
        with open(path, "a", encoding="utf-8") as f:
            f.write(json.dumps(entry, ensure_ascii=False) + "\n")
    except Exception as e:
        logger.debug("Usage tracker write failed: %s", e)


def read_recent(limit: int = 100) -> list[dict]:
    """Read the most recent N entries (for API/dashboard use)."""
    path = _get_log_path()
    if not path.exists():
        return []
    try:
        with open(path, "r", encoding="utf-8") as f:
            lines = f.readlines()
        entries = []
        for line in lines[-limit:]:
            line = line.strip()
            if line:
                entries.append(json.loads(line))
        return entries
    except Exception:
        return []


def get_summary(days: int = 7) -> dict:
    """Aggregate summary of tool usage over the last N days."""
    path = _get_log_path()
    if not path.exists():
        return {"total_calls": 0, "total_triggers": 0, "tools": {}, "skills": {}}
    cutoff = time.time() - days * 86400
    tools: dict[str, dict] = {}
    skills: dict[str, int] = {}
    total_calls = 0
    total_triggers = 0
    try:
        with open(path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    entry = json.loads(line)
                except json.JSONDecodeError:
                    continue
                ts_str = entry.get("ts", "")
                try:
                    ts = datetime.fromisoformat(ts_str).timestamp()
                except (ValueError, OSError):
                    continue
                if ts < cutoff:
                    continue

                event = entry.get("event")
                if event == "tool_call":
                    total_calls += 1
                    name = entry.get("tool", "unknown")
                    if name not in tools:
                        tools[name] = {"count": 0, "errors": 0, "total_ms": 0}
                    tools[name]["count"] += 1
                    tools[name]["total_ms"] += entry.get("duration_ms", 0)
                    if not entry.get("success", True):
                        tools[name]["errors"] += 1
                elif event == "skill_trigger":
                    total_triggers += 1
                    name = entry.get("skill", "unknown")
                    skills[name] = skills.get(name, 0) + 1
    except Exception:
        pass
    return {
        "total_calls": total_calls,
        "total_triggers": total_triggers,
        "tools": tools,
        "skills": skills,
    }
