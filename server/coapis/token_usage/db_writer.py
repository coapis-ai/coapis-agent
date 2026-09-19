"""
Token usage DB writer - 明细记录持久化。

DB 优先（token_usage 表），DB 不可用时回退 JSON 文件（token_usage_details.json，
测试/降级模式）。

Provides:
- save_token_usage()       - 每次 LLM 调用的明细入库（model_wrapper 调用）
- record_token_usage()     - 兼容旧签名
- get_user_token_usage()   - 按用户查询
- get_agent_token_usage()  - 按 agent 查询
- get_usage_history()      - 单用户/agent 历史
- get_token_usage()        - 汇总统计
- load_token_usage()       - 全量记录
"""

import json
import logging
import time
from datetime import datetime
from pathlib import Path

from ..constant import SYSTEM_DIR

logger = logging.getLogger(__name__)

SYSTEM_DIR = Path(SYSTEM_DIR)


def _details_file() -> Path:
    return SYSTEM_DIR / "token_usage_details.json"


def _engine():
    """获取全局 DB engine（未初始化返回 None）。"""
    try:
        from ..foundation.db import get_engine
        return get_engine()
    except Exception:
        return None


# ---------------------------------------------------------------------------
# 写入
# ---------------------------------------------------------------------------

def _db_insert(
    user_id: int | str | None,
    username: str | None,
    agent_id: str | None,
    model: str,
    input_tokens: int,
    output_tokens: int,
    total_tokens: int | None,
    cost_cents: float,
    created_at: float | None = None,
) -> None:
    from sqlalchemy import text
    engine = _engine()
    if engine is None:
        return
    ts = float(created_at) if created_at else time.time()
    total = int(total_tokens) if total_tokens is not None else int(input_tokens or 0) + int(output_tokens or 0)
    with engine.begin() as conn:
        conn.execute(
            text(
                "INSERT INTO token_usage "
                "(user_id, username, agent_id, model, input_tokens, output_tokens, "
                " total_tokens, cost_cents, created_at) "
                "VALUES (:uid, :uname, :aid, :model, :in_t, :out_t, :total, :cost, :ts)"
            ),
            {
                "uid": str(user_id) if user_id is not None else None,
                "uname": username,
                "aid": agent_id,
                "model": model,
                "in_t": int(input_tokens or 0),
                "out_t": int(output_tokens or 0),
                "total": total,
                "cost": float(cost_cents or 0),
                "ts": ts,
            },
        )


def save_token_usage(
    user_id: int | str | None,
    agent_id: str | None = None,
    model: str = "",
    input_tokens: int = 0,
    output_tokens: int = 0,
    total_tokens: int | None = None,
    cost_cents: float = 0.0,
    username: str | None = None,
    created_at: float | None = None,
) -> None:
    """每次 LLM 调用后记录明细（model_wrapper._record_usage_to_db 调用）。

    兼容两种调用形态：
    - model_wrapper: save_token_usage(user_id=..., username=..., agent_id=..., model=...,
      input_tokens=..., output_tokens=..., total_tokens=..., cost_cents=...)
    - 旧签名: record_token_usage(user_id, agent_id, model, in, out, cost, created_at)
    """
    try:
        engine = _engine()
        if engine is not None:
            _db_insert(
                user_id, username, agent_id, model,
                input_tokens, output_tokens, total_tokens, cost_cents, created_at,
            )
        else:
            _file_append(
                user_id, username, agent_id, model,
                input_tokens, output_tokens, total_tokens, cost_cents, created_at,
            )
    except Exception as e:
        logger.debug(f"Failed to save token usage: {e}")


def record_token_usage(
    user_id: int | str | None,
    agent_id: str | None = None,
    model: str = "",
    input_tokens: int = 0,
    output_tokens: int = 0,
    cost_cents: float = 0.0,
    created_at: float | None = None,
    username: str | None = None,
    total_tokens: int | None = None,
) -> None:
    """记录一条 token 用量明细（兼容旧签名）。"""
    save_token_usage(
        user_id,
        agent_id=agent_id,
        model=model,
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        total_tokens=total_tokens,
        cost_cents=cost_cents,
        username=username,
        created_at=created_at,
    )


def _file_append(
    user_id: int | str | None,
    username: str | None,
    agent_id: str | None,
    model: str,
    input_tokens: int,
    output_tokens: int,
    total_tokens: int | None,
    cost_cents: float,
    created_at: float | None,
) -> None:
    """文件兜底：追加到 token_usage_details.json（{"records": [...]} 格式）。"""
    file = _details_file()
    file.parent.mkdir(parents=True, exist_ok=True)
    total = int(total_tokens) if total_tokens is not None else int(input_tokens or 0) + int(output_tokens or 0)
    record = {
        "user_id": user_id,
        "username": username,
        "agent_id": agent_id,
        "model": model,
        "input_tokens": input_tokens,
        "output_tokens": output_tokens,
        "total_tokens": total,
        "cost_cents": cost_cents,
        "created_at": datetime.fromtimestamp(
            float(created_at) if created_at else time.time()
        ).isoformat(),
    }
    records = []
    if file.exists():
        try:
            with open(file, "r", encoding="utf-8") as f:
                data = json.load(f)
            records = data.get("records", []) if isinstance(data, dict) else data
        except Exception:
            records = []
    records.append(record)
    # 保留最近 10000 条
    if len(records) > 10000:
        records = records[-10000:]
    with open(file, "w", encoding="utf-8") as f:
        json.dump({"records": records}, f, ensure_ascii=False, indent=2)


# ---------------------------------------------------------------------------
# 查询
# ---------------------------------------------------------------------------

def _norm_record(row: dict) -> dict:
    """统一记录字段（created_at 转 ISO 字符串，兼容前端/旧格式）。"""
    rec = dict(row)
    ts = rec.get("created_at")
    if isinstance(ts, (int, float)) and not isinstance(ts, bool):
        rec["created_at"] = datetime.fromtimestamp(float(ts)).isoformat()
    for k in ("input_tokens", "output_tokens", "total_tokens"):
        rec[k] = int(rec.get(k) or 0)
    rec["cost_cents"] = float(rec.get("cost_cents") or 0)
    return rec


def _db_rows(where: str, params: dict) -> list[dict]:
    from sqlalchemy import text
    engine = _engine()
    if engine is None:
        return []
    with engine.connect() as conn:
        rows = conn.execute(
            text(
                "SELECT user_id, agent_id, model, input_tokens, output_tokens, "
                "total_tokens, cost_cents, created_at FROM token_usage "
                + (f"WHERE {where} " if where else "")
                + "ORDER BY created_at DESC LIMIT 10000"
            ),
            params,
        ).mappings().all()
    return [_norm_record(dict(r)) for r in rows]


def _file_rows() -> list[dict]:
    file = _details_file()
    if not file.exists():
        return []
    try:
        with open(file, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return []


def get_user_token_usage(user_id: str, agent_id: str | None = None) -> list[dict]:
    """按用户查询 token 用量记录。"""
    where = "user_id = :uid"
    params = {"uid": str(user_id)}
    if agent_id is not None:
        where += " AND agent_id = :aid"
        params["aid"] = agent_id
    rows = _db_rows(where, params)
    if not rows and _engine() is None:
        rows = [
            r for r in _file_rows()
            if str(r.get("user_id")) == str(user_id)
            and (agent_id is None or r.get("agent_id") == agent_id)
        ]
    return rows


def get_agent_token_usage(agent_id: str) -> list[dict]:
    """按 agent 查询 token 用量记录。"""
    rows = _db_rows("agent_id = :aid", {"aid": agent_id})
    if not rows and _engine() is None:
        rows = [
            r for r in _file_rows()
            if r.get("agent_id") == agent_id
        ]
    return rows


def get_usage_history(user_id: str | None = None, agent_id: str | None = None) -> list[dict]:
    """获取单用户/单 agent 的 token 用量历史。"""
    if user_id is not None and agent_id is None:
        return get_user_token_usage(user_id)
    if agent_id is not None and user_id is None:
        return get_agent_token_usage(agent_id)
    if user_id is not None and agent_id is not None:
        return get_user_token_usage(user_id, agent_id)
    # 全量
    rows = _db_rows("", {})
    if not rows and _engine() is None:
        rows = _file_rows()
    return rows


def get_token_usage(user_id: str | None = None, agent_id: str | None = None) -> dict:
    """汇总 token 用量统计（按 model 分组）。"""
    records = get_usage_history(user_id=user_id, agent_id=agent_id)
    total_input = sum(r.get("input_tokens", 0) for r in records)
    total_output = sum(r.get("output_tokens", 0) for r in records)
    total_cost = sum(r.get("cost_cents", 0) for r in records)
    by_model = {}
    for r in records:
        m = r.get("model", "unknown")
        if m not in by_model:
            by_model[m] = {"input_tokens": 0, "output_tokens": 0, "cost_cents": 0, "calls": 0}
        by_model[m]["input_tokens"] += r.get("input_tokens", 0)
        by_model[m]["output_tokens"] += r.get("output_tokens", 0)
        by_model[m]["cost_cents"] += r.get("cost_cents", 0)
        by_model[m]["calls"] += 1
    return {
        "total_input_tokens": total_input,
        "total_output_tokens": total_output,
        "total_tokens": total_input + total_output,
        "total_cost_cents": total_cost,
        "record_count": len(records),
        "by_model": by_model,
    }


def load_token_usage() -> list[dict]:
    """加载全量 token 用量明细。"""
    return get_usage_history()
