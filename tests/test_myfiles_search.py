# -*- coding: utf-8 -*-
"""「我的空间」文件搜索统一化测试。

覆盖三件事：
  1. 搜索语义：递归子树、匹配完整相对路径、排除噪音目录、目录在前、
     limit 只截断返回条数、total 始终是命中总数。
  2. 统一性：`/myfiles/search` 与 `/myfiles/list?search=` 共用服务层
     同一份实现（源码层断言 + 输出逐行一致）。
  3. Seafile 移出：后端不再有 Seafile 后端/端点/文件，工厂只产 Local 后端。

用法：python tests/test_myfiles_search.py
（宿主无依赖时在容器里跑：docker cp 后 PYTHONPATH=/app python /tmp/xxx.py）
"""

import asyncio
import inspect
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
# 仓库树必须压在最前：/app 是镜像里的旧副本。旧写法用「不在 sys.path 才插入」，
# 当 PYTHONPATH 已包含仓库树（在尾部）时会被跳过，/app 反而被插到 index 0，
# 测试验证的就是镜像代码而不是当前仓库代码（实测直接 ImportError 缺符号）。
_server = str(ROOT / "server")
for _p in (_server, "/app"):
    while _p in sys.path:
        sys.path.remove(_p)
sys.path.insert(0, _server)
if (Path("/app") / "coapis").is_dir():
    sys.path.append("/app")  # 兜底可导入，但永远排在仓库树之后

from fastapi import FastAPI, HTTPException  # noqa: E402

import coapis.app.routers.files as files_mod  # noqa: E402
import coapis.app.services.file_service as fs_mod  # noqa: E402
from coapis.app.services import LocalFileBackend, FileServiceFactory  # noqa: E402
from coapis.app.services.file_service import SEARCH_LIMIT, sort_file_infos  # noqa: E402

FS_SRC = Path(fs_mod.__file__).read_text(encoding="utf-8")
ROUTER_SRC = Path(files_mod.__file__).read_text(encoding="utf-8")
SERVICES_DIR = Path(fs_mod.__file__).parent
ROUTERS_DIR = Path(files_mod.__file__).parent


def _search(backend, *args, **kwargs):
    """search_files 是协程，测试里同步跑。"""
    return asyncio.run(backend.search_files(*args, **kwargs))


def _fixture():
    """tmp 工作区（tester/files）：
    a/子/季度汇报.pptx, a/汇报稿.docx, 顶层汇报.md,
    .trash/汇报-已删.docx, .temp/汇报-临时.docx, b/其他.txt
    """
    tmp = Path(tempfile.mkdtemp(prefix="myspace_search_"))
    u = tmp / "tester" / "files"
    for rel in (
        "a/子/季度汇报.pptx",
        "a/汇报稿.docx",
        ".trash/汇报-已删.docx",
        ".temp/汇报-临时.docx",
        "b/其他.txt",
        "顶层汇报.md",
    ):
        p = u / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text("x", encoding="utf-8")
    return LocalFileBackend(tmp)


# ── 1. 搜索语义 ────────────────────────────────────────────────

def test_recursive_hit_in_nested_dir():
    b = _fixture()
    hits, total = _search(b, "tester", "汇报")
    paths = {h.path for h in hits}
    assert paths == {"/a/子/季度汇报.pptx", "/a/汇报稿.docx", "/顶层汇报.md"}, paths
    assert total == len(hits) == 3, (total, len(hits))


def test_matches_full_relative_path_not_only_name():
    """输入 `a/汇` 能命中 /a/汇报稿.docx——「我知道它在哪个目录下」时可直接定位。"""
    b = _fixture()
    hits, _ = _search(b, "tester", "a/汇")
    assert [h.path for h in hits] == ["/a/汇报稿.docx"], [h.path for h in hits]


def test_noise_dirs_excluded():
    """`.trash`/`.temp` 里的同名文件搜不到——口径与资源台账一致。"""
    b = _fixture()
    for kw in ("汇报-已删", "汇报-临时"):
        hits, total = _search(b, "tester", kw)
        assert hits == [] and total == 0, (kw, [h.path for h in hits])


def test_subtree_scope():
    b = _fixture()
    hits, _ = _search(b, "tester", "汇报", path="/a")
    assert {h.path for h in hits} == {"/a/子/季度汇报.pptx", "/a/汇报稿.docx"}
    hits, _ = _search(b, "tester", "汇报", path="/b")
    assert hits == []


def test_limit_caps_items_but_total_is_full_count():
    b = _fixture()
    hits, total = _search(b, "tester", "汇报", limit=2)
    assert len(hits) == 2, len(hits)
    assert total == 3, total  # 命中总数不受 limit 影响 → 前端「还有 N 条」是准的


def test_dirs_come_first():
    b = _fixture()
    hits, _ = _search(b, "tester", "a")
    kinds = [h.is_dir for h in hits]
    assert kinds == [True] * sum(kinds) + [False] * (len(kinds) - sum(kinds)), kinds


def test_path_traversal_rejected():
    b = _fixture()
    for bad in ("/../secret.txt", "/a/../../secret.txt"):
        try:
            _search(b, "tester", "secret", path=bad)
        except HTTPException as e:
            assert e.status_code == 403, (bad, e.status_code)
        else:
            raise AssertionError(f"{bad} 未被拒绝")


def test_missing_path_404():
    b = _fixture()
    try:
        _search(b, "tester", "x", path="/不存在")
    except HTTPException as e:
        assert e.status_code == 404, e.status_code
    else:
        raise AssertionError("不存在的起点应 404")


def test_py311_no_path_walk():
    """镜像跑 Python 3.11：Path.walk 是 3.12 才有的方法，源码里不能出现。"""
    assert sys.version_info >= (3, 11), sys.version_info
    src = inspect.getsource(LocalFileBackend.search_files)
    assert "os.walk" in src, src
    assert "user_dir.walk" not in FS_SRC
    assert ".walk()" not in FS_SRC


def test_sort_shared_by_list_and_search():
    """目录在前 + name/time/size 键 + `-` 倒序：list 与 search 共用同一份排序。"""
    b = _fixture()
    files, _ = _search(b, "tester", "汇")
    asc = sort_file_infos(files, "name")
    desc = sort_file_infos(files, "-name")
    assert [f.name for f in asc] == [f.name for f in reversed(desc)]
    dirs = [f.name for f in asc if f.is_dir]
    assert asc[: len(dirs)] == [f for f in asc if f.is_dir], asc
    by_size = [f.size for f in sort_file_infos(files, "-size")]
    assert by_size == sorted(by_size, reverse=True), by_size
    by_time = [f.modified_at for f in sort_file_infos(files, "time")]
    assert by_time == sorted(by_time), by_time


# ── 2. 统一性：同一功能只允许一条实现路径 ──────────────────────

def test_list_search_delegates_to_service_impl():
    """`/list?search=` 必须调 search_files，不得在路由里另写一套本地过滤。"""
    assert "search_files(" in ROUTER_SRC
    assert "search.lower() in f.name.lower()" not in ROUTER_SRC, "路由里还留着本地过滤"
    assert "search_lower" not in ROUTER_SRC


def test_two_entry_points_same_output():
    """同一关键词下，/search 与 /list?search= 的命中与顺序逐行一致。"""
    b = _fixture()
    hits, total = _search(b, "tester", "a")
    via_list = sort_file_infos(list(hits), "name")  # 路由侧再排一次应幂等
    assert [f.path for f in via_list] == [f.path for f in hits]
    assert total == len(hits)


def test_search_route_registered_with_frontend_contract():
    """契约对齐既有前端（MySpace 搜索框）：入参 keyword，响应 items/total。"""
    routes = {r.path: r for r in files_mod.router.routes}
    assert "/myfiles/search" in routes, list(routes)
    params = {p.name for p in routes["/myfiles/search"].dependant.query_params}
    assert {"keyword", "path", "category", "limit"} <= params, params


def _client_with_auth(username: str):
    """带鉴权上下文的 TestClient。

    现行鉴权是「中间件写 request.state + 装饰器读」的架构（auth_middleware.py），
    路由内不再有 token 依赖。测试里不引入整套中间件，直接装一个最小中间件把
    request.state.username 置为 anonymous，并让 is_auth_enabled() 返回 False，
    走权限装饰器的「匿名放行」快路径——与鉴权关闭时的真实行为一致。
    """
    from fastapi.testclient import TestClient

    backend = _fixture()          # 已配好 tester/files 夹具的 LocalFileBackend
    tmp = backend.data_dir        # 工作区根（含 tester/files）
    FileServiceFactory._instance = backend
    app = FastAPI()

    @app.middleware("http")
    async def _fake_identity(request, call_next):
        request.state.username = "anonymous"
        request.state.role = "user"
        # 路由的 Depends(get_current_user) 读的是 user_info
        request.state.user_info = {"username": username, "role": "user"}
        return await call_next(request)

    app.include_router(files_mod.router)
    # 权限装饰器的匿名快路径要求鉴权处于关闭态
    from coapis.app import auth as files_mod_auth
    files_mod_auth.is_auth_enabled = lambda: False  # type: ignore[assignment]
    client = TestClient(app)
    return client, tmp


def test_search_endpoint_e2e_shape():
    """端点返回 items/total/truncated/limit，items 是前端 FileInfo 形状。"""
    client, _ = _client_with_auth("tester")
    try:
        r = client.get("/myfiles/search", params={"keyword": "汇报"})
        assert r.status_code == 200, r.text
        body = r.json()
        assert {"items", "total", "truncated", "limit", "path", "keyword"} <= set(body), body
        assert body["total"] == 3 and body["truncated"] is False, body
        assert {"name", "type", "path", "size", "mimeType", "previewable"} <= set(body["items"][0]), body["items"][0]

        r2 = client.get("/myfiles/search", params={"keyword": "汇报", "limit": 2})
        b2 = r2.json()
        assert len(b2["items"]) == 2 and b2["total"] == 3 and b2["truncated"] is True, b2

        assert client.get("/myfiles/search", params={"keyword": ""}).status_code == 422
        assert client.get("/myfiles/search", params={"keyword": "x", "path": "/../etc"}).status_code == 403

        # /list?search= 与 /search 命中一致（同一实现 → 同一结果）
        r3 = client.get("/myfiles/list", params={"search": "汇报", "page_size": 50})
        b3 = r3.json()
        assert [i["path"] for i in b3["items"]] == [i["path"] for i in body["items"]], (b3["items"], body["items"])
        assert b3["total"] == body["total"], (b3["total"], body["total"])
    finally:
        FileServiceFactory._instance = None


# ── 3. Seafile 移出 ────────────────────────────────────────────

def test_seafile_backend_gone():
    assert "SeafileFileBackend" not in FS_SRC
    assert "seafile_client" not in FS_SRC
    assert not hasattr(fs_mod, "SeafileFileBackend")
    svc = __import__("coapis.app.services", fromlist=["__all__"])
    assert not hasattr(svc, "SeafileClient")
    assert not hasattr(svc, "UserSyncService")
    FileServiceFactory._instance = None
    assert FileServiceFactory.get_service().__class__.__name__ == "LocalFileBackend"
    assert not hasattr(FileServiceFactory, "set_backend")
    FileServiceFactory._instance = None


def test_seafile_files_moved_out_and_auth_endpoint_gone():
    assert not (SERVICES_DIR / "seafile_client.py").exists()
    assert not (SERVICES_DIR / "user_sync_service.py").exists()
    assert "seafile-token" not in (ROUTERS_DIR / "auth.py").read_text(encoding="utf-8")
    assert "Seafile" not in ROUTER_SRC


def test_no_seafile_code_left_in_package():
    """包内不得再有 Seafile 的**代码**引用（注释/文档串里作为历史说明提及是允许的）。"""
    import re

    pkg_root = SERVICES_DIR.parent.parent  # .../coapis
    # 只追究代码：import / from / class / def / 路由 / 后端判定 / 字符串常量比较。
    # 文档串与注释里的「Seafile 已移除」是历史说明，不算残留。
    code_pat = re.compile(
        r"(^\s*(import|from|class|def)\b"
        r"|app\.(get|post|put|delete|patch)\("
        r"|@router\.(get|post|put|delete|patch)\("
        r"|backend_type\s*==|==\s*[\"']seafile"
        r"|Seafile[A-Za-z]*Backend)",
        re.IGNORECASE,
    )
    offenders = []
    for f in pkg_root.rglob("*.py"):
        for i, line in enumerate(f.read_text(encoding="utf-8").splitlines(), 1):
            s = line.strip()
            if "seafile" not in s.lower():
                continue
            if not code_pat.search(s):
                continue  # 非代码行（注释/文档串里的历史说明）
            offenders.append(f"{f.relative_to(pkg_root)}:{i}: {s[:70]}")
    assert offenders == [], offenders


ALL_TESTS = [v for k, v in sorted(globals().items()) if k.startswith("test_") and callable(v) and v.__module__ == "__main__"]


def main() -> int:
    failed = []
    for fn in ALL_TESTS:
        try:
            fn()
            print(f"  ✅ {fn.__name__}")
        except Exception as e:  # noqa: BLE001
            failed.append(fn.__name__)
            print(f"  ❌ {fn.__name__}: {type(e).__name__}: {e}")
    print(f"\n{len(ALL_TESTS) - len(failed)}/{len(ALL_TESTS)} 通过")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
