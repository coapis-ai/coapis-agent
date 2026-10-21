# -*- coding: utf-8 -*-
"""台账「产出」口径（B5 收口）：谁写出文件，谁就是 producer。

盯四件事：

1. **来源→角色映射**：``write_file/edit_file/append_file/convert`` 是会话
   产物 → producer；``upload``（用户传进来的）与 ``reconcile``（巡检补登记）
   不是产物 → reference。
2. **``convert`` 必须是合法来源**：转格式入口传的是 ``convert``，此前不在
   ``VALID_SOURCES`` 里，落库被降级成 ``other``，产物在台账里查无此人。
3. **口径只升不降**：同一文件先被引用、后被本会话写出 → 引用升 producer；
   反过来绝不把 producer 降成 reference（那等于把已交付的产物说成引用）。
4. **端到端**：``file_ledger.record`` 带 chat_id 写文件时，chat 引用落成
   producer；上传落成 reference。会话资源端点据此显示「产出」标签。
"""
from __future__ import annotations

import time

import pytest

from coapis.foundation.db.base import Base
from coapis.foundation.db.engine import get_engine, get_session, init_engine
from coapis.foundation.db.models.resources import ResourceRef
from coapis.foundation.file_ledger import (
    PRODUCER_SOURCES,
    VALID_SOURCES,
    FileLedgerService,
    role_for_source,
)
from coapis.foundation.resource_ledger import ResourceLedger
from sqlalchemy import select


@pytest.fixture()
def env(tmp_path, monkeypatch):
    """隔离环境：临时 sqlite + 临时工作区（alice 的 files/ 根）。"""
    init_engine(f"sqlite:///{tmp_path / 'role.db'}")
    Base.metadata.create_all(get_engine())
    ws = tmp_path / "workspaces" / "alice" / "files"
    ws.mkdir(parents=True)
    monkeypatch.setattr(
        "coapis.foundation.file_ledger.WORKSPACES_DIR",
        tmp_path / "workspaces",
    )
    return tmp_path


# ── 1. 来源 → 角色 ────────────────────────────────────────────────────

@pytest.mark.parametrize(
    "source,role",
    [
        ("write_file", "producer"),
        ("edit_file", "producer"),
        ("append_file", "producer"),
        ("convert", "producer"),
        ("upload", "reference"),
        ("reconcile", "reference"),
        ("other", "reference"),
        ("", "reference"),
        ("nonsense", "reference"),
    ],
)
def test_source_maps_to_role(source, role):
    assert role_for_source(source) == role


def test_producer_sources_are_the_write_sources():
    assert PRODUCER_SOURCES == frozenset(
        {"write_file", "edit_file", "append_file", "convert"}
    )


# ── 2. convert 是合法来源 ─────────────────────────────────────────────

def test_convert_is_a_valid_source():
    """转格式产物必须按 convert 入账，不能被降级成 other。"""
    assert "convert" in VALID_SOURCES


# ── 3. 口径只升不降 ───────────────────────────────────────────────────

def _key(rl: ResourceLedger, path: str) -> str:
    return rl.register(owner_scope="user", owner_id="alice", kind="file", path=path)


def _role_of(key: str, referrer_id: str) -> str | None:
    with get_session() as s:
        row = s.execute(
            select(ResourceRef)
            .where(ResourceRef.resource_key == key)
            .where(ResourceRef.referrer_kind == "chat")
            .where(ResourceRef.referrer_id == referrer_id)
        ).scalar_one_or_none()
        return row.role if row else None


def test_reference_upgrades_to_producer(env):
    rl = ResourceLedger()
    key = _key(rl, "a.md")
    assert rl.attach_ref(resource_key=key, referrer_kind="chat", referrer_id="c1")
    assert _role_of(key, "c1") == "reference"
    assert rl.attach_ref(
        resource_key=key, referrer_kind="chat", referrer_id="c1", role="producer"
    )
    assert _role_of(key, "c1") == "producer"


def test_producer_never_downgrades(env):
    rl = ResourceLedger()
    key = _key(rl, "b.md")
    assert rl.attach_ref(
        resource_key=key, referrer_kind="chat", referrer_id="c2", role="producer"
    )
    assert rl.attach_ref(
        resource_key=key, referrer_kind="chat", referrer_id="c2", role="reference"
    )
    assert _role_of(key, "c2") == "producer"


def test_attach_ref_stays_idempotent(env):
    """重复 attach 不得产生第二行引用。"""
    rl = ResourceLedger()
    key = _key(rl, "c.md")
    for _ in range(3):
        rl.attach_ref(
            resource_key=key, referrer_kind="chat", referrer_id="c3", role="producer"
        )
    with get_session() as s:
        rows = s.execute(
            select(ResourceRef)
            .where(ResourceRef.resource_key == key)
            .where(ResourceRef.referrer_id == "c3")
        ).all()
    assert len(rows) == 1


# ── 4. 端到端：record 带 chat_id ──────────────────────────────────────

def test_write_file_records_producer_role(env):
    ledger = FileLedgerService()
    path = env / "workspaces" / "alice" / "files" / "out.md"
    path.write_text("# out\n", encoding="utf-8")
    assert ledger.record(
        "alice", str(path), chat_id="chat-w", agent_id="user:alice", source="write_file"
    )
    rl = ResourceLedger()
    key = rl.register(owner_scope="user", owner_id="alice", kind="file", path="out.md")
    assert _role_of(key, "chat-w") == "producer"


def test_upload_records_reference_role(env):
    ledger = FileLedgerService()
    path = env / "workspaces" / "alice" / "files" / "up.md"
    path.write_text("# up\n", encoding="utf-8")
    assert ledger.record(
        "alice", str(path), chat_id="chat-u", agent_id="user:alice", source="upload"
    )
    rl = ResourceLedger()
    key = rl.register(owner_scope="user", owner_id="alice", kind="file", path="up.md")
    assert _role_of(key, "chat-u") == "reference"


def test_convert_records_producer_role(env):
    ledger = FileLedgerService()
    path = env / "workspaces" / "alice" / "files" / "conv.pdf"
    path.write_text("pdf", encoding="utf-8")
    assert ledger.record(
        "alice", str(path), chat_id="chat-c", source="convert"
    )
    rl = ResourceLedger()
    key = rl.register(owner_scope="user", owner_id="alice", kind="file", path="conv.pdf")
    assert _role_of(key, "chat-c") == "producer"
    # 来源本身也要按 convert 入账，不能降级成 other
    from coapis.foundation.db.models.files import FileRecord

    with get_session() as s:
        rec = s.execute(
            select(FileRecord).where(FileRecord.file_path == "conv.pdf")
        ).scalar_one()
    assert rec.source == "convert"
