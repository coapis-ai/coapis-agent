# -*- coding: utf-8 -*-
# Copyright 2026 蜜蜂 & CoApis Contributors
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU Affero General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU Affero General Public License for more details.
#
# You should have received a copy of the GNU Affero General Public License
# along with this program.  If not, see <https://www.gnu.org/licenses/>.

"""Markdown → docx conversion, built on python-docx (no pandoc in the image).

Why this exists: markdown is the process *and* deliverable format by default.
Conversion is a one-shot step at delivery, and only when the user explicitly
asked for another format. So the converter has to be reachable without the
agent shelling out to a tool that is not installed.

Supported target today: ``docx``. ``pdf`` / ``xlsx`` / ``html`` are
deliberately reported as unavailable instead of failing silently — the image
has no pandoc/libreoffice, and pretending otherwise produces empty files.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Iterable

SUPPORTED_TARGETS = ("docx", "pdf")

#: Formats we recognise but cannot produce in this image, with the reason the
#: caller should be told. Keeping this explicit stops the agent from looping on
#: unsupported targets.
#:
#: ``pdf`` moved to SUPPORTED_TARGETS: it used to be refused outright, which
#: pushed the agent onto ``python3 -c "import reportlab..."`` — an inline
#: interpreter command the guard rates L3, so "make me a PDF" turned into an
#: approval round trip. A first-class conversion path removes that detour.
UNAVAILABLE_TARGETS = {
    "xlsx": "镜像内无 xlsx 转换依赖，暂不支持 xlsx",
    "html": "html 请直接写文件即可，无需转换",
}

_HEADING_RE = re.compile(r"^(#{1,6})\s+(.*)$")
_CODE_FENCE_RE = re.compile(r"^\s*```")
_BULLET_RE = re.compile(r"^(\s*)[-*+]\s+(.*)$")
_ORDERED_RE = re.compile(r"^(\s*)\d+[.)]\s+(.*)$")
_HR_RE = re.compile(r"^\s*(-{3,}|\*{3,}|_{3,})\s*$")
_QUOTE_RE = re.compile(r"^\s*>\s?(.*)$")
_TABLE_ROW_RE = re.compile(r"^\s*\|.*\|\s*$")
_TABLE_SEP_RE = re.compile(r"^\s*\|?\s*:?-{2,}.*$")

# strong | code | emphasis | link
_INLINE_RE = re.compile(
    r"(\*\*.+?\*\*|__.+?__)"
    r"|(`+[^`]+`+)"
    r"|(\*[^*].*?\*|_[^_].*?_)"
    r"|\[([^\]]*)\]\(([^)]*)\)",
)


class MdConversionError(Exception):
    """Raised when a conversion cannot be performed."""


def _add_inline_runs(paragraph, text: str) -> None:
    """Append *text* to *paragraph*, translating markdown inline markup.

    Handles ``**strong**``, ``*emphasis*``, `` `code` `` and ``[label](url)``.
    Links keep their target visible (``label (url)``) because a docx has no
    reliable way to show a hyperlink target to a reader who copies the text.
    """
    pos = 0
    for match in _INLINE_RE.finditer(text):
        if match.start() > pos:
            paragraph.add_run(text[pos : match.start()])
        strong, code, em, label, url = match.groups()
        token = match.group(0)
        if strong is not None:
            run = paragraph.add_run(token[2:-2])
            run.bold = True
        elif code is not None:
            ticks = len(code) - len(code.strip("`"))
            run = paragraph.add_run(code.strip("`"))
            run.font.name = "Consolas"
            run.font.size = None if ticks < 3 else run.font.size
        elif em is not None:
            run = paragraph.add_run(token[1:-1])
            run.italic = True
        else:
            target = (label or "").strip()
            href = (url or "").strip()
            run = paragraph.add_run(f"{target} ({href})" if href else target)
            run.underline = True
        pos = match.end()
    if pos < len(text):
        paragraph.add_run(text[pos:])


def _split_table_row(line: str) -> list[str]:
    cells = line.strip().strip("|").split("|")
    return [c.strip() for c in cells]


def _is_table_separator(line: str) -> bool:
    return bool(_TABLE_SEP_RE.match(line.strip())) and "-" in line


def _add_table(doc, rows: Iterable[list[str]]) -> None:
    """Add a grid table; the first row is the header."""
    rows = [r for r in rows if r]
    if not rows:
        return
    width = max(len(r) for r in rows)
    table = doc.add_table(rows=len(rows), cols=width)
    try:
        table.style = "Table Grid"
    except (KeyError, ValueError):
        # Template without that style: a borderless table is still readable.
        pass
    for i, row in enumerate(rows):
        for j in range(width):
            cell = table.cell(i, j)
            cell.text = ""
            para = cell.paragraphs[0]
            _add_inline_runs(para, row[j] if j < len(row) else "")
            if i == 0:
                for run in para.runs:
                    run.bold = True
    doc.add_paragraph()


def _list_style(base: str, indent: int) -> str:
    """Map markdown indentation to the numbered list styles python-docx ships."""
    depth = min(indent // 2, 2) if indent else 0
    return base if depth == 0 else f"{base} {depth + 1}"


def _add_code_block(doc, lines: list[str]) -> None:
    for line in lines:
        para = doc.add_paragraph()
        para.paragraph_format.space_after = None
        para.paragraph_format.left_indent = None
        run = para.add_run(line if line else " ")
        run.font.name = "Consolas"


_CTRL_CHARS = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f]")


def _strip_ctrl(text: str) -> str:
    """Drop XML-illegal control characters before they reach the writers.

    python-docx writes through lxml, which raises ``ValueError: All strings
    must be XML compatible`` on NUL/control bytes — a document the agent
    pasted from a binary-ish source used to kill the whole conversion.
    Whitespace controls (tab/newline/carriage return) survive.
    """
    return _CTRL_CHARS.sub("", text) if text else text


def md_to_docx(md_text: str, out_path: Path) -> Path:
    """Render *md_text* as a docx at *out_path* and return the path."""
    md_text = _strip_ctrl(md_text)
    try:
        from docx import Document
        from docx.shared import Pt
    except ImportError as exc:  # pragma: no cover - image dependency
        raise MdConversionError(
            "python-docx 未安装，无法生成 docx",
        ) from exc

    doc = Document()
    # CJK-safe default: the stock template uses Calibri, which renders Chinese
    # via font fallback and looks inconsistent across viewers.
    normal = doc.styles["Normal"]
    normal.font.name = "Microsoft YaHei"
    normal.font.size = Pt(11)

    lines = md_text.replace("\r\n", "\n").replace("\r", "\n").split("\n")
    i = 0
    while i < len(lines):
        line = lines[i]
        stripped = line.strip()

        # Fenced code: keep verbatim, monospace, one paragraph per line.
        if _CODE_FENCE_RE.match(line):
            block: list[str] = []
            i += 1
            while i < len(lines) and not _CODE_FENCE_RE.match(lines[i]):
                block.append(lines[i])
                i += 1
            i += 1  # skip closing fence
            _add_code_block(doc, block)
            doc.add_paragraph()
            continue

        if not stripped:
            i += 1
            continue

        heading = _HEADING_RE.match(line)
        if heading:
            level = min(len(heading.group(1)), 4)
            para = doc.add_heading(level=level)
            _add_inline_runs(para, heading.group(2).strip())
            i += 1
            continue

        if _HR_RE.match(line):
            doc.add_paragraph("─" * 24)
            i += 1
            continue

        # GFM table: header row, separator row, then body rows.
        if _TABLE_ROW_RE.match(line):
            rows = [_split_table_row(line)]
            i += 1
            if i < len(lines) and _is_table_separator(lines[i]):
                i += 1
            while i < len(lines) and _TABLE_ROW_RE.match(lines[i]):
                rows.append(_split_table_row(lines[i]))
                i += 1
            _add_table(doc, rows)
            continue

        quote = _QUOTE_RE.match(line)
        if quote:
            para = doc.add_paragraph()
            para.paragraph_format.left_indent = Pt(18)
            _add_inline_runs(para, quote.group(1))
            for run in para.runs:
                run.italic = True
            i += 1
            continue

        bullet = _BULLET_RE.match(line)
        if bullet:
            para = doc.add_paragraph(
                style=_list_style("List Bullet", len(bullet.group(1))),
            )
            _add_inline_runs(para, bullet.group(2))
            i += 1
            continue

        ordered = _ORDERED_RE.match(line)
        if ordered:
            para = doc.add_paragraph(
                style=_list_style("List Number", len(ordered.group(1))),
            )
            _add_inline_runs(para, ordered.group(2))
            i += 1
            continue

        para = doc.add_paragraph()
        _add_inline_runs(para, stripped)
        i += 1

    out_path.parent.mkdir(parents=True, exist_ok=True)
    doc.save(str(out_path))
    return out_path


# ---------------------------------------------------------------------------
# Markdown -> PDF (reportlab)
# ---------------------------------------------------------------------------

# reportlab ships CID font definitions for CJK; ``STSong-Light`` renders
# Chinese without shipping a font file (the viewer supplies the glyphs).
# The Noto CJK ``.ttc`` files in the image are OTF/CFF-flavoured, which
# reportlab's TTFont rejects, so the CID route is the reliable one.
_CJK_FONT = "STSong-Light"
_MONO_FONT = "Courier"

_PDF_HEADING_SIZES = {1: 18, 2: 15, 3: 13, 4: 12}


def _pdf_styles():
    """Build the paragraph styles used by the PDF renderer."""
    from reportlab.lib.colors import HexColor
    from reportlab.lib.styles import ParagraphStyle
    from reportlab.lib.units import mm

    body = ParagraphStyle(
        "body",
        fontName=_CJK_FONT,
        fontSize=10.5,
        leading=16,
        spaceAfter=6,
    )
    heading = {
        level: ParagraphStyle(
            f"h{level}",
            parent=body,
            fontName=_CJK_FONT,
            fontSize=size,
            leading=size * 1.4,
            spaceBefore=10 if level > 1 else 0,
            spaceAfter=6,
            textColor=HexColor("#111827"),
        )
        for level, size in _PDF_HEADING_SIZES.items()
    }
    quote = ParagraphStyle(
        "quote",
        parent=body,
        leftIndent=14,
        borderPadding=4,
        borderColor=HexColor("#cbd5e1"),
        borderWidth=0,
        leftBorderWidth=3,
        textColor=HexColor("#475569"),
    )
    bullet = ParagraphStyle(
        "bullet",
        parent=body,
        bulletIndent=10,
        leftIndent=24,
        bulletFontName=_CJK_FONT,
        bulletFontSize=10.5,
    )
    code = ParagraphStyle(
        "code",
        fontName=_MONO_FONT,
        fontSize=9,
        leading=12.5,
        backColor=HexColor("#f4f4f5"),
        borderPadding=6,
        spaceAfter=8,
    )
    cell = ParagraphStyle(
        "cell",
        fontName=_CJK_FONT,
        fontSize=9.5,
        leading=13,
    )
    cell_head = ParagraphStyle(
        "cellHead",
        parent=cell,
        fontName=_CJK_FONT,
    )
    return body, heading, quote, bullet, code, cell, cell_head, mm


def _strip_inline(text: str) -> str:
    """Flatten markdown links/images; keep emphasis markers in place.

    ``[label](url)`` becomes ``label (url)`` (same rule as the docx path —
    a reader who copies the text must still see the target), ``![alt](url)``
    becomes ``alt``.  ``**``/``*``/`` ` `` survive here because
    :func:`_pdf_inline` escapes first and only then turns them into
    Paragraph's ``<b>``/``<i>``/``<font>`` markup.
    """
    out: list[str] = []
    pos = 0
    for match in _INLINE_RE.finditer(text):
        if match.start() > pos:
            out.append(text[pos : match.start()])
        _strong, _code, _em, label, url = match.groups()
        if label is not None:
            target = (label or "").strip()
            href = (url or "").strip()
            out.append(f"{target} ({href})" if href else target)
        else:
            out.append(match.group(0))
        pos = match.end()
    if pos < len(text):
        out.append(text[pos:])
    return "".join(out)


def _pdf_inline(text: str) -> str:
    """Markdown inline text -> escaped Paragraph markup.

    ``_strip_inline`` already flattens links and strips ``**``/``*``/`` ` ``
    markers, so all that is left is XML-escaping the result (``&``/``<``/``>``
    would otherwise break Paragraph) and re-applying bold/italic for the
    markers that survived stripping.
    """
    from xml.sax.saxutils import escape

    plain = escape(_strip_inline(text))
    plain = re.sub(r"\*\*(.+?)\*\*", r"<b>\1</b>", plain)
    plain = re.sub(r"(?<!\*)\*([^*\n]+)\*(?!\*)", r"<i>\1</i>", plain)
    plain = re.sub(r"`([^`\n]+)`", r"<font face='%s'>\1</font>" % _MONO_FONT, plain)
    return plain


def _add_pdf_table(story, rows: list[list[str]], styles) -> None:
    """GFM table -> reportlab Table with wrapped, CJK-capable cells."""
    from reportlab.lib.colors import HexColor
    from reportlab.platypus import Paragraph, Spacer, Table, TableStyle

    cell_style = styles[5]
    cell_head_style = styles[6]
    mm = styles[7]

    width = max(len(r) for r in rows)
    # 列数上限：等宽列减去左右内边距(10pt)后必须还剩正宽度，reportlab 遇到
    # 负可用宽会抛 ValueError（宽表实测必崩）。18mm 是内边距+一个汉字的安全
    # 下限，超出的列截断渲染，保证宽表降级为可读的窄表而不是整篇失败。
    avail = 170 * mm
    max_cols = max(1, int(avail // (18 * mm)))
    if width > max_cols:
        rows = [r[:max_cols] for r in rows]
        width = max_cols
    grid = [(row + [""] * (width - len(row))) for row in rows]

    data = []
    for idx, row in enumerate(grid):
        style = cell_head_style if idx == 0 else cell_style
        data.append([Paragraph(_pdf_inline(c[:400]), style) for c in row])

    # Equal columns, capped to the printable width; reportlab needs numbers.
    col_w = avail / width if width else avail
    table = Table(data, colWidths=[col_w] * width, repeatRows=1)
    table.setStyle(
        TableStyle(
            [
                ("GRID", (0, 0), (-1, -1), 0.5, HexColor("#cbd5e1")),
                ("BACKGROUND", (0, 0), (-1, 0), HexColor("#f1f5f9")),
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("LEFTPADDING", (0, 0), (-1, -1), 5),
                ("RIGHTPADDING", (0, 0), (-1, -1), 5),
                ("TOPPADDING", (0, 0), (-1, -1), 4),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
            ],
        ),
    )
    story.append(table)
    story.append(Spacer(1, 6))


def md_to_pdf(md_text: str, out_path: Path) -> Path:
    """Render *md_text* as a PDF at *out_path* and return the path.

    Mirrors :func:`md_to_docx` in structure (same regexes, same block model)
    so md and docx and pdf stay in lockstep: headings, fenced code, GFM
    tables, blockquotes, bullets, numbered lists, horizontal rules.
    """
    md_text = _strip_ctrl(md_text)
    try:
        from reportlab.lib.pagesizes import A4
        from reportlab.pdfbase import pdfmetrics
        from reportlab.pdfbase.cidfonts import UnicodeCIDFont
        from reportlab.platypus import (
            HRFlowable,
            ListFlowable,
            ListItem,
            Paragraph,
            SimpleDocTemplate,
            Spacer,
            XPreformatted,
        )
    except ImportError as exc:  # pragma: no cover - image dependency
        raise MdConversionError(
            "reportlab 未安装，无法生成 pdf",
        ) from exc

    try:
        pdfmetrics.getFont(_CJK_FONT)
    except KeyError:
        pdfmetrics.registerFont(UnicodeCIDFont(_CJK_FONT))

    styles = _pdf_styles()
    body, heading, quote_style, bullet_style, code_style, _cell, _cell_head, mm = styles

    story: list = []
    lines = md_text.replace("\r\n", "\n").replace("\r", "\n").split("\n")

    i = 0
    while i < len(lines):
        line = lines[i]
        stripped = line.strip()

        # Fenced code: verbatim, monospace, shaded block.
        if _CODE_FENCE_RE.match(line):
            block: list[str] = []
            i += 1
            while i < len(lines) and not _CODE_FENCE_RE.match(lines[i]):
                block.append(lines[i])
                i += 1
            i += 1  # skip closing fence
            from xml.sax.saxutils import escape

            story.append(XPreformatted(escape("\n".join(block)), code_style))
            story.append(Spacer(1, 6))
            continue

        if not stripped:
            i += 1
            continue

        heading_match = _HEADING_RE.match(line)
        if heading_match:
            level = min(len(heading_match.group(1)), 4)
            story.append(
                Paragraph(
                    _pdf_inline(heading_match.group(2).strip()),
                    heading[level],
                ),
            )
            i += 1
            continue

        if _HR_RE.match(line):
            story.append(HRFlowable(width="100%", thickness=0.6, color="#cbd5e1"))
            story.append(Spacer(1, 6))
            i += 1
            continue

        # GFM table: header row, separator row, then body rows.
        if _TABLE_ROW_RE.match(line):
            rows = [_split_table_row(line)]
            i += 1
            if i < len(lines) and _is_table_separator(lines[i]):
                i += 1
            while i < len(lines) and _TABLE_ROW_RE.match(lines[i]):
                rows.append(_split_table_row(lines[i]))
                i += 1
            _add_pdf_table(story, rows, styles)
            continue

        quote = _QUOTE_RE.match(line)
        if quote:
            story.append(Paragraph(_pdf_inline(quote.group(1)), quote_style))
            i += 1
            continue

        bullet = _BULLET_RE.match(line)
        if bullet:
            story.append(
                Paragraph(_pdf_inline(bullet.group(2)), bullet_style, bulletText="•"),
            )
            i += 1
            continue

        ordered = _ORDERED_RE.match(line)
        if ordered:
            story.append(
                Paragraph(
                    _pdf_inline(ordered.group(2)),
                    bullet_style,
                    bulletText=f"{ordered.group(1)}.",
                ),
            )
            i += 1
            continue

        story.append(Paragraph(_pdf_inline(stripped), body))
        i += 1

    if not story:
        from reportlab.platypus import Paragraph as _P

        story.append(_P("", body))

    out_path.parent.mkdir(parents=True, exist_ok=True)
    doc = SimpleDocTemplate(
        str(out_path),
        pagesize=A4,
        leftMargin=20 * mm,
        rightMargin=20 * mm,
        topMargin=18 * mm,
        bottomMargin=18 * mm,
    )
    doc.build(story)
    return out_path


def convert_file(md_path: Path, target: str, out_path: Path | None = None) -> Path:
    """Convert *md_path* to *target* and write the result.

    ``out_path`` defaults to a sibling with the new extension. Raises
    :class:`MdConversionError` with a message the user can act on.
    """
    target = (target or "").strip().lstrip(".").lower()
    if target in UNAVAILABLE_TARGETS:
        raise MdConversionError(UNAVAILABLE_TARGETS[target])
    if target not in SUPPORTED_TARGETS:
        raise MdConversionError(
            f"暂不支持转换为 {target}（可用：{', '.join(SUPPORTED_TARGETS)}）",
        )
    if not md_path.exists():
        raise MdConversionError(f"源文件不存在：{md_path}")
    if not md_path.is_file():
        raise MdConversionError(f"源文件不是普通文件：{md_path}")

    md_text = md_path.read_text(encoding="utf-8", errors="replace")
    dest = out_path or md_path.with_suffix(f".{target}")
    if target == "pdf":
        return md_to_pdf(md_text, dest)
    return md_to_docx(md_text, dest)
