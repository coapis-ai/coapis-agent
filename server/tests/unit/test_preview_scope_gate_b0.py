# -*- coding: utf-8 -*-
"""B0 安全闸门：`/api/files/preview/{path}` 作用域校验 + inline/download。

背景（2026-10-21 dev 实测）：闸门之前该端点把传入路径当绝对磁盘路径直接吐文件
——`/api/files/preview/etc/passwd` 返回 **200 / 983B**，跨用户的
`workspaces/admin/agent.json` 返回 **200 / 8624B**。答案侧一旦给出可点链接，
这就是任意文件读入口，所以作用域先于链接上线。

测试用临时工作区（monkeypatch 常量），不碰真实 dev 数据。
"""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from coapis.app.routers import file_preview as fp


# ── fixture: 临时工作区 + 模拟鉴权中间件 ──────────────────────────────

@pytest.fixture()
def env(tmp_path, monkeypatch):
    working = tmp_path / "coapis"
    workspaces = working / "workspaces"
    media = working / "media"
    for u in ("alice", "bob"):
        (workspaces / u / "files" / "media").mkdir(parents=True)
    (workspaces / "alice" / "files" / "report.md").write_text(
        "# 入市方案\n\n正文", encoding="utf-8"
    )
    (workspaces / "alice" / "files" / "media" / "shot.png").write_bytes(
        b"\x89PNG\r\n\x1a\nfake-png"
    )
    (workspaces / "bob" / "files" / "private.md").write_text(
        "bob 的私密文件", encoding="utf-8"
    )
    (workspaces / "bob" / "agent.json").write_text('{"secret": 1}', encoding="utf-8")
    media.mkdir(parents=True, exist_ok=True)
    (media / "upload.png").write_bytes(b"\x89PNG\r\n\x1a\nmedia-png")
    big = workspaces / "alice" / "files" / "big.bin"
    big.write_bytes(b"x" * (fp.MAX_PREVIEW_BYTES + 10))

    monkeypatch.setattr(fp, "WORKSPACES_DIR", workspaces)
    monkeypatch.setattr(fp, "DEFAULT_MEDIA_DIR", media)
    monkeypatch.setattr(fp, "WORKING_DIR", working)

    app = FastAPI()
    # 模拟 auth_middleware：?as=<username>&role=<role> → request.state
    @app.middleware("http")
    async def _fake_auth(request, call_next):
        request.state.username = request.query_params.get("as", "anonymous")
        request.state.role = request.query_params.get("role", "user")
        return await call_next(request)

    app.include_router(fp.router, prefix="/api")
    return TestClient(app), workspaces, media


def _get(client, path, as_user="alice", role="user", **params):
    q = {"as": as_user, "role": role}
    q.update(params)
    return client.get(f"/api/files/preview/{path}", params=q)


# ── 越界必须 403 ───────────────────────────────────────────────────

def test_system_path_rejected(env):
    client, _, _ = env
    r = _get(client, "etc/passwd")
    assert r.status_code == 403
    assert "root:" not in r.text


def test_system_path_rejected_for_admin(env):
    """管理员放宽到「全部工作区」，不是整块磁盘。"""
    client, _, _ = env
    assert _get(client, "etc/passwd", as_user="admin", role="admin").status_code == 403


def test_cross_user_rejected(env):
    client, workspaces, _ = env
    target = f"{workspaces}/bob/files/private.md"
    assert _get(client, target.lstrip("/")).status_code == 403


def test_cross_user_agent_json_rejected(env):
    client, workspaces, _ = env
    target = f"{workspaces}/bob/agent.json"
    r = _get(client, target.lstrip("/"))
    assert r.status_code == 403
    assert "secret" not in r.text


def test_dotdot_traversal_neutralized(env):
    """`..` 在 resolve() 里被折叠成「alice/bob/…」这种不存在的路径 → 404。

    逃逸不成立（既不是 bob 的文件，也读不到）；符号链接逃逸由下一条用例
    按 403 判定，那才是真实的越界通道。
    """
    client, workspaces, _ = env
    target = f"{workspaces}/alice/files/../bob/files/private.md"
    r = _get(client, target.lstrip("/"))
    assert r.status_code in (403, 404)
    assert "bob 的私密文件" not in r.text


def test_symlink_escape_rejected(env):
    client, workspaces, _ = env
    link = workspaces / "alice" / "files" / "escape"
    link.symlink_to("/etc/passwd")
    r = _get(client, f"{workspaces}/alice/files/escape".lstrip("/"))
    assert r.status_code == 403


def test_symlink_to_other_user_rejected(env):
    client, workspaces, _ = env
    link = workspaces / "alice" / "files" / "bob_link"
    link.symlink_to(workspaces / "bob" / "files" / "private.md")
    r = _get(client, f"{workspaces}/alice/files/bob_link".lstrip("/"))
    assert r.status_code == 403
    assert "bob 的私密文件" not in r.text


def test_anonymous_cannot_read_user_workspace(env):
    client, workspaces, _ = env
    target = f"{workspaces}/alice/files/report.md"
    assert _get(client, target.lstrip("/"), as_user="anonymous").status_code == 403


# ── 自己的文件必须照常可用（历史链接不失效）─────────────────────────

def test_own_workspace_ok(env):
    client, workspaces, _ = env
    target = f"{workspaces}/alice/files/report.md"
    r = _get(client, target.lstrip("/"))
    assert r.status_code == 200
    assert "入市方案" in r.text


def test_own_workspace_media_ok(env):
    client, workspaces, _ = env
    target = f"{workspaces}/alice/files/media/shot.png"
    r = _get(client, target.lstrip("/"))
    assert r.status_code == 200
    assert r.content.startswith(b"\x89PNG")


def test_global_media_dir_ok_for_owner(env):
    client, _, media = env
    target = f"{media}/upload.png"
    assert _get(client, target.lstrip("/"), as_user="bob").status_code == 200


def test_admin_reads_all_workspaces(env):
    client, workspaces, _ = env
    target = f"{workspaces}/bob/files/private.md"
    r = _get(client, target.lstrip("/"), as_user="admin", role="admin")
    assert r.status_code == 200
    assert "bob" in r.text


def test_missing_file_is_404(env):
    client, workspaces, _ = env
    target = f"{workspaces}/alice/files/nope.md"
    assert _get(client, target.lstrip("/")).status_code == 404


def test_too_large_is_413(env):
    client, workspaces, _ = env
    target = f"{workspaces}/alice/files/big.bin"
    assert _get(client, target.lstrip("/")).status_code == 413


# ── inline / download / 破缓存 ─────────────────────────────────────

def test_md_inline_is_text_plain(env):
    client, workspaces, _ = env
    target = f"{workspaces}/alice/files/report.md"
    r = _get(client, target.lstrip("/"), mode="inline")
    assert r.status_code == 200
    assert r.headers["content-type"].startswith("text/plain")
    assert "content-disposition" not in {k.lower() for k in r.headers}


def test_mode_download_forces_attachment(env):
    client, workspaces, _ = env
    target = f"{workspaces}/alice/files/report.md"
    r = _get(client, target.lstrip("/"), mode="download")
    assert r.status_code == 200
    assert "attachment" in r.headers.get("content-disposition", "")


def test_binary_defaults_to_attachment(env):
    """docx/zip 这类不内联：默认就是 attachment（历史行为不变）。"""
    client, workspaces, _ = env
    p = workspaces / "alice" / "files" / "doc.docx"
    p.write_bytes(b"PK\x03\x04fake")
    r = _get(client, f"{p}".lstrip("/"))
    assert r.status_code == 200
    assert "attachment" in r.headers.get("content-disposition", "")


def test_version_param_breaks_cache(env):
    client, workspaces, _ = env
    target = f"{workspaces}/alice/files/report.md"
    plain = _get(client, target.lstrip("/"))
    versioned = _get(client, target.lstrip("/"), v="1760000000")
    assert "no-cache" in plain.headers.get("cache-control", "")
    assert "immutable" in versioned.headers.get("cache-control", "")


def test_head_request_supported(env):
    client, workspaces, _ = env
    target = f"{workspaces}/alice/files/report.md"
    r = client.head(
        f"/api/files/preview/{target.lstrip('/')}", params={"as": "alice"}
    )
    assert r.status_code == 200
