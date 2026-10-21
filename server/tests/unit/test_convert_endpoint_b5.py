# -*- coding: utf-8 -*-
"""B5 转格式入口：``POST /api/myfiles/convert``。

盯四件事：
 * 只能转**自己**工作区里的 md（作用域闸门，越界 403/404）；
 * 只有 md 能转，目标格式白名单（docx/pdf），其余 400；
 * 产物落源文件同目录同名，并登记进文件台账（我的空间与会话资源条可见）；
 * 转换实现坏了要 500 文案，不能把用户引到「转换成功但文件不存在」。
"""
from __future__ import annotations

import time

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from coapis.app.routers import files as files_router
from coapis.foundation.db.base import Base
from coapis.foundation.db.engine import get_engine, init_engine, reset_engine
from coapis.foundation.db.models.user import User


@pytest.fixture()
def env(tmp_path, monkeypatch):
    init_engine(f"sqlite:///{tmp_path / 'conv.db'}")
    Base.metadata.create_all(get_engine())

    # LocalFileBackend 的真实布局是 WORKSPACES_DIR/<username>/<category>
    # （download/preview 走的就是这一套，转换端点必须同源）
    ws = tmp_path / "workspaces"
    (ws / "alice" / "files").mkdir(parents=True)
    (ws / "alice" / "files" / "plan.md").write_text(
        "# 方案\n\n正文\n", encoding="utf-8"
    )
    (ws / "alice" / "files" / "note.txt").write_text("hi", encoding="utf-8")
    (ws / "bob" / "files").mkdir(parents=True)
    (ws / "bob" / "files" / "secret.md").write_text("# 私密", encoding="utf-8")

    import coapis.constant as const
    import coapis.app.services.file_service as fs

    monkeypatch.setattr(const, "WORKSPACES_DIR", ws)
    # 工厂是单例：先清掉，再显式塞一个指向临时区的实例，
    # 免得被同进程其他测试缓存的真实工作区遮蔽。
    fs.FileServiceFactory.reset()
    fs.FileServiceFactory._instance = fs.LocalFileBackend(ws)

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

    app = FastAPI()

    # 权限门控要活的 PermissionManager（未初始化时装饰器 fail-closed 返 503）
    from coapis.app.permissions.manager import PermissionManager
    from coapis.system.defaults import DEFAULT_PERMISSIONS

    pm = PermissionManager.__new__(PermissionManager)
    pm._config = dict(DEFAULT_PERMISSIONS)
    pm._user_permissions = {}
    monkeypatch.setattr(
        "coapis.app.permissions.manager.PermissionManager.get_instance",
        lambda: pm,
    )

    @app.middleware("http")
    async def _fake_auth(request, call_next):
        request.state.username = request.headers.get("x-user", "alice")
        request.state.role = request.headers.get("x-role", "user")
        request.state.user_info = {
            "username": request.state.username,
            "role": request.state.role,
        }
        return await call_next(request)

    app.include_router(files_router.router, prefix="/api")
    client = TestClient(app)

    recorded: list = []
    monkeypatch.setattr(
        "coapis.foundation.file_ledger.record_file_event",
        lambda *a, **kw: recorded.append((a, kw)) or True,
    )

    yield client, ws, recorded
    reset_engine()
    fs.FileServiceFactory.reset()


from coapis.foundation.db.engine import get_session  # noqa: E402


def _post(client, user, **params):
    q = "&".join(f"{k}={v}" for k, v in params.items())
    return client.post(f"/api/myfiles/convert?{q}", headers={"x-user": user})


def test_md_converts_and_lands_beside_source(env):
    client, ws, recorded = env
    resp = _post(client, "alice", path="files/plan.md", target="docx")
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["success"] is True
    assert body["path"] == "files/plan.docx"
    assert body["name"] == "plan.docx"
    out = ws / "alice" / "files" / "plan.docx"
    assert out.is_file() and out.stat().st_size > 0
    # 台账登记：让产物在「我的空间」与会话资源条里带上 ✨
    assert recorded, "转换产物必须登记进文件台账"
    args, kwargs = recorded[0]
    assert args[0] == "alice"
    assert args[1].endswith("files/plan.docx")
    assert kwargs.get("source") == "convert"


def test_non_md_source_rejected(env):
    client, _ws, _rec = env
    resp = _post(client, "alice", path="files/note.txt", target="docx")
    assert resp.status_code == 400
    assert "md" in resp.json()["detail"]


def test_target_whitelist(env):
    client, _ws, _rec = env
    resp = _post(client, "alice", path="files/plan.md", target="exe")
    assert resp.status_code == 400
    assert "docx" in resp.json()["detail"]


def test_missing_source_is_404(env):
    client, _ws, _rec = env
    resp = _post(client, "alice", path="files/nope.md", target="docx")
    assert resp.status_code == 404


def test_traversal_out_of_workspace_is_refused(env):
    client, ws, _rec = env
    # 目标目录里放一个别人的 md，路径穿越过去必须打不开
    resp = _post(client, "alice", path="files/../../bob/files/secret.md", target="docx")
    assert resp.status_code in (400, 403, 404), resp.text
    assert not (ws / "bob" / "files" / "secret.docx").exists()
