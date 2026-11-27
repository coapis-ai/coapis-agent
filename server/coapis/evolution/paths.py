# -*- coding: utf-8 -*-
"""进化/经验产物的路径尺子（单一实现，SSOT）。

## 为什么存在

历史上同一份经验账本有两把尺子：

- **写侧**（``evolution_engine._save_experience`` / ``workspace``）
  用 ``constant.SYSTEM_EVOLUTION_DIR``，落在
  ``<WORKING_DIR>/system/evolution/evolution/experiences/approved.jsonl``。
- **读侧**（``react_agent`` 注入段）
  用 ``os.environ.get("COAPIS_DATA_DIR", "/data")``，落在
  ``/data/evolution/experiences/approved.jsonl``。

容器内既没有 ``COAPIS_DATA_DIR`` 也没有 ``/data``，所以读侧**每一次都
落空**；而读取包在 ``try/except: logger.debug(...)`` 里，落空被静默吞掉。
结果：自动提取的经验持续写盘 47 天（实测 1913 条）却从未进入任何一次
对话上下文，且日志里查不到任何异常。

本模块是这类路径的**唯一**来源，写侧与读侧必须同源。

## 物理布局说明

``system/evolution/evolution/experiences/`` 里的双层 ``evolution`` 是历史
遗留（``data_dir`` 已含 ``evolution``，拼接时又加了一次）。此处**刻意保留
原样**：统一尺子不等于搬迁生产数据，改物理路径会让存量 1913 条经验失联。

## 解析优先级

1. ``COAPIS_EVOLUTION_DIR`` —— 显式指定进化数据根（测试 / 迁移用）
2. ``COAPIS_DATA_DIR``      —— 兼容旧环境变量（历史读侧的口径）
3. ``constant.SYSTEM_EVOLUTION_DIR`` —— 生产默认

显式覆盖会打一条 INFO，保证"尺子被改过"这件事可观测。
"""

from __future__ import annotations

import logging
import os
from pathlib import Path

logger = logging.getLogger(__name__)

# 覆盖过一次就不再重复打日志，避免每次注入都刷屏。
_warned_override: str = ""


def _resolve_root() -> Path:
    """解析进化数据根目录（见模块 docstring 的优先级）。"""
    explicit = (os.environ.get("COAPIS_EVOLUTION_DIR") or "").strip()
    if explicit:
        root = Path(explicit).expanduser()
        _note_override("COAPIS_EVOLUTION_DIR", root)
        return root

    legacy = (os.environ.get("COAPIS_DATA_DIR") or "").strip()
    if legacy:
        root = Path(legacy).expanduser() / "evolution"
        _note_override("COAPIS_DATA_DIR", root)
        return root

    # 延迟导入：constant 会读取环境变量并建目录，避免模块级循环依赖。
    from ..constant import SYSTEM_EVOLUTION_DIR

    return SYSTEM_EVOLUTION_DIR


def _note_override(source: str, root: Path) -> None:
    global _warned_override
    marker = f"{source}={root}"
    if marker != _warned_override:
        logger.info("[EvolutionPaths] data root from %s: %s", source, root)
        _warned_override = marker


def evolution_root() -> Path:
    """进化数据根目录。"""
    return _resolve_root()


def approved_experiences_dir() -> Path:
    """已批准经验账本所在目录。"""
    # 双层 evolution 为历史布局，详见模块 docstring。
    return _resolve_root() / "evolution" / "experiences"


def approved_experiences_file() -> Path:
    """已批准经验账本（JSONL，一行一条）。"""
    return approved_experiences_dir() / "approved.jsonl"


def pending_experiences_dir() -> Path:
    """待审经验目录。"""
    return _resolve_root() / "evolution" / "experiences"


def cross_evolution_dir() -> Path:
    """跨智能体进化数据目录。"""
    return _resolve_root() / "cross_evolution"


def foundation_file() -> Path:
    """跨智能体基础层经验文件。"""
    return cross_evolution_dir() / "foundation.json"


# 同一个缺失路径只提醒一次，避免每轮对话刷屏。
_missing_reported: set = set()


def report_readable(path: Path, context: str = "") -> bool:
    """路径存在返回 True；不存在时打一条 WARNING 并返回 False。

    历史病灶：读侧落空被 ``logger.debug`` 吞掉，经验账本写了 47 天、
    1913 条，没有一次被读进上下文，日志里也查不到痕迹。可观测性是这个
    模块存在的理由之一 —— 落空必须留声。
    """
    if path.exists():
        return True
    key = f"{path}|{context}"
    if key not in _missing_reported:
        _missing_reported.add(key)
        logger.warning(
            "[EvolutionPaths] %s missing at %s — evolution context will be empty",
            context or "evolution file",
            path,
        )
    return False


def describe() -> dict:
    """当前尺子的解析结果，供诊断接口输出。"""
    root = _resolve_root()
    approved = approved_experiences_file()
    found = foundation_file()
    return {
        "root": str(root),
        "approved_experiences": {
            "path": str(approved),
            "exists": approved.exists(),
            "lines": (
                sum(1 for _ in approved.open(encoding="utf-8", errors="replace"))
                if approved.exists() else 0
            ),
        },
        "foundation": {
            "path": str(found),
            "exists": found.exists(),
        },
    }
