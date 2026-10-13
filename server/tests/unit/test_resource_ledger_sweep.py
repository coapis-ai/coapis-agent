# -*- coding: utf-8 -*-
"""巡检/补登记（``resource_ledger.sweep``）的行为契约。

盯三件事，都是这次 1242 条 unledgered 暴露出来的：

1. **噪音目录不算资源**：``.trash``（软删归档）与 ``.temp``（脚本暂存）里的
   文件不进清单，也不该被算成"台账缺失"。
2. **无主目录只报告不补登记**：评测沙箱 ``eval_*``、agent 工作区、已删除账号
   的残留，owner 不在用户表里；给它们补登记等于凭空造一个用户。
3. **补登记只补真用户的存量文件**，幂等，且补出来的行按冻结生命周期落成
   orphan（文件在、没有任何会话引用）——这是事实，不是 bug。
"""
from __future__ import annotations

import time

import pytest

from coapis.foundation.db.base import Base
from coapis.foundation.db.engine import get_engine, init_engine, reset_engine
from coapis.foundation.db.models.resources import Resource
from coapis.foundation.db.models.user import User
from coapis.foundation.resource_ledger import ResourceLedger
from sqlalchemy import select


@pytest.fixture()
def env(tmp_path):
    """隔离环境：临时 sqlite + 临时工作区 + 两个真实用户（alice/bob）。"""
    init_engine(f"sqlite:///{tmp_path / 'sweep.db'}")
    Base.metadata.create_all(get_engine())
    ws = tmp_path / "workspaces"
    ws.mkdir()
    from coapis.foundation.db.engine import get_session

    with get_session() as s:
        for name in ("alice", "bob"):
            s.add(
                User(
                    id=f"u_{name}",
                    username=name,
                    password_hash="x",
                    salt="x",
                    created_at=time.time(),
                )
            )
    svc = ResourceLedger(workspaces_dir=str(ws))
    yield svc, ws
    reset_engine()


def _mk(ws, user: str, rel: str, content: bytes = b"data") -> None:
    fp = ws / user / "files" / rel
    fp.parent.mkdir(parents=True, exist_ok=True)
    fp.write_bytes(content)


def _rows(owner: str) -> list[Resource]:
    from coapis.foundation.db.engine import get_session

    with get_session() as s:
        return list(
            s.execute(
                select(Resource).where(Resource.owner_id == owner)
            ).scalars().all()
        )


# ── 1. 噪音目录 ──────────────────────────────────────────────────────


def test_noise_dirs_are_not_resources(env):
    svc, ws = env
    _mk(ws, "alice", "报告.md")
    _mk(ws, "alice", ".trash/old.md")
    _mk(ws, "alice", ".temp/scripts/build.py")
    _mk(ws, "alice", "sub/.git/config")

    rep = svc.sweep(full=True)
    assert rep["unledgered"] == 1          # 只有 报告.md
    assert rep["noise_skipped"] == 3
    assert [i["path"] for i in rep["unledgered_list"]] == ["报告.md"]


def test_noise_dirs_are_not_backfilled(env):
    svc, ws = env
    _mk(ws, "alice", ".temp/x.py")
    rep = svc.sweep(full=True, backfill=True)
    assert rep["backfilled"] == 0
    assert _rows("alice") == []


# ── 2. 无主工作区目录 ────────────────────────────────────────────────


def test_non_user_workspace_is_reported_not_backfilled(env):
    svc, ws = env
    _mk(ws, "alice", "mine.md")
    _mk(ws, "eval_20261013", "clone.md")      # 评测沙箱
    _mk(ws, "deleted_user", "leftover.md")    # 已删除账号的残留

    rep = svc.sweep(full=True)
    assert rep["unledgered"] == 1
    assert rep["unowned"] == 2
    owners = {i["owner_id"] for i in rep["unowned_list"]}
    assert owners == {"eval_20261013", "deleted_user"}

    rep2 = svc.sweep(full=True, backfill=True)
    assert rep2["backfilled"] == 1           # 只补 alice
    assert [r.owner_id for r in _rows("alice")] == ["alice"]
    assert _rows("eval_20261013") == []
    assert _rows("deleted_user") == []


def test_system_workspace_is_never_scanned(env):
    svc, ws = env
    _mk(ws, "system", "agent_eval_reports/weekly.md")
    rep = svc.sweep(full=True)
    assert rep["unledgered"] == 0
    assert rep["unowned"] == 0
    assert rep["noise_skipped"] == 0


# ── 3. 补登记 ────────────────────────────────────────────────────────


def test_backfill_registers_legacy_files_once(env):
    svc, ws = env
    _mk(ws, "alice", "a.md", b"1234")
    _mk(ws, "alice", "docs/b.pdf", b"")
    _mk(ws, "bob", "c.txt")

    rep = svc.sweep(full=True, backfill=True)
    assert rep["backfilled"] == 3
    rows = _rows("alice")
    assert {r.path for r in rows} == {"a.md", "docs/b.pdf"}
    assert all(r.source == "backfill" for r in rows)
    assert all(r.fs_present == 1 for r in rows)
    assert next(r for r in rows if r.path == "a.md").size_bytes == 4

    # 幂等：第二轮不该再产生新行
    rep2 = svc.sweep(full=True, backfill=True)
    assert rep2["backfilled"] == 0
    assert rep2["unledgered"] == 0
    assert len(_rows("alice")) == 2


def test_backfilled_file_lands_as_orphan_on_next_sweep(env):
    """补登记的文件没有任何会话引用 → 按冻结生命周期落 orphan。

    这是事实陈述（文件在、没人引用），不是缺陷：一旦被重新引用，
    ``attach_ref`` 会把 orphan 拉回 draft。
    """
    svc, ws = env
    _mk(ws, "alice", "legacy.md")
    svc.sweep(full=True, backfill=True)
    rep = svc.sweep(full=True)
    assert rep["orphans"] == 1
    assert _rows("alice")[0].status == "orphan"


def test_sweep_never_deletes_files(env):
    """方向冻结：巡检可以改台账，绝不动文件系统。"""
    svc, ws = env
    _mk(ws, "alice", "keep.md")
    svc.sweep(full=True, backfill=True)
    (ws / "alice" / "files" / "keep.md").unlink()   # 用户自己删的
    rep = svc.sweep(full=True)
    assert rep["fs_missing"] == 1
    assert (ws / "alice" / "files").exists()
    assert _rows("alice")[0].fs_present == 0
