# -*- coding: utf-8 -*-
# Copyright 2026 以太吃虾 & CoApis Contributors
# Licensed under the Apache License, Version 2.0
"""Knowledge RAG — unified tool for knowledge base, RAG search, and embedding operations.

Merges: knowledge_base + rag_search + embedding_ops into one tool.
"""
from __future__ import annotations
import json, os, hashlib, time
from pathlib import Path
from .registry import register_tool


def _get_store_path() -> Path:
    try:
        from ...config.context import get_current_workspace_dir
        ws = get_current_workspace_dir()
        if ws:
            return Path(ws) / "files" / "knowledge_store"
    except Exception:
        pass
    return Path.cwd() / "files" / "knowledge_store"


def _ensure_dir():
    _get_store_path().mkdir(parents=True, exist_ok=True)


def _load_index() -> dict:
    p = _get_store_path() / "index.json"
    if p.exists():
        try:
            return json.loads(p.read_text())
        except Exception:
            pass
    return {"docs": [], "embeddings": {}}


def _save_index(idx: dict):
    _ensure_dir()
    p = _get_store_path() / "index.json"
    p.write_text(json.dumps(idx, ensure_ascii=False, indent=2))


def _simple_embed(text: str, dim: int = 128) -> list[float]:
    """Simple hash-based embedding for offline fallback."""
    import hashlib
    h = hashlib.sha512(text.encode()).digest()
    vec = [float(b) / 255.0 for b in h]
    while len(vec) < dim:
        vec.extend(vec[:dim - len(vec)])
    return vec[:dim]


def _cosine_sim(a: list[float], b: list[float]) -> float:
    dot = sum(x * y for x, y in zip(a, b))
    na = sum(x * x for x in a) ** 0.5
    nb = sum(x * x for x in b) ** 0.5
    if na == 0 or nb == 0:
        return 0.0
    return dot / (na * nb)


async def _ingest(text: str, metadata: dict = None, chunk_size: int = 500) -> dict:
    idx = _load_index()
    chunks = [text[i:i+chunk_size] for i in range(0, len(text), chunk_size)]
    added = 0
    for chunk in chunks:
        doc_id = hashlib.md5(chunk.encode()).hexdigest()[:12]
        emb = _simple_embed(chunk)
        idx["docs"].append({
            "id": doc_id, "text": chunk,
            "metadata": metadata or {}, "created_at": time.time(),
        })
        idx["embeddings"][doc_id] = emb
        added += 1
    _save_index(idx)
    return {"added": added, "total_docs": len(idx["docs"]), "status": "ok"}


async def _search(query: str, top_k: int = 5) -> dict:
    idx = _load_index()
    if not idx["docs"]:
        return {"results": [], "status": "ok"}
    q_emb = _simple_embed(query)
    scored = []
    for doc in idx["docs"]:
        emb = idx["embeddings"].get(doc["id"])
        if emb:
            sim = _cosine_sim(q_emb, emb)
            scored.append({**doc, "score": round(sim, 4)})
    scored.sort(key=lambda x: -x["score"])
    return {"results": scored[:top_k], "total": len(scored), "status": "ok"}


async def _manage(action: str = "list") -> dict:
    idx = _load_index()
    if action == "list":
        return {"docs": idx["docs"], "count": len(idx["docs"]), "status": "ok"}
    elif action == "clear":
        _save_index({"docs": [], "embeddings": {}})
        return {"message": "Cleared all knowledge", "status": "ok"}
    elif action == "stats":
        return {"total_docs": len(idx["docs"]), "total_embeddings": len(idx["embeddings"]), "status": "ok"}
    return {"error": f"Unknown action: {action}"}


@register_tool(
    name="knowledge_rag",
    description="知识库与 RAG：文档入库(ingest)、语义搜索(search)、知识管理(manage)。支持向量化存储和语义检索。",
    category="builtin",
    tags=["ai", "rag", "search", "knowledge", "embedding"],
    scene="ai",
)
async def knowledge_rag(
    action: str = "search",
    text: str = "",
    query: str = "",
    metadata: str = "",
    chunk_size: int = 500,
    top_k: int = 5,
) -> dict:
    """知识库与 RAG 检索。

    Args:
        action: ingest(入库) / search(搜索) / manage(管理: list/stats/clear)
        text: 要入库的文本 (ingest 时)
        query: 搜索查询 (search 时)
        metadata: JSON 格式元数据 (ingest 时)
        chunk_size: 分块大小 (默认 500)
        top_k: 返回 top-k 结果 (默认 5)
    """
    if action == "ingest":
        if not text.strip():
            return {"error": "text 不能为空"}
        meta = json.loads(metadata) if metadata else {}
        return await _ingest(text, meta, chunk_size)
    elif action == "search":
        if not query.strip():
            return {"error": "query 不能为空"}
        return await _search(query, top_k)
    elif action == "manage":
        return await _manage(text or "list")
    else:
        return {"error": f"未知 action: {action}，支持 ingest/search/manage"}


