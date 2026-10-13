# -*- coding: utf-8 -*-
"""``kb`` 资源面适配器 —— 薄封装现有 foundation 知识库，不重构 KB 本身。

**自动缺席**：``available()`` 在知识库为空时返回 False，注册表就不会把
``kb`` 面挂进检索路由。社区版没有内容时智能体不会看到"有知识库"这个
假象；企业版（Weaviate 填充后）自动出现。这是设计要点，不是兜底。

扫描刻意限量（文件数与单文件读取字节数都有上限）：知识库是长期积累的，
无界扫描会把检索变成 IO 灾难。
"""

from __future__ import annotations

import logging
from pathlib import Path

from .contract import (
    MAX_DISCOVER_ITEMS,
    MAX_FETCH_CHARS,
    Content,
    Hit,
    ResourceAdapter,
    ResourceMeta,
    score_match,
)

logger = logging.getLogger(__name__)

#: 单文件最多读多少字节来找匹配（知识库文件通常很短）。
_SCAN_HEAD_BYTES = 2000


def _kb_root() -> Path:
    """知识库根目录（与 FoundationManager 的 foundation_dir 一致）。"""
    return Path(__file__).resolve().parents[2] / "foundation" / "knowledge_base"


def _md_files(root: Path) -> list[Path]:
    files = []
    for f in sorted(root.rglob("*.md")):
        if f.is_file():
            files.append(f)
    return files


class KbAdapter(ResourceAdapter):
    name = "kb"

    def available(self) -> bool:
        root = _kb_root()
        return root.exists() and bool(_md_files(root))

    async def discover(self) -> list[ResourceMeta]:
        root = _kb_root()
        if not root.exists():
            return []
        metas: list[ResourceMeta] = []
        files = _md_files(root)

        # 分类（目录树两层）——先给导航，再给文件
        cats: set[str] = set()
        for f in files:
            rel = f.relative_to(root)
            if len(rel.parts) > 1:
                cats.add("/".join(rel.parts[:-1]))
        for c in sorted(cats):
            metas.append(
                ResourceMeta(
                    kind="kb",
                    ref=f"category:{c}",
                    title=c,
                    summary=f"分类，含 {sum(1 for f in files if str(f.relative_to(root)).startswith(c))} 篇",
                    status="category",
                    extra={"category": c},
                )
            )

        for f in files[:MAX_DISCOVER_ITEMS]:
            rel = str(f.relative_to(root)).replace("\\", "/")
            metas.append(
                ResourceMeta(
                    kind="kb",
                    ref=rel,
                    title=f.stem,
                    summary=f"size={f.stat().st_size}",
                    status="doc",
                    extra={"path": rel},
                )
            )
        return metas[:MAX_DISCOVER_ITEMS]

    async def search(self, query: str, limit: int = 10) -> list[Hit]:
        root = _kb_root()
        if not root.exists():
            return []
        hits: list[Hit] = []
        for f in _md_files(root)[:MAX_DISCOVER_ITEMS]:
            rel = str(f.relative_to(root)).replace("\\", "/")
            try:
                head = f.read_text(encoding="utf-8", errors="replace")[:_SCAN_HEAD_BYTES]
            except Exception:  # pragma: no cover - defensive
                head = ""
            s = max(score_match(query, f.stem), score_match(query, rel), score_match(query, head))
            if s <= 0:
                continue
            snippet = ""
            for line in head.splitlines():
                if query and (query.lower() in line.lower()):
                    snippet = line.strip()[:200]
                    break
            hits.append(
                Hit(
                    meta=ResourceMeta(
                        kind="kb",
                        ref=rel,
                        title=f.stem,
                        summary=f"size={f.stat().st_size}",
                        status="doc",
                        extra={"path": rel},
                    ),
                    score=s,
                    snippet=snippet,
                )
            )
        hits.sort(key=lambda h: (-h.score, h.meta.ref))
        return hits[: max(1, min(int(limit), MAX_DISCOVER_ITEMS))]

    async def fetch(self, ref: str) -> Content:
        root = _kb_root()
        ref = (ref or "").strip()
        if ref.startswith("category:"):
            cat = ref[len("category:") :]
            cat_dir = root / cat
            if not cat_dir.is_dir():
                return Content(kind="kb", ref=ref, text="", meta={"error": f"分类不存在: {cat}"})
            names = [str(f.relative_to(root)) for f in _md_files(cat_dir)]
            import json

            return Content(
                kind="kb",
                ref=ref,
                text=json.dumps({"category": cat, "docs": names}, ensure_ascii=False, indent=2),
                meta={"count": len(names)},
            )

        rel = ref.replace("\\", "/")
        if not rel or rel.startswith("/") or ".." in rel.split("/"):
            return Content(kind="kb", ref=ref, text="", meta={"error": "ref 非法（拒绝绝对路径与 ..）"})
        target = (root / rel).resolve()
        if not str(target).startswith(str(root.resolve())):
            return Content(kind="kb", ref=ref, text="", meta={"error": "ref 越出知识库根，已拒绝"})
        if not target.is_file():
            return Content(kind="kb", ref=ref, text="", meta={"error": f"文档不存在: {rel}"})
        try:
            raw = target.read_text(encoding="utf-8", errors="replace")
        except Exception as exc:
            return Content(kind="kb", ref=ref, text="", meta={"error": f"读取失败: {exc}"})
        truncated = len(raw) > MAX_FETCH_CHARS
        return Content(
            kind="kb",
            ref=rel,
            text=raw[:MAX_FETCH_CHARS],
            truncated=truncated,
            meta={"path": str(target)},
        )
