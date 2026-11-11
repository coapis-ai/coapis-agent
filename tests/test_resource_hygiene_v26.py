#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""v26 · 聊天资源卫生（F1-F5）：系统文件不入账、幽灵行不进清单、本轮按轮筛。

小蜜蜂 2026-11-10 报的问题："聊天中的资源包含有不存在的文件，甚至包含系统
文件（SKILL.md、HEARTBEAT.md），而且这些并非会话产出。" 实测 dev 台账 113 条
可见行里只有 46% 合格（/var/log 日志 52 行、/tmp 探针 11 行、HEARTBEAT.md 8 行、
.skills/*/SKILL.md 16 行、.temp/probe 81 行…）。修的是**五件事**：

  F1 一把尺子（``resource_category.is_system_path``）——什么才算用户手里的
     资源；采集闸门（``_normalize_file_path``）生效。
  F2 会话收尾补扫只认交付目录（旧口径 rglob 全扫 → HEARTBEAT.md/每日笔记入账）。
  F3 巡检清存量：路径不是用户资源的行软删（判据与 F1 同一把尺子）。
  F4 读面兜底：``fs_present=0`` 的行不进聊天侧清单（不等 TTL）；
     TTL 36h→2h、巡检从每天一轮改成 30 分钟一轮。
  F5 「本轮」按轮筛：``resource_refs.turn_id`` 落地，本轮面只看本轮触及的资源。

跑法：``python tests/test_resource_hygiene_v26.py``
"""

from __future__ import annotations

import os
import sys
import tempfile
import time
from pathlib import Path

os.environ["COAPISRunningMode"] = "test"

_ROOT = Path(__file__).resolve().parents[1]
for _p in (str(_ROOT), str(_ROOT / "server")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from sqlalchemy import func, select

from coapis.agents.context.reference_collector import _normalize_file_path
from coapis.foundation.db.base import BaseRow
from coapis.foundation.db.engine import get_engine, get_session, init_engine
from coapis.foundation.db.models.resources import Resource, ResourceRef
from coapis.foundation.db.models.user import User
from coapis.foundation.resource_category import is_system_path
from coapis.foundation.resource_ledger import ResourceLedger, make_resource_key

_FAILED = 0
_L: ResourceLedger = None  # type: ignore[assignment]


def check(name: str, cond: bool, extra: str = "") -> bool:
    global _FAILED
    if cond:
        print(f"  ✓ {name}")
        return True
    _FAILED += 1
    print(f"  ✗ {name}  {extra}")
    return False


def key_of(username: str, path: str) -> str:
    return make_resource_key("user", username, "file", path)


def rows(chat_id: str, username: str, **kw) -> list[dict]:
    return _L.list_resources_for_chat(
        owner_scope="user", owner_id=username, chat_id=chat_id, **kw
    )


def paths_of(chat_id: str, username: str, **kw) -> set[str]:
    return {str(r.get("path")) for r in rows(chat_id, username, **kw)}


def turn_of(username: str, path: str) -> str:
    with get_session() as s:
        r = s.execute(
            select(ResourceRef)
            .where(ResourceRef.resource_key == key_of(username, path))
            .where(ResourceRef.referrer_kind == "chat")
        ).scalar_one_or_none()
        return str(r.turn_id) if r and r.turn_id else ""


def add_user(user_id: str) -> None:
    with get_session() as s:
        if s.get(User, user_id) is None:
            s.add(
                User(
                    id=user_id,
                    username=user_id,
                    password_hash="x",
                    salt="y",
                    role="member",
                    created_at=time.time(),
                )
            )


def reg(username: str, path: str, *, role: str = "producer", turn_id: str = "") -> None:
    _L.register(
        owner_scope="user",
        owner_id=username,
        kind="file",
        path=path,
        title=Path(path).name,
        source=f"turn:{'write_file' if role == 'producer' else 'read_file'}",
        path_form="workspace",
    )


def attach(username: str, path: str, chat_id: str, *, role: str = "producer",
           turn_id: str = "") -> None:
    _L.attach_ref(
        resource_key=key_of(username, path),
        referrer_kind="chat",
        referrer_id=chat_id,
        role=role,
        turn_id=turn_id,
    )


def legacy_row(username: str, path: str, *, chat_id: str = "chat-sys",
               role: str = "reference") -> None:
    """**直插**一条台账行，绕开 ``register`` 的登记闸门。

    治理功能上线前库里躺着的老行就是这么来的：登记闸门收口后 ``register``
    不再接受系统路径，存量只能直插模拟——这正是要验收的场景（老行必须被
    巡检清掉，且清掉后不再复活）。
    """
    from coapis.foundation.db.models.resources import make_resource_key

    with get_session() as s:
        s.merge(
            Resource(
                resource_key=make_resource_key("user", username, "file", path),
                owner_scope="user",
                owner_id=username,
                kind="file",
                path=path,
                title=Path(path).name,
                status="active",
                fs_present=1,
                source="legacy",
            )
        )
    attach(username, path, chat_id, role=role)


# ── F1 尺子本体 ───────────────────────────────────────────────────────


def _case_ruler() -> None:
    print("F1 · 系统路径尺子 is_system_path（台账口径=工作区相对）")
    yes = [
        "/tmp/probe_707.py",
        "/var/log/coapis.log",
        "C:/Users/x/MEMORY.md",
        "~/MEMORY.md",
        "https://example.com/a.pdf",
        "HEARTBEAT.md",
        "HEARTBEAT.local.md",
        "MEMORY.md",
        "PROFILE.md",
        "SOUL.md",
        "AGENTS.md",
        ".skills/foo/SKILL.md",
        "skills/foo/SKILL.md",
        "memory/2026-11-08.md",
        ".temp/probe.py",
        ".trash/x.md",
        "files/.temp/probe.py",
        "files/node_modules/x.js",
        "files/MEMORY.md",
        # v26 · F1 补（2026-11-11 实测）：交付区里的平台状态文件
        "files/.session_dirs.json",
        "files/.session_dirs.lock",
        "media/docs/.nojekyll",
        # v26 · F1 补（2026-11-11 实测）：采集器把网页链接登记成了 file 行
        "files/http://www.baidu.com/link?url=abc",
        "http://www.baidu.com/link?url=abc",
        ".bootstrap_completed",
        "",
    ]
    for raw in yes:
        check(f"判系统：{raw!r}", is_system_path(raw))
    no = [
        "files/report.md",
        "files/sub/dir/report.md",
        "media/photo.png",
        "output/x.zip",
        "downloads/x.csv",
        "uploads/x.txt",
        "files/proj/MEMORY.md",
        "files/notes/HEARTBEAT.md",
        "files/report.v2.final.md",
        "media/docs/index.html",
    ]
    for raw in no:
        check(f"判用户资源：{raw!r}", not is_system_path(raw))
    check(
        "非 file 类不判（web/kb 交各自口径）",
        not is_system_path("https://x/", kind="web")
        and not is_system_path("kb/entry", kind="kb_entry"),
    )
    # 登记闸门口径（bare_top_file_ok=True）：工作区根上的散文件必须放行，
    # 系统目录/交付区根同名文件照样拦。
    gate = lambda x: is_system_path(x, bare_top_file_ok=True)
    check(
        "登记闸门放行工作区根上的散文件（归位收件箱靠它）",
        not gate("loose.md") and not gate("a.md") and not gate("报告.md"),
    )
    check(
        "散文件在聊天读面依旧隐形（默认口径不变）",
        is_system_path("loose.md"),
    )
    check(
        "登记闸门下系统目录与交付区根同名文件照样拦",
        gate(".memory/x.md")
        and gate(".skills/demo/SKILL.md")
        and gate("files/MEMORY.md")
        and gate("files/.session_dirs.json"),
    )


def _case_collector_gate(ws: Path) -> None:
    print("F1 · 采集闸门：系统文件 read_file 也不入账")
    alice = ws / "alice"
    (alice / "HEARTBEAT.md").write_text("心跳", encoding="utf-8")
    (alice / "MEMORY.md").write_text("长期记忆", encoding="utf-8")
    sk = alice / ".skills" / "foo"
    sk.mkdir(parents=True, exist_ok=True)
    (sk / "SKILL.md").write_text("技能定义", encoding="utf-8")
    skills = alice / "skills" / "bar"
    skills.mkdir(parents=True, exist_ok=True)
    (skills / "SKILL.md").write_text("技能定义", encoding="utf-8")
    fd = alice / "files"
    (fd / "sub").mkdir(parents=True, exist_ok=True)
    (fd / "交付.md").write_text("真交付", encoding="utf-8")
    (fd / "sub" / "deep.md").write_text("深层", encoding="utf-8")
    (fd / "MEMORY.md").write_text("交付区根同名文件", encoding="utf-8")

    check("HEARTBEAT.md 被闸门拦下", _normalize_file_path("HEARTBEAT.md", alice) is None)
    check(
        "MEMORY.md 被闸门拦下（绝对路径入参）",
        _normalize_file_path(str(alice / "MEMORY.md"), alice) is None,
    )
    check(".skills/foo/SKILL.md 被拦下", _normalize_file_path(".skills/foo/SKILL.md", alice) is None)
    check("skills/bar/SKILL.md 被拦下", _normalize_file_path("skills/bar/SKILL.md", alice) is None)
    check("区外 /tmp 仍被拦下", _normalize_file_path("/tmp/probe_x.py", alice) is None)
    check(
        "files/ 交付文件照常通过",
        _normalize_file_path("files/交付.md", alice) == "files/交付.md",
    )
    check(
        "深层交付文件照常通过",
        _normalize_file_path("files/sub/deep.md", alice) == "files/sub/deep.md",
    )
    check(
        "交付区根的平台同名文件拦下",
        _normalize_file_path("files/MEMORY.md", alice) is None,
    )


# ── F2 补扫只认交付目录 ───────────────────────────────────────────────


def _case_backfill_skips_system(ws: Path) -> None:
    print("F2 · 会话收尾补扫只认交付目录")
    add_user("bob")
    bob = ws / "bob"
    (bob / "HEARTBEAT.md").write_text("心跳", encoding="utf-8")
    (bob / "MEMORY.md").write_text("记忆", encoding="utf-8")
    mem = bob / "memory"
    mem.mkdir(parents=True, exist_ok=True)
    (mem / "2026-11-08.md").write_text("日记", encoding="utf-8")
    sk = bob / ".skills" / "foo"
    sk.mkdir(parents=True, exist_ok=True)
    (sk / "SKILL.md").write_text("技能", encoding="utf-8")
    tmpdir = bob / ".temp"
    tmpdir.mkdir(parents=True, exist_ok=True)
    (tmpdir / "probe_1.py").write_text("print(1)", encoding="utf-8")
    fd = bob / "files"
    fd.mkdir(parents=True, exist_ok=True)
    (fd / "真交付.md").write_text("交付", encoding="utf-8")

    chat = "chat-bf-1"
    _L.backfill_chat_session(chat_id=chat, username="bob", recent_seconds=3600.0)
    got = paths_of(chat, "bob")
    check("HEARTBEAT.md 不被补扫入账", "HEARTBEAT.md" not in got, f"{sorted(got)}")
    check("MEMORY.md 不被补扫入账", "MEMORY.md" not in got, f"{sorted(got)}")
    check(
        "memory/ 每日笔记不被补扫入账",
        not any(p.startswith("memory/") for p in got),
        f"{sorted(got)}",
    )
    check(
        ".skills/*/SKILL.md 不被补扫入账",
        not any("SKILL.md" in p for p in got),
        f"{sorted(got)}",
    )
    check(
        ".temp/probe_*.py 不被补扫入账",
        not any(p.startswith(".temp/") for p in got),
        f"{sorted(got)}",
    )
    check("files/ 真交付照常入账", "files/真交付.md" in got, f"{sorted(got)}")


# ── F3 巡检清存量 ─────────────────────────────────────────────────────


def _case_sweep_purges_system_paths(ws: Path) -> None:
    print("F3 · 巡检软删系统路径行（存量清洗）")
    add_user("bob")
    bob = ws / "bob"
    sk = bob / ".skills" / "bar"
    sk.mkdir(parents=True, exist_ok=True)
    (sk / "SKILL.md").write_text("技能定义", encoding="utf-8")
    (bob / "files" / "good.md").write_text("交付", encoding="utf-8")
    legacy_row("bob", ".skills/bar/SKILL.md")
    reg("bob", "files/good.md", role="producer")
    attach("bob", "files/good.md", "chat-f3", role="producer")
    check(
        "登记闸门收口：register 直接拒绝系统路径（不再造行/复活）",
        _L.register(
            owner_scope="user", owner_id="bob", kind="file",
            path=".skills/bar/SKILL.md", path_form="workspace",
        )
        == "",
    )
    check(
        "读面先于巡检就挡住系统路径行（F1 兜底过滤）",
        ".skills/bar/SKILL.md" not in paths_of("chat-f3", "bob"),
    )
    rep = _L.sweep(full=False, backfill=False)
    check("巡检报告带 system_expired 计数", "system_expired" in rep, f"{sorted(rep)}")
    check("巡检确有清理动作", int(rep.get("system_expired") or 0) >= 1, f"{rep}")
    with get_session() as s:
        bad = s.execute(
            select(Resource).where(
                Resource.owner_id == "bob", Resource.path == ".skills/bar/SKILL.md"
            )
        ).scalar_one()
        good = s.execute(
            select(Resource).where(
                Resource.owner_id == "bob", Resource.path == "files/good.md"
            )
        ).scalar_one()
    check(
        "系统路径行 deleted_at 置位（台账软删）",
        bad.deleted_at is not None,
    )
    check("软删不动 FS 文件（技能定义还在盘上）", (sk / "SKILL.md").is_file())
    check("正常交付行不受影响", good.deleted_at is None)
    got = paths_of("chat-f3", "bob")
    check(
        "系统路径行不再出现在会话清单",
        ".skills/bar/SKILL.md" not in got and "files/good.md" in got,
        f"{sorted(got)}",
    )
    with get_session() as s:
        kept = s.execute(
            select(Resource).where(
                Resource.owner_id == "bob",
                Resource.path == ".skills/bar/SKILL.md",
            )
        ).scalar_one_or_none()
    check(
        "台账历史行保留在库（软删不是删除，管理面可追）",
        kept is not None and kept.deleted_at is not None,
    )


def _case_scan_cap_covers_tail(ws: Path) -> None:
    """清理的**扫描**上限不能等于**报告**上限（2026-11-11 dev 实测）。

    台账 323 条可见行、8 条系统路径行全排在第 272–322 位，清理函数当时共用
    ``cap=200`` → ``limit(200)`` 扫不到尾部 → 巡检报 ``system_expired: 0``，
    存量永远清不掉。这条用例就是把这个"尾部盲区"钉死：系统行**故意排在最后**。
    """
    print("F3b · 清理扫描覆盖尾部（报告 cap ≠ 扫描 cap）")
    from coapis.foundation.resource_ledger import LEDGER_SCAN_CAP

    add_user("carol")
    carol = ws / "carol"
    (carol / "files").mkdir(parents=True, exist_ok=True)
    tail = 260
    for i in range(tail):
        (carol / "files" / f"good_{i:03d}.md").write_text("交付", encoding="utf-8")
        reg("carol", f"files/good_{i:03d}.md", role="producer")
    sk = carol / ".skills" / "tail-skill"
    sk.mkdir(parents=True, exist_ok=True)
    (sk / "SKILL.md").write_text("技能定义", encoding="utf-8")
    legacy_row("carol", ".skills/tail-skill/SKILL.md")

    with get_session() as s:
        n = len(
            s.execute(
                select(Resource).where(
                    Resource.owner_id == "carol", Resource.deleted_at.is_(None)
                )
            ).scalars().all()
        )
    check("用例前置：可见行数超过报告 cap(200)", n > 200, f"n={n}")

    rep = _L.sweep(full=False, backfill=False)
    with get_session() as s:
        tail_row = s.execute(
            select(Resource).where(
                Resource.owner_id == "carol",
                Resource.path == ".skills/tail-skill/SKILL.md",
            )
        ).scalar_one()
    check(
        f"排在第 {tail} 位之后的系统行也被清掉",
        tail_row.deleted_at is not None,
        f"system_expired={rep.get('system_expired')}",
    )
    check(
        "扫描上限是独立常量（不跟报告 cap 共用）",
        LEDGER_SCAN_CAP > 200,
        f"LEDGER_SCAN_CAP={LEDGER_SCAN_CAP}",
    )
    check(
        "尾部用例里的正常交付行照常活着",
        _visible_count("carol", "files/good_000.md") == 1,
    )


def _visible_count(owner: str, path: str) -> int:
    with get_session() as s:
        return int(
            s.execute(
                select(func.count())
                .select_from(Resource)
                .where(
                    Resource.owner_id == owner,
                    Resource.path == path,
                    Resource.deleted_at.is_(None),
                )
            ).scalar_one()
        )


# ── F4 读面兜底 ───────────────────────────────────────────────────────


def _case_read_face_hides_ghosts(ws: Path) -> None:
    print("F4 · 读面兜底：FS 已消失的行不进聊天侧清单")
    from coapis.foundation.resource_ledger import LEDGER_MISSING_TTL_SEC

    add_user("bob")
    f = ws / "bob" / "files" / "gone.md"
    f.write_text("写过又删了", encoding="utf-8")
    reg("bob", "files/gone.md")
    attach("bob", "files/gone.md", "chat-f4")
    check(
        "文件在盘上时可见",
        "files/gone.md" in paths_of("chat-f4", "bob"),
    )
    f.unlink()
    _L.sweep(full=False, backfill=False)
    check(
        "文件消失后立刻从清单消失（不等 TTL）",
        "files/gone.md" not in paths_of("chat-f4", "bob"),
    )
    with get_session() as s:
        row = s.execute(
            select(Resource).where(
                Resource.owner_id == "bob", Resource.path == "files/gone.md"
            )
        ).scalar_one()
        check("台账行保留（只标 fs_present=0）", row.deleted_at is None)
        check("fs_present 已标 0", int(row.fs_present or 0) == 0)
    check(
        "失效 TTL 降为 2h（巡检 30 分钟一轮）",
        LEDGER_MISSING_TTL_SEC == 2 * 3600,
        f"TTL={LEDGER_MISSING_TTL_SEC}",
    )
    check(
        "计数与清单同一把尺子",
        _L.count_resources_for_chat(
            owner_scope="user", owner_id="bob", chat_id="chat-f4"
        )
        == 0,
        f"count={_L.count_resources_for_chat(owner_scope='user', owner_id='bob', chat_id='chat-f4')}",
    )


# ── F5 本轮按轮筛 ─────────────────────────────────────────────────────


def _case_turn_face_filters_by_turn(ws: Path) -> None:
    print("F5 · 本轮面按轮筛（turn_id）")
    add_user("bob")
    fd = ws / "bob" / "files"
    (fd / "t1.md").write_text("第一轮", encoding="utf-8")
    (fd / "t2.md").write_text("第二轮", encoding="utf-8")
    reg("bob", "files/t1.md")
    reg("bob", "files/t2.md")
    attach("bob", "files/t1.md", "chat-f5", turn_id="turn-1")
    attach("bob", "files/t2.md", "chat-f5", turn_id="turn-2")
    check(
        "本轮面只看本轮",
        paths_of("chat-f5", "bob", turn_id="turn-1") == {"files/t1.md"},
        f"{sorted(paths_of('chat-f5', 'bob', turn_id='turn-1'))}",
    )
    check(
        "换一轮只看那一轮",
        paths_of("chat-f5", "bob", turn_id="turn-2") == {"files/t2.md"},
        f"{sorted(paths_of('chat-f5', 'bob', turn_id='turn-2'))}",
    )
    check(
        "会话面（不传 turn_id）仍是全量",
        paths_of("chat-f5", "bob") == {"files/t1.md", "files/t2.md"},
        f"{sorted(paths_of('chat-f5', 'bob'))}",
    )
    check("轮号写入台账", turn_of("bob", "files/t1.md") == "turn-1")
    attach("bob", "files/t1.md", "chat-f5", turn_id="turn-9")
    check(
        "重复引用不覆盖轮号（首次触及轮为准）",
        turn_of("bob", "files/t1.md") == "turn-1",
        f"turn={turn_of('bob', 'files/t1.md')}",
    )
    check(
        "本轮计数按轮筛",
        _L.count_resources_for_chat(
            owner_scope="user", owner_id="bob", chat_id="chat-f5", turn_id="turn-1"
        )
        == 1,
    )
    check(
        "轮号查不到时退化为会话口径（不猜轮号）",
        paths_of("chat-f5", "bob", turn_id="") == {"files/t1.md", "files/t2.md"},
    )


def main() -> int:
    with tempfile.TemporaryDirectory() as tmp:
        tmp_p = Path(tmp)
        os.environ["COAPIS_DB_PATH"] = str(tmp_p / "hygiene_v26.db")
        init_engine(f"sqlite:///{tmp_p / 'hygiene_v26.db'}")
        import coapis.foundation.db.models  # noqa: F401  (注册到 metadata)

        BaseRow.metadata.create_all(get_engine())
        ws = tmp_p / "workspaces"
        (ws / "alice" / "files").mkdir(parents=True, exist_ok=True)
        (ws / "bob" / "files").mkdir(parents=True, exist_ok=True)
        global _L
        _L = ResourceLedger(workspaces_dir=ws)

        print("=" * 70)
        print("v26 · 聊天资源卫生（F1-F5）")
        print("=" * 70)
        t0 = time.time()
        _case_ruler()
        _case_collector_gate(ws)
        _case_backfill_skips_system(ws)
        _case_sweep_purges_system_paths(ws)
        _case_scan_cap_covers_tail(ws)
        _case_read_face_hides_ghosts(ws)
        _case_turn_face_filters_by_turn(ws)
        print("-" * 70)
        print(f"耗时 {time.time() - t0:.2f}s")
        if _FAILED:
            print(f"失败 {_FAILED} 项")
            return 1
        print("全部通过")
        return 0


if __name__ == "__main__":
    sys.exit(main())


def test_resource_hygiene_v26() -> None:
    """pytest 入口（无参，规避自研脚本 tmp fixture 陷阱，见 MEMORY 十四条）。"""
    assert main() == 0
