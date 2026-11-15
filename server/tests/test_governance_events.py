"""B5-B 治理事件统一语义 —— 映射规则 + 联合视图 + 只读端点。

覆盖实施方案 8.3-B 的验收口径：

1. **一套 kind 词表**：六类 + config，映射规则只有一处（SSOT）；
2. 联合查询按 kind 收窄，多来源合并、新→旧；
3. 未识别的 event_type **不猜**（跳过），未知 kind 明确报出来；
4. 端点只读、非管理员强制只看自己。
"""

from __future__ import annotations

import json
import time
from pathlib import Path

import pytest
from coapis.app.routers import governance as gov_router
from coapis.governance.events import (
    EVENT_KINDS,
    classify_audit_event,
    list_events,
    read_audit_events,
)

# --------------------------------------------------------------------------- #
# 1. kind 词表与映射（SSOT）
# --------------------------------------------------------------------------- #


def test_kind_vocabulary():
    assert set(EVENT_KINDS) >= {
        "judge",
        "tool",
        "approval",
        "memory",
        "file_version",
        "sandbox_denied",
    }
    # 词表是元组且无重复 —— 端点与视图都引用它，不许各自造词
    assert isinstance(EVENT_KINDS, tuple)
    assert len(set(EVENT_KINDS)) == len(EVENT_KINDS)


def test_classify_tool_and_approval():
    ev = classify_audit_event(
        {
            "event_type": "tool_call",
            "timestamp": 100.0,
            "user_id": "bob",
            "resource": "execute_shell_command",
            "result": "allowed",
            "event_id": "e1",
        }
    )
    assert ev["kind"] == "tool"
    assert ev["ts"] == 100.0
    assert ev["username"] == "bob"
    assert ev["ref_id"] == "e1"

    ev = classify_audit_event(
        {
            "event_type": "approval",
            "category": "authorizations",
            "timestamp": 101.0,
            "user_id": "bob",
            "result": "allow",
            "metadata": {"session_id": "s1", "tool": "shell"},
        }
    )
    assert ev["kind"] == "approval"
    # target 是操作对象（工具/文件/命令），会话单列在 session
    assert ev["target"] == "shell"
    assert ev["session"] == "s1"


def test_classify_sandbox_denied_is_separate_from_tool_denied():
    # 沙箱（路径/命令白名单）拒绝
    ev = classify_audit_event(
        {
            "event_type": "tool_call",
            "timestamp": 1.0,
            "result": "denied_by_policy(sandbox)",
            "metadata": {"tool": "shell", "policy": "vcs_write"},
        }
    )
    assert ev["kind"] == "sandbox_denied"

    # 工具闸/监控阻断 → tool_denied（不是沙箱）
    ev = classify_audit_event(
        {
            "event_type": "tool_monitor_blocked",
            "timestamp": 1.0,
            "result": "blocked",
            "metadata": {"tool": "shell"},
        }
    )
    assert ev["kind"] == "tool_denied"

    ev = classify_audit_event(
        {
            "event_type": "tool_call",
            "timestamp": 1.0,
            "result": "denied_by_policy(guard)",
            "metadata": {"tool": "shell"},
        }
    )
    assert ev["kind"] == "tool_denied"


def test_classify_unknown_event_type_is_not_guessed():
    assert classify_audit_event({"event_type": "made_up"}) is None
    assert classify_audit_event({}) is None
    assert classify_audit_event("not a dict") is None
    # 兜底只认「有结果 + 有工具」这类可证事实，不认裸 event_type
    assert classify_audit_event({"event_type": "weird", "result": "ok"}) is None


# --------------------------------------------------------------------------- #
# 2. 审计链读取（尾部 + 过滤）
# --------------------------------------------------------------------------- #


def _write_audit(path: Path, events: list[dict]) -> Path:
    with path.open("w", encoding="utf-8") as fh:
        for ev in events:
            fh.write(json.dumps(ev, ensure_ascii=False) + "\n")
    return path


def test_read_audit_events_filters_and_orders(tmp_path):
    log = _write_audit(
        tmp_path / "audit.jsonl",
        [
            {"event_type": "tool_call", "timestamp": 1.0, "user_id": "bob", "result": "allowed"},
            {"event_type": "approval", "timestamp": 2.0, "user_id": "bob", "result": "allow"},
            {"event_type": "permission_denied", "timestamp": 3.0, "user_id": "alice"},
            {"event_type": "config_change", "timestamp": 4.0, "user_id": "admin"},
            {"event_type": "made_up", "timestamp": 5.0},
            "坏行不是字典",
        ],
    )

    all_events = read_audit_events(log)
    kinds = {e["kind"] for e in all_events}
    assert kinds == {"tool", "approval", "sandbox_denied", "config"}

    only_appr = read_audit_events(log, kinds=["approval"])
    assert [e["kind"] for e in only_appr] == ["approval"]

    only_bob = read_audit_events(log, username="bob")
    assert {e["username"] for e in only_bob} == {"bob"}

    recent = read_audit_events(log, since_ts=3.0)
    assert all(e["ts"] >= 3.0 for e in recent)

    # 新→旧
    assert [e["ts"] for e in read_audit_events(log)] == sorted(
        [e["ts"] for e in read_audit_events(log)],
        reverse=True,
    )


def test_read_audit_events_missing_file_is_empty(tmp_path):
    assert read_audit_events(tmp_path / "nope.jsonl") == []


def test_read_audit_events_tail_reads_large_file(tmp_path):
    log = tmp_path / "audit.jsonl"
    with log.open("w", encoding="utf-8") as fh:
        for i in range(2000):
            fh.write(
                json.dumps(
                    {
                        "event_type": "tool_call",
                        "timestamp": float(i),
                        "user_id": "bob",
                        "result": "allowed",
                    }
                )
                + "\n",
            )
    out = read_audit_events(log, limit=5)
    assert len(out) == 5
    assert max(e["ts"] for e in out) >= 1999  # 读的是尾部（最新）


# --------------------------------------------------------------------------- #
# 3. 联合视图
# --------------------------------------------------------------------------- #


def test_list_events_union_by_kind(tmp_path):
    log = _write_audit(
        tmp_path / "audit.jsonl",
        [
            {"event_type": "tool_call", "timestamp": 10.0, "user_id": "bob", "result": "allowed"},
            {"event_type": "approval", "timestamp": 20.0, "user_id": "bob", "result": "allow"},
        ],
    )
    res = list_events(kinds=["approval", "tool"], audit_log_path=log)
    assert res["count"] == 2
    assert [e["kind"] for e in res["events"]] == ["approval", "tool"]

    res = list_events(kinds=["approval"], audit_log_path=log)
    assert [e["kind"] for e in res["events"]] == ["approval"]


def test_list_events_rejects_unknown_kind(tmp_path):
    log = _write_audit(tmp_path / "a.jsonl", [])
    res = list_events(kinds=["tool", "made_up"], audit_log_path=log)
    assert "made_up" in (res["note"] or "")
    assert "made_up" not in res["kinds"]


def test_list_events_limit_applies(tmp_path):
    log = tmp_path / "a.jsonl"
    with log.open("w", encoding="utf-8") as fh:
        for i in range(50):
            fh.write(
                json.dumps(
                    {"event_type": "approval", "timestamp": float(i), "user_id": "bob"},
                )
                + "\n",
            )
    res = list_events(kinds=["approval"], limit=7, audit_log_path=log)
    assert res["count"] == 7
    assert res["limit"] == 7


# --------------------------------------------------------------------------- #
# 4. 端点
# --------------------------------------------------------------------------- #


def _client(monkeypatch, *, username="bob", role="user", audit: Path):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    monkeypatch.setattr(gov_router, "list_events", lambda **kw: _list(audit, **kw))

    app = FastAPI()
    app.include_router(gov_router.router, prefix="/api")

    @app.middleware("http")
    async def _ident(request, call_next):  # pragma: no cover
        request.state.username = username
        request.state.role = role
        return await call_next(request)

    return TestClient(app)


def _list(audit: Path, **kw):
    from coapis.governance.events import list_events as real

    return real(audit_log_path=audit, **kw)


def test_endpoint_scope_forces_own_events(tmp_path, monkeypatch):
    log = _write_audit(
        tmp_path / "a.jsonl",
        [
            {"event_type": "approval", "timestamp": 1.0, "user_id": "bob"},
            {"event_type": "approval", "timestamp": 2.0, "user_id": "alice"},
        ],
    )
    client = _client(monkeypatch, username="bob", role="user", audit=log)

    r = client.get("/api/governance/events")
    assert r.status_code == 200
    body = r.json()
    assert body["scope"] == "bob"
    assert {e["username"] for e in body["events"]} == {"bob"}

    # 非管理员传 user=alice 也不给看
    r = client.get("/api/governance/events", params={"user": "alice"})
    assert {e["username"] for e in r.json()["events"]} == {"bob"}


def test_endpoint_admin_scope_and_kind_filter(tmp_path, monkeypatch):
    log = _write_audit(
        tmp_path / "a.jsonl",
        [
            {"event_type": "approval", "timestamp": 1.0, "user_id": "bob"},
            {"event_type": "tool_call", "timestamp": 2.0, "user_id": "alice", "result": "allowed"},
        ],
    )
    client = _client(monkeypatch, username="admin", role="admin", audit=log)

    r = client.get("/api/governance/events", params={"kind": "tool"})
    body = r.json()
    assert body["scope"] == "all"
    assert [e["kind"] for e in body["events"]] == ["tool"]

    r = client.get("/api/governance/events", params={"user": "alice"})
    assert {e["username"] for e in r.json()["events"]} == {"alice"}


def test_endpoint_rejects_unknown_kind(tmp_path, monkeypatch):
    log = _write_audit(tmp_path / "a.jsonl", [])
    client = _client(monkeypatch, username="admin", role="admin", audit=log)
    r = client.get("/api/governance/events", params={"kind": "made_up"})
    assert r.status_code == 400
    assert "made_up" in r.json()["detail"]


def test_endpoint_requires_identity(tmp_path, monkeypatch):
    log = _write_audit(tmp_path / "a.jsonl", [])
    client = _client(monkeypatch, username="", role="", audit=log)
    r = client.get("/api/governance/events")
    assert r.status_code == 401


def test_endpoint_sandbox_status_is_readonly(tmp_path, monkeypatch):
    monkeypatch.setenv("COAPIS_SANDBOX_MODE", "off")
    monkeypatch.setenv("COAPIS_SANDBOX_PROBE_FILE", str(tmp_path / "probe.json"))
    client = _client(monkeypatch, username="bob", role="user", audit=tmp_path / "a.jsonl")

    r = client.get("/api/governance/sandbox-status")
    assert r.status_code == 200
    body = r.json()
    assert body["mode"] == "off"
    assert body["probed"] is False
    assert body["probe"] is None

    # 重探仅管理员
    r = client.get("/api/governance/sandbox-status", params={"refresh": "true"})
    assert r.status_code == 403
