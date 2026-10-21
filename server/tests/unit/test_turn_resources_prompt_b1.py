# -*- coding: utf-8 -*-
"""本轮资源清单注入提示词（B1 的 agent 侧消费）。

盯两件事：

1. 有资源时提示词里必须出现「## 本轮资源」，网页给链接、文件给路径，
   产出/引用要区分 —— 这是追问时免重搜的依据。
2. 无资源时必须返回空串 —— 不能往系统提示词里塞空段落白吃 token。
"""
from __future__ import annotations

from coapis.agents.react_agent import CoApisAgent


def _block(items):
    agent = CoApisAgent.__new__(CoApisAgent)
    return agent._build_turn_resources_block(items)


def test_block_renders_web_and_files():
    txt = _block(
        [
            # 采集器本轮快照的真实形状：网页用 ref，文件用 path
            {"kind": "web", "title": "韦伯", "ref": "https://example.com/a", "role": "reference"},
            {"kind": "file", "title": "webb_summary.md", "path": "files/webb_summary.md", "role": "producer"},
            {"kind": "file", "title": "AGENTS.md", "path": "AGENTS.md", "role": "reference"},
            # 台账端点形状：统一 path
            {"kind": "web", "title": "台账", "path": "https://example.com/b", "role": "reference"},
        ]
    )
    assert "## 本轮资源" in txt
    assert "https://example.com/a" in txt
    assert "https://example.com/b" in txt
    assert "files/webb_summary.md" in txt
    assert "产出" in txt and "引用" in txt


def test_block_empty_when_no_items():
    assert _block([]) == ""
    assert _block([{"kind": "other", "title": "x", "path": "y"}]) == ""


def test_block_caps_at_fifteen():
    items = [
        {"kind": "web", "title": f"t{i}", "ref": f"https://e/{i}", "role": "reference"}
        for i in range(40)
    ]
    txt = _block(items)
    assert txt.count("- 网页：") == 15
