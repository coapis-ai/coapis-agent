# -*- coding: utf-8 -*-
"""Resource ledger (R1, 清单面).

State table + reference table for the resource contract. See
``db/models/resources.py`` for why this is **not** merged into
``file_records`` (event stream vs. state table) and why ``resource_key``
carries the owner component.

Design rules (same as ``file_ledger``):

* **Fire-and-forget** — every public method swallows its own exceptions; a
  broken ledger must never break the message path.
* **Counts are derived** — reference counts come from ``resource_refs`` only;
  there is no stored counter.
* **Sweep is one-way (FS → DB)** — the sweep may mark ``fs_present`` and move
  statuses, it **never deletes filesystem files**. A reverse sweep would let
  the database delete user files, which is unacceptable.

Lifecycle (frozen, §6 of the contract):

    draft ──(用户确认/交付)──► official
      │                          │
      │                          ├──(会话删除 → refs 清空)──► orphan
      ├──(refs 空 + FS 存在)────► orphan
      └──(归档)─────────────────► archived
    orphan ──(被重新引用)────────► draft
    任意 ──(软删)────────────────► deleted (deleted_at 置位，FS 不动)
"""

from __future__ import annotations

import logging
import time
from pathlib import Path, PurePosixPath
from typing import Any, Optional

from sqlalchemy import func, or_, select, update

from ..constant import WORKSPACES_DIR
from .db.engine import get_session
from .db.models.resources import (
    VALID_KINDS,
    VALID_OWNER_SCOPES,
    VALID_REFERRER_KINDS,
    VALID_ROLES,
    VALID_STATUSES,
    Resource,
    ResourceRef,
    make_resource_key,
)
from .db.models.user import User

logger = logging.getLogger(__name__)

#: 噪音目录：里面的东西不是用户的"资源"。``.trash`` 是软删归档、``.temp`` 是
#: 脚本暂存。补扫/巡检与消费面补扫共用这一份定义，避免两边口径漂移。
#: （实测 dev：1242 条 unledgered 里 298 条来自 ``.trash``/``.temp``。）
NOISE_DIR_PARTS = frozenset({
    ".trash", ".temp", ".git", "__pycache__", "node_modules", "venv",
    ".venv", "site-packages", ".ipynb_checkpoints",
})

#: 工作区根下从来不是用户的目录（系统产物）。评测沙箱、agent 工作区、已删除
#: 账号的残留由 ``_known_usernames()`` 判定，这里只硬挡系统目录。
NON_USER_WORKSPACE_DIRS = frozenset({"system"})

#: 单次补扫最多登记多少个文件（防止一次巡检写爆数据库）。
BACKFILL_CAP = 5000

#: 台账行"文件已消失"多久后软删（秒）。巡检每天 03:00 跑一次，取 36h ≈ 两个
#: 巡检周期：一次看不见可能只是文件正在被移动/写入中途，两次都看不见才算真没了。
#: 软删只写 ``deleted_at``，**永不删 FS 文件**（沿用 sweep 铁律）。
LEDGER_MISSING_TTL_SEC = 36 * 3600


def title_from_path(kind: str, path: str) -> str:
    """``kind=file`` 的兜底标题 = 文件名。

    台账钩子（``file_ledger._sync_resource``）登记时不传标题，实测 dev 347 行里
    94 行 ``title`` 为空 → 前端资源条只能退化成显示整条路径
    （``files/2026-10/2026-10-22_任务/报告.docx``）。标题是纯展示字段，文件名
    就是最诚实的默认值，不需要 LLM 起名。
    """
    if str(kind) != "file":
        return ""
    name = PurePosixPath(str(path or "").replace("\\", "/")).name
    return name.strip()


def canonical_file_path(path: str, *, form: str = "workspace") -> str:
    """``kind=file`` 的规范路径：**相对用户工作区根**（``workspaces/{user}``）。

    台账历史上只有一条写入路径（文件台账钩子 + 巡检补扫），口径是 **files 根**
    相对路径（``report.md``、``media/x.png``）；会话资源采集器（B1）按对外契约
    写的是 **工作区**相对（``files/report.md``）。两种口径算出两个 key，同一个
    文件在台账里分裂成两行——前端资源条出现「同一文件两条、其中一条显示已删除」。
    统一以工作区相对为准（它同时是前端与回答正文链接的口径），旧口径在唯一的
    写入口换算，采集器与钩子从此同键。
    """
    p = str(path or "").replace("\\", "/").strip().strip("/")
    if not p:
        return ""
    if form == "files_root":
        return p if p.startswith("files/") else f"files/{p}"
    return p


#: 已带工作区分类前缀的路径。
WS_TOP_DIRS = ("files/", "media/", "output/", "downloads/", "uploads/")


def workspace_relative_path(path: str, owner_dir: Optional[Path] = None) -> str:
    """台账存储口径 → 对外契约口径（工作区相对）。

    规范口径本身就是工作区相对，这里主要给**存量裸路径**（files 根相对的历史行）
    兜底：文件真实落在 ``files/`` 下时补前缀。前端 ``toMyfilesParams`` 按首段决定
    走哪个分类，裸路径 ``report.md`` 会被当成 media 而 404。
    """
    p = str(path or "").replace("\\", "/").strip().strip("/")
    if not p:
        return ""
    if p.startswith(WS_TOP_DIRS):
        return p
    if owner_dir is not None:
        try:
            if (owner_dir / p).is_file():
                return p
        except OSError:  # pragma: no cover - defensive
            pass
        return f"files/{p}"
    return f"files/{p}"


class ResourceLedger:
    def __init__(self, workspaces_dir: Optional[Path] = None) -> None:
        self._ws = Path(workspaces_dir) if workspaces_dir else WORKSPACES_DIR

    # ── internals ─────────────────────────────────────────────────────

    def _files_root(self, owner_id: str) -> Path:
        """Absolute root a ``kind=file`` path is relative to.

        Only ``user`` owners have a workspace files root; agent/workspace
        scoped resources keep their path as given and are not FS-verified.
        """
        return self._ws / owner_id / "files"

    def _resolve_file_path(self, owner_id: str, path: str) -> Path:
        """台账里的 file 路径 → 绝对路径（两种历史口径都能解析）。

        规范口径是工作区相对；存量数据里还有 files 根相对的裸路径（``x.md``），
        按存在性回退，避免把真实存在的文件误判成「已删除」。
        """
        cand = self._ws / owner_id / path
        if cand.is_file():
            return cand
        alt = self._files_root(owner_id) / path
        if alt.is_file():
            return alt
        return cand

    def _abs_path(self, res: Resource) -> Optional[Path]:
        if res.kind != "file" or res.owner_scope != "user":
            return None
        return self._resolve_file_path(res.owner_id, res.path)

    def resolve_file_path(self, owner_id: str, path: str) -> Optional[Path]:
        """台账路径 → 存在的绝对路径；不存在返回 ``None``。

        给「会话资源列表」这类出口用：存在性判断必须与台账同一口径，
        否则前端会把真实存在的文件显示成「已删除」。
        """
        owner_id = str(owner_id or "").strip()
        path = str(path or "").strip()
        if not owner_id or not path:
            return None
        resolved = self._resolve_file_path(owner_id, path)
        return resolved if resolved.is_file() else None

    def _count_refs(self, s, resource_key: str) -> int:
        return s.execute(
            select(func.count())
            .select_from(ResourceRef)
            .where(ResourceRef.resource_key == resource_key)
        ).scalar_one()

    # ── write ─────────────────────────────────────────────────────────

    def register(
        self,
        *,
        owner_scope: str,
        owner_id: str,
        kind: str,
        path: str,
        title: Optional[str] = None,
        source: str = "hook",
        path_form: str = "files_root",
    ) -> str:
        """Register (or re-see) a resource; returns ``resource_key``.

        Idempotent: re-registering the same owner/kind/path refreshes
        ``last_seen_at`` / ``size_bytes`` and never creates a second row.
        Never raises — returns ``""`` on failure.

        ``path_form`` 声明调用方用的是哪种口径：文件台账钩子/巡检补扫传
        ``"files_root"``（相对 ``workspaces/{user}/files``），会话资源采集器传
        ``"workspace"``（相对 ``workspaces/{user}``）。两者都换算成工作区相对后
        才参与 key 计算，同一文件只会有一行。
        """
        try:
            if owner_scope not in VALID_OWNER_SCOPES or kind not in VALID_KINDS:
                return ""
            owner_id = (owner_id or "").strip()
            path = (path or "").strip()
            if kind == "file":
                # 统一口径后再算 key：采集器的 ``files/x`` 与钩子的 ``x`` 必须
                # 落到同一行，否则同一文件在台账里分裂成两条记录。
                path = canonical_file_path(path, form=path_form)
            if not owner_id or not path:
                return ""
            key = make_resource_key(owner_scope, owner_id, kind, path)
            now = time.time()
            # 标题兜底：调用方没给标题时用文件名（见 title_from_path）。
            title_in = (title or "").strip() or title_from_path(kind, path)
            with get_session() as s:
                res = s.execute(
                    select(Resource).where(Resource.resource_key == key)
                ).scalar_one_or_none()
                if res is None:
                    size = 0
                    p = self._abs_path_kind(kind, owner_id, path)
                    if p is not None and p.exists():
                        size = p.stat().st_size
                    s.add(
                        Resource(
                            resource_key=key,
                            owner_scope=owner_scope,
                            owner_id=owner_id,
                            kind=kind,
                            path=path,
                            title=title_in or None,
                            status="draft",
                            size_bytes=size,
                            version=1,
                            source=source or "hook",
                            fs_present=1,
                            first_seen_at=now,
                            last_seen_at=now,
                            updated_at=now,
                        )
                    )
                else:
                    res.last_seen_at = now
                    res.updated_at = now
                    # 版本推进只在**内容真的换了**时发生：重新 stat 一次文件，
                    # 大小与台账记录不同才算新版；同一份内容重复引用版本不动。
                    if kind == "file":
                        try:
                            _p = self._resolve(abs_path, owner_id)
                            _st = _p.stat() if _p is not None else None
                            if _st is not None:
                                size = int(_st.st_size)
                        except Exception:  # pragma: no cover - defensive
                            size = None
                    if size and res.size_bytes and size != res.size_bytes:
                        res.version = int(res.version or 1) + 1
                        res.size_bytes = size
                    elif size and res.size_bytes != size:
                        res.size_bytes = size
                    if title:
                        res.title = title
                    elif not res.title and title_in:
                        # 只补空标题，不把采集器给过的真实标题（网页标题等）降级成文件名。
                        res.title = title_in
                    if res.status == "deleted":
                        # Soft-deleted rows are resurrected on re-registration.
                        res.deleted_at = None
                        res.status = "draft"
            return key
        except Exception as exc:  # pragma: no cover - defensive
            logger.debug("resource ledger register failed (ignored): %s", exc)
            return ""

    def _abs_path_kind(self, kind: str, owner_id: str, path: str) -> Optional[Path]:
        if kind == "file" and owner_id:
            return self._resolve_file_path(owner_id, path)
        return None

    def attach_ref(
        self,
        *,
        resource_key: str,
        referrer_kind: str,
        referrer_id: str,
        role: str = "reference",
    ) -> bool:
        """Attach a referrer. Idempotent (unique key). Never raises."""
        try:
            if referrer_kind not in VALID_REFERRER_KINDS or role not in VALID_ROLES:
                return False
            if not resource_key or not referrer_id:
                return False
            with get_session() as s:
                res = s.execute(
                    select(Resource).where(Resource.resource_key == resource_key)
                ).scalar_one_or_none()
                if res is None:
                    return False
                existing = s.execute(
                    select(ResourceRef)
                    .where(ResourceRef.resource_key == resource_key)
                    .where(ResourceRef.referrer_kind == referrer_kind)
                    .where(ResourceRef.referrer_id == referrer_id)
                ).scalar_one_or_none()
                if existing is None:
                    s.add(
                        ResourceRef(
                            resource_key=resource_key,
                            referrer_kind=referrer_kind,
                            referrer_id=referrer_id,
                            role=role,
                            created_at=time.time(),
                        )
                    )
                elif role == "producer" and existing.role != "producer":
                    # 口径只升不降：同一文件先被引用、后被本会话写出时，
                    # 这条引用就是「产出」。降口径会把已交付的产物说成引用。
                    existing.role = "producer"
                # orphan → draft on re-reference (frozen lifecycle).
                if res.status == "orphan":
                    res.status = "draft"
                    res.updated_at = time.time()
            return True
        except Exception as exc:  # pragma: no cover - defensive
            logger.debug("resource ledger attach_ref failed (ignored): %s", exc)
            return False

    def detach_ref(
        self,
        *,
        resource_key: str,
        referrer_kind: str,
        referrer_id: str,
    ) -> bool:
        """Remove one referrer; moves the resource to ``orphan`` if refs empty.

        Unlike the file ledger, DELETE is allowed here: a reference is a
        relation, not an append-only event. The resource row itself is never
        deleted (soft delete only).
        """
        try:
            with get_session() as s:
                row = s.execute(
                    select(ResourceRef)
                    .where(ResourceRef.resource_key == resource_key)
                    .where(ResourceRef.referrer_kind == referrer_kind)
                    .where(ResourceRef.referrer_id == referrer_id)
                ).scalar_one_or_none()
                if row is None:
                    return False
                s.delete(row)
                # 必须 flush 再计数：同一 session 里 DELETE 尚未下发到 DB，
                # 直接 count 会把刚删掉的行算进去，refs 清空也判不出 orphan。
                s.flush()
                remaining = self._count_refs(s, resource_key)
                if remaining == 0:
                    res = s.execute(
                        select(Resource).where(Resource.resource_key == resource_key)
                    ).scalar_one_or_none()
                    if res is not None and res.status in ("draft", "official"):
                        res.status = "orphan"
                        res.updated_at = time.time()
            return True
        except Exception as exc:  # pragma: no cover - defensive
            logger.debug("resource ledger detach_ref failed (ignored): %s", exc)
            return False

    def detach_refs_by_referrer(self, referrer_kind: str, referrer_id: str) -> int:
        """R2: release **all** refs of one referrer (a deleted chat/session).

        Returns the number of refs removed. Every resource left with zero refs
        moves to ``orphan`` (frozen lifecycle: 会话删除 → refs 清空 → orphan).
        Resource rows are never deleted here — only the relation goes away.
        Never raises.
        """
        if referrer_kind not in VALID_REFERRER_KINDS or not referrer_id:
            return 0
        try:
            with get_session() as s:
                rows = s.execute(
                    select(ResourceRef)
                    .where(ResourceRef.referrer_kind == referrer_kind)
                    .where(ResourceRef.referrer_id == referrer_id)
                ).scalars().all()
                if not rows:
                    return 0
                keys = {r.resource_key for r in rows}
                for r in rows:
                    s.delete(r)
                s.flush()  # DELETE must reach the DB before counting
                for key in keys:
                    if self._count_refs(s, key) == 0:
                        res = s.execute(
                            select(Resource).where(Resource.resource_key == key)
                        ).scalar_one_or_none()
                        if res is not None and res.status in ("draft", "official"):
                            res.status = "orphan"
                            res.updated_at = time.time()
                return len(rows)
        except Exception as exc:  # pragma: no cover - defensive
            logger.debug("resource ledger detach_refs failed (ignored): %s", exc)
            return 0

    def mark_status(self, resource_key: str, status: str) -> bool:
        """Move a resource to ``status``. Never raises."""
        try:
            if status not in VALID_STATUSES:
                return False
            with get_session() as s:
                res = s.execute(
                    select(Resource).where(Resource.resource_key == resource_key)
                ).scalar_one_or_none()
                if res is None:
                    return False
                res.status = status
                res.updated_at = time.time()
                if status == "deleted":
                    res.deleted_at = time.time()
            return True
        except Exception as exc:  # pragma: no cover - defensive
            logger.debug("resource ledger mark_status failed (ignored): %s", exc)
            return False

    # ── sweep (FS → DB, one-way) ─────────────────────────────────────

    def _files_root_index(self, owner_id: str) -> dict:
        """``basename → [(rel, abs, size, mtime)]``：该用户 files 根下所有可当"新位置"的文件。

        扫描口径与巡检主循环一致（files 根相对路径），返回的 rel 经
        ``canonical_file_path(..., form="files_root")`` 换算后即台账口径。
        排除 ``NOISE_DIR_PARTS``（回收站/暂存/git…）——把文件移进回收站是**删除**，
        不是换位置，资源条指向 ``.trash/...`` 也根本下载不到（前端分类只认
        ``files/``/``media/``）。这类行交给 ``_expire_missing`` 软删。
        """
        index: dict[str, list[tuple[str, Path, int, float]]] = {}
        root = self._files_root(owner_id)
        if not root.is_dir():
            return index
        try:
            found = list(root.rglob("*"))
        except OSError:
            return index
        for f in found:
            try:
                if not f.is_file():
                    continue
                rel = f.relative_to(root).as_posix()
                if NOISE_DIR_PARTS.intersection(PurePosixPath(rel).parts):
                    continue
                st = f.stat()
            except OSError:
                continue
            index.setdefault(f.name, []).append((rel, f, st.st_size, st.st_mtime))
        return index

    @staticmethod
    def _pick_relocate_target(
        cands: list[tuple[str, Path, int, float]], size_hint: int
    ) -> Optional[tuple[str, Path, int, float]]:
        """同名候选里选一个；判不准就返回 ``None``（宁留旧行也不猜）。"""
        if not cands:
            return None
        if len(cands) == 1:
            return cands[0]
        pool = [c for c in cands if size_hint and c[2] == size_hint] or cands
        pool.sort(key=lambda c: (-c[3], len(c[0].split("/")), c[0]))
        best, second = pool[0], pool[1]
        if best[2] == second[2] and best[3] == second[3]:
            return None  # 大小与 mtime 全同 → 无法判定是哪一个
        return best

    def _relocate_missing(self, cap: int = 200) -> dict:
        """台账跟随移动：文件在工作区里换了位置 → 台账行改指新位置。

        为什么必须迁 ``resource_refs``：``resource_key`` 含路径，路径一变 key 就变，
        而会话资源条/采集器全靠 refs 找资源。只改 path 不迁 refs，等于把整条会话的
        资源引用清空（顺带还会被孤儿判定打上 orphan）。

        新位置已有台账行时**合并**：refs 迁过去（同 referrer+role 去重），旧行删除
        —— 同一文件在台账里永远只有一行，这是 key 口径统一后必须守住的不变量。
        """
        relocated: list[dict] = []
        now = time.time()
        with get_session() as s:
            rows = s.execute(
                select(Resource)
                .where(
                    Resource.kind == "file",
                    Resource.owner_scope == "user",
                    Resource.fs_present == 0,
                    Resource.deleted_at.is_(None),
                )
                .limit(cap)
            ).scalars().all()
            indices: dict[str, dict] = {}
            for res in rows:
                name = PurePosixPath(str(res.path)).name
                if not name:
                    continue
                owner = res.owner_id
                if owner not in indices:
                    indices[owner] = self._files_root_index(owner)
                cands = indices[owner].get(name) or []
                target = self._pick_relocate_target(cands, int(res.size_bytes or 0))
                if target is None:
                    continue
                new_rel, abs_p, size, mtime = target
                new_path = canonical_file_path(new_rel, form="files_root")
                new_key = make_resource_key(
                    res.owner_scope, res.owner_id, res.kind, new_path
                )
                old_key = res.resource_key
                old_path = str(res.path)
                if new_key == old_key:
                    continue
                existing = s.execute(
                    select(Resource).where(Resource.resource_key == new_key)
                ).scalar_one_or_none()
                old_refs = list(
                    s.execute(
                        select(ResourceRef).where(ResourceRef.resource_key == old_key)
                    ).scalars().all()
                )
                if existing is not None:
                    # 合并：旧行的 refs 迁到新行，重复引用直接丢。
                    for ref in old_refs:
                        dup = s.execute(
                            select(ResourceRef)
                            .where(
                                ResourceRef.resource_key == new_key,
                                ResourceRef.referrer_kind == ref.referrer_kind,
                                ResourceRef.referrer_id == ref.referrer_id,
                                ResourceRef.role == ref.role,
                            )
                            .limit(1)
                        ).scalar_one_or_none()
                        if dup is not None:
                            s.delete(ref)
                        else:
                            ref.resource_key = new_key
                    s.delete(res)
                    s.flush()
                    keep = existing
                else:
                    if old_refs:
                        s.execute(
                            update(ResourceRef)
                            .where(ResourceRef.resource_key == old_key)
                            .values(resource_key=new_key)
                        )
                    res.resource_key = new_key
                    res.path = new_path
                    keep = res
                keep.fs_present = 1
                keep.size_bytes = int(size)
                keep.last_seen_at = now
                keep.updated_at = now
                if keep.status == "orphan":
                    keep.status = "draft"
                if not keep.title:
                    keep.title = title_from_path("file", new_path)
                relocated.append(
                    {
                        "owner_id": owner,
                        "from": old_path,
                        "to": new_path,
                        "merged": existing is not None,
                    }
                )
                if len(relocated) >= cap:
                    break
        return {
            "relocated": len(relocated),
            "relocated_list": relocated[:50],
        }

    def _expire_missing(
        self, ttl_sec: float = LEDGER_MISSING_TTL_SEC, cap: int = 500
    ) -> dict:
        """确认消失（连续两个巡检周期看不见）→ 软删台账行，资源条不再挂死链。

        ``updated_at`` 天然就是"第一次发现缺失"的时刻：缺失行不在扫描可见集里，
        之后的巡检不会再刷它（``fs_present`` 已是 0，标记循环跳过），所以不需要
        额外的"缺失起始时间"列。首轮发现只起表，超过 TTL 才软删。
        """
        expired: list[dict] = []
        now = time.time()
        with get_session() as s:
            rows = s.execute(
                select(Resource)
                .where(
                    Resource.kind == "file",
                    Resource.owner_scope == "user",
                    Resource.fs_present == 0,
                    Resource.deleted_at.is_(None),
                )
                .limit(cap)
            ).scalars().all()
            for res in rows:
                if res.updated_at is None:
                    res.updated_at = now  # 起表：这一轮开始计时
                    continue
                if now - float(res.updated_at) < ttl_sec:
                    continue
                res.deleted_at = now
                res.status = "deleted"
                res.updated_at = now
                expired.append(
                    {
                        "owner_id": res.owner_id,
                        "path": res.path,
                        "missing_days": round((now - float(res.updated_at)) / 86400, 2),
                    }
                )
        return {"expired": len(expired), "expired_list": expired[:50]}

    def _backfill_titles(self, cap: int = 5000) -> int:
        """给存量空标题补文件名（实测 dev 347 行里 94 行标题为空）。"""
        titled = 0
        with get_session() as s:
            rows = s.execute(
                select(Resource)
                .where(
                    Resource.kind == "file",
                    Resource.deleted_at.is_(None),
                    or_(Resource.title.is_(None), Resource.title == ""),
                )
                .limit(cap)
            ).scalars().all()
            for res in rows:
                name = title_from_path("file", res.path)
                if name:
                    res.title = name
                    titled += 1
        return titled


    def sweep(
        self,
        *,
        full: bool = False,
        backfill: bool = False,
        relocate: bool = True,
        expire_after: Optional[float] = None,
    ) -> dict:
        """Reconcile the ledger against the filesystem. **Never deletes files.**

        Report keys:
        * ``fs_missing`` — ledger rows whose file is gone (``fs_present=0``)
        * ``fs_present`` — rows verified present
        * ``relocated`` — fs_missing 行其实是**被移动**了：台账改指工作区里的新位置，
          ``resource_refs`` 一起迁（``relocate=False`` 关闭）
        * ``expired`` — fs_missing 行超过 ``expire_after`` 秒（默认两个巡检周期）
          仍看不见 → 软删台账行，资源条不再挂死链；**永不删 FS 文件**
        * ``titled`` — 空标题补上文件名的行数（钩子登记不传标题的存量）
        * ``orphans`` — resources with zero refs (status moved to orphan)
        * ``unledgered`` — files on FS with no ledger row **and a real user owner**
        * ``unowned`` — files under a workspace dir that is not a known user
          (agent workspace、评测沙箱、已删除账号的残留)。只报告、**不补登记**：
          凭空造一个 owner 会把别人的文件挂到不存在的用户名下。
        * ``noise_skipped`` — 落在 ``NOISE_DIR_PARTS`` 里的文件（软删归档/暂存）
        * ``backfilled`` — ``backfill=True`` 时实际新建的台账行数
        * ``fs_missing_list`` / ``orphan_list`` / ``unledgered_list`` /
          ``unowned_list`` — the lists the contract requires the report to be
          able to *enumerate* (§6), capped at ``report_cap`` entries so the
          response stays bounded.
        """
        report = {
            "fs_missing": 0,
            "fs_present": 0,
            "relocated": 0,
            "expired": 0,
            "titled": 0,
            "orphans": 0,
            "unledgered": 0,
            "unowned": 0,
            "noise_skipped": 0,
            "backfilled": 0,
            "fs_missing_list": [],
            "relocated_list": [],
            "expired_list": [],
            "orphan_list": [],
            "unledgered_list": [],
            "unowned_list": [],
        }
        cap = 200
        pending: list[tuple[str, str]] = []
        try:
            with get_session() as s:
                rows = s.execute(
                    select(Resource)
                    .where(Resource.kind == "file")
                    .where(Resource.owner_scope == "user")
                    .where(Resource.deleted_at.is_(None))
                ).scalars().all()
                seen: dict[str, set[str]] = {}
                for res in rows:
                    p = self._abs_path(res)
                    present = p is not None and p.exists()
                    flag = 1 if present else 0
                    if res.fs_present != flag:
                        res.fs_present = flag
                        res.updated_at = time.time()
                    if present:
                        report["fs_present"] += 1
                        seen.setdefault(res.owner_id, set()).add(res.path)
                    else:
                        report["fs_missing"] += 1
                        if len(report["fs_missing_list"]) < cap:
                            report["fs_missing_list"].append(
                                {"owner_id": res.owner_id, "path": res.path,
                                 "resource_key": res.resource_key}
                            )
                    if self._count_refs(s, res.resource_key) == 0:
                        if res.status in ("draft", "official"):
                            res.status = "orphan"
                            res.updated_at = time.time()
                        report["orphans"] += 1
                        if len(report["orphan_list"]) < cap:
                            report["orphan_list"].append(
                                {"owner_id": res.owner_id, "path": res.path,
                                 "status": res.status,
                                 "resource_key": res.resource_key}
                            )

                if full:
                    users = self._known_usernames()
                    for owner_id, root in self._user_file_roots():
                        if not root.exists():
                            continue
                        known = seen.get(owner_id, set())
                        # 台账统一口径是工作区相对（``files/x``），巡检扫的是 files 根
                        # （``x``）。比对必须先换算，否则每轮巡检都把已登记的文件当成
                        # 未入账、重复走一遍补登记。
                        known = {
                            canonical_file_path(k, form="workspace") for k in known
                        }
                        # users 表读不到时 users=None，退回旧口径（全部算 unledgered），
                        # 不能因为查不到用户就把真用户的文件划成无主。
                        unowned_owner = users is not None and owner_id not in users
                        for f in root.rglob("*"):
                            if not f.is_file():
                                continue
                            rel = f.relative_to(root).as_posix()
                            if NOISE_DIR_PARTS.intersection(
                                f.relative_to(root).parts
                            ):
                                report["noise_skipped"] += 1
                                continue
                            # 台账存量行有两种口径：规范的工作区相对
                            # （``files/x.md``）与历史的 files 根相对裸路径
                            # （``x.md``）。判"已登记"必须两种都认，否则补扫
                            # 每轮都把同一批老文件重新登记一遍。
                            if rel in known or canonical_file_path(
                                rel, form="files_root"
                            ) in known:
                                continue
                            if unowned_owner:
                                report["unowned"] += 1
                                if len(report["unowned_list"]) < cap:
                                    report["unowned_list"].append(
                                        {"owner_id": owner_id, "path": rel}
                                    )
                                continue
                            report["unledgered"] += 1
                            if len(report["unledgered_list"]) < cap:
                                report["unledgered_list"].append(
                                    {"owner_id": owner_id, "path": rel}
                                )
                            if backfill and len(pending) < BACKFILL_CAP:
                                pending.append((owner_id, rel))

            # ── 台账跟随移动 / 失效 / 补标题（各自独立事务）───────────
            # 顺序固定：先搬家（文件还在，只是换了位置）→ 再判死（真没了）→
            # 最后补标题。反过来会把"移动"误判成"删除"。
            # 三段各自兜底：任何一段炸了都不能把整份巡检报告一起带走。
            try:
                if relocate:
                    rep = self._relocate_missing(cap=cap)
                    report["relocated"] = rep["relocated"]
                    report["relocated_list"] = rep["relocated_list"]
            except Exception:
                logger.exception("ledger: 台账跟随移动失败")
            try:
                rep = self._expire_missing(
                    ttl_sec=(
                        LEDGER_MISSING_TTL_SEC
                        if expire_after is None
                        else float(expire_after)
                    ),
                    cap=cap,
                )
                report["expired"] = rep["expired"]
                report["expired_list"] = rep["expired_list"]
            except Exception:
                logger.exception("ledger: 台账失效判定失败")
            try:
                report["titled"] = self._backfill_titles()
            except Exception:
                logger.exception("ledger: 台账标题补齐失败")

            # 补登记放在外层 session 之外：register() 自带一个 session，
            # 在巡检事务里嵌套开第二个 session 会把锁顺序搞乱。
            if backfill and pending:
                for owner_id, rel in pending:
                    key = self.register(
                        owner_scope="user",
                        owner_id=owner_id,
                        kind="file",
                        path=rel,
                        title=Path(rel).name,
                        source="backfill",
                        # 巡检扫的是 files 根，口径与钩子一致。
                        path_form="files_root",
                    )
                    if key:
                        report["backfilled"] += 1
                logger.info(
                    "resource sweep backfilled %d legacy file(s)", report["backfilled"]
                )
            return report
        except Exception as exc:  # pragma: no cover - defensive
            logger.debug("resource ledger sweep failed (ignored): %s", exc)
            return report

    def _user_file_roots(self):
        """Yield (username, files_root) for every workspace on disk.

        系统目录（``workspaces/system``，放评测报告等）直接跳过；评测沙箱
        ``eval_*``、agent 工作区、已删除账号的残留由 ``_known_usernames()`` 在
        巡检里划成 ``unowned``，不在这里硬删。
        """
        if not self._ws.exists():
            return
        for d in sorted(self._ws.iterdir()):
            if not d.is_dir():
                continue
            if d.name in NON_USER_WORKSPACE_DIRS or d.name in NOISE_DIR_PARTS:
                continue
            yield d.name, d / "files"

    def _known_usernames(self) -> Optional[set[str]]:
        """用户表里的用户名；读不到返回 ``None``（调用方退回旧口径）。

        作用是把"有主但没台账行的文件"和"根本不是用户的工作区目录"分开：后者
        补登记等于凭空造 owner。
        """
        try:
            with get_session() as s:
                return set(s.execute(select(User.username)).scalars().all())
        except Exception as exc:  # pragma: no cover - defensive
            logger.debug("resource ledger user lookup failed (ignored): %s", exc)
            return None

    # ── read ──────────────────────────────────────────────────────────

    def list_resources(
        self,
        *,
        owner_scope: str,
        owner_id: str,
        kind: Optional[str] = None,
        status: Optional[str] = None,
        chat_id: Optional[str] = None,
        limit: int = 50,
        offset: int = 0,
    ) -> list[dict]:
        """Resources with derived ref counts. Never raises (returns []).

        ``chat_id`` filters through ``resource_refs`` (the only source of
        reference truth) instead of a denormalised column: a resource shows up
        for a chat only if that chat actually references it.
        """
        try:
            with get_session() as s:
                stmt = select(Resource).where(
                    Resource.owner_scope == owner_scope
                ).where(Resource.owner_id == owner_id)
                # 软删行不进默认清单（与 memories 的 deleted_at 惯例一致）。
                stmt = stmt.where(Resource.deleted_at.is_(None))
                if kind:
                    stmt = stmt.where(Resource.kind == kind)
                if status:
                    stmt = stmt.where(Resource.status == status)
                if chat_id:
                    ref_keys = (
                        select(ResourceRef.resource_key)
                        .where(ResourceRef.referrer_kind == "chat")
                        .where(ResourceRef.referrer_id == chat_id)
                    )
                    stmt = stmt.where(Resource.resource_key.in_(ref_keys))
                stmt = stmt.order_by(Resource.last_seen_at.desc()).limit(limit).offset(offset)
                rows = s.execute(stmt).scalars().all()
                out = []
                for r in rows:
                    d = r.to_dict()
                    d["ref_count"] = self._count_refs(s, r.resource_key)
                    out.append(d)
                return out
        except Exception as exc:  # pragma: no cover - defensive
            logger.debug("resource ledger list failed (ignored): %s", exc)
            return []

    def count_resources_for_chat(
        self,
        *,
        owner_scope: str,
        owner_id: str,
        chat_id: str,
        include_deleted: bool = False,
    ) -> int:
        """Count of **distinct resources** referenced by one chat.

        与 ``list_resources_for_chat`` 同一份合并口径 —— 计数与清单必须同源，
        否则前端资源条会出现「折叠行写 17、展开只有 12 条」。
        """
        return len(
            self._chat_resource_rows(
                owner_scope=owner_scope,
                owner_id=owner_id,
                chat_id=chat_id,
                include_deleted=include_deleted,
            )
        )

    #: 同一资源多条引用时取哪个角色显示（越靠前越"强"：产出 > 附件 > 导出 > 引用）
    _CHAT_ROLE_PRIORITY = {"producer": 0, "attachment": 1, "export": 2, "reference": 3}

    def _chat_resource_rows(
        self,
        *,
        owner_scope: str,
        owner_id: str,
        chat_id: str,
        fetch_cap: int = 2000,
        include_deleted: bool = False,
    ) -> list[dict]:
        """本会话引用的资源，**已按 (kind, 规范路径) 合并成一行**。

        合并是必须的，不是锦上添花：台账历史上存在两种路径口径（文件钩子写
        files 根相对 ``x.md``，采集器写工作区相对 ``files/x.md``），同一文件
        算出两个 key、留下两行。写入口已统一换算，**存量行**还在库里，读侧不
        合并就会在资源条里出现「同一文件两条、其中一条显示已删除」。合并规则：
          - 键：``(kind, canonical_file_path(path, form="workspace"))``
          - 角色：取最强（producer 优先）
          - ``ref_count``：各 key 的引用数求和
          - 时间：取最新
        ``fetch_cap`` 是防御性上限（合并需要全量行，不能先分页再合并）。

        Never raises (returns []).
        """
        if not chat_id:
            return []
        try:
            with get_session() as s:
                stmt = (
                    select(Resource, ResourceRef.role)
                    .join(ResourceRef, ResourceRef.resource_key == Resource.resource_key)
                    .where(Resource.owner_scope == owner_scope)
                    .where(Resource.owner_id == owner_id)
                    .where(ResourceRef.referrer_kind == "chat")
                    .where(ResourceRef.referrer_id == chat_id)
                    .limit(fetch_cap)
                )
                # 软删行默认不出（与 memories 惯例一致）；会话面板要灰显
                # 「已删除」，由调用方显式 include_deleted=True 带出。
                if not include_deleted:
                    stmt = stmt.where(Resource.deleted_at.is_(None))
                owner_dir = self._ws / owner_id
                merged: dict[tuple[str, str], dict] = {}
                for r, role in s.execute(stmt).all():
                    d = r.to_dict()
                    kind = str(d.get("kind") or "")
                    raw = str(d.get("path") or "")
                    # 合并键必须与端点对外给的口径一致：workspace_relative_path
                    # 会把存量裸路径补成 ``files/…``，采集器写的本来就是 ``files/…``
                    # —— 同一口径才合得起来（canonical_file_path 补不出 media/ 前缀）。
                    norm = (
                        workspace_relative_path(raw, owner_dir)
                        if kind == "file"
                        else raw
                    )
                    d["path"] = norm
                    key = (kind, norm)
                    prev = merged.get(key)
                    if prev is None:
                        d["ref_count"] = self._count_refs(s, r.resource_key)
                        d["role"] = role
                        merged[key] = d
                        continue
                    # 同资源另一行：角色取强、引用数求和、时间取新
                    if self._CHAT_ROLE_PRIORITY.get(
                        role, 9
                    ) < self._CHAT_ROLE_PRIORITY.get(prev["role"], 9):
                        prev["role"] = role
                    prev["ref_count"] = int(prev.get("ref_count") or 0) + self._count_refs(
                        s, r.resource_key
                    )
                    for field in ("last_seen_at", "updated_at", "first_seen_at"):
                        newer, older = d.get(field), prev.get(field)
                        if field == "first_seen_at":
                            if newer and (not older or newer < older):
                                prev[field] = newer
                        elif newer and (not older or newer > older):
                            prev[field] = newer
                rows = list(merged.values())
                rows.sort(key=lambda x: (x.get("last_seen_at") or 0), reverse=True)
                return rows
        except Exception as exc:  # pragma: no cover - defensive
            logger.debug("chat resource list failed (ignored): %s", exc)
            return []

    def list_resources_for_chat(
        self,
        *,
        owner_scope: str,
        owner_id: str,
        chat_id: str,
        limit: int = 200,
        offset: int = 0,
        include_deleted: bool = False,
    ) -> list[dict]:
        """Resources referenced by one chat, **with that chat's ref role**.

        ``role`` (producer / reference) is a property of the *reference*, not
        of the resource — the same file produced by chat A is merely cited by
        chat B. ``list_resources`` cannot express that (it returns resource
        rows), so the chat resource panel uses this join instead: one row per
        **resource**（同资源多口径的存量行已合并），carrying the strongest role
        this chat has on it.

        Never raises (returns []).
        """
        rows = self._chat_resource_rows(
            owner_scope=owner_scope,
            owner_id=owner_id,
            chat_id=chat_id,
            include_deleted=include_deleted,
        )
        if offset:
            rows = rows[offset:]
        if limit:
            rows = rows[:limit]
        return rows

    def count_resources(
        self,
        *,
        owner_scope: str,
        owner_id: str,
        kind: Optional[str] = None,
        status: Optional[str] = None,
        chat_id: Optional[str] = None,
    ) -> int:
        """Total matching rows (pre-pagination). Filters mirror ``list_resources``.

        The paginated read面 returns ``limit`` rows; the UI needs the unpaginated
        total to render "还有 N 项未加载". If the two filter sets ever diverge the
        tail row lies, so this method is deliberately a copy of the same clauses.
        """
        try:
            with get_session() as s:
                stmt = select(func.count()).select_from(Resource).where(
                    Resource.owner_scope == owner_scope
                ).where(Resource.owner_id == owner_id).where(
                    Resource.deleted_at.is_(None)
                )
                if kind:
                    stmt = stmt.where(Resource.kind == kind)
                if status:
                    stmt = stmt.where(Resource.status == status)
                if chat_id:
                    ref_keys = (
                        select(ResourceRef.resource_key)
                        .where(ResourceRef.referrer_kind == "chat")
                        .where(ResourceRef.referrer_id == chat_id)
                    )
                    stmt = stmt.where(Resource.resource_key.in_(ref_keys))
                return int(s.execute(stmt).scalar() or 0)
        except Exception as exc:  # pragma: no cover - defensive
            logger.debug("resource ledger count failed (ignored): %s", exc)
            return 0

    def stats(self, *, owner_scope: str, owner_id: str) -> dict:
        """Status/kind breakdown plus orphan and FS-missing counts."""
        try:
            with get_session() as s:
                rows = s.execute(
                    select(Resource)
                    .where(Resource.owner_scope == owner_scope)
                    .where(Resource.owner_id == owner_id)
                    .where(Resource.deleted_at.is_(None))
                ).scalars().all()
                by_status: dict[str, int] = {}
                by_kind: dict[str, int] = {}
                orphans = 0
                for r in rows:
                    by_status[r.status] = by_status.get(r.status, 0) + 1
                    by_kind[r.kind] = by_kind.get(r.kind, 0) + 1
                    if self._count_refs(s, r.resource_key) == 0:
                        orphans += 1
                return {
                    "total": len(rows),
                    "by_status": by_status,
                    "by_kind": by_kind,
                    "orphans": orphans,
                    "fs_missing": sum(1 for r in rows if r.fs_present == 0),
                }
        except Exception as exc:  # pragma: no cover - defensive
            logger.debug("resource ledger stats failed (ignored): %s", exc)
            return {"total": 0, "by_status": {}, "by_kind": {}, "orphans": 0, "fs_missing": 0}


_LEDGER: Optional[ResourceLedger] = None


def get_resource_ledger() -> ResourceLedger:
    global _LEDGER
    if _LEDGER is None:
        _LEDGER = ResourceLedger()
    return _LEDGER
