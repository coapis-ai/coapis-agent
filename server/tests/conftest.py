# -*- coding: utf-8 -*-
"""测试期 CWD 污染哨兵。

背景：``sqlite3.connect(path)`` 的默认语义是「文件不存在就建一个 0 字节库」。
测试若把相对路径交给它，就会在**进程 CWD**（开发机上是仓库根，生产容器里是
数据根）留下孤儿 ``*.db``。这类文件既不会被清理，也会让下一次启动/探测
「看起来又误建了」。

本 fixture 不阻止创建（不改 CWD，避免影响依赖相对路径的用例），而是：
每个用例结束后比对 CWD 下的 ``*.db`` 集合，**新增即失败**，并把新增文件
搬到该用例的 ``tmp_path`` 里，避免污染在多次运行间累积。
"""
from __future__ import annotations

import shutil
from pathlib import Path

import pytest


def _cwd_dbs() -> dict[str, Path]:
    cwd = Path.cwd()
    return {p.name: p for p in cwd.glob("*.db")}


@pytest.fixture(autouse=True)
def cwd_db_pollution_guard(tmp_path: Path) -> None:
    """用例期间在 CWD 新建的 ``*.db`` 视为缺陷，立即失败并移出 CWD。"""
    before = _cwd_dbs()
    yield
    new = {k: v for k, v in _cwd_dbs().items() if k not in before}
    if not new:
        return
    dump = tmp_path / "cwd_db_pollution"
    dump.mkdir(parents=True, exist_ok=True)
    moved = []
    for name, path in sorted(new.items()):
        target = dump / name
        try:
            shutil.move(str(path), str(target))
            moved.append(f"{name} -> {target}")
        except OSError as exc:  # CWD 只读挂载时搬不动，如实报告
            moved.append(f"{name} (CWD={path.parent}，搬移失败: {exc})")
    pytest.fail(
        "测试在进程 CWD 里创建了 SQLite 库（sqlite3.connect 对不存在的文件会"
        "静默建 0 字节库）：\n  "
        + "\n  ".join(moved)
        + f"\nCWD={Path.cwd()}\n"
        "修法：测试用 tmp_path 拼绝对路径；诊断脚本用 scripts/_probe_db.connect_ro。"
    )
