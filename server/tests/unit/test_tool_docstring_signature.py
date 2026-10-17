"""Tool docstrings must not document parameters that do not exist.

Discovered 2026-10-17 while compacting ``browser_use``'s docstring: it
documented ``path``, ``page_x`` and ``page_y`` for as long as anyone can
remember, and the function has none of them — the real parameters are
``output_path`` (pdf) and ``file_path`` (file_download).  A model that
followed the documentation faithfully got
``browser_use() got an unexpected keyword argument 'path'``.

The same class of defect is invisible everywhere else, so the check runs
over every registered tool: documented-but-undocumented params are a crash,
undocumented params are a guess.
"""

from __future__ import annotations

import inspect
import re

import pytest

from coapis.agents.tools import registry as tool_registry

_ARG_LINE = re.compile(r"^\s{4,8}(?P<name>[a-z_][a-z0-9_]*)\s*(\([^)]*\))?\s*:")


def _documented_args(func) -> set[str]:
    doc = inspect.getdoc(func) or ""
    names: set[str] = set()
    for line in doc.splitlines():
        match = _ARG_LINE.match(line)
        if match:
            names.add(match.group("name"))
    return names


def _registered_tools() -> list:
    import coapis.agents.tools._auto_register  # noqa: F401  (import = register)

    return [
        (name, reg.func)
        for name, reg in tool_registry.get_registered_tools().items()
        if callable(reg.func)
    ]


def test_registered_tools_exist():
    tools = _registered_tools()
    assert len(tools) > 20, f"registry exposed {len(tools)} tools"


@pytest.mark.parametrize(
    ("name", "func"),
    _registered_tools(),
    ids=[name for name, _ in _registered_tools()],
)
def test_documented_params_match_the_signature(name: str, func) -> None:
    signature = inspect.signature(func)
    accepted = {
        parameter.name
        for parameter in signature.parameters.values()
        if parameter.kind
        in (
            inspect.Parameter.POSITIONAL_OR_KEYWORD,
            inspect.Parameter.KEYWORD_ONLY,
        )
    }
    has_var_kwargs = any(
        parameter.kind == inspect.Parameter.VAR_KEYWORD
        for parameter in signature.parameters.values()
    )
    documented = _documented_args(func)
    ghost = documented - accepted
    assert not ghost, (
        f"{name}: the docstring advertises parameter(s) {sorted(ghost)} that "
        "the function does not accept; a model following the documentation "
        "crashes on them"
    )
    if not has_var_kwargs and documented:
        silent = accepted - documented - {"args", "kwargs"}
        assert not silent, (
            f"{name}: parameter(s) {sorted(silent)} exist in the signature "
            "with no documentation, so the model can only guess them"
        )


def test_browser_use_documents_its_real_path_params():
    """D1 最省模式：路径参数合并为 path，旧名靠 **kwargs 兼容而非进 schema。

    原守卫针对"docstring 声明了签名里不存在的路径参数"；签名瘦身后
    output_path/file_path/snapshot_filename/filename 统一由 path 承载，
    旧调用方传入旧名必须仍被接受，所以签名必须保留 VAR_KEYWORD。
    """
    import inspect

    from coapis.agents.tools.browser_control import browser_use

    documented = _documented_args(browser_use)
    assert "path" in documented
    for legacy in ("output_path", "file_path", "snapshot_filename", "filename"):
        assert legacy not in documented, f"{legacy} 应已移出 schema"
    assert "page_x" not in documented
    assert "page_y" not in documented

    sig = inspect.signature(browser_use)
    assert any(
        p.kind == p.VAR_KEYWORD for p in sig.parameters.values()
    ), "签名必须保留 **kwargs 以吸收旧参数名"


def test_browser_use_schema_stays_compact():
    """The B0-2 lever, tightened by D1: 51 params / 5,358 chars → 30 / 3,102.

    The budget is the measured post-D1 size plus room for a few added
    parameters; a rebound past it means the god-tool signature is creeping
    back and every session pays for it.
    """
    import json

    from agentscope.tool import Toolkit

    from coapis.agents.tools.browser_control import browser_use

    toolkit = Toolkit()
    toolkit.register_tool_function(browser_use)
    blob = json.dumps(
        toolkit.get_json_schemas(),
        ensure_ascii=False,
        separators=(",", ":"),
    )
    assert len(blob) < 3_600, f"browser_use schema is {len(blob)} chars"
