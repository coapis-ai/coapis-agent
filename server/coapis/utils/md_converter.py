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

SUPPORTED_TARGETS = ("docx",)

#: Formats we recognise but cannot produce in this image, with the reason the
#: caller should be told. Keeping this explicit stops the agent from looping on
#: unsupported targets.
UNAVAILABLE_TARGETS = {
    "pdf": "镜像内无 pandoc/libreoffice，暂不支持 pdf",
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


def md_to_docx(md_text: str, out_path: Path) -> Path:
    """Render *md_text* as a docx at *out_path* and return the path."""
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
    return md_to_docx(md_text, dest)
