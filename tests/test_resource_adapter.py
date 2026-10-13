# -*- coding: utf-8 -*-
"""资源契约 · 消费面（ResourceAdapter）验收测试。

逐条对齐方案文档 A3.3 与闸门 0 冻结清单的 DoD：

  1. **签名冻结**：ABC 与五个适配器实现签名一致（不得增删参数）；
  2. **只读方向**：消费面读清单面，不改写；台账优先、FS 补扫；
  3. **多用户隔离**：命中带 owner_id，跨用户不串（吸取 memories 事故）；
  4. **路径遍历防护**：``..`` / 绝对路径 / 越出 owner 根一律拒绝；
  5. **脱敏**：db 的 salt/token 列、mcp 的 URL query 与 env 不得出现在输出；
  6. **自动缺席**：知识库为空时 kb 面不出现在可用面里（不是兜底，是设计）；
  7. **路由**：scope 单面 / scope 空并发全查 + source 标签 / 空 query = 发现模式；
  8. **fire-and-forget**：任何一面挂了都不抛异常，只记 errors。

独立运行：python tests/test_resource_adapter.py
"""

import asyncio
import inspect
import json
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "server"))

RESULTS: list = []


def check(name: str, cond: bool, detail: str = ""):
    RESULTS.append((name, bool(cond), detail))
    print(f"[{'PASS' if cond else 'FAIL'}] {name}" + (f"  ({detail})" if detail and not cond else ""))


def _setup():
    tmp = Path(tempfile.mkdtemp(prefix="resource_adapter_"))
    (tmp / "system").mkdir(parents=True)
    db_path = tmp / "system" / "coapis.db"

    from coapis.foundation.db.base import BaseRow
    from coapis.foundation.db.engine import get_engine, init_engine

    import coapis.foundation.db.models  # noqa: F401  (registers all models)

    init_engine(f"sqlite:///{db_path}")
    BaseRow.metadata.create_all(get_engine())

    ws = tmp / "workspaces"
    for u in ("alice", "bob"):
        (ws / u / "files").mkdir(parents=True)

    # file_adapter 在调用时读 coapis.constant.WORKSPACES_DIR，所以改模块属性即可
    import coapis.constant as constant

    constant.WORKSPACES_DIR = ws

    # 建两张表用于 db 面测试：test_users 带敏感列，report_rows 普通表
    # （刻意不碰模型自带的 users 表——它有 NOT NULL 约束，raw SQL 插不进去）
    from sqlalchemy import text

    with get_engine().connect() as conn:
        conn.execute(text('CREATE TABLE test_users (id INTEGER PRIMARY KEY, username TEXT, salt TEXT, api_key TEXT)'))
        conn.execute(text("INSERT INTO test_users (username, salt, api_key) VALUES ('alice','SALT-LEAK-ME','sk-SECRET')"))
        conn.execute(text("CREATE TABLE report_rows (id INTEGER PRIMARY KEY, quarter TEXT, amount REAL)"))
        conn.execute(text("INSERT INTO report_rows (quarter, amount) VALUES ('Q3', 42)"))
        conn.commit()

    return tmp, ws


def _ctx(user: str, ws: Path):
    from coapis.config.session_context import set_session_context

    set_session_context(
        user_id=user,
        session_id=f"console:{user}",
        channel="console",
        username=user,
        workspace_dir=ws / user,
    )


def main():
    tmp, ws = _setup()

    from coapis.agents.resources.contract import (
        Content,
        Hit,
        ResourceAdapter,
        ResourceMeta,
        score_match,
    )
    from coapis.agents.resources.db_adapter import DbAdapter
    from coapis.agents.resources.file_adapter import FileAdapter
    from coapis.agents.resources.kb_adapter import KbAdapter
    from coapis.agents.resources.mcp_adapter import McpAdapter
    from coapis.agents.resources.web_adapter import WebAdapter

    # ── 1. 签名冻结 ────────────────────────────────────────────────
    abc_sig = {
        "discover": ("self",),
        "search": ("self", "query", "limit"),
        "fetch": ("self", "ref"),
    }
    for meth, params in abc_sig.items():
        got = tuple(inspect.signature(getattr(ResourceAdapter, meth)).parameters)
        check(f"ABC 签名冻结 {meth}", got == params, f"{got} != {params}")

    for ad in (FileAdapter, DbAdapter, KbAdapter, McpAdapter, WebAdapter):
        for meth, params in abc_sig.items():
            got = tuple(inspect.signature(getattr(ad, meth)).parameters)
            check(f"{ad.name}.{meth} 签名与 ABC 一致", got == params, f"{got} != {params}")

    # ── 2. 中文打分 ────────────────────────────────────────────────
    check("整串命中得满分", score_match("季度报表", "季度报表模板") == 1.0)
    check("CJK bigram 捞到部分命中", score_match("报表", "季度报表模板") > 0.5)
    check("无关词得 0 分", score_match("zzz", "季度报表模板") == 0.0)

    # ── 3. file 面：台账优先 + FS 补扫 ─────────────────────────────
    from coapis.foundation.resource_ledger import ResourceLedger

    rl = ResourceLedger(workspaces_dir=ws)
    fa = FileAdapter(ledger=rl)

    p = ws / "alice" / "files" / "季度报表.md"
    p.write_text("Q3 营收 42 万元。", encoding="utf-8")
    key_a = rl.register(kind="file", owner_scope="user", owner_id="alice", path="季度报表.md", title="季度报表")
    rl.attach_ref(resource_key=key_a, referrer_kind="chat", referrer_id="c1")
    (ws / "alice" / "files" / "notes.md").write_text("未入台账的笔记", encoding="utf-8")

    _ctx("alice", ws)
    metas = asyncio.run(fa.discover())
    ledgered = [m for m in metas if m.extra.get("ledgered")]
    unledgered = [m for m in metas if not m.extra.get("ledgered")]
    check("台账行进入发现面", len(ledgered) == 1, f"{len(ledgered)}")
    check("FS 补扫捞到未入台账的文件", len(unledgered) == 1, f"{len(unledgered)}")
    check("未入台账标 status=unledgered", unledgered and unledgered[0].status == "unledgered")

    hits = asyncio.run(fa.search("季度报表", 10))
    check("file 检索命中台账行", hits and hits[0].meta.ref == "季度报表.md", f"{hits[:1]}")

    content = asyncio.run(fa.fetch("季度报表.md"))
    check("file fetch 取到正文", "42 万元" in content.text, f"{content.text[:40]}")

    bad = asyncio.run(fa.fetch("../bob/files/notes.md"))
    check("file fetch 拒绝 .. 逃逸", bad.text == "" and "error" in bad.meta, f"{bad.meta}")

    # ── 4. 多用户隔离 ──────────────────────────────────────────────
    pb = ws / "bob" / "files" / "季度报表.md"
    pb.write_text("bob 的报表", encoding="utf-8")
    key_b = rl.register(kind="file", owner_scope="user", owner_id="bob", path="季度报表.md", title="季度报表")
    rl.attach_ref(resource_key=key_b, referrer_kind="chat", referrer_id="c2")

    _ctx("alice", ws)
    a_hits = asyncio.run(fa.search("季度报表", 10))
    check("alice 只看到自己的资源", all(h.meta.owner_id == "alice" for h in a_hits), f"{[h.meta.owner_id for h in a_hits]}")

    _ctx("bob", ws)
    b_hits = asyncio.run(fa.search("季度报表", 10))
    check("bob 只看到自己的资源", all(h.meta.owner_id == "bob" for h in b_hits), f"{[h.meta.owner_id for h in b_hits]}")

    # ── 5. db 面：发现 / 检索 / 脱敏 ───────────────────────────────
    _ctx("alice", ws)
    da = DbAdapter()
    db_metas = asyncio.run(da.discover())
    names = {m.ref for m in db_metas}
    check("db 发现列出表", {"test_users", "report_rows", "resources"} <= names, f"{sorted(names)}")

    db_hits = asyncio.run(da.search("test_users", 10))
    check("db 检索命中表名", db_hits and db_hits[0].meta.ref == "test_users", f"{db_hits[:1]}")

    db_content = asyncio.run(da.fetch("test_users"))
    check("db fetch 脱敏 salt", "SALT-LEAK-ME" not in db_content.text and '"salt": "***"' in db_content.text, f"{db_content.text[:160]}")
    check("db fetch 脱敏 api_key", "sk-SECRET" not in db_content.text, f"{db_content.text[:160]}")
    check("db fetch 带结构摘要", "row_count" in db_content.text)

    check("db fetch 拒绝不存在的表", asyncio.run(da.fetch("nope")).meta.get("error") is not None)

    # ── 6. kb 面：自动缺席 + 命中 ─────────────────────────────────
    import coapis.agents.resources.kb_adapter as kb_mod

    kb_root = tmp / "kb"
    (kb_root / "general" / "research").mkdir(parents=True)
    (kb_root / "general" / "research" / "定价策略.md").write_text(
        "# 定价\n季度报表口径以营收为准。\n", encoding="utf-8"
    )
    kb_mod._kb_root = lambda: kb_root
    kb = KbAdapter()
    check("kb 有内容时可用", kb.available())
    kb_metas = asyncio.run(kb.discover())
    check("kb 发现含分类与文档", any(m.status == "category" for m in kb_metas) and any(m.status == "doc" for m in kb_metas))
    kb_hits = asyncio.run(kb.search("季度报表", 10))
    check("kb 检索命中正文", kb_hits and kb_hits[0].meta.ref.endswith("定价策略.md"), f"{kb_hits[:1]}")
    check("kb 命中带 snippet", kb_hits and "季度报表" in kb_hits[0].snippet, f"{kb_hits[:1]}")
    check("kb fetch 拒绝 ..", asyncio.run(kb.fetch("../etc/passwd")).meta.get("error") is not None)

    empty_kb = tmp / "kb_empty"
    empty_kb.mkdir()
    kb_mod._kb_root = lambda: empty_kb
    check("kb 空库时自动缺席", not kb.available())
    kb_mod._kb_root = lambda: kb_root

    # ── 7. mcp 面：发现 + 脱敏 ────────────────────────────────────
    _ctx("alice", ws)
    (ws / "alice" / "agent.json").write_text(
        json.dumps(
            {
                "mcp": {
                    "clients": {
                        "mcp-server-oa": {
                            "name": "oa",
                            "enabled": True,
                            "transport": "streamable_http",
                            "url": "http://oa.internal/mcp?token=SECRET-TOKEN",
                            "headers": {"Authorization": "Bearer SECRET"},
                        },
                        "tavily_search": {
                            "name": "tavily",
                            "enabled": False,
                            "transport": "stdio",
                            "command": "npx",
                            "args": ["-y", "tavily-mcp"],
                            "env": {"TAVILY_API_KEY": "SECRET"},
                        },
                    }
                }
            }
        ),
        encoding="utf-8",
    )
    ma = McpAdapter()
    mcp_metas = asyncio.run(ma.discover())
    check("mcp 发现列出服务", len(mcp_metas) == 2, f"{len(mcp_metas)}")
    blob = json.dumps([m.to_dict() for m in mcp_metas], ensure_ascii=False)
    check("mcp 发现不泄露 URL token", "SECRET-TOKEN" not in blob, f"{blob[:160]}")
    check("mcp 发现不泄露 headers/env", "Bearer SECRET" not in blob and "SECRET" not in blob, f"{blob[:160]}")
    mcp_hits = asyncio.run(ma.search("oa", 10))
    check("mcp 检索命中服务", mcp_hits and mcp_hits[0].meta.ref == "mcp-server-oa", f"{mcp_hits[:1]}")
    mcp_content = asyncio.run(ma.fetch("mcp-server-oa"))
    check("mcp fetch 仍脱敏", "SECRET" not in mcp_content.text, f"{mcp_content.text[:160]}")

    # ── 8. 路由：scope / 全查 / 发现模式 ──────────────────────────
    from coapis.agents.resources import registry as reg

    reg.register_defaults()
    names = reg.available_adapters()
    check("可用面含 file/db/kb/mcp", {"file", "db", "kb", "mcp"} <= set(names), f"{names}")

    # web 面在测试里不打真网络，打桩
    async def _stub_search(self, query, limit=10):
        return [
            Hit(
                meta=ResourceMeta(kind="web", ref="http://x/1", title=f"web-{query}", summary="web"),
                score=0.4,
                snippet="stub",
            )
        ]

    WebAdapter.search = _stub_search  # type: ignore[assignment]

    merged = asyncio.run(reg.search(None, "季度报表", 10))
    srcs = {h["source"] for h in merged["hits"]}
    check("全查结果带 source 标签", {"file", "kb", "web"} <= srcs, f"{srcs}")
    check("全查按 score 降序", [h["score"] for h in merged["hits"]] == sorted([h["score"] for h in merged["hits"]], reverse=True))

    scoped = asyncio.run(reg.search("kb", "季度报表", 10))
    check("scope 单面只查该面", all(h["source"] == "kb" for h in scoped["hits"]), f"{[h['source'] for h in scoped['hits']]}")

    bad_scope = asyncio.run(reg.search("nope", "x", 10))
    check("不可用的 scope 记 errors", bad_scope["errors"].get("nope"), f"{bad_scope['errors']}")

    disc = asyncio.run(reg.search("file", "", 10))
    check("空 query 走发现模式", disc["mode"] == "discover" and len(disc["hits"]) >= 2, f"{disc['mode']} {len(disc['hits'])}")

    # ── 9. fire-and-forget ────────────────────────────────────────
    import coapis.agents.resources.db_adapter as db_mod

    def _boom(*_a, **_k):
        raise RuntimeError("engine down")

    orig_engine = db_mod._engine
    db_mod._engine = _boom
    check("db 面挂了返回空、不抛", asyncio.run(DbAdapter().search("users", 10)) == [])
    db_mod._engine = orig_engine

    # 适配器内部已 fire-and-forget（_table_names 吞异常），所以注册表这一层
    # 要单独验证"某面抛异常时只记 errors、不抛、其他面照常命中"。
    reg_db = reg.ADAPTERS["db"]
    orig_db_search = reg_db.search

    async def _raise(self, query, limit=10):
        raise RuntimeError("模拟面崩溃")

    reg_db.search = _raise.__get__(reg_db)
    merged2 = asyncio.run(reg.search(None, "季度报表", 10))
    check("注册表吞掉单面异常并记 errors", "db" in merged2["errors"], f"{merged2['errors']}")
    check("单面挂了仍有其他面命中", any(h["source"] == "file" for h in merged2["hits"]), f"{merged2['hits'][:1]}")
    reg_db.search = orig_db_search

    # ── 10. 工具层形状 ────────────────────────────────────────────
    from coapis.agents.tools.resource_search import resource_search

    _ctx("alice", ws)
    tool_res = asyncio.run(resource_search(scope="file", query="季度报表", limit=5))
    check(
        "工具返回统一形状",
        {"mode", "scope", "query", "hits", "sources", "total", "hint"} <= set(tool_res),
        f"{sorted(tool_res)}",
    )
    check("工具命中带 source", tool_res["hits"] and tool_res["hits"][0]["source"] == "file")

    # ── 汇总 ──────────────────────────────────────────────────────
    passed = sum(1 for _, ok, _ in RESULTS if ok)
    print(f"\n{'=' * 60}\nPASS {passed}/{len(RESULTS)}")
    for name, ok, detail in RESULTS:
        if not ok:
            print(f"  FAIL {name}: {detail}")
    return 0 if passed == len(RESULTS) else 1


if __name__ == "__main__":
    sys.exit(main())
