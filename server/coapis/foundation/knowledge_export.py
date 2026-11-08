# -*- coding: utf-8 -*-
# Copyright 2026 蜜蜂 & CoApis Contributors
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU Affero General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# You should have received a copy of the GNU Affero General Public License
# along with this program.  If not, see <https://www.gnu.org/licenses/>.

"""知识投影层 —— 数据库 ``memories`` 表 → Markdown + index.json。

方案 v3 §批次1（问题 #1/#2/#6）。**真相层只有一个：数据库。**
磁盘上的 ``knowledge_base/`` 是每次全量重建的*投影*，允许被覆盖，
绝不能当成数据源来写。

落点（D1 + 台账选址）：

* 全局晋升（scope ∈ {workspace, agent}）→ ``WORKING_DIR/foundation/knowledge_base/``
  —— 与 kb 检索、启动注入、运行时索引同址；
* 用户记忆（scope = user）→ ``WORKSPACES_DIR/<user>/knowledge_base/``。

不变量：

1. **全量重建 + 幂等**：同一份数据库两次导出一字不差；
2. **签名去抖**：``(行数, max(updated_at), max(deleted_at))`` 未变 → 不写盘；
3. **删除会传播**：软删/硬删的行在投影里消失（清理陈旧 ``.md``）；
4. **原子写**：先写 ``*.tmp`` 再 ``os.replace``，读者永远看到完整文件；
5. 投影只读：本模块不读文件、不改数据库，纯 DB → 文件。
"""

from __future__ import annotations

import json
import logging
import os
import re
import time
from pathlib import Path
from typing import Any, Iterable

from sqlalchemy import and_, or_

from ..constant import (
    KNOWLEDGE_CATEGORY_QUOTA,
    KNOWLEDGE_GLOBAL_TOP_K,
    KNOWLEDGE_PROMOTE_MIN_IMPORTANCE,
)
from .db.engine import get_session
from .db.models.memory import Memory
from .memory_repository import MemoryEntry, ScopeType

logger = logging.getLogger(__name__)

#: 共享层去重阈值：与既有共享条目余弦相似度 ≥ 此值即视为同一条，不重复晋升
COSINE_DEDUP_THRESHOLD = 0.92


def _knowledge_clause():
    """台账 → 文件投影的准入条件：存活 **且** 不是机器维护日志。

    ``source=dream`` 的行是 dream 每轮写的运行台账（``status=success;
    reason=consolidated; summary=workspace=ok``），它是"机器干了什么"的记录，
    不是知识。它们留在台账里供治理列表查看/撤销，但不进投影——否则知识库目录里
    一半是运行日志，检索与注入都被噪声淹没。

    导出与启动自检**必须共用这一个尺子**：自检按全表数、导出按准入数，两个数
    永远对不上，等于每次启动都全量重建。``source`` 可为 NULL，``notin_`` 对
    NULL 求值为 NULL（行会被丢掉），故显式放行 NULL。
    """
    from ..constant import KNOWLEDGE_NOISE_SOURCES

    noise = tuple(KNOWLEDGE_NOISE_SOURCES)
    if not noise:
        return Memory.deleted_at.is_(None)
    return and_(
        Memory.deleted_at.is_(None),
        or_(Memory.source.is_(None), Memory.source.notin_(noise)),
    )


def _repo() -> Any:
    """记忆仓库（写侧用）。取不到返回 ``None``，调用方判空。"""
    try:
        from .repository_factory import RepositoryFactory

        return RepositoryFactory.get_memory_repository()
    except Exception:
        logger.debug("knowledge_export: factory unavailable", exc_info=True)
    try:
        from .memory_repository_impl import SqlaMemoryRepository

        return SqlaMemoryRepository()
    except Exception:
        logger.debug("knowledge_export: sqlite impl unavailable", exc_info=True)
        return None

#: 投影文件格式版本（读侧可用它拒绝旧格式）
PROJECTION_VERSION = 1

#: 全局投影（记忆层根目录）：<WORKING_DIR>/foundation/knowledge_base
GLOBAL_RELATIVE = ("foundation", "knowledge_base")

#: 用户投影：<WORKSPACES_DIR>/<user>/knowledge_base
USER_RELATIVE = ("knowledge_base",)

_SAFE_CATEGORY = re.compile(r"[^0-9A-Za-z_\-]")

#: 静态模板（仓库内的思维框架）→ WORKING_DIR/foundation/
_STATIC_MDS = ("core_principles.md", "thinking_patterns.md")

_REPO_FOUNDATION_DIR = Path(__file__).resolve().parent


# ── 目录解析 ─────────────────────────────────────────────────────────


def foundation_root() -> Path:
    """记忆层根目录（运行时可写）：``WORKING_DIR/foundation``。

    仓库里的 ``server/coapis/foundation/`` 是**代码目录**，运行时写不得进去
    （容器里它是镜像内路径，升级即丢；多实例部署会互相踩）。
    """
    from ..constant import WORKING_DIR

    return WORKING_DIR / "foundation"


def global_knowledge_dir() -> Path:
    """全局知识投影目录（= FoundationManager 的 knowledge_base）。"""
    return foundation_root() / "knowledge_base"


def user_knowledge_dir(username: str) -> Path:
    """用户知识投影目录：``WORKING_DIR/foundation/users/<user>/knowledge_base``。

    选址与 :func:`foundation_root` 同根 —— 历史上它落在 ``WORKSPACES_DIR/<user>/``
    （工作空间目录），于是同一个知识投影有**两把尺子**：注入读 foundation，
    导出写 workspaces，两边永远对不上，旧目录里还堆了上千个孤儿文件。
    """
    name = str(username or "").strip() or "_anon"
    return foundation_root() / "users" / name / Path(*USER_RELATIVE)


def safe_category(raw: Any) -> str:
    """分类名消毒：只允许 ``[0-9A-Za-z_-]``，其余归入 ``general``。

    分类会进目录名，``../x`` 之类的值能把投影文件写到目录外。
    """
    cat = str(raw or "").strip()
    if not cat:
        return "general"
    cat = _SAFE_CATEGORY.sub("_", cat)[:32]
    return cat or "general"


# ── 行 → 投影条目 ────────────────────────────────────────────────────


def _fmt_time(ts: float | None) -> str:
    """epoch → ``YYYY-MM-DDTHH:MM:SS``（UTC）。

    不带 ``Z``：读侧 ``MemoryEntry.from_dict`` 走 ``datetime.fromisoformat``，
    ``Z`` 后缀要 Python 3.11+ 才认，投影格式不绑 Python 版本。
    """
    if not ts:
        return ""
    return time.strftime("%Y-%m-%dT%H:%M:%S", time.gmtime(float(ts)))


def row_to_dict(row: Memory) -> dict[str, Any]:
    """DB 行 → ``foundation.memory_entry.MemoryEntry.from_dict`` 认识的字典。

    字段名以读侧为准（``priority_score`` / ``user_confirmed`` / ``source_session``
    是 ``memory_entry.MemoryEntry`` 的名字，不是表列名）。

    ``memory_type=core`` 是刻意的：投影里放的就是"已确认注入"的那批，与
    :meth:`FoundationManager.get_core_memories` 的口径一致。
    """
    created = _fmt_time(row.created_at)
    updated = _fmt_time(row.updated_at) or created
    return {
        "id": f"mem-{row.id}",
        "db_id": row.id,
        "content": row.content or "",
        "title": row.title or "",
        "memory_type": "core",
        "category": safe_category(row.category),
        "tags": [row.scope, row.category],
        "priority_score": float(row.importance or 0.0),
        "created_at": created,
        "last_accessed_at": updated,
        "access_count": 0,
        "user_confirmed": True,
        "source_agent": row.agent_id or "",
        "source_user": row.user_id or "",
        "source_session": row.session_id or "",
        # 投影自描述（读侧 from_dict 会忽略未知键）
        "scope": row.scope,
        "source": row.source or "",
        "session_id": row.session_id,
        "updated_at": updated,
    }


def render_markdown(d: dict[str, Any]) -> str:
    """条目 → 人可读的 Markdown（供导出/审阅/迁移，不参与检索）。"""
    lines = [
        f"# {d['title'] or d['id']}",
        "",
        f"- id: {d['id']}",
        f"- scope: {d['scope']}",
        f"- category: {d['category']}",
        f"- importance: {d['priority_score']:.2f}",
        f"- source: {d['source']}",
        f"- user: {d['source_user']}",
        f"- session: {d['source_session'] or '-'}",
        f"- created: {d['created_at']}",
        "",
        d["content"] or "",
        "",
    ]
    return "\n".join(lines)


# ── 写盘原语 ─────────────────────────────────────────────────────────


def _atomic_write(path: Path, text: str) -> None:
    """先写 tmp 再 replace：读者不会看到半截文件。"""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(text, encoding="utf-8")
    os.replace(tmp, path)


def _signature(rows: Iterable[Memory]) -> str:
    """投影签名：行数 + 最新改动时间 + 最新删除时间。

    软删会推进 ``updated_at``（``delete()`` 同时写两列），因此归档/撤销/新增
    都会改变签名；无变化时导出直接跳过写盘。
    """
    n = 0
    mx_upd = 0.0
    mx_del = 0.0
    for r in rows:
        n += 1
        mx_upd = max(mx_upd, float(r.updated_at or 0.0))
        mx_del = max(mx_del, float(r.deleted_at or 0.0))
    return f"{n}:{mx_upd:.3f}:{mx_del:.3f}"


def _write_projection(kb_dir: Path, dicts: list[dict[str, Any]], signature: str) -> int:
    """写一份投影（md 分目录 + index.json），并清掉不在集合里的陈旧文件。"""
    kb_dir.mkdir(parents=True, exist_ok=True)
    expected: set[Path] = set()

    for d in dicts:
        target = kb_dir / d["scope"] / d["category"] / f"{d['id']}.md"
        expected.add(target)
        if not target.exists():
            _atomic_write(target, render_markdown(d))

    # 陈旧清理：投影是集合的镜像，不是追加日志。
    # 遍历 kb 下**所有**子目录，不写死 ("global", "user")：写入侧是按行的
    # ``scope`` 建目录（user/workspace/agent 都可能），硬编码两份名字等于
    # "agent/ 目录里的文件永远不会被清"——dev 上 63 个失效的 agent/dream 文件
    # 就是这么留下的（自检数文件 198 vs 台账 135，每轮启动都全量重建）。
    stale = 0
    bases = [p for p in kb_dir.iterdir() if p.is_dir()]
    for base in bases:
        for md in base.rglob("*.md"):
            if md not in expected:
                try:
                    md.unlink()
                    stale += 1
                except OSError:
                    logger.warning("Projection: failed to prune %s", md)
        for sub in sorted(
            (p for p in base.rglob("*") if p.is_dir()), key=lambda p: len(p.parts), reverse=True,
        ):
            try:
                sub.rmdir()  # 只删空目录，非空自动失败
            except OSError:
                pass
    try:
        kb_dir.rmdir()  # 只删空目录，非空自动失败
    except OSError:
        pass

    index = {
        "version": PROJECTION_VERSION,
        "generated_at": time.time(),
        "signature": signature,
        "count": len(dicts),
        "entries": dicts,
    }
    _atomic_write(
        kb_dir / "index.json",
        json.dumps(index, ensure_ascii=False, indent=2),
    )
    return stale


def _read_signature(kb_dir: Path) -> str | None:
    idx = kb_dir / "index.json"
    if not idx.exists():
        return None
    try:
        return json.loads(idx.read_text(encoding="utf-8")).get("signature")
    except (json.JSONDecodeError, OSError, ValueError):
        return None


def _scope_dir_name(row: Memory) -> str:
    """目录分层：全局面（workspace/agent）统一进 ``global/``，用户面进 ``user/``。"""
    return "user" if row.scope == "user" else "global"


# ── 导出主入口 ───────────────────────────────────────────────────────


def export_from_db(force: bool = False) -> dict[str, Any]:
    """数据库 → 投影文件（全量重建，幂等）。

    Returns:
        ``{"global": n, "users": {user: n}, "total": n, "written": bool,
        "pruned": n, "ms": n}``；异常由调用方吞掉（投影坏了不能影响主流程）。
    """
    t0 = time.monotonic()
    with get_session() as s:
        rows = (
            s.query(Memory)
            .filter(_knowledge_clause())
            .order_by(Memory.id.asc())
            .all()
        )
        # detached 后仍可读属性（expire_on_commit=False）
        rows = list(rows)

    total = len(rows)
    signature = _signature(rows)

    groups: dict[Path, list[dict[str, Any]]] = {}
    user_counts: dict[str, int] = {}
    global_n = 0
    for row in rows:
        if row.scope == "user":
            kb = user_knowledge_dir(row.user_id)
            user_counts[row.user_id] = user_counts.get(row.user_id, 0) + 1
        else:
            kb = global_knowledge_dir()
            global_n += 1
        groups.setdefault(kb, []).append(row_to_dict(row))

    if not force:
        current = {kb: _read_signature(kb) for kb in groups}
        # 每组的签名只看组内行
        sigs = {}
        for kb, _ in groups.items():
            sigs[kb] = _signature(
                [r for r in rows if _kb_of(r) == kb],
            )
        if all(current.get(kb) == sigs[kb] for kb in groups):
            return {
                "global": global_n,
                "users": user_counts,
                "total": total,
                "written": False,
                "pruned": 0,
                "ms": int((time.monotonic() - t0) * 1000),
            }

    pruned = 0
    for kb, dicts in groups.items():
        g_rows = [r for r in rows if _kb_of(r) == kb]
        pruned += _write_projection(kb, dicts, _signature(g_rows))

    # 整组清空的目录要单独清扫：``_write_projection`` 只为"还有行"的目录收尾，
    # 某用户/某分类的行全删光后它的目录根本不会被调用 → 陈旧 .md 留着、
    # index.json 还写着旧计数 → "删一条 → 文件消失"在这条链上断掉，自检也永远
    # 判数量不符（每轮启动都全量重建）。
    pruned += _sweep_empty_projection(set(groups.keys()))

    return {
        "global": global_n,
        "users": user_counts,
        "total": total,
        "written": True,
        "pruned": pruned,
        "ms": int((time.monotonic() - t0) * 1000),
    }


def _sweep_empty_projection(written_dirs: set) -> int:
    """删掉整组清空目录里的 ``mem-*.md``，并把 index.json 计数归零。

    静态骨架文件（``core_principles.md`` 等）不在删除范围内。
    """
    removed = 0
    for kb in _all_projection_dirs():
        if kb in written_dirs or not kb.is_dir():
            continue
        for p in kb.rglob("*.md"):
            if p.name.startswith("mem-"):
                p.unlink()
                removed += 1
        (kb / "index.json").write_text(
            json.dumps({"version": PROJECTION_VERSION, "count": 0}, ensure_ascii=False),
            encoding="utf-8",
        )
    return removed


def _kb_of(row: Memory) -> Path:
    return user_knowledge_dir(row.user_id) if row.scope == "user" else global_knowledge_dir()


def verify_projection() -> dict[str, Any]:
    """启动自检：投影条目数是否等于数据库里"该被投影"的行数。

    计数口径与 :func:`_knowledge_clause` 同一把尺子（机器维护日志不计入）。
    不等（崩在半路 / 迁移过 / 手工删过文件）→ 调用方触发 :func:`export_from_db`
    全量重建。绝不静默回退到旧文件。
    """
    with get_session() as s:
        alive = s.query(Memory).filter(_knowledge_clause()).count()
    files = 0
    for kb in _all_projection_dirs():
        if not kb.is_dir():
            continue  # 该投影目录还没生成（首次启动/未写过），不算不一致
        idx = kb / "index.json"
        if not idx.exists():
            return {"ok": False, "reason": "missing_index", "db": alive, "files": 0}
        # 数**真实文件**，不拿 index.json 的 count 当现状：那个计数是导出自己
        # 写下去的，手工删文件、半路崩溃时它照样写着"我全"，自检就永远查不出
        # 问题（数文件"这杆秤本身是弯的）。index.json 只校验能否解析。
        files += sum(1 for f in kb.rglob("*.md") if f.name.startswith("mem-"))
        try:
            if int(json.loads(idx.read_text(encoding="utf-8")).get("count", -1)) < 0:
                return {"ok": False, "reason": "bad_index", "db": alive, "files": files}
        except (json.JSONDecodeError, OSError, ValueError, TypeError):
            return {"ok": False, "reason": "bad_index", "db": alive, "files": files}
    return {"ok": files == alive, "reason": "count_mismatch" if files != alive else "",
            "db": alive, "files": files}


def _all_projection_dirs() -> list[Path]:
    """当前存在的投影目录：只有 foundation 根一个来源（全局 + foundation/users/*）。

    选址唯一 —— 历史上这里扫 ``WORKSPACES_DIR``，导出写工作空间、注入读
    foundation，两把尺子永远对不上。
    """
    dirs = [global_knowledge_dir()]
    users = foundation_root() / "users"
    if users.is_dir():
        for ws in users.iterdir():
            if ws.is_dir():
                dirs.append(ws / Path(*USER_RELATIVE))
    return dirs


def ensure_static_templates() -> list[str]:
    """把仓库内的思维框架（core_principles/thinking_patterns）复制进记忆层。

    运行时读的是 ``WORKING_DIR/foundation/``，代码目录在容器里不该被写。
    存在即跳过（用户改过的模板不被覆盖）。
    """
    root = foundation_root()
    root.mkdir(parents=True, exist_ok=True)
    (root / "knowledge_base").mkdir(parents=True, exist_ok=True)
    created: list[str] = []
    for name in _STATIC_MDS:
        src = _REPO_FOUNDATION_DIR / name
        dst = root / name
        if dst.exists() or not src.is_file():
            continue
        try:
            dst.write_text(src.read_text(encoding="utf-8"), encoding="utf-8")
            created.append(name)
        except OSError:
            logger.warning("Foundation templates: failed to seed %s", name, exc_info=True)
    return created


def enforce_category_quota(
    *,
    scope: str,
    user_id: str = "",
    category: str,
    quota: int,
) -> int:
    """单用户单分类配额（D-3）：超限按 importance 归档最弱的。

    淘汰 = 归档（软删 ``deleted_at``）而不是物理删除，撤销与审计都还看得见。
    只用仓库既有方法（list_entries + delete），不给仓库 ABC 加新面。
    """
    q = int(quota or 0)
    if q <= 0:
        return 0
    repo = _repo()
    if repo is None:
        return 0
    try:
        rows = repo.list_entries(
            scope=scope, user_id=user_id or "", category=category, limit=q + 200,
        )
    except Exception:
        logger.debug("quota: list failed (scope=%s cat=%s)", scope, category, exc_info=True)
        return 0
    if len(rows) <= q:
        return 0
    rows.sort(key=lambda r: (float(r.importance or 0.0), r.id or 0))
    evicted = 0
    for row in rows[: len(rows) - q]:
        if row.id is None:
            continue
        try:
            if repo.delete(row.id):
                evicted += 1
        except Exception:
            logger.debug("quota: evict failed (id=%s)", row.id, exc_info=True)
    if evicted:
        logger.info(
            "Knowledge quota: scope=%s user=%s cat=%s quota=%d evicted=%d",
            scope, user_id or "-", category, q, evicted,
        )
    return evicted


def promote_to_shared(limit: int | None = None) -> dict[str, Any]:
    """跨用户晋升（功能点 6）：高分个人沉淀 → workspace 共享层。

    现状是 165 条 100% 是 ``scope=user``，共享层 0 行 —— 平台号称的"共同
    进化"从来没有共享层。这里补上：按 importance 取高分条目，与既有共享条目
    做特征向量去重（同一条不重复晋升），写 ``scope=workspace`` + 分类配额裁剪。

    幂等：同一行被再次扫到时余弦相似度 = 1.0 → 跳过，所以不需要额外标记列。
    """
    from ..constant import (
        KNOWLEDGE_CATEGORY_QUOTA,
        KNOWLEDGE_GLOBAL_TOP_K,
        KNOWLEDGE_PROMOTE_MIN_IMPORTANCE,
    )
    from .hash_similarity import cosine_similarity, feature_vector

    top_k = int(limit if limit is not None else KNOWLEDGE_GLOBAL_TOP_K)
    repo = _repo()
    if repo is None:
        return {"scanned": 0, "promoted": 0, "reason": "no_repo"}
    if top_k <= 0:
        return {"scanned": 0, "promoted": 0, "reason": "top_k_disabled"}

    with get_session() as s:
        cands = (
            s.query(Memory)
            .filter(
                Memory.scope == "user",
                _knowledge_clause(),
                Memory.importance >= KNOWLEDGE_PROMOTE_MIN_IMPORTANCE,
            )
            .order_by(Memory.importance.desc(), Memory.id.desc())
            .limit(top_k * 3)
            .all()
        )
        existing = (
            s.query(Memory).filter(Memory.scope == "workspace", Memory.deleted_at.is_(None)).all()
        )
        # workspace 行必须带 user_id=""（仓库读取侧的哨兵），并集入既有共享条目做去重
        pool = [row_to_dict(r) for r in existing]
        scanned = len(cands)
        promoted = 0
        dup_skipped = 0
        for row in cands:
            data = row_to_dict(row)
            text = f"{data.get('title', '')} {data.get('content', '')}"
            vec = feature_vector(text)
            if any(cosine_similarity(vec, feature_vector(
                f"{e.get('title', '')} {e.get('content', '')}",
            )) >= COSINE_DEDUP_THRESHOLD for e in pool):
                dup_skipped += 1
                continue
            if promoted >= top_k:
                break
            try:
                # 写侧字段必须取 ORM 行本体：``row_to_dict`` 是读侧扁平格式
                # （importance 改名 priority_score、agent_id 改名 source_agent），
                # 拿它当写侧来源会把 importance 写成 0、agent_id 写成 None——
                # 共享层 15 条 importance 全 0 就是这么来的（注入永远排最后）。
                # 分类统一写 "knowledge"（方案 D-2）：个人层保留原 category，
                # 共享层按来源分类记账会让配额变成"每类各一份"的口径漂移。
                repo.add(MemoryEntry(
                    scope=ScopeType.WORKSPACE,
                    user_id="",
                    agent_id=row.agent_id,
                    category="knowledge",
                    title=row.title or "",
                    content=row.content or "",
                    source="promote_shared",
                    importance=float(row.importance or 0.0),
                    session_id=row.session_id,
                ))
            except Exception:
                logger.warning("promote_to_shared: add failed (id=%s)", data.get("id"), exc_info=True)
                continue
            pool.append(data)
            promoted += 1
        categories = sorted({e.get("category") for e in pool if e.get("category")})

    evicted = 0
    for cat in categories:
        evicted += enforce_category_quota(
            scope="workspace", user_id="", category=cat, quota=KNOWLEDGE_CATEGORY_QUOTA,
        )
    if promoted:
        export_from_db()
    result = {
        "scanned": scanned,
        "promoted": promoted,
        "dedup_skipped": dup_skipped,
        "evicted": evicted,
    }
    logger.info("promote_to_shared: %s", result)
    return result


__all__ = [
    "PROJECTION_VERSION",
    "ensure_static_templates",
    "enforce_category_quota",
    "export_from_db",
    "foundation_root",
    "global_knowledge_dir",
    "promote_to_shared",
    "render_markdown",
    "row_to_dict",
    "safe_category",
    "user_knowledge_dir",
    "verify_projection",
]
