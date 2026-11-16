# -*- coding: utf-8 -*-
"""台账契约扫描：所有 write_ledger(...) 调用点只能传签名里存在的参数。

为什么需要这条测试（2026-11-16 实锤）：
``loop_gates._write_ledger`` 传了签名里不存在的 ``complexity=""``，
``write_ledger`` 抛 TypeError，被调用方 ``except Exception: pass`` 吞掉，
于是"循环闸在岗、台账 0 行"持续数日无人察觉。单测当时用
``fake_write_ledger(**kwargs)`` 兜底，任何参数都收，同样测不出来。

本扫描把"参数名拼错/签名漂移"这一整类静默故障变成显式失败。
"""
from __future__ import annotations

import ast
import inspect
import os

from coapis.decision import ledger_contract

_SERVER_ROOT = os.path.dirname(
    os.path.dirname(os.path.dirname(os.path.abspath(ledger_contract.__file__)))
)  # .../server（含 coapis/ 与 tests/，调用点两边都有）


def _iter_py_files(root: str):
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [
            d for d in dirnames if d not in ("__pycache__", "node_modules", ".git")
        ]
        for fn in filenames:
            if fn.endswith(".py"):
                yield os.path.join(dirpath, fn)


def test_write_ledger_signature_is_keyword_only_and_closed():
    """签名必须收口（无 **kwargs），否则本扫描失去意义。"""
    params = inspect.signature(ledger_contract.write_ledger).parameters
    assert not any(
        p.kind == inspect.Parameter.VAR_KEYWORD for p in params.values()
    ), "write_ledger 一旦加 **kwargs，调用点错参将重新变成静默故障"


def test_all_write_ledger_call_sites_match_signature():
    valid = set(inspect.signature(ledger_contract.write_ledger).parameters)
    offenders: list[str] = []
    scanned = 0

    for path in _iter_py_files(_SERVER_ROOT):
        try:
            tree = ast.parse(open(path, encoding="utf-8").read())
        except (SyntaxError, UnicodeDecodeError):
            continue
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            fn = node.func
            name = fn.attr if isinstance(fn, ast.Attribute) else (
                fn.id if isinstance(fn, ast.Name) else ""
            )
            if name != "write_ledger":
                continue
            scanned += 1
            rel = os.path.relpath(path, _SERVER_ROOT)
            for kw in node.keywords:
                if kw.arg is None:
                    continue  # **dict 展开：交给运行时 bind 校验
                if kw.arg not in valid:
                    offenders.append(
                        "%s:%d 未知参数 %s=（write_ledger 不支持）"
                        % (rel, node.lineno, kw.arg)
                    )

    assert scanned >= 10, "扫描到的调用点过少（%d），可能路径推导错了" % scanned
    assert not offenders, "write_ledger 调用点存在签名外参数：\n" + "\n".join(
        offenders
    )
