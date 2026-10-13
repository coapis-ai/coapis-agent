# -*- coding: utf-8 -*-
"""``mcp`` 资源面适配器 —— 只读，发现已配置的 MCP 服务。

数据源是**当前工作区的 ``agent.json``**（MCP 配置的唯一权威落盘处，
``MCPConfigWatcher`` 就是读它做热加载的）。不依赖运行中的 MCP client，
所以服务离线也能发现——发现面本来就该是配置面，不是连接面。

**脱敏是硬要求**：MCP 配置里 ``env`` / ``headers`` / URL 的 query 串经常
直接就是 API key 与访问令牌。这些值进模型上下文 = 进日志、进缓存、进远端
API 的请求体。本适配器只输出"有哪些服务、什么传输方式"，凭据一律不出现在
输出里。
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit

from .contract import (
    MAX_DISCOVER_ITEMS,
    Content,
    Hit,
    ResourceAdapter,
    ResourceMeta,
    score_match,
)

logger = logging.getLogger(__name__)


def _mask_url(url: str) -> str:
    """去掉 URL 的凭据与 query（令牌常挂在 query 上）。"""
    if not url:
        return ""
    try:
        parts = urlsplit(url)
        netloc = parts.netloc.split("@")[-1]  # 丢掉 user:pass@
        return urlunsplit((parts.scheme, netloc, parts.path, "", ""))
    except Exception:
        return "<url>"


def _workspace_dir() -> Path | None:
    try:
        from ...config.session_context import get_current_workspace_dir

        ws = get_current_workspace_dir()
        if ws:
            return Path(ws)
    except Exception:  # pragma: no cover - defensive
        pass
    return None


def _clients() -> dict:
    ws = _workspace_dir()
    if not ws:
        return {}
    cfg_path = ws / "agent.json"
    if not cfg_path.exists():
        return {}
    try:
        data = json.loads(cfg_path.read_text(encoding="utf-8"))
    except Exception as exc:
        logger.debug("mcp adapter: agent.json unreadable (ignored): %s", exc)
        return {}
    mcp = data.get("mcp") or {}
    clients = mcp.get("clients") or {}
    return clients if isinstance(clients, dict) else {}


class McpAdapter(ResourceAdapter):
    name = "mcp"

    async def discover(self) -> list[ResourceMeta]:
        metas: list[ResourceMeta] = []
        for key, cfg in _clients().items():
            if not isinstance(cfg, dict):
                continue
            transport = str(cfg.get("transport") or "stdio")
            enabled = bool(cfg.get("enabled", True))
            summary = f"transport={transport} enabled={enabled}"
            if transport in ("streamable_http", "sse"):
                summary += f" url={_mask_url(str(cfg.get('url') or ''))}"
            else:
                cmd = str(cfg.get("command") or "")
                args = [str(a) for a in (cfg.get("args") or [])][:6]
                summary += f" command={cmd} {' '.join(args)}".strip()
            metas.append(
                ResourceMeta(
                    kind="mcp",
                    ref=str(key),
                    title=str(cfg.get("name") or key),
                    summary=summary,
                    status="enabled" if enabled else "disabled",
                    extra={
                        "transport": transport,
                        "enabled": enabled,
                        "description": str(cfg.get("description") or ""),
                    },
                )
            )
        return metas[:MAX_DISCOVER_ITEMS]

    async def search(self, query: str, limit: int = 10) -> list[Hit]:
        hits: list[Hit] = []
        for m in await self.discover():
            hay = f"{m.title} {m.ref} {m.extra.get('description', '')}"
            s = score_match(query, hay)
            if s > 0:
                hits.append(Hit(meta=m, score=s, snippet=m.summary))
        hits.sort(key=lambda h: (-h.score, h.meta.ref))
        return hits[: max(1, min(int(limit), MAX_DISCOVER_ITEMS))]

    async def fetch(self, ref: str) -> Content:
        key = (ref or "").strip()
        clients = _clients()
        if key not in clients:
            return Content(kind="mcp", ref=ref, text="", meta={"error": f"MCP 服务不存在: {key}"})
        cfg = clients[key]
        if not isinstance(cfg, dict):
            return Content(kind="mcp", ref=key, text="", meta={"error": "配置项格式异常"})
        body = {
            "key": key,
            "name": cfg.get("name", ""),
            "description": cfg.get("description", ""),
            "transport": cfg.get("transport", "stdio"),
            "enabled": cfg.get("enabled", True),
            "url": _mask_url(str(cfg.get("url") or "")),
            "command": cfg.get("command", ""),
            "args": [str(a) for a in (cfg.get("args") or [])][:20],
            "note": (
                "env/headers 已刻意省略（含凭据）。要调用该服务的工具，"
                "用智能体已注册的 MCP 工具，不要用本适配器执行。"
            ),
        }
        import json as _json

        txt = _json.dumps(body, ensure_ascii=False, indent=2)
        return Content(kind="mcp", ref=key, text=txt, truncated=False, meta={"enabled": body["enabled"]})
