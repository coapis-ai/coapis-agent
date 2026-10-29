# -*- coding: utf-8 -*-
"""A6：上传提示语补「会话归属 / 台账 / 版次」，且不得与台账两套口径。"""
from __future__ import annotations

import coapis.app.agent_context as ac
import coapis.config.session_context as sc
import coapis.foundation.file_ledger as fl
from coapis.agents.utils.message_processing import _upload_notice


class _Ledger:
    def __init__(self, version: int):
        self._version = version

    def upload_version(self, _username, _path):
        return self._version


def _bind(monkeypatch, *, username="alice", chat="c1", session="s1", version=3):
    monkeypatch.setattr(sc, "get_current_username", lambda: username)
    monkeypatch.setattr(sc, "get_current_chat_id", lambda: chat)
    monkeypatch.setattr(sc, "get_current_session_id", lambda: session)
    monkeypatch.setattr(ac, "get_current_username", lambda: username)
    monkeypatch.setattr(fl, "get_file_ledger", lambda: _Ledger(version))


def test_notice_carries_session_ledger_and_version(monkeypatch):
    _bind(monkeypatch, version=3)
    text = _upload_notice("/ws/alice/files/uploads/doc.pdf", "zh")
    assert text.startswith("用户上传文件，已经下载到 /ws/alice/files/uploads/doc.pdf")
    assert "已归入本会话" in text
    assert "已入台账 第3版" in text


def test_notice_omits_ledger_when_not_ledgered(monkeypatch):
    _bind(monkeypatch, version=0)
    text = _upload_notice("/ws/alice/media/x.png", "zh")
    assert "已归入本会话" in text
    assert "已入台账" not in text


def test_notice_falls_back_without_context(monkeypatch):
    _bind(monkeypatch, username=None, chat=None, session=None)
    assert (
        _upload_notice("/tmp/x.pdf", "zh")
        == "用户上传文件，已经下载到 /tmp/x.pdf"
    )


def test_notice_english(monkeypatch):
    _bind(monkeypatch, version=2)
    text = _upload_notice("/ws/alice/files/a.md", "en")
    assert "User uploaded a file, downloaded to /ws/alice/files/a.md" in text
    assert "attached to this chat" in text
    assert "ledgered v2" in text


def test_notice_uses_legacy_username_context(monkeypatch):
    _bind(monkeypatch, username=None, version=1)
    monkeypatch.setattr(ac, "get_current_username", lambda: "bob")
    seen = {}

    class _Spy(_Ledger):
        def upload_version(self, username, path):
            seen["username"] = username
            return 1

    monkeypatch.setattr(fl, "get_file_ledger", lambda: _Spy(1))
    text = _upload_notice("/ws/bob/files/a.md", "zh")
    assert seen["username"] == "bob"
    assert "已入台账 第1版" in text


def test_notice_survives_ledger_failure(monkeypatch):
    _bind(monkeypatch)

    def _boom():
        raise RuntimeError("ledger down")

    monkeypatch.setattr(fl, "get_file_ledger", _boom)
    assert _upload_notice("/tmp/x.pdf", "zh") == "用户上传文件，已经下载到 /tmp/x.pdf"
