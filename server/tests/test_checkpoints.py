"""B5-A 检查点最小版 —— 服务层 + 端点测试。

覆盖（对应实施方案 8.3 出口验收 1/2 与 D13「默认关 + 恢复二次确认」）：

1. 开关默认关：列表 404、动作 503，detail 写明怎么开启；
2. 创建/列表：只读指纹快照，摘要字段齐全；
3. **预览不落盘**（dry_run 自证）：预览前后工作区文件哈希逐个相等、
   检查点仓库文件清单与 index 不变；
4. 恢复必须显式授权：无 ``confirm: true`` → 400；
5. 授权恢复后文件内容与检查点哈希一致，且自动生成「恢复前检查点」；
6. 内容块缺失 → 整体中止（409），且**不做半恢复**（工作区零改动）；
7. 作用域：非管理员查他人 → 403；相对路径逃逸 → 拒绝写入；
8. 排除规则：密钥/数据库/日志/字节码不入快照，数据卷系统目录拒绝作为作用域。

所有工作区与仓库目录都在 ``tmp_path`` 里造，绝不碰真实数据卷。
"""

from __future__ import annotations

import hashlib
import json
import shutil
from pathlib import Path

import pytest
from coapis.app.routers import checkpoints as ckpt_router
from coapis.checkpoints import (
    CheckpointIntegrityError,
    CheckpointNotFoundError,
    CheckpointPathError,
    CheckpointService,
    ConfirmRequiredError,
    KIND_MANUAL,
    KIND_PRE_RESTORE,
    checkpoints_enabled,
    is_excluded,
    scan_entries,
    workspace_files_root,
)
from coapis.checkpoints.paths import PathEscapeError, safe_join

USER = "ckpttester"


# --------------------------------------------------------------------------- #
# helpers / fixtures
# --------------------------------------------------------------------------- #


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _tree(root: Path, files: dict[str, str]) -> None:
    root.mkdir(parents=True, exist_ok=True)
    for rel, text in files.items():
        p = root / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text, encoding="utf-8")


def _disk_state(root: Path) -> dict[str, str]:
    """工作区现状 {相对路径: sha256}，用于自证「盘上没动」。"""
    out: dict[str, str] = {}
    for p in sorted(root.rglob("*")):
        if p.is_file():
            out[p.relative_to(root).as_posix()] = _sha(p.read_bytes())
    return out


def _store_state(store: Path) -> dict[str, str]:
    out: dict[str, str] = {}
    if not store.exists():
        return out
    for p in sorted(store.rglob("*")):
        rel = p.relative_to(store).as_posix()
        out[rel] = "dir" if p.is_dir() else _sha(p.read_bytes())
    return out


@pytest.fixture()
def ws(tmp_path, monkeypatch):
    """把 WORKSPACES_DIR 指到 tmp，并开启开关。返回 tmp 根。"""
    import coapis.constant as constant

    monkeypatch.setattr(constant, "WORKSPACES_DIR", tmp_path)
    monkeypatch.setenv("COAPIS_CHECKPOINTS_ENABLED", "true")
    files_root = tmp_path / USER / "files"
    _tree(
        files_root,
        {
            "a.txt": "第一版 A",
            "sub/b.txt": "第一版 B",
            "keep.txt": "不变",
        },
    )
    return tmp_path


def _service(ws: Path) -> CheckpointService:
    return CheckpointService(USER)


def _client(monkeypatch, *, username=USER, role="user", enabled=True):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    if enabled:
        monkeypatch.setenv("COAPIS_CHECKPOINTS_ENABLED", "true")
    else:
        monkeypatch.delenv("COAPIS_CHECKPOINTS_ENABLED", raising=False)

    app = FastAPI()
    app.include_router(ckpt_router.router, prefix="/api")

    @app.middleware("http")
    async def _inject_identity(request, call_next):  # pragma: no cover
        request.state.username = username
        request.state.role = role
        request.state.user_info = {"username": username, "role": role}
        return await call_next(request)

    return TestClient(app)


# --------------------------------------------------------------------------- #
# 1. 开关
# --------------------------------------------------------------------------- #


def test_flag_defaults_off(monkeypatch):
    monkeypatch.delenv("COAPIS_CHECKPOINTS_ENABLED", raising=False)
    assert checkpoints_enabled() is False
    for raw in ("", "0", "false", "nope", " "):
        monkeypatch.setenv("COAPIS_CHECKPOINTS_ENABLED", raw)
        assert checkpoints_enabled() is False, raw
    for raw in ("1", "true", "TRUE", "yes", "on", "enabled"):
        monkeypatch.setenv("COAPIS_CHECKPOINTS_ENABLED", raw)
        assert checkpoints_enabled() is True, raw


def test_disabled_endpoints_explain(monkeypatch, ws):
    client = _client(monkeypatch, enabled=False)

    r = client.get("/api/checkpoints")
    assert r.status_code == 404
    assert "COAPIS_CHECKPOINTS_ENABLED" in r.json()["detail"]

    r = client.post("/api/checkpoints/preview", json={"checkpoint_id": "x"})
    assert r.status_code == 503
    assert "COAPIS_CHECKPOINTS_ENABLED" in r.json()["detail"]

    r = client.post("/api/checkpoints/restore", json={"checkpoint_id": "x", "confirm": True})
    assert r.status_code == 503


# --------------------------------------------------------------------------- #
# 2. 创建 / 列表
# --------------------------------------------------------------------------- #


def test_create_and_list(ws):
    svc = _service(ws)
    cp = svc.create_checkpoint(session="sess-1", note="开工前")
    assert cp.kind == KIND_MANUAL
    assert cp.file_count == 3
    assert cp.session == "sess-1"
    # 内容寻址：每个文件都有 sha256，且与实际盘上一致
    for rel, meta in cp.files.items():
        assert meta["sha256"] == _sha((ws / USER / "files" / rel).read_bytes())

    items = svc.list_checkpoints()
    assert [c.checkpoint_id for c in items] == [cp.checkpoint_id]
    assert svc.list_checkpoints(session="nope") == []
    got = svc.get_checkpoint(cp.checkpoint_id)
    assert got.note == "开工前"

    with pytest.raises(CheckpointNotFoundError):
        svc.get_checkpoint("does-not-exist")


def test_create_dry_run_writes_nothing(ws):
    svc = _service(ws)
    store = ws / USER / "checkpoints"
    before = _store_state(store)
    cp = svc.create_checkpoint(dry_run=True, note="只算不改")
    assert cp.file_count == 3
    assert _store_state(store) == before
    assert svc.list_checkpoints() == []


# --------------------------------------------------------------------------- #
# 3. 预览 = 只读（dry_run 自证）
# --------------------------------------------------------------------------- #


def test_preview_is_readonly_and_lists_diffs(ws):
    svc = _service(ws)
    cp = svc.create_checkpoint(note="基线")
    files_root = ws / USER / "files"
    # 改一个、删一个、加一个
    (files_root / "a.txt").write_text("改坏的 A", encoding="utf-8")
    (files_root / "sub/b.txt").unlink()
    (files_root / "new.txt").write_text("新增", encoding="utf-8")

    disk_before = _disk_state(files_root)
    store_before = _store_state(ws / USER / "checkpoints")

    plan = svc.preview_restore(cp.checkpoint_id)
    payload = plan.to_dict()

    kinds = {d.rel: d.kind for d in plan.diffs}
    assert kinds["a.txt"] == "changed"
    assert kinds["sub/b.txt"] == "missing"
    assert kinds["new.txt"] == "extra"
    assert kinds["keep.txt"] == "unchanged"
    assert payload["dry_run"] is True
    assert payload["writable"] is True
    assert sorted(d["rel"] for d in payload["diffs"]) == [
        "a.txt",
        "keep.txt",
        "new.txt",
        "sub/b.txt",
    ]
    # 自证：预览完盘上一个字节都没动，检查点仓库清单不变
    assert _disk_state(files_root) == disk_before
    assert _store_state(ws / USER / "checkpoints") == store_before


# --------------------------------------------------------------------------- #
# 4/5. 恢复：授权 + 哈希一致 + 恢复前自动留底
# --------------------------------------------------------------------------- #


def test_restore_requires_confirm(ws):
    svc = _service(ws)
    cp = svc.create_checkpoint()
    with pytest.raises(ConfirmRequiredError):
        svc.restore(cp.checkpoint_id, confirm=False)


def test_restore_with_confirm_matches_hashes(ws):
    svc = _service(ws)
    cp = svc.create_checkpoint(note="基线")
    files_root = ws / USER / "files"
    (files_root / "a.txt").write_text("改坏的 A", encoding="utf-8")
    (files_root / "sub/b.txt").unlink()
    (files_root / "new.txt").write_text("新增", encoding="utf-8")
    sha_before = {
        rel: _sha((files_root / rel).read_bytes()) for rel in ("a.txt",)
    }

    out = svc.restore(cp.checkpoint_id, confirm=True, session="sess-1")

    assert sorted(out.restored) == ["a.txt", "sub/b.txt"]
    assert "keep.txt" in out.skipped
    assert out.total_bytes > 0
    # 恢复后逐文件哈希 == 检查点记录的哈希
    for rel in out.restored:
        assert _sha((files_root / rel).read_bytes()) == cp.files[rel]["sha256"]
    # 检查点里没有的文件不被删（恢复是回滚，不是清空）
    assert (files_root / "new.txt").read_text(encoding="utf-8") == "新增"
    assert sha_before["a.txt"] != _sha((files_root / "a.txt").read_bytes())

    # 恢复前自动留底，且指向被恢复的检查点
    items = svc.list_checkpoints()
    kinds = {c.kind for c in items}
    assert KIND_PRE_RESTORE in kinds
    pre = [c for c in items if c.kind == KIND_PRE_RESTORE][0]
    assert out.pre_restore_checkpoint_id == pre.checkpoint_id
    assert pre.pre_restore_of == cp.checkpoint_id
    # 留底快照里 a.txt 是"改坏"那一刻的内容
    assert pre.files["a.txt"]["sha256"] == sha_before["a.txt"]


# --------------------------------------------------------------------------- #
# 6. 内容块缺失 → 整体中止，不做半恢复
# --------------------------------------------------------------------------- #


def test_missing_blob_aborts_without_partial_restore(ws):
    svc = _service(ws)
    cp = svc.create_checkpoint()
    files_root = ws / USER / "files"
    (files_root / "a.txt").write_text("改坏 A", encoding="utf-8")
    (files_root / "sub/b.txt").write_text("改坏 B", encoding="utf-8")

    # 抹掉一个内容块（模拟仓库损坏）
    digests = [cp.files["a.txt"]["sha256"], cp.files["sub/b.txt"]["sha256"]]
    for d in digests:
        path = svc.store.blob_path(d)
        if path.exists():
            path.unlink()

    plan = svc.preview_restore(cp.checkpoint_id)
    assert plan.writable is False
    assert len(plan.missing_blobs) >= 1

    state = _disk_state(files_root)
    with pytest.raises(CheckpointIntegrityError):
        svc.restore(cp.checkpoint_id, confirm=True)
    # 半恢复没发生
    assert _disk_state(files_root) == state


# --------------------------------------------------------------------------- #
# 7. 作用域与路径
# --------------------------------------------------------------------------- #


def test_scope_non_admin_forbidden(ws, monkeypatch):
    client = _client(monkeypatch, username="bob", role="user")
    r = client.get("/api/checkpoints", params={"user": USER})
    assert r.status_code == 403

    r = client.post("/api/checkpoints/preview", json={"checkpoint_id": "x", "user": USER})
    assert r.status_code == 403


def test_admin_can_scope(ws, monkeypatch):
    client = _client(monkeypatch, username="admin", role="admin")
    r = client.get("/api/checkpoints", params={"user": USER})
    assert r.status_code == 200
    assert r.json()["username"] == USER
    assert r.json()["count"] == 0


def test_router_restore_requires_confirm(ws, monkeypatch):
    svc = _service(ws)
    cp = svc.create_checkpoint()
    client = _client(monkeypatch, username=USER, role="user")

    r = client.post("/api/checkpoints/restore", json={"checkpoint_id": cp.checkpoint_id})
    assert r.status_code == 400
    assert "confirm" in r.json()["detail"]

    r = client.post(
        "/api/checkpoints/restore",
        json={"checkpoint_id": cp.checkpoint_id, "confirm": True},
    )
    assert r.status_code == 200
    body = r.json()
    assert body["username"] == USER
    assert body["pre_restore_checkpoint_id"]

    r = client.post("/api/checkpoints/restore", json={"checkpoint_id": "ghost", "confirm": True})
    assert r.status_code == 404


def test_router_list_and_preview_dry_run(ws, monkeypatch):
    svc = _service(ws)
    cp = svc.create_checkpoint(session="sess-9")
    files_root = ws / USER / "files"
    (files_root / "a.txt").write_text("改坏", encoding="utf-8")

    disk_before = _disk_state(files_root)
    client = _client(monkeypatch, username=USER, role="user")

    r = client.get("/api/checkpoints")
    assert r.status_code == 200
    data = r.json()
    assert data["enabled"] is True
    assert data["count"] == 1
    assert data["items"][0]["checkpoint_id"] == cp.checkpoint_id

    r = client.get("/api/checkpoints", params={"session": "sess-9"})
    assert r.json()["count"] == 1

    r = client.post("/api/checkpoints/preview", json={"checkpoint_id": cp.checkpoint_id})
    assert r.status_code == 200
    plan = r.json()
    assert plan["dry_run"] is True
    assert plan["wrote_to_disk"] is False
    assert plan["to_restore_count"] == 1
    assert _disk_state(files_root) == disk_before


def test_path_escape_rejected(ws):
    svc = _service(ws)
    with pytest.raises(PathEscapeError):
        safe_join(ws / USER / "files", "../secrets.txt")
    with pytest.raises((PathEscapeError, CheckpointPathError)):
        safe_join(ws / USER / "files", "/etc/passwd")


def test_illegal_username_rejected(ws):
    with pytest.raises(CheckpointPathError):
        CheckpointService("../escape")


# --------------------------------------------------------------------------- #
# 8. 排除规则
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize(
    "rel",
    [
        "secret.pem",
        "a.key",
        "dump.db",
        "run.log",
        "module.pyc",
        ".git/config",
        ".env",
        "certs/x.crt",
        "",
    ],
)
def test_is_excluded_rules(rel):
    assert is_excluded(rel) is True


def test_scan_entries_excludes_and_hashes(ws):
    files_root = ws / USER / "files"
    _tree(
        files_root,
        {
            "good.txt": "留",
            "skip.log": "日志",
            "cache.pyc": "字节码",
            "data.sqlite": "库",
            ".git/HEAD": "git",
            ".env": "密钥",
        },
    )
    entries = scan_entries(files_root)
    rels = {e.rel for e in entries}
    assert rels == {"good.txt", "a.txt", "keep.txt", "sub/b.txt"}
    for e in entries:
        assert e.sha256 == _sha((files_root / e.rel).read_bytes())


def test_scope_root_outside_workspaces_rejected(ws):
    """作用域根必须在工作区内（挡掉把整盘/数据卷当作用域）。"""
    with pytest.raises(CheckpointPathError):
        CheckpointService(USER, scope_root=ws.parent)


def test_scope_root_forbidden_directory_rejected(tmp_path):
    """作用域根命中禁止目录（数据卷系统目录/密钥目录）→ 显式拒绝。"""
    from coapis.checkpoints.paths import ScopeForbiddenError, guard_scope_root

    bad = tmp_path / "system"
    bad.mkdir(parents=True, exist_ok=True)
    with pytest.raises(ScopeForbiddenError):
        guard_scope_root(bad, workspaces_dir=tmp_path, forbidden=[bad])
    # 工作区内的正常根放行
    ok = tmp_path / "bob" / "files"
    ok.mkdir(parents=True, exist_ok=True)
    assert guard_scope_root(ok, workspaces_dir=tmp_path, forbidden=[bad]).name == "files"


def test_ledger_source_restore_is_whitelisted():
    """恢复回灌台账用的 source='restore' 必须在台账白名单里（否则被记成 other）。"""
    from coapis.foundation.file_ledger import PRODUCER_SOURCES, VALID_SOURCES

    assert "restore" in VALID_SOURCES
    # 恢复是"把文件写回来"= 产出方；口径与 write_file 同源
    assert "restore" in PRODUCER_SOURCES
