# -*- coding: utf-8 -*-
"""Unit tests for the file ledger service (M2)."""
from __future__ import annotations

from pathlib import Path

import pytest

import coapis.foundation.file_ledger as fl
from coapis.foundation.db.base import Base
from coapis.foundation.db.engine import get_engine, init_engine, reset_engine
from coapis.foundation.file_ledger import FileLedgerService


@pytest.fixture()
def env(tmp_path, monkeypatch):
    db_path = tmp_path / "test_file_ledger.db"
    init_engine(f"sqlite:///{db_path}")
    Base.metadata.create_all(get_engine())
    ws = tmp_path / "workspaces"
    ws.mkdir()
    wd = tmp_path / "working"
    (wd / "files").mkdir(parents=True)
    # 隔离共享根目录，防止 reconcile 扫到真实 WORKING_DIR/files 造成串扰
    monkeypatch.setattr(fl, "WORKING_DIR", wd)
    monkeypatch.setattr(fl, "WORKSPACES_DIR", ws)
    svc = FileLedgerService(workspaces_dir=ws)
    yield svc, ws
    reset_engine()


def _mk(ws: Path, user: str, rel: str, content: bytes = b"data") -> Path:
    fp = ws / user / "files" / rel
    fp.parent.mkdir(parents=True, exist_ok=True)
    fp.write_bytes(content)
    return fp


def test_record_inserts_row(env):
    svc, ws = env
    fp = _mk(ws, "alice", "notes/a.txt", b"hello world")
    ok = svc.record(
        "alice", str(fp), session_id="s1", agent_id="bot",
        source="write_file",
    )
    assert ok is True
    res = svc.list_records("alice")
    assert res["total"] == 1
    item = res["items"][0]
    assert item["file_path"] == "notes/a.txt"
    assert item["source"] == "write_file"
    assert item["session_id"] == "s1"
    assert item["agent_id"] == "bot"
    assert item["size_bytes"] == len(b"hello world")


def test_record_skips_outside_files_dir(env):
    svc, ws = env
    outsider = ws / "alice" / "outside.txt"
    outsider.parent.mkdir(parents=True, exist_ok=True)
    outsider.write_bytes(b"x")
    assert svc.record("alice", str(outsider), source="write_file") is False
    assert svc.list_records("alice")["total"] == 0


def test_record_requires_user_and_path(env):
    svc, _ = env
    assert svc.record(None, "/tmp/x", source="write_file") is False
    assert svc.record("bob", None, source="write_file") is False


def test_unknown_source_normalized(env):
    svc, ws = env
    fp = _mk(ws, "ann", "a.txt")
    assert svc.record("ann", str(fp), source="weird") is True
    assert svc.list_records("ann")["items"][0]["source"] == "other"


def test_dedupe_keeps_newest_version(env):
    svc, ws = env
    fp = _mk(ws, "carol", "doc.md", b"v1")
    svc.record("carol", str(fp), source="write_file")
    fp.write_bytes(b"version-two-longer")
    svc.record("carol", str(fp), source="edit_file")
    res = svc.list_records("carol")
    assert res["total"] == 1
    assert res["items"][0]["source"] == "edit_file"
    assert res["items"][0]["size_bytes"] == len(b"version-two-longer")


def test_filter_by_session_and_source(env):
    svc, ws = env
    a = _mk(ws, "dan", "a.txt")
    b = _mk(ws, "dan", "b.txt")
    svc.record("dan", str(a), session_id="s1", source="upload")
    svc.record("dan", str(b), session_id="s2", source="write_file")
    assert svc.list_records("dan", session_id="s1")["total"] == 1
    assert svc.list_records("dan", source="upload")["total"] == 1
    assert (
        svc.list_records("dan", source="upload", session_id="s2")["total"] == 0
    )


def test_pagination(env):
    svc, ws = env
    for i in range(5):
        fp = _mk(ws, "erin", f"f{i}.txt")
        svc.record("erin", str(fp), source="write_file")
    res = svc.list_records("erin", limit=2, offset=0)
    assert res["total"] == 5
    assert len(res["items"]) == 2
    res2 = svc.list_records("erin", limit=10, offset=3)
    assert len(res2["items"]) == 2


def test_stats(env):
    svc, ws = env
    a = _mk(ws, "fred", "a.md", b"# hi")
    b = _mk(ws, "fred", "img/pic.png", b"\x89PNG")
    c = _mk(ws, "fred", "data.csv", b"a,b")
    svc.record("fred", str(a), source="write_file")
    svc.record("fred", str(b), source="upload")
    svc.record("fred", str(c), source="reconcile")
    st = svc.stats("fred")
    assert st["total_files"] == 3
    assert st["total_size"] == len(b"# hi") + len(b"\x89PNG") + len(b"a,b")
    assert st["by_source"]["write_file"] == 1
    assert st["by_source"]["upload"] == 1
    assert st["by_source"]["reconcile"] == 1
    assert st["by_extension"][".md"] == 1
    assert st["by_extension"][".png"] == 1
    assert st["by_extension"][".csv"] == 1


def test_reconcile_backfills_missing(env):
    svc, ws = env
    a = _mk(ws, "gina", "a.txt", b"aa")
    _mk(ws, "gina", "sub/b.txt", b"bbb")
    svc.record("gina", str(a), source="write_file")  # a.txt already ledgered
    res = svc.reconcile()
    assert res["scanned"] >= 2
    assert res["inserted"] == 1
    assert svc.stats("gina")["total_files"] == 2
    # idempotent
    res2 = svc.reconcile()
    assert res2["inserted"] == 0
    assert svc.stats("gina")["total_files"] == 2


def test_reconcile_no_workspaces(env):
    svc, _ = env
    assert svc.reconcile() == {"scanned": 0, "inserted": 0}


def test_list_empty_user(env):
    svc, _ = env
    res = svc.list_records("nobody")
    assert res["items"] == []
    assert res["total"] == 0


# ── upload_version（A6 上传提示语「第几版」的台账口径） ────────────────


def test_upload_version_counts_upload_rows(env):
    svc, ws = env
    fp = _mk(ws, "alice", "uploads/doc.pdf")
    for _ in range(3):
        assert svc.record("alice", str(fp), session_id="s1", source="upload")
    assert svc.upload_version("alice", str(fp)) == 3


def test_upload_version_ignores_other_sources(env):
    svc, ws = env
    fp = _mk(ws, "alice", "gen/report.md")
    svc.record("alice", str(fp), source="write_file")
    assert svc.upload_version("alice", str(fp)) == 0


def test_upload_version_scopes_per_user(env):
    svc, ws = env
    fp = _mk(ws, "alice", "uploads/doc.pdf")
    svc.record("alice", str(fp), source="upload")
    other = _mk(ws, "bob", "uploads/doc.pdf")
    svc.record("bob", str(other), source="upload")
    assert svc.upload_version("alice", str(fp)) == 1
    assert svc.upload_version("bob", str(other)) == 1


def test_upload_version_outside_root_and_empty_args(env):
    svc, ws = env
    outsider = ws / "alice" / "media" / "x.png"
    outsider.parent.mkdir(parents=True, exist_ok=True)
    outsider.write_bytes(b"x")
    assert svc.upload_version("alice", str(outsider)) == 0
    assert svc.upload_version("", str(outsider)) == 0
    assert svc.upload_version("alice", "") == 0
