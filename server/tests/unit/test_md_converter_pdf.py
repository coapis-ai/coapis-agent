# -*- coding: utf-8 -*-
"""markdown → pdf/docx 转换链路测试（含宽表/超大输入等降级路径）。

对应诉求：生成 PDF 与生成 Word 一样是交付动作，必须稳定成功且不进审批，
中文必须真实渲染出来。
"""
from pathlib import Path

import pytest

from coapis.utils.md_converter import (
    MdConversionError,
    convert_file,
    md_to_docx,
    md_to_pdf,
)

MD_FULL = (
    "# 标题一\n\n正文 **加粗** 与 中文段落，含 `code` 与 [链接](https://example.com)。\n\n"
    "## 二级标题\n\n- 项目甲\n- 项目乙\n\n> 引用行内容\n\n```python\nprint('hi')\n```\n\n"
    "| 列甲 | 列乙 |\n| --- | --- |\n| 数字一 | 二行 |\n| 三 | 四 |\n\n尾段结束。\n"
)


# ---------------------------------------------------------------------------
# 正常路径
# ---------------------------------------------------------------------------


def test_pdf_magic_and_size(tmp_path):
    out = tmp_path / "a.pdf"
    md_to_pdf(MD_FULL, out)
    data = out.read_bytes()
    assert data[:4] == b"%PDF"
    assert len(data) > 500


def test_docx_magic_and_size(tmp_path):
    out = tmp_path / "a.docx"
    md_to_docx(MD_FULL, out)
    assert out.read_bytes()[:2] == b"PK"


def test_pdf_renders_cjk_text(tmp_path):
    """中文必须真的进字形，不能是空白页。"""
    pypdf = pytest.importorskip("pypdf")
    out = tmp_path / "cjk.pdf"
    md_to_pdf(MD_FULL, out)
    text = "\n".join(
        page.extract_text() or "" for page in pypdf.PdfReader(str(out)).pages
    )
    for probe in ("标题一", "中文段落", "项目甲", "引用行内容", "列甲", "数字一", "尾段结束"):
        assert probe in text, f"缺字形: {probe}"
    # 链接按 docx 同规则展开为「文字 (url)」
    assert "https://example.com" in text


# ---------------------------------------------------------------------------
# 降级路径：任何输入都不能抛未捕获异常
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "md_text",
    [
        "",
        "   \n\t\n",
        "\n".join(f"# h{i}\n\n正文" for i in range(20000)),  # 超大文档
        "|" + "a|" * 200 + "\n" + "|---|" * 200 + "\n" + "|b|" * 200,  # 超宽表
        "![" * 5000 + "x",  # 伪图片洪水
        "a\x00b\n\n" + "c" * 5000,  # NUL 注入
        "| 甲 |\n| - |\n未闭合",  # 残缺表
        "# 标题\n\n" + "- 项\n" * 5000,  # 超长列表
    ],
)
@pytest.mark.parametrize("fmt", ["pdf", "docx"])
def test_hostile_input_never_crashes(tmp_path, md_text, fmt):
    out = tmp_path / f"x.{fmt}"
    fn = md_to_pdf if fmt == "pdf" else md_to_docx
    fn(md_text, out)
    assert out.exists()
    assert out.stat().st_size > 0


def test_wide_table_is_capped_not_fatal(tmp_path):
    """200 列等宽会让 reportlab 算出负列宽并崩，必须截断渲染。"""
    md = "|" + "列|" * 200 + "\n" + "|---|" * 200 + "\n" + "|值|" * 200
    out = tmp_path / "wide.pdf"
    md_to_pdf(md, out)
    assert out.read_bytes()[:4] == b"%PDF"


# ---------------------------------------------------------------------------
# 分发入口
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("target", ["pdf", "PDF", " Pdf "])
def test_convert_file_target_is_case_insensitive(tmp_path, target):
    src = tmp_path / "d.md"
    src.write_text(MD_FULL, encoding="utf-8")
    result = convert_file(src, target)
    assert result.suffix == ".pdf"
    assert result.read_bytes()[:4] == b"%PDF"


def test_convert_file_defaults_to_sibling_name(tmp_path):
    src = tmp_path / "d.md"
    src.write_text(MD_FULL, encoding="utf-8")
    assert convert_file(src, "docx").name == "d.docx"


@pytest.mark.parametrize("target", ["xlsx", "pptx", "md", "", None])
def test_convert_file_rejects_unsupported_target(tmp_path, target):
    src = tmp_path / "d.md"
    src.write_text(MD_FULL, encoding="utf-8")
    with pytest.raises(MdConversionError):
        convert_file(src, target)


def test_convert_file_missing_source(tmp_path):
    with pytest.raises(MdConversionError):
        convert_file(tmp_path / "nope.md", "pdf")


def test_convert_file_rejects_directory(tmp_path):
    with pytest.raises(MdConversionError):
        convert_file(tmp_path, "pdf")
