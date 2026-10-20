"""注册完整性：注册表里的工具名必须就是被装饰的那个函数。

事故（2026-10-20 定位）：``doc_reader.py`` 里 ``@register_tool(name="doc_reader")``
被贴到了内部辅助函数 ``_read_chars_budget`` 上（f8ff7d5 把分页基座插在装饰器和
``async def doc_reader`` 之间）。上游 ``Toolkit.register_tool_function`` 默认用
``func.__name__`` 当工具名，于是模型看到的工具叫 ``_read_chars_budget``、零参数，
而真正的文档解析工具 ``doc_reader`` 根本不在 schema 里 —— PDF 只能被 ``read_file``
吐成二进制（"这是PDF原始二进制内容，无法直接阅读" 循环），Excel 只能退化成
"pip install openpyxl 再跑脚本"。

这类错位对既有测试完全隐形：``test_doc_reader_*.py`` 直接 import 模块函数调用，
绕过了注册表。所以这里把三层都锁住：

  1. 注册表里 ``name == func.__name__``（装饰器贴错 = 名字对不上）；
  2. 工具名不得以下划线开头（内部辅助函数混进 schema 的指纹）；
  3. toolkit 注册必须显式传 ``func_name``（注册表名字是唯一权威），
     且 ``doc_reader`` 是异步工具、带 ``file_path/pages/sheet/mode`` 参数。

Run: pytest server/tests/unit/test_tool_registration_integrity.py -q
"""

from __future__ import annotations

import inspect
import os
import sys
import warnings

warnings.filterwarnings("ignore")
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

import pytest  # noqa: E402
from agentscope.tool import Toolkit  # noqa: E402

from coapis.agents.tools import registry as tool_registry  # noqa: E402


def _registered():
    """Import side effect: every builtin tool registers itself."""
    import coapis.agents.tools._auto_register  # noqa: F401

    return tool_registry.get_registered_tools()


def test_registry_name_matches_decorated_function():
    """装饰器贴到别的函数上 = 注册名与函数名对不上，这条必红。"""
    reg = _registered()
    assert reg, "注册表为空"
    drift = sorted(
        f"{name} -> def {r.func.__name__}"
        for name, r in reg.items()
        if r.func.__name__ != name
    )
    assert not drift, (
        "register_tool(name=...) 装饰的不是同名函数（工具会以函数名进 schema）："
        f"{drift}"
    )


def test_no_private_helper_in_tool_schema():
    """``_`` 开头的名字出现在工具表里，就是辅助函数被当成工具注册了。"""
    reg = _registered()
    leaks = sorted(n for n in reg if n.startswith("_"))
    assert not leaks, f"内部辅助函数混进了工具注册表：{leaks}"


def test_toolkit_registration_uses_registry_name():
    """注册表名字是唯一权威：toolkit 必须显式收到 func_name。"""
    src = os.path.join(
        os.path.dirname(__file__), "..", "..", "coapis", "agents", "react_agent.py"
    )
    with open(src, encoding="utf-8") as fh:
        code = fh.read()
    assert "func_name=tool_name" in code, (
        "react_agent 注册内置工具时未显式传 func_name，"
        "工具名会退化成 func.__name__（doc_reader 事故的根因）"
    )


def test_doc_reader_is_a_real_async_tool():
    """doc_reader 必须真的在注册表里，且是可调用带参数的异步工具。"""
    reg = _registered()
    assert "doc_reader" in reg, "doc_reader 未注册"
    func = reg["doc_reader"].func
    assert func.__name__ == "doc_reader"
    assert inspect.iscoroutinefunction(func), "doc_reader 不是异步工具"
    params = set(inspect.signature(func).parameters)
    assert {"file_path", "pages", "sheet", "mode"} <= params, f"参数缺失：{params}"


def test_doc_reader_schema_reaches_the_model():
    """模型看到的 schema 里必须有 doc_reader，且带 file_path 参数。"""
    reg = _registered()
    toolkit = Toolkit()
    for name, registration in reg.items():
        toolkit.register_tool_function(
            registration.func,
            func_name=name,
            namesake_strategy="skip",
        )
    schemas = toolkit.get_json_schemas()
    names = {s["function"]["name"] for s in schemas}
    assert "doc_reader" in names, f"schema 里没有 doc_reader：{sorted(names)}"
    assert not [n for n in names if n.startswith("_")], "schema 里有助手函数"
    doc = next(s for s in schemas if s["function"]["name"] == "doc_reader")
    assert "file_path" in doc["function"]["parameters"]["properties"], (
        "doc_reader 的 schema 没有 file_path —— 模型无法用它读文件"
    )


def test_doc_reader_reads_xlsx_and_pdf():
    """能力层冒烟：Excel 与 PDF 都能解析出文本（依赖齐全时）。"""
    import asyncio
    from pathlib import Path

    import pytest

    from coapis.agents.tools.doc_reader import doc_reader

    tmp = Path("/tmp/_reg_integrity")
    tmp.mkdir(exist_ok=True)

    xlsx = tmp / "t.xlsx"
    try:
        from openpyxl import Workbook

        wb = Workbook()
        wb.active.append(["名称", "数量"])
        wb.active.append(["蜜蜂", 3])
        wb.save(xlsx)
    except Exception:  # pragma: no cover - dependency absent
        pytest.skip("openpyxl unavailable")
    out = asyncio.run(doc_reader(action="read", file_path=str(xlsx)))
    assert "error" not in out, f"Excel 解析失败：{out}"
    assert "蜜蜂" in out.get("content", ""), out

    pdf = tmp / "t.pdf"
    try:
        import fitz  # pymupdf

        doc = fitz.open()
        page = doc.new_page()
        page.insert_text((72, 72), "hello coapis")
        doc.save(pdf)
        doc.close()
    except Exception:  # pragma: no cover - dependency absent
        pytest.skip("pymupdf unavailable")
    out = asyncio.run(doc_reader(action="read", file_path=str(pdf)))
    assert "error" not in out, f"PDF 解析失败：{out}"
    assert "hello coapis" in out.get("content", ""), out
