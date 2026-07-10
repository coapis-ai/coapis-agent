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
"""Security operations — audit log + crypto ops merged.

Combines audit_log (SHA-256 chained immutable audit trail) with crypto_ops
(hashing, HMAC, base64) into a single tool via action parameter.
"""

from __future__ import annotations

import base64
import hashlib
import hmac as hmac_mod
import json
import logging
import os
import time
from pathlib import Path
from typing import Any

from .registry import register_tool

logger = logging.getLogger(__name__)

# ── Audit log storage ──
AUDIT_DIR = Path(os.environ.get("COAPIS_AUDIT_DIR",
    os.path.join(os.path.dirname(__file__), "..", "..", "..", "data", "audit")))
CHAIN_FILE = AUDIT_DIR / "chain.jsonl"


def _ensure_dir():
    AUDIT_DIR.mkdir(parents=True, exist_ok=True)


def _hash_entry(prev_hash: str, entry: dict) -> str:
    payload = prev_hash + json.dumps(entry, sort_keys=True, ensure_ascii=False)
    return hashlib.sha256(payload.encode()).hexdigest()


def _get_last_hash() -> str:
    if not CHAIN_FILE.exists():
        return "0" * 64
    try:
        with open(CHAIN_FILE) as f:
            lines = f.readlines()
            if lines:
                return json.loads(lines[-1]).get("hash", "0" * 64)
    except Exception:
        pass
    return "0" * 64


def _read_entries(limit: int = 100, filters: dict | None = None) -> list[dict]:
    if not CHAIN_FILE.exists():
        return []
    entries = []
    with open(CHAIN_FILE) as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            entry = json.loads(line)
            data = entry.get("data", {})
            if filters:
                if filters.get("actor") and data.get("actor") != filters["actor"]:
                    continue
                if filters.get("action") and data.get("action") != filters["action"]:
                    continue
                if filters.get("resource") and data.get("resource") != filters["resource"]:
                    continue
                if filters.get("result") and data.get("result") != filters["result"]:
                    continue
                if filters.get("since") and data.get("timestamp", 0) < filters["since"]:
                    continue
            entries.append(entry)
            if len(entries) >= limit:
                break
    return entries


def _verify_chain() -> dict[str, Any]:
    if not CHAIN_FILE.exists():
        return {"valid": True, "entries": 0, "message": "审计日志为空"}
    entries = []
    with open(CHAIN_FILE) as f:
        for line in f:
            line = line.strip()
            if line:
                entries.append(json.loads(line))
    prev_hash = "0" * 64
    broken_at = -1
    for i, entry in enumerate(entries):
        expected = _hash_entry(prev_hash, entry.get("data", {}))
        if entry.get("hash") != expected:
            broken_at = i
            break
        prev_hash = entry.get("hash", "")
    return {
        "valid": broken_at == -1,
        "entries": len(entries),
        "broken_at": broken_at if broken_at >= 0 else None,
        "message": "链完整性验证通过" if broken_at == -1 else f"链在第{broken_at}条记录处断裂",
    }


def _get_workspace() -> Path:
    try:
        from ...config.context import get_current_workspace_dir
        ws = get_current_workspace_dir()
        if ws:
            return Path(ws)
    except Exception:
        pass
    return Path.cwd()


async def security_ops(
    action: str = "log",
    # audit params
    actor: str = "agent",
    operation: str = "",
    resource: str = "",
    result_status: str = "success",
    detail: str = "",
    since: int = 0,
    filters: str = "",
    # crypto params
    text: str = "",
    algorithm: str = "sha256",
    secret: str = "",
    signature: str = "",
    file_path: str = "",
    encoding: str = "utf-8",
    output_format: str = "hex",
    # common
    limit: int = 50,
    **kwargs: Any,
) -> dict[str, Any]:
    """安全操作统一工具。

    审计操作: log / query / verify / stats
    加密操作: hash / hmac_sign / hmac_verify / base64_encode / base64_decode / file_hash
    """
    # ── Audit operations ──
    if action == "log":
        if not operation.strip():
            return {"error": "operation 不能为空"}
        _ensure_dir()
        ts = int(time.time())
        entry = {"actor": actor, "action": operation.strip(), "resource": resource,
                 "result": result_status, "detail": detail[:500], "timestamp": ts}
        prev = _get_last_hash()
        h = _hash_entry(prev, entry)
        record = {"data": entry, "hash": h, "prev": prev}
        with open(CHAIN_FILE, "a") as f:
            f.write(json.dumps(record, ensure_ascii=False) + "\n")
        return {"action": "log", "hash": h[:16] + "...", "ts": time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(ts))}

    elif action == "query":
        # Read from unified audit_logs table (primary source)
        try:
            from ...user_system.database import UserSystemDB
            db = UserSystemDB()
            parsed = {}
            if filters.strip():
                try:
                    parsed = json.loads(filters)
                except Exception:
                    pass
            if since:
                parsed["since"] = since

            conditions, params = [], []
            if parsed.get("actor"):
                conditions.append("username = ?"); params.append(parsed["actor"])
            if parsed.get("action"):
                conditions.append("action = ?"); params.append(parsed["action"])
            if parsed.get("resource"):
                conditions.append("resource_id = ?"); params.append(parsed["resource"])
            if parsed.get("since"):
                conditions.append("created_at >= ?"); params.append(float(parsed["since"]))

            where = "WHERE " + " AND ".join(conditions) if conditions else ""
            rows = db.execute(
                f"SELECT * FROM audit_logs {where} ORDER BY created_at DESC LIMIT ?",
                params + [limit],
            ).fetchall()

            entries = []
            for row in rows:
                det = row["details"] or "{}"
                if isinstance(det, str):
                    try: det = json.loads(det)
                    except: det = {}
                entries.append({
                    "id": row["id"], "username": row["username"], "action": row["action"],
                    "resource_type": row["resource_type"], "resource_id": row["resource_id"],
                    "result": det.get("result", ""), "detail": det.get("detail", ""),
                    "hash": det.get("hash", "")[:16] + "..." if det.get("hash") else "",
                    "created_at": row["created_at"],
                })
            return {"action": "query", "count": len(entries), "entries": entries}
        except Exception as e:
            # Fallback to chain file
            parsed = {}
            if filters.strip():
                try: parsed = json.loads(filters)
                except: pass
            if since: parsed["since"] = since
            entries = _read_entries(limit=limit, filters=parsed or None)
            return {"action": "query", "count": len(entries),
                    "entries": [{"data": e["data"], "hash": e["hash"][:16] + "..."} for e in entries],
                    "source": "chain_fallback"}

    elif action == "verify":
        _ensure_dir()
        return {"action": "verify", **_verify_chain()}

    elif action == "stats":
        # Read from unified audit_logs table (primary source)
        try:
            from ...user_system.database import UserSystemDB
            db = UserSystemDB()
            total_row = db.execute("SELECT COUNT(*) as cnt FROM audit_logs").fetchone()
            total = total_row["cnt"] if total_row else 0
            action_rows = db.execute(
                "SELECT action, COUNT(*) as cnt FROM audit_logs GROUP BY action ORDER BY cnt DESC"
            ).fetchall()
            by_action = {r["action"]: r["cnt"] for r in action_rows}
            user_rows = db.execute(
                "SELECT username, COUNT(*) as cnt FROM audit_logs GROUP BY username ORDER BY cnt DESC LIMIT 10"
            ).fetchall()
            by_actor = {r["username"]: r["cnt"] for r in user_rows}
            latest = db.execute("SELECT created_at FROM audit_logs ORDER BY created_at DESC LIMIT 1").fetchone()
            first = db.execute("SELECT created_at FROM audit_logs ORDER BY created_at ASC LIMIT 1").fetchone()
            return {
                "action": "stats", "total": total, "by_actor": by_actor, "by_action": by_action,
                "chain_valid": _verify_chain().get("valid", False),
                "first_ts": first["created_at"] if first else 0,
                "last_ts": latest["created_at"] if latest else 0,
                "source": "db",
            }
        except Exception:
            # Fallback to chain file
            entries = _read_entries(limit=10000)
            if not entries:
                return {"action": "stats", "total": 0}
            by_actor, by_action = {}, {}
            for e in entries:
                d = e.get("data", {})
                by_actor[d.get("actor", "unknown")] = by_actor.get(d.get("actor", "unknown"), 0) + 1
                by_action[d.get("action", "unknown")] = by_action.get(d.get("action", "unknown"), 0) + 1
            return {"action": "stats", "total": len(entries), "by_actor": by_actor, "by_action": by_action,
                    "chain_valid": _verify_chain().get("valid", False),
                    "first_ts": entries[-1]["data"].get("timestamp", 0) if entries else 0,
                    "last_ts": entries[0]["data"].get("timestamp", 0) if entries else 0,
                    "source": "chain_fallback"}

    # ── Crypto operations ──
    elif action == "hash":
        if not text.strip() and not file_path.strip():
            return {"error": "text 或 file_path 不能为空"}
        algo = algorithm.lower().strip()
        h = hashlib.new(algo)
        if file_path.strip():
            fp = Path(file_path.strip())
            if not fp.is_absolute():
                fp = _get_workspace() / fp
            if not fp.exists():
                return {"error": f"文件不存在: {file_path}"}
            with open(fp, "rb") as f:
                while chunk := f.read(8192):
                    h.update(chunk)
        else:
            h.update(text.encode(encoding))
        digest = h.hexdigest() if output_format == "hex" else base64.b64encode(h.digest()).decode()
        return {"algorithm": algo, "hash": digest, "input_type": "file" if file_path else "text"}

    elif action == "hmac_sign":
        if not text.strip() or not secret.strip():
            return {"error": "text 和 secret 不能为空"}
        algo = algorithm.lower().strip()
        sig = hmac_mod.new(secret.encode(encoding), text.encode(encoding), algo).hexdigest()
        return {"algorithm": algo, "signature": sig}

    elif action == "hmac_verify":
        if not all([text, secret, signature]):
            return {"error": "text, secret, signature 不能为空"}
        algo = algorithm.lower().strip()
        expected = hmac_mod.new(secret.encode(encoding), text.encode(encoding), algo).hexdigest()
        return {"algorithm": algo, "verified": hmac_mod.compare_digest(expected, signature.strip())}

    elif action == "base64_encode":
        if not text.strip():
            return {"error": "text 不能为空"}
        return {"encoded": base64.b64encode(text.encode(encoding)).decode()}

    elif action == "base64_decode":
        if not text.strip():
            return {"error": "text 不能为空"}
        try:
            return {"decoded": base64.b64decode(text.strip()).decode(encoding)}
        except Exception as e:
            return {"error": str(e)}

    elif action == "file_hash":
        if not file_path.strip():
            return {"error": "file_path 不能为空"}
        fp = Path(file_path.strip())
        if not fp.is_absolute():
            fp = _get_workspace() / fp
        if not fp.exists():
            return {"error": f"文件不存在: {file_path}"}
        results = {}
        for algo_name in ("md5", "sha1", "sha256"):
            h = hashlib.new(algo_name)
            with open(fp, "rb") as f:
                while chunk := f.read(8192):
                    h.update(chunk)
            results[algo_name] = h.hexdigest()
        return {"file": str(fp), "hashes": results}

    return {"error": f"未知 action: {action}。审计: log/query/verify/stats; 加密: hash/hmac_sign/hmac_verify/base64_encode/base64_decode/file_hash"}


# ── Backward-compat aliases ──
audit_log = security_ops
crypto_ops = security_ops
