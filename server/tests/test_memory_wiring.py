# -*- coding: utf-8 -*-
"""长期记忆接线回归 —— 防止"压缩摘要永远进不了长期记忆"复发。

根因一（2026-11-22 dev 实锤）：``Workspace.runner`` 把 agent 的
``memory_manager`` 接成了文件版 ``MemoryManager``，而真正实现了
``add_summarize_task / get_memory_prompt / memory_search`` 的注册表后端
（remelight）只被赋给 ``memory_backend`` 供 dream 定时任务用。于是
``light_context_manager`` 里两条交接路径（压缩后 :979、每 N 轮 :1177）
每次都撞上 ``hand_to_long_term_memory`` 的 "lacks add_summarize_task"
分支，只留一行 INFO 就被丢弃——长期记忆从未收到过任何东西。

根因二（同一轮改动自身引入）：为换掉 legacy 而删了模块级
``from .memory_manager import MemoryManager``，但 ServiceManager 的
``name="memory"`` 工厂仍在用它 → 容器启动即 NameError，workspace 起不来。
全量测试 2079 条无一条覆盖该工厂，故未拦住。
"""
from __future__ import annotations

import inspect

from coapis.agents.memory.base_memory_manager import get_memory_manager_backend


def _runner_source():
    from coapis.agents.workspace import Workspace

    return inspect.getsource(Workspace.runner.fget)


def test_legacy_manager_resolves_for_memory_service():
    """ServiceManager 的 memory 工厂依赖模块级符号，删不得。"""
    import coapis.agents.workspace as ws_mod
    from coapis.agents.memory_manager import MemoryManager

    assert "MemoryManager" in vars(ws_mod), (
        "workspace 模块缺 MemoryManager 符号："
        "name='memory' 服务会在启动时抛 NameError"
    )
    assert vars(ws_mod)["MemoryManager"] is MemoryManager


def test_runner_shares_one_memory_manager_across_both_roles():
    """agent 的 memory_manager 与 dream 的 memory_backend 必须同一个对象。"""
    src = _runner_source()

    assert "r.memory_manager = _memory_manager" in src, (
        "agent 的 memory_manager 又被接回非注册表后端：长期记忆会断链"
    )
    assert "r.memory_backend = _memory_manager" in src
    # 同一处构造、两处赋值，避免两份实例各自持有任务队列
    assert src.count("_memory_manager = _mm_cls(") == 1


def test_agent_role_backend_provides_long_term_api():
    """默认后端必须齐备 agent 侧用到的全部长期记忆能力。"""
    mm_cls = get_memory_manager_backend("remelight")
    required = (
        "add_summarize_task",   # hand_to_long_term_memory 唯一入口
        "list_summarize_status",  # /compact /summarize 的状态查询
        "get_memory_prompt",     # 系统提示里的长期记忆引导
        "list_memory_tools",     # 记忆检索工具注册
        "memory_search",
        "dream",                 # 夜间进化
        "close",
    )
    missing = [n for n in required if not hasattr(mm_cls, n)]
    assert not missing, "后端缺少长期记忆接口: %s" % missing


def test_legacy_manager_cannot_serve_agent_role():
    """锁住历史病灶：文件版没有长期记忆接口，所以不能被交给 agent。"""
    from coapis.agents.memory_manager import MemoryManager

    for name in ("add_summarize_task", "get_memory_prompt", "memory_search"):
        assert not hasattr(MemoryManager, name), (
            "%s 现在有了长期记忆接口，本用例的病灶描述已过期，"
            "请连同本文件 docstring 一起更新" % name
        )
