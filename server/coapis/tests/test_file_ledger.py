# -*- coding: utf-8 -*-
"""Unit tests for the file ledger service (foundation/file_ledger.py).

Coverage: record / list / stats / dedupe, dual-root acceptance (per-user
workspace files + legacy shared WORKING_DIR/files), and reconcile sweeps.
"""

import time

import pytest

from coapis.foundation import file_ledger as fl
from coapis.foundation.db.base import Base
from coapis.foundation.db.engine import get_engine, init_engine, reset_engine
from coapis.foundation.db.models.files import FileRecord  # noqa: F401  (registers model)


@pytest.fixture()
def ledger_env(tmp_path, monkeypatch):
    """Isolated ledger env: temp dirs + temp sqlite + fresh singleton."""
    ws = tmp_path / "workspaces"
    wd = tmp_path / "working"
    (wd / "files").mkdir(parents=True)
    monkeypatch.setattr(fl, "WORKSPACES_DIR", ws)
    monkeypatch.setattr(fl, "WORKING_DIR", wd)
    init_engine(f"sqlite:///{tmp_path / 'ledger.db'}")
    Base.metadata.create_all(get_engine())
    monkeypatch.setattr(fl, "_ledger", fl.FileLedgerService(str(ws)))
    yield ws, wd
    reset_engine()


def _mk(path, content=b"data"):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(content)
    return path


def _items(username, **kw):
    return fl.get_file_ledger().list_records(username, **kw)["items"]


class TestRecord:
    def test_record_in_user_files(self, ledger_env):
        ws, _ = ledger_env
        f = _mk(ws / "alice" / "files" / "a.txt", b"hello")
        assert fl.get_file_ledger().record("alice", str(f), source="write_file") is True
        rows = _items("alice")
        assert len(rows) == 1
        assert rows[0]["file_path"] == "a.txt"
        assert rows[0]["size_bytes"] == 5
        assert rows[0]["source"] == "write_file"

    def test_record_outside_roots_rejected(self, ledger_env):
        _, wd = ledger_env
        f = _mk(wd / "elsewhere.txt")
        assert fl.get_file_ledger().record("alice", str(f)) is False
        assert _items("alice") == []

    def test_record_empty_path_rejected(self, ledger_env):
        assert fl.get_file_ledger().record("alice", "") is False

    def test_record_legacy_shared_without_user(self, ledger_env):
        _, wd = ledger_env
        f = _mk(wd / "files" / "legacy.bin")
        assert fl.get_file_ledger().record("", str(f), source="write_file") is True
        rows = _items("shared")
        assert len(rows) == 1
        assert rows[0]["file_path"] == "legacy.bin"

    def test_record_legacy_shared_with_user_attributed(self, ledger_env):
        _, wd = ledger_env
        f = _mk(wd / "files" / "job.out")
        assert fl.get_file_ledger().record("bob", str(f)) is True
        rows = _items("bob")
        assert len(rows) == 1
        assert rows[0]["file_path"] == "job.out"

    def test_dedupe_keeps_latest(self, ledger_env):
        ws, _ = ledger_env
        f = _mk(ws / "alice" / "files" / "a.txt", b"hello")
        led = fl.get_file_ledger()
        led.record("alice", str(f), source="write_file")
        time.sleep(0.01)
        f.write_bytes(b"hello world!")
        led.record("alice", str(f), source="write_file")
        rows = _items("alice")
        assert len(rows) == 1
        assert rows[0]["size_bytes"] == 12


class TestFiltersStats:
    def test_filters_and_stats(self, ledger_env):
        ws, _ = ledger_env
        f = _mk(ws / "alice" / "files" / "a.txt")
        led = fl.get_file_ledger()
        assert led.record("alice", str(f), session_id="s1", source="write_file")
        assert len(_items("alice", session_id="s1")) == 1
        assert _items("alice", session_id="other") == []
        assert _items("alice", source="upload") == []
        stats = led.stats("alice")
        assert stats["total_files"] == 1
        assert stats["total_size"] == 4
        assert stats["by_source"] == {"write_file": 1}
        assert ".txt" in stats["by_extension"]

    def test_stats_unknown_user_zero(self, ledger_env):
        stats = fl.get_file_ledger().stats("ghost")
        assert stats["total_files"] == 0
        assert stats["total_size"] == 0
        assert stats["by_source"] == {}


class TestReconcile:
    def test_reconcile_users_and_shared(self, ledger_env):
        ws, wd = ledger_env
        _mk(ws / "alice" / "files" / "a.txt")
        _mk(ws / "alice" / "files" / "sub" / "b.md")
        _mk(ws / "carol" / "files" / "c.txt")
        _mk(wd / "files" / "legacy.log")
        res = fl.get_file_ledger().reconcile()
        assert res["inserted"] >= 4
        assert {r["file_path"] for r in _items("alice")} == {"a.txt", "sub/b.md"}
        assert [r["file_path"] for r in _items("shared")] == ["legacy.log"]
        # Second pass inserts nothing (dedupe)
        res2 = fl.get_file_ledger().reconcile()
        assert res2["inserted"] == 0

    def test_reconcile_empty_dirs(self, ledger_env):
        ws, _ = ledger_env
        ws.mkdir(parents=True)
        res = fl.get_file_ledger().reconcile()
        assert res == {"scanned": 0, "inserted": 0}


class TestDeliverables:
    """Approved plan C1: status machine / deliverables view / archive / title."""

    def test_status_transition(self, ledger_env):
        ws, _ = ledger_env
        f = _mk(ws / "alice" / "files" / "report.docx")
        led = fl.get_file_ledger()
        assert led.record("alice", str(f), source="write_file", title="季度报告")
        rows = _items("alice")
        assert rows[0]["status"] == "draft"
        assert rows[0]["title"] == "季度报告"
        assert led.update_record_status(
            "alice", "report.docx", "delivered", description="已交付客户"
        )
        rows = _items("alice")
        assert rows[0]["status"] == "delivered"
        assert rows[0]["description"] == "已交付客户"
        assert rows[0]["updated_at"] is not None
        # invalid status rejected, no mutation
        assert led.update_record_status("alice", "report.docx", "bogus") is False
        assert _items("alice")[0]["status"] == "delivered"

    def test_list_deliverables_filter_and_order(self, ledger_env):
        ws, _ = ledger_env
        a = _mk(ws / "alice" / "files" / "a.txt")
        b = _mk(ws / "alice" / "files" / "b.txt")
        c = _mk(ws / "alice" / "files" / "c.txt")
        led = fl.get_file_ledger()
        led.record("alice", str(a), source="write_file")
        led.record("alice", str(b), source="write_file")
        led.record("alice", str(c), source="write_file")
        time.sleep(0.02)
        led.update_record_status("alice", "a.txt", "delivered")
        time.sleep(0.02)
        led.update_record_status("alice", "b.txt", "archived")
        all_items = led.list_deliverables("alice")
        assert {d["file_path"] for d in all_items} == {"a.txt", "b.txt", "c.txt"}
        assert [d["file_path"] for d in led.list_deliverables("alice", status="delivered")] == ["a.txt"]
        assert [d["file_path"] for d in led.list_deliverables("alice", status="archived")] == ["b.txt"]
        # newest activity first (b updated last)
        assert all_items[0]["file_path"] == "b.txt"
        # row id IS exposed: PATCH /records/{id}/status and
        # POST /records/{id}/archive target records with it, and the
        # client keys list items by it.
        assert isinstance(all_items[0]["id"], int)
        # dedupe: rewriting a file adds no duplicate entry
        time.sleep(0.02)
        a.write_bytes(b"again")
        led.record("alice", str(a), source="edit_file")
        assert len(led.list_deliverables("alice")) == 3

    def test_archive_file(self, ledger_env):
        ws, _ = ledger_env
        f = _mk(ws / "alice" / "files" / "a.txt")
        led = fl.get_file_ledger()
        led.record("alice", str(f), source="write_file")
        assert led.archive_file("alice", "a.txt") is True
        assert _items("alice")[0]["status"] == "archived"
        # unknown path -> False
        assert led.archive_file("alice", "nope.txt") is False
        # owner isolation on row-id resolution
        assert led.resolve_path("alice", 99999) is None

    def test_title_kwarg(self, ledger_env):
        ws, _ = ledger_env
        f = _mk(ws / "alice" / "files" / "notes.md")
        led = fl.get_file_ledger()
        assert led.record("alice", str(f), source="upload", title="原始文件名.pdf")
        assert _items("alice")[0]["title"] == "原始文件名.pdf"
        # no title -> None
        g = _mk(ws / "alice" / "files" / "plain.md")
        assert led.record("alice", str(g), source="write_file")
        titles = {r["file_path"]: r["title"] for r in _items("alice")}
        assert titles["plain.md"] is None
