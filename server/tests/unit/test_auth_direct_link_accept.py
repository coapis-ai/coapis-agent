# -*- coding: utf-8 -*-
"""直链鉴权回归：`Accept: text/html` 放行**不得**吃掉 `/api/*` 的 token 认证。

背景（2026-10-22 企业环境实测）：产出卡「下载」在新标签打开显示「需要登录」。
根因是鉴权中间件里 SPA 的 `Accept: text/html` 放行跑在 header/query token
之前——浏览器顶层导航必带 `text/html` → username 被置为 `anonymous` →
`@require_permission` 抛 401，`?token=` 查询串认证整个被废掉。
curl 能过（`Accept: */*`）、浏览器不能过，正是「我测过能用」与
「用户点了要登录」的差异来源。

本测试锁死三件事：
 1. `/api/*` 带 `text/html` + `?token=` → 必须按 token 认（200）
 2. `/api/*` 带 `text/html` 且无 token → 必须 401（不得匿名放行）
 3. 非 `/api/` 的 SPA 路由带 `text/html` 无 token → 仍放行（前端自判登录态）
"""

from __future__ import annotations

import pytest
from fastapi import FastAPI, Request
from fastapi.testclient import TestClient

from coapis.app import auth as auth_mod
from coapis.app.auth_middleware import install_auth_middleware

TOKEN = "tok-direct-link-123"
HTML_ACCEPT = "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8"


@pytest.fixture()
def env(monkeypatch):
    """真实中间件 + 桩鉴权（不碰 dev 的 users/token 存储）。"""
    monkeypatch.setattr(auth_mod, "is_auth_enabled", lambda: True)
    monkeypatch.setattr(auth_mod, "verify_token", lambda t: "alice" if t == TOKEN else None)
    monkeypatch.setattr(
        auth_mod,
        "get_user",
        lambda u: {"username": u, "role": "admin"} if u == "alice" else None,
    )

    app = FastAPI()
    install_auth_middleware(app)

    @app.get("/api/myfiles/download")
    async def _download(request: Request):  # pragma: no cover - 断言用
        return {"ok": True, "username": request.state.username}

    @app.get("/api/files/preview/files/x.md")
    async def _preview(request: Request):  # pragma: no cover - 断言用
        return {"ok": True, "username": request.state.username}

    @app.get("/chat/abc123")
    async def _spa():  # pragma: no cover - 断言用
        return {"ok": True}

    return TestClient(app)


# ── 浏览器顶层导航：带 token 必须通 ──────────────────────────────────


def test_html_accept_with_query_token_passes(env):
    r = env.get("/api/myfiles/download", headers={"Accept": HTML_ACCEPT}, params={"token": TOKEN})
    assert r.status_code == 200, r.text
    assert r.json()["username"] == "alice"


def test_html_accept_with_header_token_passes(env):
    r = env.get(
        "/api/myfiles/download",
        headers={"Accept": HTML_ACCEPT, "Authorization": f"Bearer {TOKEN}"},
    )
    assert r.status_code == 200, r.text
    assert r.json()["username"] == "alice"


def test_star_accept_with_query_token_passes(env):
    r = env.get("/api/myfiles/download", headers={"Accept": "*/*"}, params={"token": TOKEN})
    assert r.status_code == 200, r.text


def test_preview_endpoint_same_rule(env):
    r = env.get(
        "/api/files/preview/files/x.md",
        headers={"Accept": HTML_ACCEPT},
        params={"token": TOKEN},
    )
    assert r.status_code == 200, r.text
    assert r.json()["username"] == "alice"


# ── 无 token / 坏 token：不得匿名放行 ────────────────────────────────


def test_html_accept_without_token_is_401(env):
    r = env.get("/api/myfiles/download", headers={"Accept": HTML_ACCEPT})
    assert r.status_code == 401, r.text


def test_html_accept_bad_token_is_401(env):
    r = env.get(
        "/api/myfiles/download",
        headers={"Accept": HTML_ACCEPT},
        params={"token": "nope"},
    )
    assert r.status_code == 401, r.text


def test_no_accept_no_token_is_401(env):
    r = env.get("/api/myfiles/download")
    assert r.status_code == 401, r.text


# ── SPA 前端路由：保持放行（前端自判登录态）────────────────────────


def test_spa_route_html_accept_no_token_passes_through(env):
    r = env.get("/chat/abc123", headers={"Accept": HTML_ACCEPT})
    assert r.status_code == 200, r.text
