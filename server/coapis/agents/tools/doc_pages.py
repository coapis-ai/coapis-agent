"""B3: the paginated document base — parse once, take what you need.
(2026-10-17, 片4-6 施工单 B3)

``doc_reader`` returns a whole document in one string, capped at
``max_chars=100000``.  Measured on dev the same document costs 100,000
characters on the first read and 241,000 on the second, and the 100K cap
truncates silently — the model is told "truncated: true" and nothing about
where it stopped, so it re-reads the whole thing.  Against the calibrated
budget (allowance 215,040 chars) a single read is 46% of the window and a
re-read is 112%: one document is enough to overflow a session.

This module is the base every document consumer reads through:

* **parse once** — the document is parsed into canonical markdown plus a
  block index (docx: headings level ≤ 2, tables; pdf: page; xlsx: sheet with
  row-range sub-blocks; pptx: slide; txt/md: headings, else 6000 chars);
* **persist** — ``<workspace>/.doccache/<key>.md`` plus
  ``<key>.index.json``, keyed by absolute path + mtime + format, so a second
  read costs zero parsing and a re-uploaded file is a new key;
* **take by need** — ``index`` / ``range`` / ``search`` / ``full``, every
  return carrying the cursor (``next: start=<offset>``) so "read the rest"
  is a position, not a guess.

The cap is a *budget*, not a constant: callers pass the per-call allowance
from ``context_budget`` (``READ_CHARS``), and exceeding it is reported as
such — never as a silent truncation.
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

#: Characters per block before it is split (拍板 §6: 6000).
BLOCK_CHARS = 6000
#: Rows per xlsx sub-block when a sheet is bigger than BLOCK_CHARS.
XLSX_ROWS_PER_BLOCK = 200
#: Characters of context around a search hit.
SEARCH_CONTEXT_CHARS = 200
#: Hits reported per search.
SEARCH_MAX_HITS = 20
#: Cache entries kept before the oldest are pruned.
CACHE_MAX_ENTRIES = 100
#: Documents above this size must be read paginated (拍板 §6).
FULL_READ_MAX_CHARS = 200_000

CACHE_DIRNAME = ".doccache"


@dataclass
class DocBlock:
    """One addressable piece of a parsed document."""

    i: int
    kind: str
    title: str
    start: int
    end: int
    meta: dict[str, Any] = field(default_factory=dict)

    @property
    def chars(self) -> int:
        return self.end - self.start

    def as_dict(self) -> dict[str, Any]:
        out = {
            "i": self.i,
            "kind": self.kind,
            "title": self.title,
            "start": self.start,
            "end": self.end,
            "chars": self.chars,
        }
        if self.meta:
            out["meta"] = self.meta
        return out


@dataclass
class ParsedDoc:
    """Canonical markdown plus the block index a document parses into."""

    path: str
    fmt: str
    text: str
    blocks: list[DocBlock]
    key: str
    cached: bool = False

    @property
    def chars(self) -> int:
        return len(self.text)

    def index_rows(self) -> list[dict[str, Any]]:
        return [b.as_dict() for b in self.blocks]


# ── cache ───────────────────────────────────────────────────────────


def _cache_dir(_hint: Path | str | None = None) -> Path:
    """The parse cache lives in the *user's* workspace, never the CWD.

    Multi-user isolation is the point: one user's parsed markdown must not
    be readable through another user's cache directory.
    """
    root = None
    try:
        from ...config.context import get_current_workspace_dir

        root = get_current_workspace_dir()
    except Exception:  # pragma: no cover - context unavailable
        root = None
    base = Path(root) if root else Path(os.getcwd())
    return base / CACHE_DIRNAME


def cache_key(abs_path: str, fmt: str) -> str:
    """Content-addressed key: path + mtime + size + format."""
    st = os.stat(abs_path)
    raw = f"{abs_path}|{int(st.st_mtime_ns)}|{int(st.st_size)}|{fmt}"
    return hashlib.sha1(raw.encode("utf-8", "surrogateescape")).hexdigest()[:24]


def _cache_paths(key: str, cache_dir: Path) -> tuple[Path, Path]:
    return cache_dir / f"{key}.md", cache_dir / f"{key}.index.json"


def _load_cache(key: str, cache_dir: Path) -> ParsedDoc | None:
    md, idx = _cache_paths(key, cache_dir)
    if not (md.is_file() and idx.is_file()):
        return None
    try:
        text = md.read_text(encoding="utf-8")
        meta = json.loads(idx.read_text(encoding="utf-8"))
        blocks = [
            DocBlock(
                i=int(b["i"]),
                kind=str(b["kind"]),
                title=str(b["title"]),
                start=int(b["start"]),
                end=int(b["end"]),
                meta=dict(b.get("meta") or {}),
            )
            for b in meta.get("blocks", [])
        ]
        if not blocks:
            return None
        return ParsedDoc(
            path=str(meta.get("path", "")),
            fmt=str(meta.get("fmt", "")),
            text=text,
            blocks=blocks,
            key=key,
            cached=True,
        )
    except (OSError, ValueError, KeyError, TypeError) as exc:
        logger.debug("doc cache read failed for %s: %s", key, exc)
        return None


def _save_cache(doc: ParsedDoc, cache_dir: Path) -> None:
    try:
        cache_dir.mkdir(parents=True, exist_ok=True)
        md, idx = _cache_paths(doc.key, cache_dir)
        md.write_text(doc.text, encoding="utf-8")
        idx.write_text(
            json.dumps(
                {
                    "path": doc.path,
                    "fmt": doc.fmt,
                    "chars": doc.chars,
                    "blocks": doc.index_rows(),
                },
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )
        _prune_cache(cache_dir)
        doc.cached = True
    except OSError as exc:
        logger.debug("doc cache write failed for %s: %s", doc.key, exc)


def _prune_cache(cache_dir: Path) -> None:
    """Keep the newest ``CACHE_MAX_ENTRIES`` parsed documents."""
    try:
        entries = [p for p in cache_dir.glob("*.md") if p.is_file()]
    except OSError:
        return
    if len(entries) <= CACHE_MAX_ENTRIES:
        return
    entries.sort(key=lambda p: p.stat().st_mtime, reverse=True)
    for stale in entries[CACHE_MAX_ENTRIES:]:
        try:
            stale.unlink()
            index = stale.with_suffix(".index.json")
            if index.is_file():
                index.unlink()
        except OSError:
            continue


# ── block building ──────────────────────────────────────────────────


def _blocks_from_sections(
    sections: list[tuple[str, str, str, dict[str, Any] | None]],
) -> tuple[str, list[DocBlock]]:
    """Join ``(kind, title, text, meta)`` sections into text + blocks.

    Sections are concatenated with blank lines; a block's span is its own
    text inside the joined document, so ``range`` reads exactly one block.
    """
    parts: list[str] = []
    blocks: list[DocBlock] = []
    offset = 0
    for i, (kind, title, text, meta) in enumerate(sections):
        body = text.rstrip()
        if not body:
            continue
        start = offset
        parts.append(body)
        offset += len(body)
        blocks.append(
            DocBlock(
                i=len(blocks),
                kind=kind,
                title=title or f"{kind} {len(blocks) + 1}",
                start=start,
                end=offset,
                meta=meta or {},
            ),
        )
        parts.append("\n\n")
        offset += 2
    return "".join(parts), blocks


def _split_oversized(
    kind: str,
    title: str,
    text: str,
    limit: int = BLOCK_CHARS,
) -> list[tuple[str, str, str, dict[str, Any] | None]]:
    """Cut a section longer than *limit* at line boundaries."""
    if len(text) <= limit:
        return [(kind, title, text, None)]
    lines = text.split("\n")
    out: list[tuple[str, str, str, dict[str, Any] | None]] = []
    chunk: list[str] = []
    size = 0
    part = 0

    def _emit(piece: str) -> None:
        nonlocal chunk, size, part
        part += 1
        out.append(
            (kind, f"{title} · 第{part}段", piece, {"part": part}),
        )
        chunk, size = [], 0

    for line in lines:
        if len(line) > limit:
            # A single line longer than the budget (minified text, one-line
            # CSV): cut it by characters, since there is no boundary to cut.
            if chunk:
                _emit("\n".join(chunk))
            for offset in range(0, len(line), limit):
                _emit(line[offset : offset + limit])
            continue
        if chunk and size + len(line) + 1 > limit:
            _emit("\n".join(chunk))
        chunk.append(line)
        size += len(line) + 1
    if chunk:
        _emit("\n".join(chunk))
    return out


_HEADING_RE = re.compile(r"^(#{1,3})\s+(.*)$")


def _blocks_from_markdown(text: str) -> list[tuple[str, str, str, Any]]:
    """Split plain markdown/text at level-1..3 headings, else by size."""
    lines = text.split("\n")
    sections: list[tuple[str, str, str, Any]] = []
    buf: list[str] = []
    title = "开头"
    size = 0
    for line in lines:
        match = _HEADING_RE.match(line)
        if match and (buf and size >= 200 or not buf and sections):
            sections.append((("heading"), title, "\n".join(buf), None))
            buf, size = [], 0
            title = match.group(2).strip()[:120]
            buf.append(line)
            size += len(line) + 1
            continue
        if match and not sections and not buf:
            title = match.group(2).strip()[:120]
        buf.append(line)
        size += len(line) + 1
        if size >= BLOCK_CHARS:
            sections.append(("heading", title, "\n".join(buf), None))
            buf, size = [], 0
            title = f"{title} · 续"
    if buf:
        sections.append(("heading", title, "\n".join(buf), None))
    if not sections:
        sections = [("text", "全文", text, None)]
    out: list[tuple[str, str, str, Any]] = []
    for kind, sec_title, sec_text, meta in sections:
        out.extend(_split_oversized(kind, sec_title, sec_text))
    return out


# ── format parsers ──────────────────────────────────────────────────

_DOCX_HEADING = re.compile(r"^(heading|标题)\s*(\d+)", re.IGNORECASE)


def _docx_sections(path: str) -> list[tuple[str, str, str, Any]]:
    """docx → heading sections (level ≤ 2) with tables kept inline."""
    from docx import Document
    from docx.document import Document as _DocType
    from docx.oxml.table import CT_Tbl
    from docx.oxml.text.paragraph import CT_P
    from docx.table import Table
    from docx.text.paragraph import Paragraph

    doc = Document(path)

    def _iter_blocks(parent):
        parent_elm = parent.element.body if isinstance(parent, _DocType) else parent._tc
        for child in parent_elm.iterchildren():
            if isinstance(child, CT_P):
                yield Paragraph(child, parent)
            elif isinstance(child, CT_Tbl):
                yield Table(child, parent)

    def _table_text(table: Table) -> str:
        rows: list[str] = []
        for row in table.rows:
            cells = [c.text.replace("\n", " ").strip() for c in row.cells]
            line = " | ".join(cells).strip(" |")
            if line:
                rows.append(line)
        return "\n".join(rows)

    sections: list[tuple[str, str, str, Any]] = []
    buf: list[str] = []
    title = "开头"

    def _flush() -> None:
        nonlocal buf
        text = "\n".join(buf).strip()
        if text:
            sections.append(("heading", title, text, None))
        buf = []

    for block in _iter_blocks(doc):
        if isinstance(block, Paragraph):
            text = block.text.strip()
            if not text:
                continue
            style = (block.style.name or "") if block.style else ""
            match = _DOCX_HEADING.match(style.strip())
            level = int(match.group(2)) if match else None
            if level is not None and level <= 2:
                _flush()
                title = text[:120]
                buf.append(f"{'#' * min(level, 3)} {text}")
            else:
                buf.append(text)
        else:
            tbl = _table_text(block)
            if tbl:
                buf.append(tbl)
    _flush()

    # Headers / footers (deduped) as their own block.
    seen: set[str] = set()
    extras: list[str] = []
    for section in doc.sections:
        for label, container in (("页眉", section.header), ("页脚", section.footer)):
            if container.is_linked_to_previous:
                continue
            chunk = [p.text.strip() for p in container.paragraphs if p.text.strip()]
            for table in container.tables:
                tbl = _table_text(table)
                if tbl:
                    chunk.append(tbl)
            text = "\n".join(chunk).strip()
            if text and text not in seen:
                seen.add(text)
                extras.append(f"【{label}】{text}")
    if extras:
        sections.append(("heading", "页眉页脚", "\n".join(extras), None))

    out: list[tuple[str, str, str, Any]] = []
    for kind, sec_title, sec_text, meta in sections:
        out.extend(_split_oversized(kind, sec_title, sec_text))
    return out


def _pdf_sections(path: str) -> list[tuple[str, str, str, Any]]:
    """pdf → one block per page (fitz when available)."""
    try:
        import fitz  # PyMuPDF

        with fitz.open(path) as doc:
            return [
                (
                    "page",
                    f"第{number}页",
                    page.get_text("text").strip(),
                    {"page": number},
                )
                for number, page in enumerate(doc, start=1)
            ]
    except ImportError:
        logger.debug("pymupdf unavailable, paginating pdf via pymupdf4llm")
    except Exception as exc:
        logger.warning("pymupdf page split failed for %s: %s", path, exc)

    import pymupdf4llm

    md = pymupdf4llm.to_markdown(path)
    pages = md.split("\x0c") if "\x0c" in md else [md]
    if len(pages) < 2:
        pages = md.split("\n\n# Page")
    return [
        ("page", f"第{number}页", page.strip(), {"page": number})
        for number, page in enumerate(pages, start=1)
        if page.strip()
    ]


def _pptx_sections(path: str) -> list[tuple[str, str, str, Any]]:
    """pptx → one block per slide (shapes, tables, notes)."""
    from pptx import Presentation
    from pptx.enum.shapes import MSO_SHAPE_TYPE

    prs = Presentation(path)

    def _shape_text(shapes) -> list[str]:
        out: list[str] = []
        for shape in shapes:
            if shape.shape_type == MSO_SHAPE_TYPE.GROUP:
                out.extend(_shape_text(shape.shapes))
                continue
            if getattr(shape, "has_table", False):
                for row in shape.table.rows:
                    cells = [c.text.strip() for c in row.cells]
                    line = " | ".join(cells).strip(" |")
                    if line:
                        out.append(line)
                continue
            if getattr(shape, "has_text_frame", False):
                text = shape.text_frame.text.strip()
                if text:
                    out.append(text)
        return out

    sections: list[tuple[str, str, str, Any]] = []
    for number, slide in enumerate(prs.slides, start=1):
        parts = _shape_text(slide.shapes)
        if slide.has_notes_slide:
            notes = slide.notes_slide.notes_text_frame.text.strip()
            if notes:
                parts.append(f"【备注】{notes}")
        title = ""
        if slide.shapes:
            for shape in slide.shapes:
                if getattr(shape, "has_text_frame", False):
                    candidate = shape.text_frame.text.strip()
                    if candidate:
                        title = candidate.splitlines()[0][:80]
                        break
        sections.append(
            (
                "slide",
                f"第{number}页{': ' + title if title else ''}",
                "\n".join(parts),
                {"slide": number},
            ),
        )
    return sections


def _xlsx_sections(path: str) -> list[tuple[str, str, str, Any]]:
    """xlsx → one block per sheet; a big sheet splits by row ranges."""
    import openpyxl

    wb = openpyxl.load_workbook(path, read_only=True, data_only=True)
    formula_wb = None
    sections: list[tuple[str, str, str, Any]] = []
    for name in wb.sheetnames:
        ws = wb[name]
        rows: list[str] = []
        for r_idx, row in enumerate(ws.iter_rows(values_only=True), start=1):
            cells: list[str] = []
            for c_idx, value in enumerate(row, start=1):
                if value is not None:
                    cells.append(str(value))
                    continue
                if formula_wb is None:
                    formula_wb = openpyxl.load_workbook(
                        path,
                        read_only=False,
                        data_only=False,
                    )
                raw = formula_wb[name].cell(row=r_idx, column=c_idx).value
                cells.append("" if raw is None else str(raw))
            line = " | ".join(cells).strip(" |")
            if line.strip():
                rows.append(line)
        if not rows:
            continue
        header = rows[0]
        body = rows[1:]
        chunks: list[tuple[str, str, str, Any]] = []
        part = 0
        for offset in range(0, len(body), XLSX_ROWS_PER_BLOCK):
            part += 1
            piece = body[offset : offset + XLSX_ROWS_PER_BLOCK]
            text = "\n".join([header] + piece) if piece else header
            chunks.append(
                (
                    "sheet",
                    f"Sheet: {name} · 行{offset + 2}-{offset + len(piece) + 1}",
                    text,
                    {
                        "sheet": name,
                        "rows": len(piece),
                        "part": part,
                    },
                ),
            )
        if not chunks:
            chunks = [("sheet", f"Sheet: {name}", header, {"sheet": name})]
        sections.extend(chunks)
    return sections


def parse_document(
    abs_path: str,
    fmt: str,
    cache_dir: Path | None = None,
) -> dict[str, Any]:
    """Parse *abs_path* into canonical markdown + block index (cached).

    Returns ``{"doc": ParsedDoc}`` or ``{"error": ...}``.  The cache is keyed
    by path + mtime + size + format, so a re-uploaded file is a new key and
    an untouched file costs zero parsing.
    """
    key = cache_key(abs_path, fmt)
    directory = cache_dir if cache_dir is not None else _cache_dir(Path(abs_path).parent)
    cached = _load_cache(key, directory)
    if cached is not None:
        return {"doc": cached}

    # A ``.docx`` that starts with ``D0CF11E0`` is a 1997-era OLE2 file
    # (Word 97-2003 / WPS), not OOXML: every zip-based parser answers
    # "Package not found" and the model reads that as a broken tool.  Say
    # what the file actually is.
    if fmt in ("docx", "pptx", "xlsx", "xlsm"):
        try:
            head = Path(abs_path).read_bytes()[:8]
        except OSError as exc:
            return {"error": f"读取失败：{exc}"}
        if head.startswith(b"\xd0\xcf\x11\xe0"):
            return {
                "error": (
                    f"文件的扩展名是 .{fmt}，内容其实是 OLE2 复合文档"
                    "（Word/Excel/PPT 97-2003 老格式）。请先转成现代格式"
                    "（.docx/.xlsx/.pptx）再读；mode=full 的 libreoffice "
                    "兜底可以处理它。"
                ),
                "format_detected": "ole2",
            }

    try:
        if fmt == "docx":
            sections = _docx_sections(abs_path)
        elif fmt == "pdf":
            sections = _pdf_sections(abs_path)
        elif fmt == "pptx":
            sections = _pptx_sections(abs_path)
        elif fmt in ("xlsx", "xlsm"):
            sections = _xlsx_sections(abs_path)
        else:
            sections = _blocks_from_markdown(
                Path(abs_path).read_text(encoding="utf-8", errors="ignore"),
            )
    except ImportError as exc:
        return {
            "error": (
                f"{fmt} 分页解析缺少依赖：{exc}。用 install_dependency 安装"
                "（python-docx / pymupdf / python-pptx / openpyxl），"
                "不要改用 shell 解压。"
            ),
        }
    except Exception as exc:
        logger.warning("doc pagination parse failed for %s: %s", abs_path, exc)
        return {"error": f"{fmt} 分页解析失败：{type(exc).__name__}: {exc}"}

    text, blocks = _blocks_from_sections(sections)
    if not blocks:
        return {"error": f"{fmt} 解析后没有可读内容（空文档？）。"}
    doc = ParsedDoc(
        path=abs_path,
        fmt=fmt,
        text=text,
        blocks=blocks,
        key=key,
    )
    _save_cache(doc, directory)
    return {"doc": doc}


# ── the four read modes ─────────────────────────────────────────────


def _cursor(
    doc: ParsedDoc,
    after: int,
    limit: int,
    hint_param: str = "start",
) -> dict[str, Any]:
    """Where the next read starts, and how much of the document is left."""
    remaining = max(0, doc.chars - after)
    return {
        "read_to": after,
        "total_chars": doc.chars,
        "remaining_chars": remaining,
        "next_start": min(after, doc.chars),
        "hint": (
            f"继续读取请用 {hint_param}={after}"
            if remaining
            else "已读到文档末尾"
        ),
        "limit": limit,
    }


def _fit_limit(max_chars: int | None, doc: ParsedDoc) -> int:
    limit = max_chars if max_chars and max_chars > 0 else BLOCK_CHARS
    return min(limit, doc.chars) if doc.chars else limit


def read_doc_blocks(
    doc: ParsedDoc,
    start: int,
    end: int | None,
    max_chars: int | None,
) -> dict[str, Any]:
    """A *block* range ``[start, end]`` (inclusive), capped by the budget.

    Block numbers are the addresses printed by ``mode=index``.  This is the
    primary pagination unit: a model that read ``[7] section 第三章 4120-5860``
    asks for ``start=7&end=7`` and gets that section, never two characters of
    it.  Character offsets are a separate, explicitly named parameter
    (``start_char``/``end_char``) so the two units can never be confused.
    """
    count = len(doc.blocks)
    if count == 0:
        return {"mode": "range", "error": "文档没有可分页的块。"}
    lo = max(0, int(start or 0))
    if lo >= count:
        return {
            "mode": "range",
            "unit": "block",
            "error": (
                f"start={lo} 超出块数（共 {count} 块，编号 0-{count - 1}）。"
                "先用 mode=index 查看块号。"
            ),
            "block_count": count,
            "total_chars": doc.chars,
        }
    hi = count - 1 if end is None else min(count - 1, int(end))
    if hi < lo:
        return {
            "mode": "range",
            "unit": "block",
            "error": f"end={hi} 小于 start={lo}，区间为空。",
            "block_count": count,
            "total_chars": doc.chars,
        }

    limit = _fit_limit(max_chars, doc)
    span_start = doc.blocks[lo].start
    span_end = doc.blocks[hi].end
    span_chars = span_end - span_start
    budget = min(span_chars, limit)
    text = doc.text[span_start : span_start + budget]
    # Which blocks made it out whole, and where the next read must resume.
    taken = [
        b.i
        for b in doc.blocks
        if b.start >= span_start and b.end <= span_start + budget
    ]
    resumed = span_start + budget
    next_block = next(
        (b.i for b in doc.blocks if b.end > resumed),
        count,
    )
    remaining_blocks = max(0, count - next_block)
    return {
        "mode": "range",
        "unit": "block",
        "format": doc.fmt,
        "path": doc.path,
        "start": lo,
        "end": hi,
        "blocks_returned": taken,
        "char_span": [span_start, span_start + budget],
        "chars": len(text),
        "requested_chars": span_chars,
        "content": text,
        "blocks": [
            doc.blocks[i].as_dict() for i in range(lo, min(hi, count - 1) + 1)
        ][:8],
        "over_budget": span_chars > budget,
        "cursor": {
            "next_block": next_block,
            "remaining_blocks": remaining_blocks,
            "read_to_char": resumed,
            "total_chars": doc.chars,
            "remaining_chars": max(0, doc.chars - resumed),
            "limit": limit,
            "hint": (
                f"继续读取请用 mode=range 配 start={next_block}"
                if remaining_blocks
                else "已到最后一块；如需全文请用 mode=full"
            ),
        },
        "cached": doc.cached,
    }


def read_doc_index(doc: ParsedDoc) -> dict[str, Any]:
    """The map: every block with its address, in one compact table."""
    rows = doc.index_rows()
    lines = [
        f"[{b['i']}] {b['kind']} {b['title']} "
        f"{b['start']}-{b['end']} ({b['chars']}字符)"
        for b in rows
    ]
    return {
        "mode": "index",
        "format": doc.fmt,
        "path": doc.path,
        "total_chars": doc.chars,
        "block_count": len(rows),
        "blocks": rows,
        "index": "\n".join(lines),
        "hint": (
            "用 mode=range 配 start=<块号>&end=<块号> 取某一块的正文（块号即上面的"
            " [i]，单次上限为预算字符数），用 mode=search 配 keywords 定位关键词。"
        ),
        "cached": doc.cached,
    }


def read_doc_range(
    doc: ParsedDoc,
    start: int,
    end: int | None,
    max_chars: int | None,
) -> dict[str, Any]:
    """A character range, capped by the caller's budget, with a cursor."""
    limit = _fit_limit(max_chars, doc)
    lo = max(0, int(start or 0))
    if lo >= doc.chars:
        return {
            "mode": "range",
            "error": (
                f"start={lo} 超出文档长度（{doc.chars} 字符）。"
                "先用 mode=index 查看块地址。"
            ),
            "total_chars": doc.chars,
        }
    hard = doc.chars if end is None else min(doc.chars, int(end))
    if hard <= lo:
        return {
            "mode": "range",
            "error": f"end={hard} 不大于 start={lo}，区间为空。",
            "total_chars": doc.chars,
        }
    span = hard - lo
    budget = min(span, limit)
    text = doc.text[lo : lo + budget]
    hit_blocks = [
        b.as_dict()
        for b in doc.blocks
        if b.start < lo + budget and b.end > lo
    ]
    return {
        "mode": "range",
        "unit": "char",
        "format": doc.fmt,
        "path": doc.path,
        "start": lo,
        "end": lo + budget,
        "chars": budget,
        "requested_chars": span,
        "content": text,
        "blocks": hit_blocks[:8],
        "over_budget": span > budget,
        "cursor": _cursor(doc, lo + budget, limit, "start_char"),
        "cached": doc.cached,
    }


def read_doc_search(
    doc: ParsedDoc,
    keywords: str,
    max_chars: int | None,
) -> dict[str, Any]:
    """Locate keywords: ±200 characters around each hit, with addresses."""
    terms = [t for t in re.split(r"[\s,，]+", str(keywords or "")) if t]
    if not terms:
        return {"mode": "search", "error": "keywords 为空。"}
    limit = _fit_limit(max_chars, doc)
    lowered = doc.text.lower()
    hits: list[dict[str, Any]] = []
    total = 0
    for term in terms:
        needle = term.lower()
        pos = lowered.find(needle)
        per_term = 0
        while pos != -1 and per_term < 4 and len(hits) < SEARCH_MAX_HITS:
            lo = max(0, pos - SEARCH_CONTEXT_CHARS)
            hi = min(doc.chars, pos + len(term) + SEARCH_CONTEXT_CHARS)
            snippet = doc.text[lo:hi]
            total += len(snippet)
            hits.append(
                {
                    "term": term,
                    "at": pos,
                    "start": lo,
                    "end": hi,
                    "block": next(
                        (b.i for b in doc.blocks if b.start <= pos < b.end),
                        None,
                    ),
                    "text": snippet,
                },
            )
            per_term += 1
            pos = lowered.find(needle, pos + len(term))
            if total >= limit:
                break
        if total >= limit:
            break
    return {
        "mode": "search",
        "format": doc.fmt,
        "path": doc.path,
        "keywords": terms,
        "hits": len(hits),
        "total_chars": doc.chars,
        "results": hits,
        "hint": (
            "命中位置可用 mode=range 配 start=<block>&end=<block> 展开阅读"
            "（results 里的 block 即块号），或用 start_char/end_char 按字符定位。"
            if hits
            else "未命中。换关键词，或用 mode=index 通览结构。"
        ),
        "cursor": _cursor(doc, min(doc.chars, total), limit, "start_char"),
        "cached": doc.cached,
    }


def read_doc_full(
    doc: ParsedDoc,
    max_chars: int | None,
) -> dict[str, Any]:
    """Whole document, capped by the budget — and the cap is *said*."""
    limit = max_chars if max_chars and max_chars > 0 else FULL_READ_MAX_CHARS
    limit = min(limit, FULL_READ_MAX_CHARS)
    text = doc.text[:limit]
    truncated = doc.chars > limit
    return {
        "mode": "full",
        "format": doc.fmt,
        "path": doc.path,
        "total_chars": doc.chars,
        "chars": len(text),
        "content": text,
        "truncated": truncated,
        "cursor": _cursor(doc, len(text), limit, "start_char"),
        "warning": (
            f"文档共 {doc.chars} 字符，本次返回 {len(text)} 字符（预算上限 "
            f"{limit}）。整读大文档会吃掉会话预算，请改用 mode=index + "
            "mode=range 分页读取。"
            if truncated
            else ""
        ),
        "cached": doc.cached,
    }


def read_document(
    abs_path: str,
    fmt: str,
    mode: str = "index",
    start: int | None = None,
    end: int | None = None,
    keywords: str | None = None,
    max_chars: int | None = None,
    cache_dir: Path | None = None,
    start_char: int | None = None,
    end_char: int | None = None,
) -> dict[str, Any]:
    """Parse (cached) then serve one of index/range/search/full.

    ``range`` is block-number based (``start``/``end``, the ``[i]`` addresses
    from ``index``); pass ``start_char``/``end_char`` to slice by character
    offset instead.  The two units are separate parameters on purpose —
    inferring which one a number means is how pagination goes in circles.
    """
    parsed = parse_document(abs_path, fmt, cache_dir=cache_dir)
    if "error" in parsed:
        return parsed
    doc = parsed["doc"]
    if mode == "index":
        return read_doc_index(doc)
    if mode == "range":
        if start_char is not None and start_char >= 0:
            return read_doc_range(doc, start_char, end_char, max_chars)
        return read_doc_blocks(doc, start or 0, end, max_chars)
    if mode == "search":
        return read_doc_search(doc, keywords or "", max_chars)
    if mode == "full":
        return read_doc_full(doc, max_chars)
    return {
        "error": (
            f"mode={mode!r} 无效。可用：index / range / search / full。"
        ),
    }
