# -*- coding: utf-8 -*-
"""``file`` 资源面适配器 —— 只读清单面（``ResourceLedger``）+ FS 补扫。

**方向冻结**：消费面只读清单面，绝不改写。FS 是真相源，台账是可重建镜像。

检索顺序刻意是"台账优先、FS 补扫"：

* 台账行带 status / 引用计数 / 归属，是治理视角的权威（R1 的产出）。
* 历史存量文件（台账上线前产生的）在台账里没有行，只扫台账会让智能体
  在自己的工作区里"看不见自己的文件"——这是不可接受的体验。补扫把这些
  标成 ``ledgered=False``，让智能体知道"这文件存在，但还没进治理清单"。

``fetch()`` 必须做**路径遍历防护**：``ref`` 来自模型输入，``../`` 拼接能读出
别人的工作区。解析后必须落在 owner 的 files 根内。
"""

from __future__ import annotations

import logging
from pathlib import Path

from ...foundation.resource_ledger import (
    NOISE_DIR_PARTS,
    canonical_file_path,
)
from .contract import (
    MAX_DISCOVER_ITEMS,
    MAX_FETCH_CHARS,
    MAX_FS_SCAN_ITEMS,
    Content,
    Hit,
    ResourceAdapter,
    ResourceMeta,
    score_match,
)

logger = logging.getLogger(__name__)

_TEXT_SUFFIXES = {
    ".md", ".txt", ".py", ".js", ".ts", ".tsx", ".jsx", ".json", ".yaml", ".yml",
    ".toml", ".csv", ".tsv", ".html", ".css", ".sql", ".sh", ".ini", ".env", ".log",
}

#: 可列出、不可直接 ``fetch()`` 的文档/图片后缀。
#: 列出是为了让智能体"看见自己的文件"——工作区里占大头的就是 docx/pdf/图片，
#: 只扫文本后缀会让智能体在自己的工作区里瞎掉（不可接受的体验）。
#: 取内容走 ``doc_reader``（文档）/ ``view_image``（图片），不在本适配器里硬啃二进制。
_DOC_SUFFIXES = {
    ".docx", ".doc", ".pdf", ".xlsx", ".xls", ".pptx", ".ppt",
    ".png", ".jpg", ".jpeg", ".gif", ".bmp", ".webp", ".svg",
}

#: 扫描时跳过的噪音目录（这些目录里的文件不是用户的"资源"，占了配额会让
#: 真正的文档被挤出清单——实测 .temp 里的脚本能吃掉整个扫描预算）。
#: 口径与巡检面共用同一份定义，避免两边一个把 .trash 当资源、另一个不当。
_SKIP_DIR_PARTS = NOISE_DIR_PARTS

#: 文档与文本各自的扫描配额。文档单独配额，保证"看得见自己的文档"。
_DOC_QUOTA = 20
_TEXT_QUOTA = 40

#: 后缀 → 该用哪个工具取内容。
_READER_BY_SUFFIX = {
    ".docx": "doc_reader", ".doc": "doc_reader", ".pdf": "doc_reader",
    ".xlsx": "doc_reader", ".xls": "doc_reader", ".pptx": "doc_reader",
    ".ppt": "doc_reader",
    ".png": "view_image", ".jpg": "view_image", ".jpeg": "view_image",
    ".gif": "view_image", ".bmp": "view_image", ".webp": "view_image",
    ".svg": "view_image",
}


def _current_owner() -> str:
    """当前资源归属者（用户名）。无上下文时返回空串（适配器自动哑火）。"""
    try:
        from ...config.session_context import get_current_user_id, get_current_username

        uid = get_current_user_id()
        if uid:
            return str(uid)
        name = get_current_username()
        if name:
            return str(name)
    except Exception:  # pragma: no cover - defensive
        pass
    return ""


def _files_root(owner_id: str) -> Path:
    from ...constant import WORKSPACES_DIR

    return WORKSPACES_DIR / owner_id / "files"


def _safe_rel(rel: str) -> str:
    """归一化 ``ref``，拒绝绝对路径与 ``..`` 逃逸。"""
    rel = (rel or "").strip().replace("\\", "/")
    if not rel:
        return ""
    if rel.startswith("/") or rel.startswith("~"):
        return ""
    parts = [p for p in rel.split("/") if p]
    if any(p == ".." for p in parts):
        return ""
    return "/".join(parts)


class FileAdapter(ResourceAdapter):
    name = "file"

    def __init__(self, ledger: object | None = None) -> None:
        self._ledger = ledger

    def _get_ledger(self):
        if self._ledger is None:
            from ...foundation.resource_ledger import get_resource_ledger

            self._ledger = get_resource_ledger()
        return self._ledger

    async def discover(self) -> list[ResourceMeta]:
        owner = _current_owner()
        if not owner:
            return []
        metas: list[ResourceMeta] = []
        paths: set[str] = set()

        # ── 1. 台账行（权威：带 status / 引用计数） ──────────────────
        try:
            rows = self._get_ledger().list_resources(
                owner_scope="user",
                owner_id=owner,
                kind="file",
                limit=MAX_DISCOVER_ITEMS,
            )
            for r in rows:
                rel = str(r.get("path") or "")
                paths.add(rel)
                metas.append(
                    ResourceMeta(
                        kind="file",
                        ref=rel,
                        title=str(r.get("title") or Path(rel).name),
                        summary=(
                            f"status={r.get('status')} refs={r.get('ref_count')} "
                            f"size={r.get('size_bytes', 0)}"
                        ),
                        status=str(r.get("status") or ""),
                        owner_id=owner,
                        extra={
                            "ledgered": True,
                            "fs_present": int(r.get("fs_present", 1)),
                            "ref_count": int(r.get("ref_count", 0)),
                        },
                    )
                )
        except Exception as exc:  # pragma: no cover - defensive
            logger.debug("file adapter ledger read failed (ignored): %s", exc)

        # ── 2. FS 补扫（台账未覆盖的历史文件） ───────────────────────
        root = _files_root(owner)
        if root.exists():
            docs: list[ResourceMeta] = []
            texts: list[ResourceMeta] = []
            for f in sorted(root.rglob("*")):
                if not f.is_file():
                    continue
                rel_parts = f.relative_to(root).parts
                if any(p in _SKIP_DIR_PARTS for p in rel_parts):
                    continue
                suffix = f.suffix.lower()
                is_doc = suffix in _DOC_SUFFIXES
                is_text = suffix in _TEXT_SUFFIXES
                if not is_doc and not is_text:
                    continue
                rel = str(f.relative_to(root)).replace("\\", "/")
                # 台账统一口径是工作区相对（register 落库为 "files/xxx"），而本扫描根
                # 就是 files/ 目录，rel 少了 "files/" 前缀。直接拿 rel 比对台账永远
                # 不命中 → 已入账的文件被当成"未入账"重复上报，ref 也两套口径混用。
                canon = canonical_file_path(rel, form="files_root")
                if canon in paths:
                    continue
                reader = _READER_BY_SUFFIX.get(suffix)
                meta = ResourceMeta(
                    kind="file",
                    ref=canon,
                    title=f.name,
                    summary=(
                        f"size={f.stat().st_size} (未入台账)"
                        if is_text
                        else f"size={f.stat().st_size} (未入台账, 用 {reader} 读取)"
                    ),
                    status="unledgered",
                    owner_id=owner,
                    extra={"ledgered": False, "readable": is_text, "reader": reader},
                )
                if is_doc:
                    if len(docs) < _DOC_QUOTA:
                        docs.append(meta)
                elif len(texts) < _TEXT_QUOTA:
                    texts.append(meta)
                if len(docs) >= _DOC_QUOTA and len(texts) >= _TEXT_QUOTA:
                    break
            # 文档排在前面：预算被吃掉时先丢文本，不能先丢文档
            metas.extend(docs)
            metas.extend(texts)
        return metas[:MAX_DISCOVER_ITEMS]

    async def search(self, query: str, limit: int = 10) -> list[Hit]:
        hits: list[Hit] = []
        for m in await self.discover():
            hay = f"{m.title} {m.ref} {m.summary}"
            s = score_match(query, hay)
            if s > 0:
                hits.append(Hit(meta=m, score=s, snippet=m.summary))
        hits.sort(key=lambda h: (-h.score, h.meta.ref))
        return hits[: max(1, min(int(limit), MAX_DISCOVER_ITEMS))]

    async def fetch(self, ref: str) -> Content:
        owner = _current_owner()
        rel = _safe_rel(ref)
        if not owner or not rel:
            return Content(
                kind="file",
                ref=ref,
                text="",
                meta={"error": "ref 非法（拒绝绝对路径与 .. 逃逸）或无当前用户上下文"},
            )
        root = _files_root(owner)
        target = (root / rel).resolve()
        if not str(target).startswith(str(root.resolve())):
            return Content(
                kind="file",
                ref=ref,
                text="",
                meta={"error": "ref 解析后越出 owner 工作区，已拒绝"},
            )
        if not target.exists() or not target.is_file():
            return Content(
                kind="file",
                ref=ref,
                text="",
                meta={"error": f"文件不存在: {rel}"},
            )
        suffix = target.suffix.lower()
        if suffix in _DOC_SUFFIXES:
            # 二进制文档不在本适配器里硬啃——指路到对的读取工具，
            # 免得模型拿到一坨乱码后继续往下编。
            return Content(
                kind="file",
                ref=rel,
                text="",
                meta={
                    "error": f"该格式（{suffix}）不由本适配器读取",
                    "reader": _READER_BY_SUFFIX.get(suffix),
                    "hint": f"用 {_READER_BY_SUFFIX.get(suffix)} 工具读取 {rel}",
                },
            )
        try:
            raw = target.read_text(encoding="utf-8", errors="replace")
        except Exception as exc:
            return Content(
                kind="file",
                ref=ref,
                text="",
                meta={"error": f"读取失败（可能是二进制文件）: {exc}"},
            )
        truncated = len(raw) > MAX_FETCH_CHARS
        return Content(
            kind="file",
            ref=rel,
            text=raw[:MAX_FETCH_CHARS],
            truncated=truncated,
            meta={"path": str(target), "size": target.stat().st_size},
        )
