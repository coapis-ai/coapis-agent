"""清扫未收场审批意图行（sweep_orphaned_intents）的行为锁定。

背景：审批的 future 只活在进程内存里。进程一重启，DB 里的 pending 行
再没人写，读侧永远看见"未收场"的僵尸行。这里锁三件事：
  1) 旧的未收场行被按超时收场，且 decide_source 标 maintenance（与真实
     用户超时区分）；
  2) grace 窗口内的未收场行**不动**（那是本辈子还在等人裁决的活行）；
  3) 已收场的行不被改写（收场不可逆）。
"""

from __future__ import annotations

import os
import time

import pytest
from sqlalchemy import create_engine

from coapis.foundation.db.base import Base
from coapis.foundation.db.engine import init_engine, get_session


@pytest.fixture()
def scratch_db(tmp_path):
    db_file = tmp_path / "sweep.db"
    url = f"sqlite:///{db_file}"

    import coapis.foundation.db.models  # noqa: F401  触发全部表注册

    Base.metadata.create_all(create_engine(url))
    saved = os.environ.get("COAPIS_DATABASE_URL")
    os.environ["COAPIS_DATABASE_URL"] = url
    init_engine(url)
    try:
        yield url
    finally:
        if saved is None:
            os.environ.pop("COAPIS_DATABASE_URL", None)
        else:
            os.environ["COAPIS_DATABASE_URL"] = saved
        import coapis.foundation.db.engine as engine_mod

        engine_mod._engine = None
        if hasattr(engine_mod, "_session_factory"):
            engine_mod._session_factory = None
        engine_mod._explicit_url = None


def _seed(request_id: str, *, created_at: float, outcome: str = "") -> None:
    from coapis.foundation.db.models.approval import ApprovalIntent

    with get_session() as s:
        row = s.get(ApprovalIntent, request_id)
        if row is None:
            row = ApprovalIntent(request_id=request_id)
            s.add(row)
        row.session_id = "console:admin"
        row.user_id = "admin"
        row.agent_id = "user:admin"
        row.channel = "console"
        row.tool_name = "execute_shell_command"
        row.severity = "SAFE"
        row.findings_count = 0
        row.timeout_seconds = 300.0
        row.created_at = created_at
        row.outcome = outcome
        row.decision = "" if not outcome else "approved"
        row.decide_source = "" if not outcome else "user_click"
        row.resolved_at = 0.0 if not outcome else created_at + 1


def _read(request_id: str) -> dict:
    from coapis.foundation.db.models.approval import ApprovalIntent

    with get_session() as s:
        row = s.get(ApprovalIntent, request_id)
        return {
            "decision": row.decision,
            "outcome": row.outcome,
            "decide_source": row.decide_source,
            "resolved_at": float(row.resolved_at or 0.0),
        }


def test_sweep_resolves_orphans_but_keeps_live_and_closed(scratch_db):
    from coapis.app.approvals.intent_ledger import sweep_orphaned_intents

    now = time.time()
    _seed("orphan-old", created_at=now - 3600)          # 上辈子留下的
    _seed("pending-live", created_at=now - 5)            # 本辈子还在等
    _seed("already-closed", created_at=now - 3600, outcome="applied")

    count = sweep_orphaned_intents(grace_seconds=90.0)

    assert count == 1, "只应收场 grace 之外的未收场行"
    orphan = _read("orphan-old")
    assert orphan["decision"] == "timed_out"
    assert orphan["outcome"] == "auto:abandoned_at_startup"
    # 与真实用户超时区分：清扫必须留得出来
    assert orphan["decide_source"] == "maintenance"
    assert orphan["resolved_at"] > 0, "清扫要写收场时间"

    # grace 内：本辈子刚入队、还在等人裁决 → 不许动
    live = _read("pending-live")
    assert live["outcome"] == "", "grace 内的活行被误伤"
    assert live["decision"] == ""

    # 已收场：不可被清扫改写
    closed = _read("already-closed")
    assert closed["decision"] == "approved"
    assert closed["outcome"] == "applied"
    assert closed["decide_source"] == "user_click"


def test_sweep_is_idempotent_and_never_raises(scratch_db):
    from coapis.app.approvals.intent_ledger import sweep_orphaned_intents

    now = time.time()
    _seed("orphan-a", created_at=now - 7200)
    assert sweep_orphaned_intents(grace_seconds=90.0) == 1
    # 第二次没有新的孤儿可收 → 0，且不报错
    assert sweep_orphaned_intents(grace_seconds=90.0) == 0
    # 空库/无匹配同样静默返回 0
    assert sweep_orphaned_intents(grace_seconds=90.0) == 0
