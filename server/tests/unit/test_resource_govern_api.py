# -*- coding: utf-8 -*-
"""资源台账管理面端点测试（v20 · A 期 · W2/W3/W6 的 API 面）。

覆盖的正是历次返工的重灾区（照 `test_chat_resources_endpoint_b2.py` 的教训）：
1. 列表筛选：**source / 关键词必须在 SQL 里做完**，前端不再补一刀；`total` 跟着
   过滤条件走（分页尺子一致）；非法值当没传——筛选参数永远不能让列表"莫名变空"。
2. 治理动作：定稿/转草稿/归档/软删只动台账，**永不碰磁盘文件**；非法 action 400。
3. 散文件归位（W6 · 拍板 D4）：搬进 `files/_inbox/`，台账 path 与引用跟着搬家；
   系统目录 / 目录本身 / 越界路径进 failed——**没有 delete 这个动作**。
4. 越权：非管理员传 `owner_id` 指定他人 → 一律按自己算，动不到别人工作区。
5. 巡检只报告，不搬不删（G6 铁律，端点层再锁一次）。

跑法（权威口径：权威 compose + 一次性容器）：

    cd coapis-agent && docker compose -f docker/docker-compose.yaml \\
      run --rm -v "$PWD:/app" -w /app server \\
      python -m pytest server/tests/unit/test_resource_govern_api.py -q
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

SERVER_ROOT = Path(__file__).resolve().parents[2]
REPO_ROOT = SERVER_ROOT.parent
for _p in (SERVER_ROOT, REPO_ROOT):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

from fastapi import FastAPI, Request  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from coapis.app import auth as auth_mod  # noqa: E402
from coapis.app.permissions import decorators as perm_mod  # noqa: E402
from coapis.app.routers import files as files_router  # noqa: E402
from coapis.foundation import resource_ledger as ledger_mod  # noqa: E402
from coapis.foundation.resource_ledger import ResourceLedger  # noqa: E402


@pytest.fixture()
def api(tmp_path, monkeypatch):
    """最小 app：files 路由（= /api/myfiles）+ 测试库 + 临时工作区 + 假登录。

    三个桩缺一不可：
    - 权限校验：装饰器在**请求时**调 ``_perform_permission_check``（模块级名字
      查找），所以 patch 这个函数就能让路由照常跑；patch ``require_permission``
      本身没用（装饰在导入时就定型了）。
    - 身份：端点里的 ``get_current_user`` 与各路由内调用的 ``require_admin``
      分处两个命名空间，**两边都要 patch**，否则管理员判定走真鉴权。
    - 工作区根：台账单例换成指向临时目录的实例，测试绝不碰 /apps/ai/coapis。
    """
    from coapis.foundation.db.engine import get_engine, init_engine, reset_engine

    init_engine(f"sqlite+pysqlite:///{tmp_path / 'govern_test.db'}")
    # 建表：register() 把异常吞进 logger.debug，没有表就是"注册成功返回空 + 清单
    # 永远零条"——静默变空的教科书现场，fixture 必须自己把 schema 建起来。
    from coapis.foundation.db.base import BaseRow
    import coapis.foundation.db.models  # noqa: F401  (注册全部模型)

    BaseRow.metadata.create_all(get_engine())

    base = tmp_path / "ws"
    for user in ("alice", "bob"):
        (base / user / "files").mkdir(parents=True)
        (base / user / "knowledge").mkdir(parents=True)

    # 台账把"工作区属于哪个已知用户"当真相：users 表空表时，任何工作区都算
    # 无主（巡检把它记进 unowned 而不是 unledgered）。测试要的是"有主散文件"，
    # 所以先把用户建出来——尺子不对，断言再怎么写都是假的。
    from coapis.foundation.db.engine import get_session
    from coapis.foundation.db.models.user import User

    with get_session() as s:
        for i, name in enumerate(("alice", "bob"), start=1):
            # users.id 是整型主键、非自增（本库惯例），测试必须自己给号。
            s.add(User(id=i, username=name, password_hash="x", salt="x", role="user"))

    ledger = ResourceLedger(workspaces_dir=base)
    monkeypatch.setattr(ledger_mod, "get_resource_ledger", lambda: ledger)

    def _fake_check(request: Request, permission: str) -> None:
        """权限桩：只锁一条真语义——``admin:admin`` 需要管理员角色。

        patch 的是装饰器在**请求时**调用的 ``_perform_permission_check``
        （模块级名字查找，运行时生效）；patch ``require_permission`` 本身没用
        （装饰在导入时就定型了）。其余权限放行，本测试不测权限矩阵。
        """
        from fastapi import HTTPException

        if permission == "admin:admin" and getattr(request.state, "role", "user") != "admin":
            raise HTTPException(status_code=403, detail="需要管理员权限")

    monkeypatch.setattr(perm_mod, "_perform_permission_check", _fake_check)

    def _fake_user(request: Request) -> dict:
        return {
            "username": getattr(request.state, "username", "alice"),
            "role": getattr(request.state, "role", "user"),
        }

    monkeypatch.setattr(files_router, "get_current_user", _fake_user)
    monkeypatch.setattr(auth_mod, "get_current_user", _fake_user)

    app = FastAPI()

    @app.middleware("http")
    async def _fake_auth(request: Request, call_next):
        request.state.username = request.query_params.get("user", "alice")
        request.state.role = request.query_params.get("role", "user")
        return await call_next(request)

    # files 路由自带 /myfiles 前缀（router = APIRouter(prefix="/myfiles")），
    # 这里只补 /api —— 再叠一层 /myfiles 会让所有断言撞 404。
    app.include_router(files_router.router, prefix="/api")
    with TestClient(app) as client:
        yield client
    reset_engine()


def _ledger() -> ResourceLedger:
    return ResourceLedger()


def _seed(owner: str, path: str, **kw) -> str:
    """登记一条台账，返回 resource_key。"""
    return _ledger().register(
        owner_scope="user",
        owner_id=owner,
        kind=kw.get("kind", "file"),
        path=path,
        title=kw.get("title"),
        source=kw.get("source", "hook"),
        path_form=kw.get("path_form", "files_root"),
    )


def _row(key: str) -> dict:
    """台账当前那一行（拿清单当尺子，不去摸 ORM 私有东西）。

    ``owner_scope="all"`` 是按归属者过滤的口径，配 ``owner_id`` 用会查不出东西——
    看某人的台账就用 ``user`` 口径，尺子要选对。
    """
    for item in _ledger().list_resources(owner_scope="user", owner_id="alice",
                                         status=None, limit=200):
        if item["resource_key"] == key:
            return item
    return {}


def _row_including_deleted(key: str) -> dict:
    """软删行不出清单，读原始状态直接查表。"""
    from coapis.foundation.db.engine import get_session
    from coapis.foundation.db.models.resources import Resource

    with get_session() as s:
        row = s.query(Resource).filter(Resource.resource_key == key).one()
        return {"status": row.status, "path": row.path, "version": row.version,
                "category": row.category}


def _list(client: TestClient, **params) -> dict:
    q = "&".join(f"{k}={v}" for k, v in params.items() if v not in (None, ""))
    resp = client.get(f"/api/myfiles/resources?{q}")
    assert resp.status_code == 200, resp.text
    return resp.json()


# ── 1. 列表筛选（W2 五维里后端承担的两维 + 关键词）──────────────


def test_list_filters_source_and_keyword(api):
    _seed("alice", "files/plan_a.md", source="hook", title="季度计划")
    _seed("alice", "files/gen_b.md", source="turn:msg_1", title="生成的报告")
    _seed("alice", "files/old.txt", source="backfill", title="补登记")

    assert len(_list(api)["items"]) == 3, "全量应当三条"

    by_source = _list(api, source="hook")
    assert [i["path"] for i in by_source["items"]] == ["files/plan_a.md"], \
        "source 过滤必须在 SQL 里做完"
    assert by_source["total"] == 1, "total 必须跟着过滤条件走（分页尺子一致）"

    # 前缀匹配：turn:msg_1 / turn:msg_2 都算「本轮产出」
    _seed("alice", "files/gen_c.md", source="turn:msg_2", title="第二份")
    turns = _list(api, source="turn")
    assert sorted(i["path"] for i in turns["items"]) == ["files/gen_b.md", "files/gen_c.md"]

    # 关键词：不区分大小写，名称与路径都参与匹配
    assert [i["path"] for i in _list(api, q="PLAN")["items"]] == ["files/plan_a.md"], \
        "关键词应在名称/路径上做大小写不敏感的包含匹配"
    assert [i["path"] for i in _list(api, q="生成")["items"]] == ["files/gen_b.md"]

    # 非法值当没传：筛选参数永远不能让列表"莫名变空"
    assert len(_list(api, source="不存在的来源")["items"]) == 4
    assert len(_list(api, category="不存在的类别")["items"]) == 4


# ── 2. 治理动作（W3 定稿入口的后端半边）────────────────────────


def test_govern_publish_and_undo_touch_only_ledger(api):
    key = _seed("alice", "files/plan_a.md", title="季度计划")

    resp = api.patch(f"/api/myfiles/resources/{key}",
                     params={"user": "alice"}, json={"action": "publish"})
    assert resp.status_code == 200, resp.text
    assert resp.json()["status"] == "official", resp.json()
    assert _row_including_deleted(key)["status"] == "official", "定稿即进 official"
    assert _row_including_deleted(key)["version"] >= 1, "定稿要有版本徽标"

    resp2 = api.patch(f"/api/myfiles/resources/{key}",
                      params={"user": "alice"}, json={"action": "to_draft"})
    assert resp2.status_code == 200, resp2.text
    assert _row_including_deleted(key)["status"] == "draft", "撤销定稿回草稿"

    # 非法动作必须 400，且不许留下半截状态
    resp3 = api.patch(f"/api/myfiles/resources/{key}",
                      params={"user": "alice"}, json={"action": "explode"})
    assert resp3.status_code == 400, resp3.text
    assert _row_including_deleted(key)["status"] == "draft"


def test_govern_soft_delete_keeps_file(api, tmp_path):
    """软删语义：台账标 deleted，磁盘文件必须原样留着。"""
    real = tmp_path / "ws" / "alice" / "files"
    (real / "keep.md").write_text("内容", encoding="utf-8")
    key = _seed("alice", "files/keep.md", title="要留下的文件")

    resp = api.patch(f"/api/myfiles/resources/{key}",
                     params={"user": "alice"}, json={"action": "delete"})
    assert resp.status_code == 200, resp.text
    assert _row_including_deleted(key)["status"] == "deleted"
    assert (real / "keep.md").exists(), "软删绝不动磁盘文件"
    # 清单只给活资源
    assert key not in [i["resource_key"] for i in _list(api)["items"]]


# ── 3. 散文件归位（W6 · 拍板 D4）───────────────────────────────


def test_inbox_moves_file_and_reledgers(api, tmp_path):
    base = tmp_path / "ws" / "alice"
    (base / "loose.md").write_text("散文件", encoding="utf-8")
    key = _seed("alice", "loose.md", source="reconcile", title="散文件",
                path_form="workspace")
    _ledger().attach_ref(resource_key=key, referrer_kind="chat",
                         referrer_id="c1", role="reference")

    resp = api.post("/api/myfiles/resources/inbox",
                    params={"user": "alice"}, json={"paths": ["loose.md"]})
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["moved_count"] == 1, body
    assert not (base / "loose.md").exists(), "原位置不该留文件"
    moved = base / "files" / "_inbox" / "loose.md"
    assert moved.exists(), "必须搬进 files/_inbox/（拍板 D4）"
    assert moved.read_text(encoding="utf-8") == "散文件", "搬家不许改内容"

    # 搬家是"文件+台账+引用"三件事一起搬。尺子用路径：归位会把台账重新登记到
    # files/_inbox/ 口径，注册时那个 key 不是稳定标识。
    by_chat = _ledger().list_resources(owner_scope="user", owner_id="alice",
                                       chat_id="c1", limit=50)
    assert len(by_chat) == 1, f"搬家后引用必须还认得：{by_chat}"
    assert by_chat[0]["path"] == "files/_inbox/loose.md", by_chat
    # 类别 = 内容类别注册表（按扩展名，词表是 doc/sheet/pdf/image/…），
    # 不是目录名：.md → doc。前端下拉必须读 /resources/categories，别自己编词。
    from coapis.foundation.resource_category import VALID_CATEGORIES

    assert by_chat[0]["category"] in VALID_CATEGORIES, by_chat
    assert by_chat[0]["category"] == "doc", by_chat


def test_inbox_refuses_system_dirs_and_registered_files(api, tmp_path):
    base = tmp_path / "ws" / "alice"
    (base / ".memory").mkdir()
    (base / ".memory" / "x.md").write_text("记忆", encoding="utf-8")
    # 已在位登记的文件：归位无事可做（它是聊天正在引用的活资源，
    # 被勾一下就搬家 = 把引用源挪位置 = 用户视角"文件凭空消失"）
    (base / "files" / "normal.md").write_text("正常", encoding="utf-8")
    _seed("alice", "files/normal.md", title="在位文件")

    resp = api.post("/api/myfiles/resources/inbox", params={"user": "alice"},
                    json={"paths": [".memory/x.md", "files/normal.md", "files",
                                    "../escape.md", ""]})
    assert resp.status_code == 200, resp.text
    body = resp.json()
    refused = {f["path"] for f in body["failed"]} | {s["path"] for s in body["skipped"]}
    # 系统目录：skip 或 fail 都算"没动它"，实现走哪条都认——但文件必须原样在
    assert ".memory/x.md" in refused, f"系统目录不许动（拍板 D4）：{body}"
    assert "files/normal.md" in refused, f"在位登记文件不搬：{body}"
    assert "files" in refused, f"目录本身不搬：{body}"
    assert "../escape.md" in refused, f"越界路径拒绝：{body}"
    assert (base / ".memory" / "x.md").exists(), "系统目录里的文件必须原样在"
    assert (base / "files" / "normal.md").exists(), "在位文件不许被扫进收件箱"
    assert body["moved_count"] == 0, f"一次都不该搬：{body}"


def test_inbox_owner_isolation(api, tmp_path):
    """非管理员传 owner_id 指定他人 → 一律按自己算，动不到别人工作区。"""
    bob = tmp_path / "ws" / "bob"
    (bob / "loose.md").write_text("鲍勃的文件", encoding="utf-8")

    resp = api.post("/api/myfiles/resources/inbox", params={"user": "alice"},
                    json={"paths": ["loose.md"], "owner_id": "bob"})
    assert resp.status_code == 200, resp.text
    assert (bob / "loose.md").exists(), "普通用户动不到别人的工作区"
    assert not (bob / "files" / "_inbox" / "loose.md").exists()
    assert resp.json()["moved_count"] == 0, resp.json()

    # 管理员代他人归位：合法，搬的是别人的文件
    resp2 = api.post("/api/myfiles/resources/inbox",
                     params={"user": "root", "role": "admin"},
                     json={"paths": ["loose.md"], "owner_id": "bob"})
    assert resp2.status_code == 200, resp2.text
    assert resp2.json()["moved_count"] == 1, resp2.json()
    assert (bob / "files" / "_inbox" / "loose.md").exists()
    assert not (bob / "loose.md").exists()


def test_inbox_requires_paths(api):
    resp = api.post("/api/myfiles/resources/inbox",
                    params={"user": "alice"}, json={"paths": []})
    assert resp.status_code == 400, resp.text


# ── 4. 巡检只报告，不搬不删（G6 铁律，端点层再锁一次）──────────


def test_sweep_reports_only(api, tmp_path):
    # 巡检扫的是 **files/ 根**（台账口径 "files/x" ↔ 扫描口径 "x"），散文件要放在
    # files/ 根下才看得见；先给 alice 一条活记录当归属者锚点。
    _seed("alice", "files/anchor.md", title="锚点")
    (tmp_path / "ws" / "alice" / "files" / "loose2.md").write_text("散", encoding="utf-8")
    resp = api.post("/api/myfiles/resources/sweep",
                    params={"user": "root", "role": "admin"})
    assert resp.status_code == 200, resp.text
    rep = resp.json()
    assert "loose2.md" in {i["path"] for i in rep["unledgered_list"]}, rep
    assert rep.get("unledgered") >= 1, rep
    assert (tmp_path / "ws" / "alice" / "files" / "loose2.md").exists(), "巡检不许搬文件"


def test_sweep_is_admin_only(api):
    resp = api.post("/api/myfiles/resources/sweep", params={"user": "alice"})
    assert resp.status_code == 403, "巡检是管理员动作（拍板 D6）"
