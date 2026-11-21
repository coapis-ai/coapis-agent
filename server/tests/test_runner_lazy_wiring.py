# -*- coding: utf-8 -*-
"""Runner 懒接线回归 —— 防止"刷新后助手回复消失"复发。

根因（2026-11-20 dev 实锤）：Workspace.runner 属性只在**首次创建** Runner 时
一次性接线 chat_manager/_mcp_manager；workspace 服务是懒启动的，Runner 若先
于服务就绪被创建并缓存，就会永久缺接线 → query_handler 取不到 chat →
_persist_chat_messages 与状态置 idle 整块**静默跳过** → 会话快照只剩 user
消息，刷新后助手回复消失。

本文件锁两层防线（C 防线由 dev 真流量 E2E 覆盖）：
1. Workspace._wire_runner 幂等补接线（服务就绪后自动补齐，且不清已接的）；
2. Runner._resolve_chat_manager 兜底（从自身 _workspace 现取现接并缓存）。
"""
from __future__ import annotations

from types import SimpleNamespace


class _FakeRunner:
    """最小 Runner 替身：只记录 set_* 接线结果。"""

    def __init__(self):
        self._chat_manager = None
        self._mcp_manager = None

    def set_chat_manager(self, cm):
        self._chat_manager = cm

    def set_mcp_manager(self, m):
        self._mcp_manager = m


def _bare_workspace():
    from coapis.agents.workspace import Workspace

    ws = object.__new__(Workspace)
    ws.agent_id = "test-agent"
    ws.username = "tester"
    ws.chat_manager = None
    ws._mcp_manager = None
    return ws


def test_wire_runner_is_idempotent_and_late_safe():
    """服务晚到也要接上；已接的不得被后续访问清掉。"""
    ws = _bare_workspace()
    r = _FakeRunner()

    # 服务未就绪：不得接线、不得抛错
    ws._wire_runner(r)
    assert r._chat_manager is None
    assert r._mcp_manager is None

    # 服务就绪：补接线
    cm = object()
    mcp = object()
    ws.chat_manager = cm
    ws._mcp_manager = mcp
    ws._wire_runner(r)
    assert r._chat_manager is cm
    assert r._mcp_manager is mcp

    # 幂等：重复访问/属性缺失都不得回退或抛错
    ws._wire_runner(r)
    assert r._chat_manager is cm
    ws.chat_manager = None
    ws._wire_runner(r)
    assert r._chat_manager is cm
    ws._wire_runner(None)  # 不得抛错


def test_runner_resolve_chat_manager_falls_back_to_workspace():
    """Runner 侧兜底：接线缺失时从 _workspace 现取现接并缓存。"""
    from coapis.app.runner.runner import AgentRunner

    r = object.__new__(AgentRunner)
    r.agent_id = "test-agent"
    r._chat_manager = None
    cm = object()
    r._workspace = SimpleNamespace(chat_manager=cm, workspace_id="w1")

    assert r._resolve_chat_manager() is cm
    assert r._chat_manager is cm  # 自愈后缓存，后续零开销


def test_runner_resolve_chat_manager_none_when_unavailable():
    from coapis.app.runner.runner import AgentRunner

    r = object.__new__(AgentRunner)
    r.agent_id = "test-agent"
    r._chat_manager = None
    r._workspace = SimpleNamespace(chat_manager=None)

    assert r._resolve_chat_manager() is None
    assert r._chat_manager is None
