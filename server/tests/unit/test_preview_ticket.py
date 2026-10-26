# -*- coding: utf-8 -*-
"""一次性预览票据（preview_ticket）单元测试 —— 方案 D6「直链去 token」。

背景：预览/下载直链把 24h 的 JWT 明文挂在 URL 上（浏览器历史、访问日志、
Referer 都能捞到）。D6 改为 60 秒一次性票据：签发即焚。

覆盖：
- issue → redeem 成功，且票据一次性（第二次兑换返回 None）
- 过期票据被拒
- mode 不匹配被拒（preview 票据不能当 download 兑换）
- 空/未知票据被拒
- 非法 mode 签发直接报错
- TTL 常量 = 60 秒（方案口径）
- 驻留上限 MAX_LIVE 生效（不无限吃内存）
"""
from __future__ import annotations

import time

import pytest

from coapis.app.services import preview_ticket as pt


@pytest.fixture(autouse=True)
def _clean_store():
    pt.reset()
    yield
    pt.reset()


def test_issue_then_redeem_once():
    token, ttl = pt.issue("alice", "files/2026-10/a.pdf", "files", "preview")
    assert token and ttl == pt.TTL_SECONDS
    ticket = pt.redeem(token, "preview")
    assert ticket is not None
    assert (ticket.username, ticket.path, ticket.category, ticket.mode) == (
        "alice",
        "files/2026-10/a.pdf",
        "files",
        "preview",
    )
    # 一次性：第二次兑换必须失败
    assert pt.redeem(token, "preview") is None


def test_expired_ticket_rejected():
    token, _ = pt.issue("alice", "files/a.md", "files", "preview")
    pt._store[token] = pt.Ticket(
        username="alice",
        path="files/a.md",
        category="files",
        mode="preview",
        expires=time.time() - 1,
    )
    assert pt.redeem(token, "preview") is None
    # 兑换即从表里摘除，不留僵尸条目
    assert pt.live_count() == 0


def test_mode_mismatch_rejected():
    token, _ = pt.issue("alice", "files/a.md", "files", "preview")
    # preview 票据不能当 download 用（防止拿预览票据换下载权限）
    assert pt.redeem(token, "download") is None
    # 兑换失败同样消耗票据
    assert pt.redeem(token, "preview") is None


def test_empty_and_unknown_token_rejected():
    assert pt.redeem("", "preview") is None
    assert pt.redeem("definitely-not-a-ticket", "preview") is None


def test_invalid_mode_rejected_at_issue():
    with pytest.raises(ValueError):
        pt.issue("alice", "files/a.md", "files", "exec")


def test_ttl_is_60_seconds():
    assert pt.TTL_SECONDS == 60


def test_issue_sweeps_expired():
    # 先塞一张已过期的，再签发新票据 → 过期条目应被清掉
    pt._store["stale"] = pt.Ticket("a", "p", "files", "preview", time.time() - 5)
    pt.issue("alice", "files/a.md", "files", "preview")
    assert "stale" not in pt._store
    assert pt.live_count() == 1


def test_max_live_cap():
    for i in range(pt.MAX_LIVE + 50):
        pt.issue("alice", f"files/f{i}.md", "files", "preview")
    assert pt.live_count() <= pt.MAX_LIVE
