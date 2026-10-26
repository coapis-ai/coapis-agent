# -*- coding: utf-8 -*-
"""会话资源采集器（B1 · 会话引用与产出资源体验）。

一次回答里智能体读了哪些网页、搜到了什么、写了哪个文件——这些事实今天只留在
工具结果里，用户看不到。本模块把它们**归一、去重、登记**，产出两份东西：

1. **台账**（``ResourceLedger``）：``register`` + ``attach_ref(referrer="chat")``
   —— 资源清单是权威账本，刷新页面后仍能按 chat_id 还原引用列表。
2. **本轮上下文**（ContextVar）：同一请求同一任务内流转，外层 ``stream_query``
   在 completed 响应事件上挂 ``event.resources``，前端即时渲染。

设计约束：
* **Fire-and-forget** —— 采集器坏了绝不能坏消息链路；每个入口自吞异常。
* **零 LLM** —— 采集是纯代码解析工具结果，不额外花 token。
* **只登记真实存在的文件** —— 路径必须 ``is_file()``，模型幻觉出来的路径进不了台账。
* **作用域** —— 只登记落在**当前用户工作区**内的文件；``/tmp`` 等区外路径不进台账
  （预览端点 B0 也拒绝它们，两边口径一致）。

采集口径（工具 → 资源）：
    write_file / edit_file / send_file_to_user  → file  (role=producer)
    read_file / doc_reader / grep_search / glob_search → file (role=reference)
    web_search / web_fetch / browser_use        → web   (role=reference)
"""

from __future__ import annotations

import html
import json
import logging
import re
from contextvars import ContextVar
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional

logger = logging.getLogger(__name__)

#: 一轮回答最多透出多少条资源（前端资源条上限 200，台账侧留余量）。
MAX_TURN_RESOURCES = 20

#: 单个工具调用最多贡献多少条资源（glob 一次列 50 个文件不该刷屏）。
MAX_PER_CALL = 8

#: 一次搜索最多暂存多少条候选链接（等正文闸门筛，见 finalize_web_references）。
MAX_SEARCH_CANDIDATES = 15

#: 工具名 → (kind, role)。未列出的工具不采集。
FILE_PRODUCER_TOOLS = frozenset({"write_file", "edit_file", "send_file_to_user"})
FILE_REFERENCE_TOOLS = frozenset(
    {"read_file", "doc_reader", "grep_search", "glob_search", "view_image"}
)
WEB_REFERENCE_TOOLS = frozenset({"web_search", "web_fetch", "browser_use"})

#: 绝对路径形态：至少两段、以常见根目录开头（避免把 "a/b" 这种相对碎片当路径）。
#: 交替项必须**长前缀在前**——``/app`` 排在 ``/apps`` 前会让 ``/apps/ai/...``
#: 被 ``/app`` 吃掉两字符后匹配失败，dev 的真实工作区路径（/apps/ai/coapis-dev/…）
#: 就整条采集不到。
_ABS_PATH_RE = re.compile(
    r"(?P<path>"
    r"(?:/workspaces|/apps|/app|/data|/mnt|/home|/root|/var|/opt|/srv|/tmp|/usr)"
    r"/[^\s'\"`|<>()\[\]]{2,256}"
    r")"
)

#: 行式输出里的路径（glob_search 的 ``path:line: content`` 形态）。
_GLOB_LINE_RE = re.compile(r"^(?P<path>[^\s:]{3,256}):\d+:")

#: 输出文本里的 URL。
_URL_RE = re.compile(r"https?://[^\s'\"`|<>()\[\]]{5,300}")

#: 正文里的 markdown 链接 `[标题](url)` —— 正文闸门的匹配依据。
_MD_LINK_RE = re.compile(r"\[(?P<title>[^\]\n]{1,160})\]\((?P<url>https?://[^)\s]{5,300})\)")

#: 规范化时剥掉的跟踪参数（正文里粘贴链接时这些参数经常丢，不该因此判为未引用）。
_TRACKING_PARAMS = re.compile(r"[?&](utm_[a-z]+|spm|from|ref|ref_src|gclid|scid)=[^&]*")

_TRAILING_PUNCT = ".,;:!?)]}'\"<>，。；：！？）】」"


def _clean_path(raw: str) -> str:
    return raw.rstrip(_TRAILING_PUNCT)


@dataclass
class TurnResources:
    """本轮采集到的资源（去重后按出现顺序）。"""

    chat_id: str = ""
    username: str = ""
    items: list[dict] = field(default_factory=list)
    seen: set[str] = field(default_factory=set)
    #: 搜索/输出里出现过的链接候选，等正文闸门裁决（见 finalize_web_references）
    pending_web: list[dict] = field(default_factory=list)

    def add(self, item: dict) -> bool:
        key = f"{item.get('kind')}::{item.get('ref')}"
        if key in self.seen:
            return False
        if len(self.items) >= MAX_TURN_RESOURCES:
            return False
        self.seen.add(key)
        self.items.append(item)
        return True


_turn_resources_ctx: ContextVar[Optional[TurnResources]] = ContextVar(
    "turn_resources", default=None
)


def begin_turn(chat_id: str, username: str) -> None:
    """Start collecting for this turn (called by the runner before execution)."""
    _turn_resources_ctx.set(TurnResources(chat_id=str(chat_id or ""), username=str(username or "")))


def get_turn_resources() -> Optional[TurnResources]:
    return _turn_resources_ctx.get()


def take_turn_resources() -> list[dict]:
    """Snapshot of what this turn collected (safe to call from the outer stream)."""
    turn = _turn_resources_ctx.get()
    return list(turn.items) if turn is not None else []


# ── 文本抽取 ────────────────────────────────────────────────────────


def _iter_text_chunks(output: Any) -> list[str]:
    """Flatten a tool output (dict / Msg / ToolResponse / str) into text chunks."""
    chunks: list[str] = []
    try:
        if output is None:
            return chunks
        if isinstance(output, str):
            return [output]
        if isinstance(output, (list, tuple)):
            # 块列表（ToolResultBlock.output 的另一种形态）
            for item in output:
                chunks.extend(_iter_text_chunks(item))
            return chunks
        content = None
        if isinstance(output, dict):
            content = output.get("content")
            meta = output.get("metadata")
            if isinstance(meta, dict):
                for k in ("url", "title", "file_path", "path"):
                    v = meta.get(k)
                    if isinstance(v, str) and v:
                        chunks.append(v)
            # 裸 TextBlock / 工具返回里的 "text" 字段
            own_text = output.get("text")
            if isinstance(own_text, str) and own_text:
                chunks.append(own_text)
            # agentscope 的 ToolResultBlock 把结果放在 "output"（str 或块列表），
            # 不是 "content"。post_acting 从 memory 取到的正是这种块。
            outp = output.get("output")
            if outp is not None and output.get("type") == "tool_result":
                chunks.extend(_iter_text_chunks(outp))
        else:
            content = getattr(output, "content", None)
            meta = getattr(output, "metadata", None)
            if isinstance(meta, dict):
                for k in ("url", "title", "file_path", "path"):
                    v = meta.get(k)
                    if isinstance(v, str) and v:
                        chunks.append(v)
        if isinstance(content, str):
            chunks.append(content)
        elif isinstance(content, list):
            for block in content:
                if isinstance(block, dict):
                    for key in ("text", "content", "data"):
                        v = block.get(key)
                        if isinstance(v, str) and v:
                            chunks.append(v)
                else:
                    v = getattr(block, "text", None)
                    if isinstance(v, str) and v:
                        chunks.append(v)
    except Exception:  # pragma: no cover - defensive
        return chunks
    return chunks


def _workspace_root(username: str) -> Optional[Path]:
    if not username:
        return None
    try:
        from ...constant import WORKSPACES_DIR

        # resolve() 与 _normalize_file_path 里的 resolve 同形：/tmp 是符号链接
        # 时，一侧解析一侧不解析会让 relative_to 直接失败（测试里踩过）。
        return (Path(WORKSPACES_DIR) / username).resolve()
    except Exception:  # pragma: no cover - defensive
        return None


def _normalize_file_path(raw: str, workspace: Optional[Path]) -> Optional[str]:
    """Map a tool-reported path to a workspace-relative path, or drop it.

    Only files that **exist** and live **inside the caller's workspace** are
    registered; the preview endpoint (B0) refuses anything else, so keeping the
    same scope here means every link we render is a link that works.

    作用域判定只有一条：**resolve 之后落在当前用户工作区内、且文件真实存在**。
    这条判据天然排除 ``/tmp`` 草稿、跨用户路径、模型幻觉出来的路径，也与预览
    端点（B0）的口径完全一致——工作区外的东西既进不了清单，也点不开。
    （``/tmp`` 前缀不能当判据：测试与部分部署的临时目录就建在 ``/tmp`` 下，
    按字面前缀一刀切会把合法文件全判成区外，dev 实测踩过。）
    """
    raw = _clean_path((raw or "").strip())
    if not raw:
        return None
    if workspace is None:
        return None
    if raw.startswith("file://"):
        raw = raw.replace("file://", "", 1)
    if raw.startswith(("http://", "https://")):
        return None
    try:
        p = Path(raw)
        if not p.is_absolute():
            p = workspace / raw.lstrip("/")
        p = p.resolve()
    except Exception:  # pragma: no cover - defensive
        return None
    try:
        rel = p.relative_to(workspace)
    except ValueError:
        return None
    if not p.is_file():
        return None
    return str(rel)


def _extract_file_paths(text: str, workspace: Optional[Path]) -> list[str]:
    found: list[str] = []
    for m in _ABS_PATH_RE.finditer(text or ""):
        rel = _normalize_file_path(m.group("path"), workspace)
        if rel:
            found.append(rel)
    for line in (text or "").splitlines()[:200]:
        m = _GLOB_LINE_RE.match(line.strip())
        if m:
            rel = _normalize_file_path(m.group("path"), workspace)
            if rel:
                found.append(rel)
    return found


def _extract_urls(text: str) -> list[tuple[str, str]]:
    """Return ``(url, title)`` pairs from a tool output.

    web_search returns JSON with ``results[].title/url``; other outputs only
    carry bare URLs, in which case the URL doubles as the title.
    """
    out: list[tuple[str, str]] = []
    raw = text or ""
    stripped = raw.strip()
    if stripped.startswith("{") and '"results"' in stripped[:400]:
        try:
            data = json.loads(stripped)
            for item in data.get("results", []) or []:
                if not isinstance(item, dict):
                    continue
                url = str(item.get("url") or "")
                title = str(item.get("title") or "")
                if url.startswith(("http://", "https://")):
                    # 搜索聚合器返回 HTML 实体（&amp;/&#39;/&quot;…），不反转义
                    # 会原样入库，前端显示成 `R&amp;D` 这种乱码。
                    title = html.unescape(title).strip() if title else ""
                    out.append((url, title or url))
            if out:
                return out
        except Exception:  # pragma: no cover - defensive
            pass
    for m in _URL_RE.finditer(raw):
        url = _clean_path(m.group(0))
        out.append((url, url))
    return out


# ── 采集主入口 ──────────────────────────────────────────────────────


def collect_from_tool_call(
    tool_call: Any,
    output: Any,
    *,
    chat_id: str = "",
    username: str = "",
) -> list[dict]:
    """Collect resources from one acting step; appends to the turn collector.

    Never raises. Returns the items added by this call.
    """
    added: list[dict] = []
    try:
        turn = _turn_resources_ctx.get()
        if turn is None:
            return added
        tool_name = ""
        tool_input: dict = {}
        try:
            if isinstance(tool_call, dict):
                tool_name = str(tool_call.get("name", ""))
                raw_input = tool_call.get("input") or tool_call.get("arguments")
            else:
                tool_name = str(getattr(tool_call, "name", ""))
                raw_input = getattr(tool_call, "input", None)
            if isinstance(raw_input, str):
                try:
                    raw_input = json.loads(raw_input)
                except Exception:
                    raw_input = {}
            if isinstance(raw_input, dict):
                tool_input = raw_input
        except Exception:  # pragma: no cover - defensive
            return added

        if not tool_name:
            return added

        username = username or turn.username
        chat_id = chat_id or turn.chat_id
        workspace = _workspace_root(username)
        texts = _iter_text_chunks(output)
        blob = "\n".join(texts)

        candidates: list[dict] = []

        if tool_name in FILE_PRODUCER_TOOLS or tool_name in FILE_REFERENCE_TOOLS:
            role = "producer" if tool_name in FILE_PRODUCER_TOOLS else "reference"
            paths: list[str] = []
            for key in ("file_path", "path", "notebook_path"):
                v = tool_input.get(key)
                if isinstance(v, str) and v:
                    rel = _normalize_file_path(v, workspace)
                    if rel:
                        paths.append(rel)
            if tool_name in ("glob_search", "grep_search") or not paths:
                for t in texts:
                    paths.extend(_extract_file_paths(t, workspace))
            seen_local: set[str] = set()
            for rel in paths:
                if rel in seen_local:
                    continue
                seen_local.add(rel)
                candidates.append(
                    {
                        "kind": "file",
                        "ref": rel,
                        "title": Path(rel).name,
                        "role": role,
                        "source": tool_name,
                    }
                )
                if len(candidates) >= MAX_PER_CALL:
                    break

        elif tool_name in WEB_REFERENCE_TOOLS:
            # 闸门（D2-A）：只有智能体**显式访问**的页面（web_fetch / browser_use
            # 传了 url）算"真引用"，立即登记；web_search 返回的十条链接只是候选
            # —— 实测 15 条里只有 2 条被正文引用，全量入库会让台账变成搜索流水账。
            # 候选先攒着，回复写完后由 finalize_web_references 按正文裁决。
            v = tool_input.get("url")
            if isinstance(v, str) and v.startswith(("http://", "https://")):
                candidates.append(
                    {
                        "kind": "web",
                        "ref": v,
                        "title": v,
                        "role": "reference",
                        "source": tool_name,
                    }
                )

            pending: list[tuple[str, str]] = []
            for t in texts:
                pending.extend(_extract_urls(t))
            for url, title in pending:
                if url == v:
                    continue
                if len(turn.pending_web) >= MAX_SEARCH_CANDIDATES:
                    break
                turn.pending_web.append(
                    {
                        "kind": "web",
                        "ref": url,
                        "title": title,
                        "role": "reference",
                        "source": tool_name,
                    }
                )
        else:
            return added

        for item in candidates:
            if not turn.add(item):
                continue
            added.append(item)
            _ledger_register(item, chat_id=chat_id, username=username)

        if added:
            logger.debug(
                "turn resources: +%d from %s (total %d, chat=%s)",
                len(added),
                tool_name,
                len(turn.items),
                chat_id,
            )
    except Exception as exc:  # pragma: no cover - defensive
        logger.debug("resource collection skipped (%s): %s", tool_name, exc)
    return added


#: 正文里 URL 后常紧跟标点（中文正文尤其如此："…/p/1。"），正则不排除就会吞进 URL。
_URL_TRAILING = ".,;:!?、。，；：！？）)】」》”’\"'`"


def _clean_url(u: str) -> str:
    """剥掉 URL 尾部粘连的中英文标点。"""
    return (u or "").rstrip(_URL_TRAILING)


def _norm_url(u: str) -> str:
    """规范化 URL 供正文匹配：去 fragment、去跟踪参数、去尾斜杠、小写域名。

    path 大小写敏感所以不动；跟踪参数（utm_*/spm/from/ref…）在正文里粘贴
    链接时经常被丢掉，不剥会误判成"没引用"。
    """
    u = (u or "").strip().split("#", 1)[0]
    u = _TRACKING_PARAMS.sub("", u)
    u = re.sub(r"[?&]+$", "", u).rstrip("/")
    m = re.match(r"(https?)://([^/]+)(.*)$", u)
    if not m:
        return u
    return f"{m.group(1).lower()}://{m.group(2).lower()}{m.group(3)}"


def _cited_in_body(key: str, cited: dict[str, str]) -> bool:
    """正文里是否引用了这个 URL（精确，或一方是另一方在 /?#&= 边界处的截断）。"""
    if not key:
        return False
    if key in cited:
        return True
    for c in cited:
        if not c:
            continue
        if key.startswith(c) and len(c) >= 12 and (
            len(key) == len(c) or key[len(c)] in "/?#&="
        ):
            return True
        if c.startswith(key) and len(key) >= 12 and (
            len(c) == len(key) or c[len(key)] in "/?#&="
        ):
            return True
    return False


def finalize_web_references(body_text: str) -> int:
    """正文闸门：搜索结果里的链接，只有正文真正引用了才算"引用"。

    回复写完后调用（post_reply 钩子）。候选一律不入台账 —— 命中正文的才登记，
    台账因此与前端展示口径一致（台账是资源清单的权威源）。标题优先用正文里
    markdown 链接的锚文本，比搜索聚合器给的标题干净。返回保留条数。
    """
    turn = _turn_resources_ctx.get()
    if turn is None:
        return 0
    pending = turn.pending_web
    turn.pending_web = []
    if not pending or not body_text:
        return 0

    cited: dict[str, str] = {}
    for m in _MD_LINK_RE.finditer(body_text):
        title = html.unescape(m.group("title")).strip()
        cited.setdefault(_norm_url(_clean_url(m.group("url"))), title)
    for m in _URL_RE.finditer(body_text):
        cited.setdefault(_norm_url(_clean_url(m.group(0))), "")
    if not cited:
        return 0

    kept = 0
    for item in pending:
        key = _norm_url(item.get("ref", ""))
        if not _cited_in_body(key, cited):
            continue
        title = cited.get(key, "")
        if title and len(title) >= 4:
            item["title"] = title
        if not turn.add(item):
            continue
        _ledger_register(item, chat_id=turn.chat_id, username=turn.username)
        kept += 1
    if kept:
        logger.info(
            "web reference gate: kept %d/%d search links cited in reply",
            kept,
            len(pending),
        )
    return kept


def _ledger_register(item: dict, *, chat_id: str, username: str) -> None:
    """Register in the resource ledger and attach the chat as referrer."""
    try:
        from ...foundation.resource_ledger import get_resource_ledger

        ledger = get_resource_ledger()
        key = ledger.register(
            owner_scope="user",
            owner_id=username,
            kind=item["kind"],
            path=item["ref"],
            title=item.get("title"),
            source=f"turn:{item.get('source', '')}",
            # 采集器的 ref 是工作区相对路径（与前端/回答正文同一口径）。
            path_form="workspace",
        )
        if not key:
            return
        item["resource_key"] = key
        if chat_id:
            ledger.attach_ref(
                resource_key=key,
                referrer_kind="chat",
                referrer_id=chat_id,
                role=item.get("role", "reference"),
            )
    except Exception as exc:  # pragma: no cover - defensive
        logger.debug("ledger register skipped: %s", exc)
