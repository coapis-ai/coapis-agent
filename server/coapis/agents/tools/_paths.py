# -*- coding: utf-8 -*-
"""工具层工作区解析——**禁止回退进程 CWD**。

历史缺陷：二十来个工具里写着 ``return Path.cwd()`` 作为「拿不到工作区」的
兜底。进程 CWD 在容器里是 ``/app``、在数据根是 ``/apps/ai/coapis-dev``，
于是 ``Path.cwd() / "files" / "x.db"`` 这类相对路径会在**数据根目录**里
建出 ``data_store.db`` 之类的孤儿库；``sqlite3.connect`` 的默认语义又是
「不存在就建」，于是每次探测/启动/测试都在数据根留下 0 字节空库。

本模块给出唯一允许的兜底：拿不到工作区时，落到
``WORKING_DIR/files/_orphan/<工具名>/`` 并打 WARN——产物可见、可清理，
且永远不会污染进程 CWD。
"""
from __future__ import annotations

import logging
from pathlib import Path

from ...constant import WORKING_DIR

logger = logging.getLogger(__name__)

_ORPHAN_ROOT = WORKING_DIR / "files" / "_orphan"


def current_workspace_dir() -> Path | None:
    """当前请求上下文的工作区；无上下文返回 None。"""
    try:
        from ...config.context import get_current_workspace_dir

        ws = get_current_workspace_dir()
    except Exception:  # 无请求上下文 / 上下文未初始化
        return None
    if not ws:
        return None
    return Path(ws)


def workspace_dir(caller: str) -> Path:
    """工作区目录；无上下文时落到隔离目录并 WARN（绝不返回 CWD）。"""
    ws = current_workspace_dir()
    if ws is not None:
        return ws
    fallback = _ORPHAN_ROOT / caller
    logger.warning(
        "工具 %r 无工作区上下文，回退隔离目录 %s（原实现回退进程 CWD=%s，"
        "会把产物写进启动目录）",
        caller,
        fallback,
        Path.cwd(),
    )
    fallback.mkdir(parents=True, exist_ok=True)
    return fallback


def files_dir(caller: str) -> Path:
    """工作区下的 ``files/`` 产物目录（自动创建）。"""
    out = workspace_dir(caller) / "files"
    out.mkdir(parents=True, exist_ok=True)
    return out
