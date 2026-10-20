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
"""Multi-format document reader (PDF / DOCX / PPTX / XLSX / CSV / text).

Design notes — this is a *base capability*, so it is deliberately strict:

* **Path resolution mirrors ``read_file``.** Chat uploads and ``+``-picker
  references reach the tool as bare names, ``/media/x.docx`` or legacy
  ``file://`` URIs; resolving them against the process CWD (the old behaviour,
  CWD = ``/app`` in the container) never found them.  Every accepted shape is
  probed against folder reference → workspace ``files/`` → ``files/media`` →
  workspace → global media dir, and a miss returns concrete candidate paths
  instead of a bare "文件不存在".
* **No CLI fallbacks.** ``pandoc`` / ``pdftotext`` / ``libreoffice`` are not in
  the image and the tool guard rejects the shell routes that would reach them,
  so the fallback is the ``markitdown`` library (CLI only as a last resort).
* **Honest about formats.** Legacy OLE2 ``.doc/.xls/.ppt`` are *not* claimed as
  supported; they get an explicit "convert to OOXML" answer.
* **Content dimensions that matter.** DOCX tables and headers/footers, PPTX
  grouped shapes / tables / speaker notes, XLSX formula fallback.
"""
from __future__ import annotations

import asyncio
import logging
import os
import subprocess
import urllib.parse
from pathlib import Path
from typing import Any, Optional

from .registry import register_tool

logger = logging.getLogger(__name__)

#: Extensions this tool can actually parse.
SUPPORTED_FORMATS = {
    ".pdf": "pdf",
    ".docx": "docx",
    ".pptx": "pptx",
    ".xlsx": "xlsx",
    ".csv": "csv",
    ".txt": "text",
    ".md": "text",
    ".rst": "text",
    ".html": "text",
    ".htm": "text",
    ".json": "text",
    ".yaml": "text",
    ".yml": "text",
    ".toml": "text",
    ".py": "text",
    ".js": "text",
    ".ts": "text",
    ".java": "text",
    ".go": "text",
    ".rs": "text",
    ".xml": "text",
    ".sql": "text",
    ".sh": "text",
}

#: Legacy OLE2 binaries: advertised by nothing, rejected with a clear answer.
LEGACY_FORMATS = {
    ".doc": "docx",
    ".xls": "xlsx",
    ".ppt": "pptx",
}

#: Image extensions: this tool does not OCR; point at ``view_image``.
IMAGE_FORMATS = {".png", ".jpg", ".jpeg", ".gif", ".webp", ".bmp"}

_MAX_GLOB_CANDIDATES = 8


def _detect_format(filepath: str) -> str | None:
    ext = Path(filepath).suffix.lower()
    return SUPPORTED_FORMATS.get(ext)


# --------------------------------------------------------------------------
# Path resolution
# --------------------------------------------------------------------------
def _clean_input_path(raw: str) -> str:
    """Strip URI decorations and percent-encoding from a user-supplied path."""
    text = (raw or "").strip().strip('"').strip("'")
    if not text:
        return ""
    if text.startswith("file://"):
        parsed = urllib.parse.urlparse(text)
        # ``file:///abs/x`` → path; ``file://x`` (legacy UI) → netloc is the name
        text = urllib.parse.unquote(parsed.path or parsed.netloc)
    elif "://" in text:
        text = urllib.parse.unquote(urllib.parse.urlparse(text).path)
    else:
        text = urllib.parse.unquote(text)
    return text.strip()


def _candidate_paths(raw: str) -> list[Path]:
    """Build the ordered list of places *raw* could legitimately point to.

    Mirrors ``read_file`` semantics (folder reference, then the workspace's
    ``files/`` tree) and adds the chat-upload media directories.  The process
    CWD is intentionally *last*: it is ``/app`` in the container and never
    contains user files.
    """
    text = _clean_input_path(raw)
    if not text:
        return []

    name = os.path.basename(text.rstrip("/"))
    rel = text.lstrip("/")
    out: list[Path] = []

    def _add(p: Path | str | None) -> None:
        if not p:
            return
        try:
            cand = Path(p)
        except (OSError, ValueError):
            return
        if cand not in out:
            out.append(cand)

    # 1) literal (absolute paths work as-is)
    _add(Path(os.path.abspath(text)))
    # 2) folder reference (chat "directory reference" = conversation CWD)
    try:
        from ...config.context import get_current_folder_ref

        folder_ref = get_current_folder_ref()
        if folder_ref:
            _add(Path(folder_ref) / rel)
            if name:
                _add(Path(folder_ref) / name)
    except Exception:
        pass
    # 3) current agent workspace: files/ tree first (chat uploads live there)
    try:
        from ...config.context import get_current_workspace_dir

        ws = get_current_workspace_dir()
        if ws:
            ws = Path(ws)
            _add(ws / "files" / rel)
            if name:
                _add(ws / "files" / name)
                _add(ws / "files" / "media" / name)
            _add(ws / rel)
            if name:
                _add(ws / "media" / name)
                _add(ws / name)
    except Exception:
        pass
    # 4) global media dir (channel uploads)
    try:
        from ...constant import DEFAULT_MEDIA_DIR

        if name:
            _add(Path(DEFAULT_MEDIA_DIR) / name)
    except Exception:
        pass
    # 5) last resort: process CWD (legacy behaviour, kept for compatibility)
    _add(Path(os.path.join(os.getcwd(), rel)))
    return out


def _resolve_existing(raw: str) -> tuple[Optional[Path], list[Path]]:
    """Resolve *raw* to an existing file.

    Returns ``(path, candidates)``: ``path`` is the resolved file (or ``None``),
    ``candidates`` are concrete places the caller can try next — surfaced to the
    model so it stops guessing paths.
    """
    for cand in _candidate_paths(raw):
        try:
            if cand.is_file():
                return cand, []
        except OSError:
            continue
    return None, _search_candidates(raw)


def _search_candidates(raw: str) -> list[Path]:
    """Glob the workspace for the bare filename so the model gets real paths."""
    name = os.path.basename(_clean_input_path(raw).rstrip("/"))
    if not name:
        return []
    roots: list[Path] = []
    try:
        from ...config.context import get_current_folder_ref, get_current_workspace_dir

        folder_ref = get_current_folder_ref()
        if folder_ref:
            roots.append(Path(folder_ref))
        ws = get_current_workspace_dir()
        if ws:
            roots += [Path(ws) / "files", Path(ws)]
    except Exception:
        pass
    try:
        from ...constant import DEFAULT_MEDIA_DIR

        roots.append(Path(DEFAULT_MEDIA_DIR))
    except Exception:
        pass

    found: list[Path] = []
    seen: set[str] = set()
    for root in roots:
        if not root.is_dir():
            continue
        try:
            for hit in root.rglob(name):
                if hit.is_file() and str(hit) not in seen:
                    seen.add(str(hit))
                    found.append(hit)
                    if len(found) >= _MAX_GLOB_CANDIDATES:
                        return found
        except (OSError, RecursionError):
            continue
    return found


# --------------------------------------------------------------------------
# markitdown fallback (library first, CLI last)
# --------------------------------------------------------------------------
async def _read_with_markitdown(filepath: str) -> Optional[dict[str, Any]]:
    """Parse with markitdown: Python API first, CLI as a last resort."""
    try:
        from markitdown import MarkItDown

        def _convert() -> str:
            return MarkItDown().convert(filepath).text_content or ""

        text = await asyncio.to_thread(_convert)
        if text.strip():
            return {"content": text, "chars": len(text), "format": "markitdown"}
        logger.debug("markitdown returned no text for %s", filepath)
    except ImportError:
        logger.debug("markitdown library unavailable")
    except Exception as exc:
        logger.warning("markitdown API failed for %s: %s", filepath, exc)

    if shutil_which("markitdown"):
        try:
            proc = await asyncio.create_subprocess_exec(
                "markitdown",
                filepath,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, _ = await asyncio.wait_for(proc.communicate(), timeout=60)
            content = stdout.decode(errors="replace")
            if content.strip():
                return {"content": content, "chars": len(content), "format": "markitdown-cli"}
        except Exception as exc:
            logger.warning("markitdown CLI failed for %s: %s", filepath, exc)
    return None


def shutil_which(name: str) -> Optional[str]:
    """``shutil.which`` without importing shutil at module scope (kept local)."""
    import shutil

    return shutil.which(name)


# --------------------------------------------------------------------------
# DOCX
# --------------------------------------------------------------------------
def _docx_text(filepath: str) -> dict[str, Any]:
    """Paragraphs *and* tables in document order, plus headers/footers."""
    from docx import Document
    from docx.document import Document as _DocType
    from docx.oxml.table import CT_Tbl
    from docx.oxml.text.paragraph import CT_P
    from docx.table import _Cell, Table
    from docx.text.paragraph import Paragraph

    doc = Document(filepath)

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

    parts: list[str] = []
    for block in _iter_blocks(doc):
        if isinstance(block, Paragraph):
            if block.text.strip():
                parts.append(block.text)
        else:
            tbl = _table_text(block)
            if tbl:
                parts.append(tbl)

    # Headers / footers (deduped: Word repeats the same header on every section)
    seen: set[str] = set()
    extras: list[str] = []
    for section in doc.sections:
        for label, container in (("页眉", section.header), ("页脚", section.footer)):
            if container.is_linked_to_previous:
                continue
            chunk: list[str] = []
            for para in container.paragraphs:
                if para.text.strip():
                    chunk.append(para.text.strip())
            for table in container.tables:
                tbl = _table_text(table)
                if tbl:
                    chunk.append(tbl)
            text = "\n".join(chunk).strip()
            if text and text not in seen:
                seen.add(text)
                extras.append(f"【{label}】{text}")
    if extras:
        parts.append("\n".join(extras))

    content = "\n\n".join(parts)
    return {"content": content, "chars": len(content), "format": "python-docx"}


async def _read_docx(filepath: str) -> dict[str, Any]:
    try:
        return _docx_text(filepath)
    except ImportError:
        logger.debug("python-docx unavailable, falling back to markitdown")
    except Exception as exc:
        logger.warning("python-docx failed for %s: %s", filepath, exc)
    fallback = await _read_with_markitdown(filepath)
    if fallback:
        return fallback
    return {
        "error": (
            "DOCX 解析失败：python-docx 与 markitdown 均不可用。"
            "请安装 python-docx 或 markitdown（install_dependency），"
            "不要改用 shell/CLI 解压（护栏会拒），也不要用 read_file 读二进制。"
        ),
    }


# --------------------------------------------------------------------------
# PPTX
# --------------------------------------------------------------------------
def _pptx_text(filepath: str) -> dict[str, Any]:
    """Text from every shape, recursing into groups, plus tables and notes."""
    from pptx import Presentation
    from pptx.enum.shapes import MSO_SHAPE_TYPE

    prs = Presentation(filepath)

    def _iter_shapes(shapes):
        for shape in shapes:
            if shape.shape_type == MSO_SHAPE_TYPE.GROUP:
                yield from _iter_shapes(shape.shapes)
            else:
                yield shape

    def _shape_text(shape) -> str:
        chunks: list[str] = []
        if getattr(shape, "has_text_frame", False):
            for para in shape.text_frame.paragraphs:
                line = "".join(run.text for run in para.runs).strip()
                if not line:
                    line = para.text.strip()
                if line:
                    chunks.append(line)
        if getattr(shape, "has_table", False):
            for row in shape.table.rows:
                cells = [c.text.replace("\n", " ").strip() for c in row.cells]
                line = " | ".join(cells).strip(" |")
                if line:
                    chunks.append(line)
        return "\n".join(chunks)

    slides: list[str] = []
    for idx, slide in enumerate(prs.slides, start=1):
        chunks: list[str] = []
        for shape in _iter_shapes(slide.shapes):
            text = _shape_text(shape)
            if text:
                chunks.append(text)
        if slide.has_notes_slide:
            notes = (slide.notes_slide.notes_text_frame.text or "").strip()
            if notes:
                chunks.append(f"【备注】{notes}")
        if chunks:
            slides.append(f"=== 第 {idx} 页 ===\n" + "\n".join(chunks))

    content = "\n\n".join(slides)
    return {"content": content, "chars": len(content), "format": "python-pptx", "slides": len(slides)}


async def _read_pptx(filepath: str) -> dict[str, Any]:
    try:
        return _pptx_text(filepath)
    except ImportError:
        logger.debug("python-pptx unavailable, falling back to markitdown")
    except Exception as exc:
        logger.warning("python-pptx failed for %s: %s", filepath, exc)
    fallback = await _read_with_markitdown(filepath)
    if fallback:
        return fallback
    return {
        "error": (
            "PPTX 解析失败：python-pptx 与 markitdown 均不可用。"
            "请安装 python-pptx 或 markitdown（install_dependency）。"
        ),
    }


# --------------------------------------------------------------------------
# XLSX
# --------------------------------------------------------------------------
def _xlsx_text(
    filepath: str,
    sheet: Optional[str] = None,
    max_rows: int = 2000,
) -> dict[str, Any]:
    """Read values; when a formula has no cached value, show the formula."""
    import openpyxl

    wb = openpyxl.load_workbook(filepath, read_only=False, data_only=True)
    names = [sheet] if sheet else wb.sheetnames
    if sheet and sheet not in wb.sheetnames:
        return {
            "error": f"工作表 '{sheet}' 不存在。可用工作表：{', '.join(wb.sheetnames)}",
        }

    formula_wb = None  # lazily loaded only when a formula cell lacks a value
    blocks: list[str] = []
    for name in names:
        ws = wb[name]
        rows: list[str] = []
        for r_idx, row in enumerate(ws.iter_rows(values_only=True), start=1):
            cells: list[str] = []
            for c_idx, value in enumerate(row, start=1):
                if value is not None:
                    cells.append(str(value))
                    continue
                # No cached value: a programmatically generated workbook was
                # never opened by Excel, so data_only yields None.  Show the
                # formula itself rather than an empty cell.
                if formula_wb is None:
                    formula_wb = openpyxl.load_workbook(
                        filepath,
                        read_only=False,
                        data_only=False,
                    )
                raw = formula_wb[name].cell(row=r_idx, column=c_idx).value
                cells.append("" if raw is None else str(raw))
            line = " | ".join(cells).strip(" |")
            if line.strip():
                rows.append(line)
            if len(rows) >= max_rows:
                rows.append(f"…（已截断，仅显示前 {max_rows} 行）")
                break
        if rows:
            blocks.append(f"=== Sheet: {name} ===\n" + "\n".join(rows))

    content = "\n\n".join(blocks)
    return {
        "content": content,
        "chars": len(content),
        "format": "openpyxl",
        "sheets": len(names),
    }


async def _read_xlsx(filepath: str, sheet: Optional[str] = None) -> dict[str, Any]:
    try:
        return _xlsx_text(filepath, sheet=sheet)
    except ImportError:
        logger.debug("openpyxl unavailable, falling back to markitdown")
    except Exception as exc:
        logger.warning("openpyxl failed for %s: %s", filepath, exc)
    fallback = await _read_with_markitdown(filepath)
    if fallback:
        return fallback
    return {
        "error": (
            "XLSX 解析失败：openpyxl 与 markitdown 均不可用。"
            "请安装 openpyxl 或 markitdown（install_dependency）。"
        ),
    }


# --------------------------------------------------------------------------
# PDF
# --------------------------------------------------------------------------
async def _read_pdf(filepath: str, pages: Optional[str] = None) -> dict[str, Any]:
    page_list: Optional[list[int]] = None
    if pages:
        try:
            picked = [int(p) for p in str(pages).replace(",", " ").split() if p.strip()]
        except ValueError:
            return {"error": f"pages 参数格式无效：{pages}（例：1-3 或 1 2 5）"}
        if any(p < 1 for p in picked):
            return {"error": "pages 页码从 1 开始"}
        # pymupdf4llm takes 0-based page indices; users speak 1-based.
        page_list = [p - 1 for p in picked]

    try:
        import pymupdf4llm

        if page_list:
            md = pymupdf4llm.to_markdown(filepath, pages=page_list)
        else:
            md = pymupdf4llm.to_markdown(filepath)
        return {"content": md, "chars": len(md), "format": "pymupdf4llm"}
    except ImportError:
        logger.debug("pymupdf4llm unavailable, falling back to markitdown")
    except Exception as exc:
        logger.warning("pymupdf4llm failed for %s: %s", filepath, exc)

    fallback = await _read_with_markitdown(filepath)
    if fallback:
        return fallback
    return {
        "error": (
            "PDF 解析失败：pymupdf4llm 与 markitdown 均不可用。"
            "请安装 pymupdf4llm 或 markitdown（install_dependency），"
            "扫描版 PDF 需要 OCR，请改用 view_image 查看页面。"
        ),
    }


async def _read_text(filepath: str, max_chars: int = 100000) -> dict[str, Any]:
    try:
        content = Path(filepath).read_text(encoding="utf-8", errors="ignore")
        truncated = len(content) > max_chars
        return {
            "content": content[:max_chars],
            "chars": len(content),
            "truncated": truncated,
            "format": "text",
        }
    except Exception as exc:
        return {"error": str(exc)}


def _legacy_format(file_path: str) -> Optional[str]:
    ext = Path(_clean_input_path(file_path)).suffix.lower()
    return LEGACY_FORMATS.get(ext)


def _read_chars_budget() -> int:
    """Per-call character allowance for one read (治理台账 READ_CHARS).

    The cap used to be a literal ``100000`` inside the tool — 46% of a
    calibrated 215,040-char session budget, and invisible to governance.  It
    now comes from the ledger, with 20000 as the fallback when governance is
    unavailable.
    """
    try:
        from ...governance.limits import LimitKind, ledger_for_agent

        limit = ledger_for_agent().limit(LimitKind.READ_CHARS)
        if limit is not None and limit.budget > 0:
            return int(limit.budget)
    except Exception:  # governance is optional; never break a read
        pass
    return 20000


#: A file this large (bytes) is read paginated, never whole.  Bytes are a
#: cheap proxy: text-heavy OOXML/PDF of this size parses to ≥ 200K chars.
_PAGINATE_SIZE_BYTES = 200_000


async def _paginated_read(
    fp: str,
    fmt: str,
    mode: str,
    start: int,
    end: int,
    keywords: str,
    max_chars: int,
    start_char: int = -1,
    end_char: int = -1,
) -> dict[str, Any]:
    """Serve one paginated read through the B3 base (parse once, cached)."""
    from .doc_pages import read_document

    try:
        return await asyncio.to_thread(
            read_document,
            str(fp),
            fmt,
            mode,
            None if start < 0 else start,
            None if end < 0 else end,
            keywords or None,
            max_chars,
            None,
            None if start_char < 0 else start_char,
            None if end_char < 0 else end_char,
        )
    except Exception as exc:  # pagination must never be the reason a read fails
        logger.warning(
            "paginated %s read failed for %s: %s",
            mode,
            fp,
            exc,
        )
        return {
            "error": (
                f"分页读取（{mode}）失败：{type(exc).__name__}: {exc}。"
                "可改用 mode=full 配合 max_chars 限量读取。"
            ),
            "file": fp,
        }


@register_tool(
    name="doc_reader",
    description=(
        "多格式文档解析：PDF/DOCX/PPTX/XLSX/CSV/文本 → 结构化文本。"
        "路径可用绝对路径、files/ 相对路径或 /media/ 形式；"
        "老格式 .doc/.xls/.ppt 不支持，请先转成 .docx/.xlsx/.pptx。"
    ),
    category="builtin",
    tags=["file", "reader", "document", "office"],
    dependencies=[
        {"name": "python-docx", "manager": "pip", "required": False, "reason": "DOCX 解析"},
        {"name": "python-pptx", "manager": "pip", "required": False, "reason": "PPTX 解析"},
        {"name": "openpyxl", "manager": "pip", "required": False, "reason": "XLSX 解析"},
        {"name": "pymupdf4llm", "manager": "pip", "required": False, "reason": "PDF 解析"},
        {"name": "markitdown", "manager": "pip", "required": False, "reason": "文档解析兜底"},
    ],
)
async def doc_reader(
    action: str = "read",
    file_path: str = "",
    content: str = "",
    max_chars: int = 0,
    auto_detect: bool = True,
    pages: str = "",
    sheet: str = "",
    mode: str = "full",
    start: int = -1,
    end: int = -1,
    start_char: int = -1,
    end_char: int = -1,
    keywords: str = "",
    goal: str = "",
) -> dict[str, Any]:
    """Parse a document into structured text.

    Args:
        action: "read" | "detect" | "formats"
        file_path: Absolute path, workspace-relative path, or ``/media/x.docx``.
        content: Raw text to process directly (skips file access).
        max_chars: Character cap for one read. ``0`` takes the governance
            READ_CHARS budget (20000 when governance is off).
        auto_detect: Detect format from extension.
        pages: PDF page selection, e.g. ``"1-3"`` / ``"2 5"``.
        sheet: XLSX worksheet name (default: all sheets).
        mode: How much of the document to take (B3 pagination).
            ``"full"`` (default) is the document up to the cap;
            ``"index"`` is the block map — headings / pages / sheets /
            slides numbered ``[0..n]`` (read this first for big files, then
            address blocks by that number); ``"range"`` is blocks
            ``[start, end]`` inclusive; ``"search"`` locates ``keywords``
            with ±200 characters each.  Paginated modes read from a parsed,
            cached copy of the document, so a second read costs nothing.
        start: mode="range" — first **block number** from ``index``.
        end: mode="range" — last block number (inclusive; omit for the last).
        start_char: mode="range" — slice by character offset instead of block
            number (used by the ``full`` read cursor).  Never mix units.
        end_char: mode="range" — end character offset (exclusive).
        keywords: mode="search" — terms to locate (space-separated).
        goal: mode="digest" — the question the document is being read for.
            The digest walks the block index with the compaction model
            (caps: 12 calls / 120000 input characters) and returns
            sections, facts and pointers into the original — never the
            original text.

    Returns:
        Parse result, with the read cursor (``read_to`` /
        ``remaining_chars`` / ``next_start``) on paginated reads.  On a
        missing file the result carries ``candidates`` — real paths found in
        the workspace — so the caller can retry with one of them instead of
        guessing.
    """
    if max_chars <= 0:
        max_chars = _read_chars_budget()
    mode = (mode or "full").strip().lower()
    if mode not in ("full", "index", "range", "search", "digest"):
        return {
            "error": "mode 无效。可用：full / index / range / search / digest",
        }

    if action == "formats":
        return {
            "action": "formats",
            "supported": SUPPORTED_FORMATS,
            "legacy_unsupported": sorted(LEGACY_FORMATS),
            "images_use": "view_image",
        }

    if not file_path.strip() and not content.strip():
        return {"error": "file_path 或 content 不能都为空"}

    if action == "detect":
        resolved, candidates = _resolve_existing(file_path)
        if resolved is None:
            return {
                "error": f"文件不存在: {file_path}",
                "candidates": [str(c) for c in candidates],
            }
        fmt = _detect_format(str(resolved))
        return {
            "action": "detect",
            "file": str(resolved),
            "format": fmt,
            "supported": fmt is not None,
            "legacy": _legacy_format(str(resolved)) is not None,
            "size_kb": round(resolved.stat().st_size / 1024, 1),
        }

    if content.strip():
        resolved_file = "(content)"
        result: dict[str, Any] = {
            "content": content[:max_chars],
            "chars": len(content),
            "format": "text",
            "truncated": len(content) > max_chars,
        }
    else:
        resolved, candidates = _resolve_existing(file_path)
        if resolved is None:
            hint = "未找到文件。"
            if candidates:
                hint += (
                    "工作区里同名/相近的文件："
                    + "；".join(str(c) for c in candidates)
                    + "。请用其中某个绝对路径重试，或用 glob_search 列出候选。"
                )
            else:
                hint += (
                    "请用 glob_search(pattern=\"**\", path=\"<工作区绝对路径>\") "
                    "定位文件，不要猜路径，也不要用 read_file 读二进制文档。"
                )
            return {"error": f"文件不存在: {file_path}", "hint": hint, "candidates": [str(c) for c in candidates]}

        fp = str(resolved)
        resolved_file = fp
        legacy_target = _legacy_format(fp)
        if legacy_target:
            return {
                "error": (
                    f"{Path(fp).suffix} 是旧版二进制格式，本系统不支持解析。"
                    f"请先在 Word/Excel/PPT 里另存为 .{legacy_target}，再重新上传。"
                ),
                "file": fp,
            }
        if Path(fp).suffix.lower() in IMAGE_FORMATS:
            return {
                "error": "图片请用 view_image 查看（doc_reader 不做 OCR）",
                "file": fp,
            }

        fmt = _detect_format(fp) if auto_detect else "text"
        if not fmt:
            return {
                "error": f"不支持的格式: {Path(fp).suffix}",
                "file": fp,
                "supported": sorted(SUPPORTED_FORMATS),
            }

        # ── B3 pagination (2026-10-17) ──────────────────────────────
        # index / range / search read a parsed, cached copy of the document
        # and return a cursor, so "read the rest" is a position and a second
        # read costs no parsing.  A whole-document read of a big file is the
        # exact overflow this exists to stop (measured on dev: 100,000 chars
        # on the first read, 241,000 on the second, against a 215,040-char
        # session budget), so it hands over the map plus the first block.
        if mode == "digest":
            from .doc_digest import digest_document

            try:
                return await digest_document(str(fp), fmt, goal)
            except Exception as exc:
                return {
                    "mode": "digest",
                    "error": (
                        f"摘要读取失败：{type(exc).__name__}: {exc}。"
                        "可改用 mode=index / mode=range 分页读取。"
                    ),
                    "file": fp,
                }
        if mode in ("index", "range", "search"):
            return await _paginated_read(
                fp,
                fmt,
                mode,
                start,
                end,
                keywords,
                max_chars,
                start_char,
                end_char,
            )
        if mode == "full":
            try:
                size = Path(fp).stat().st_size
            except OSError:
                size = 0
            if size >= _PAGINATE_SIZE_BYTES:
                index = await _paginated_read(
                    fp,
                    fmt,
                    "index",
                    -1,
                    -1,
                    "",
                    max_chars,
                )
                if "error" not in index:
                    head = await _paginated_read(
                        fp,
                        fmt,
                        "range",
                        0,
                        -1,
                        "",
                        max_chars,
                    )
                    return {
                        "mode": "index+head",
                        "format": fmt,
                        "path": fp,
                        "total_chars": index.get("total_chars"),
                        "blocks": index.get("blocks"),
                        "index": index.get("index"),
                        "content": head.get("content", ""),
                        "cursor": head.get("cursor"),
                        "warning": (
                            f"文档共 {index.get('total_chars')} 字符，过大，"
                            "不整读。已返回结构索引 + 首块；请用 mode=range "
                            "配 start/end 分页取用，或 mode=search 配 "
                            "keywords 定位。"
                        ),
                    }

        if fmt == "pdf":
            result = await _read_pdf(fp, pages=pages or None)
        elif fmt == "docx":
            result = await _read_docx(fp)
        elif fmt == "pptx":
            result = await _read_pptx(fp)
        elif fmt == "xlsx":
            result = await _read_xlsx(fp, sheet=sheet or None)
        else:
            result = await _read_text(fp, max_chars)

    if "error" in result:
        return result

    content_text = result.get("content", "")
    truncated = bool(result.get("truncated"))
    if len(content_text) > max_chars:
        content_text = content_text[:max_chars]
        truncated = True

    total = result.get("chars", len(content_text))
    out = {
        "action": "read",
        "file": resolved_file,
        "chars": result.get("chars", 0),
        "format": result.get("format", "unknown"),
        "truncated": truncated,
        "returned_chars": len(content_text),
        "content": content_text,
    }
    if truncated:
        # Say where it stopped: a silent cap is what made a document get
        # re-read whole (measured on dev: 100,000 then 241,000 characters).
        out["cursor"] = {
            "read_to": len(content_text),
            "total_chars": total,
            "remaining_chars": max(0, total - len(content_text)),
            "next_start": len(content_text),
            "hint": (
                f"本次返回 {len(content_text)}/{total} 字符（预算 {max_chars}）。"
                f"继续请用 mode=range 配 start_char={len(content_text)}，"
                "或 mode=index 先看结构。"
            ),
        }
    return out
