#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""实测 browser_use 的 schema 体量与瘦身空间（只读诊断，不改代码）。"""
import json
import sys

sys.path.insert(0, "/app")

from coapis.agents.tools.browser_control import browser_use  # noqa: E402


def size_of(fn) -> int:
    from agentscope.tools import ToolFunction  # noqa: F401

    schema = fn.__annotations__  # noqa: E401
    return len(json.dumps(schema, ensure_ascii=False))


def main() -> None:
    import inspect

    doc = browser_use.__doc__ or ""
    sig = inspect.signature(browser_use)
    params = list(sig.parameters)
    print("browser_use 参数数:", len(params))
    print("docstring chars:", len(doc))
    # 参数默认值 + 注解序列化体量
    ann = {}
    for p in params:
        pa = sig.parameters[p]
        ann[p] = {
            "annotation": str(pa.annotation),
            "default": repr(pa.default),
            "doc": "",
        }
    blob = json.dumps(ann, ensure_ascii=False)
    print("参数注解 JSON chars:", len(blob))
    print("合计（docstring + 注解）:", len(doc) + len(blob))
    # 每个参数的注解长度
    per = sorted(
        ((len(json.dumps(v, ensure_ascii=False)), k) for k, v in ann.items()),
        reverse=True,
    )
    print("最大 8 个参数注解:")
    for n, k in per[:8]:
        print("   %-22s %d" % (k, n))


main()
