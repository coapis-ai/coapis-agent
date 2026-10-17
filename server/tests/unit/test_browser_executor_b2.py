"""``_get_executor`` must be a module-level name (B2).

It used to be defined *inside* ``if _USE_SYNC_PLAYWRIGHT:``.  Eight action
functions (``_ensure_browser``, ``_action_start``, ``_action_stop``,
``_action_open``, ``_action_navigate``, ``_action_click``, ``_action_type``,
``_action_snapshot``) reference it 17 times, and on Linux the flag is False,
so the definition never existed while the references did.  Linux survived only
because the branches calling it are also gated by the same flag; on Windows
(``sys.platform == "win32"`` + reload mode) every one of them is a NameError
inside a browser call.

The test is AST-based on purpose: a plain import check would pass even with
the nested definition, because the name is simply absent from the module.
"""

from __future__ import annotations

import ast
import inspect
from concurrent import futures

import pytest

from coapis.agents.tools import browser_control as bc

SOURCE = inspect.getsource(bc)
TREE = ast.parse(SOURCE)


def _module_functions() -> list[ast.AST]:
    return [
        node
        for node in ast.walk(TREE)
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
    ]


class TestExecutorIsModuleLevel:
    def test_name_lives_on_the_module(self):
        assert hasattr(bc, "_get_executor"), (
            "_get_executor must be importable from the module, not nested "
            "inside a conditional block"
        )

    def test_defined_at_top_level_of_the_module(self):
        top = {
            node.name
            for node in TREE.body
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
        }
        assert "_get_executor" in top, "_get_executor is nested"

    def test_not_nested_inside_the_sync_playwright_branch(self):
        for node in TREE.body:
            if isinstance(node, ast.If):
                for sub in ast.walk(node):
                    if (
                        isinstance(sub, (ast.FunctionDef, ast.AsyncFunctionDef))
                        and sub.name == "_get_executor"
                    ):
                        pytest.fail("_get_executor is defined inside an if-block")

    def test_returns_a_thread_pool(self):
        assert isinstance(bc._get_executor(), futures.ThreadPoolExecutor)

    def test_singleton(self):
        assert bc._get_executor() is bc._get_executor()


class TestEveryCallSiteResolves:
    """No function may load a name the module does not define."""

    def test_no_unbound_reference(self):
        offenders = []
        for func in _module_functions():
            local_defs = {
                n.name
                for n in ast.walk(func)
                if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))
                and n is not func
            }
            args = {
                a.arg
                for a in list(func.args.args)
                + list(func.args.kwonlyargs)
                + list(func.args.posonlyargs)
            }
            assigned = {
                t.id
                for n in ast.walk(func)
                if isinstance(n, ast.Assign)
                for t in ast.walk(n)
                if isinstance(t, ast.Name) and isinstance(t.ctx, ast.Store)
            }
            for node in ast.walk(func):
                if (
                    isinstance(node, ast.Name)
                    and node.id == "_get_executor"
                    and isinstance(node.ctx, ast.Load)
                ):
                    if not (
                        "_get_executor" in local_defs
                        or "_get_executor" in args
                        or "_get_executor" in assigned
                        or hasattr(bc, "_get_executor")
                    ):
                        offenders.append((func.name, node.lineno))
        assert not offenders, f"unbound _get_executor at {offenders}"

    def test_call_sites_are_many_and_unchanged(self):
        # The fix must not have deleted the call sites; it only moved the
        # definition.  17 references existed at discovery; guard the count.
        refs = SOURCE.count("_get_executor()")
        assert refs >= 15, f"only {refs} call sites left — call sites were dropped"

    def test_run_sync_still_gated_by_the_flag(self):
        # Behaviour must not change on Linux: async path stays async.
        assert inspect.iscoroutinefunction(bc._run_sync)
