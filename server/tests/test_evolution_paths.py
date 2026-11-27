# -*- coding: utf-8 -*-
"""M1 进化路径尺子（evolution.paths）回归测试。

治的病：写侧用 ``constant.SYSTEM_EVOLUTION_DIR``、读侧用
``COAPIS_DATA_DIR``（默认 ``/data``），两把尺子导致注入侧永远读不到
经验账本（实测 1913 条写盘、0 条被读），且异常被 ``logger.debug`` 吞掉。
"""

import asyncio
import json
import logging
from pathlib import Path
from types import SimpleNamespace

import pytest

from coapis.evolution import paths


@pytest.fixture(autouse=True)
def _clear_env(monkeypatch):
    """两条环境变量都必须清干净，否则测试互相污染。"""
    monkeypatch.delenv("COAPIS_EVOLUTION_DIR", raising=False)
    monkeypatch.delenv("COAPIS_DATA_DIR", raising=False)
    paths._missing_reported.clear()


def test_default_root_is_system_evolution_dir():
    """不配任何环境变量时，尺子必须落在 constant 的权威目录上。"""
    from coapis.constant import SYSTEM_EVOLUTION_DIR

    assert paths.evolution_root() == SYSTEM_EVOLUTION_DIR
    assert paths.approved_experiences_file() == (
        SYSTEM_EVOLUTION_DIR / "evolution" / "experiences" / "approved.jsonl"
    )


def test_default_root_is_not_the_dead_data_path():
    """反证：绝不能再退回历史上那个不存在的 /data 尺子。"""
    assert paths.approved_experiences_file() != Path(
        "/data/evolution/experiences/approved.jsonl",
    )


def test_explicit_override_wins(monkeypatch, tmp_path):
    monkeypatch.setenv("COAPIS_EVOLUTION_DIR", str(tmp_path))
    assert paths.evolution_root() == tmp_path
    assert paths.approved_experiences_file() == (
        tmp_path / "evolution" / "experiences" / "approved.jsonl"
    )
    assert paths.foundation_file() == tmp_path / "cross_evolution" / "foundation.json"


def test_legacy_data_dir_env_still_honoured(monkeypatch, tmp_path):
    """保留旧变量语义：<DATA_DIR>/evolution 才是进化根。"""
    monkeypatch.setenv("COAPIS_DATA_DIR", str(tmp_path))
    assert paths.evolution_root() == tmp_path / "evolution"
    assert paths.foundation_file() == (
        tmp_path / "evolution" / "cross_evolution" / "foundation.json"
    )


def test_writer_and_reader_point_at_same_file(tmp_path, monkeypatch):
    """核心不变式：engine 的写入位置 == 注入侧的读取位置。"""
    from coapis.evolution.evolution_engine import EvolutionEngine

    monkey_root = tmp_path
    engine = EvolutionEngine(data_dir=monkey_root)

    _Exp = SimpleNamespace(
        experience_id="e-m1",
        title="m1 title",
        content="m1 content",
        experience_type="rule",
        category="test",
        tags=[],
        confidence=0.9,
        status="approved",
        source_agent_id="agent-a",
        source_session_id="sess-1",
        source_username="u1",
        applicable_scope="global",
        created_at=None,
        updated_at=None,
        version=1,
        source="manual",
        to_dict=lambda: {"experience_id": "e-m1"},
    )

    asyncio.run(engine._save_experience(_Exp))

    # 写侧真实落点
    written = monkey_root / "evolution" / "experiences" / "approved.jsonl"
    assert written.exists(), "engine 未按预期布局写盘"

    # 读侧尺子必须指向同一个 inode
    from coapis.evolution.paths import approved_experiences_file

    assert approved_experiences_file() != written  # 默认根不是 tmp
    monkeypatch.setenv("COAPIS_EVOLUTION_DIR", str(monkey_root))
    assert approved_experiences_file() == written
    saved = json.loads(written.read_text(encoding="utf-8").splitlines()[-1])
    assert saved["experience_id"] == "e-m1"


def test_saved_experience_carries_timestamp(tmp_path):
    """落盘必须自带时间戳。

    实测存量 1913 条经验没有任何时间字段，注入侧的 180 天新鲜度衰减只能
    一律给中性权重 —— 时间尺子空转。这条测试锁死"新写入必须可计时"。
    """
    from coapis.evolution.evolution_engine import EvolutionEngine
    from coapis.evolution.recall import age_days, freshness

    engine = EvolutionEngine(data_dir=tmp_path)
    _Exp = SimpleNamespace(
        experience_id="e-ts", title="t", content="c", experience_type="rule",
        category="test", tags=[], confidence=0.8, status="approved",
        source_agent="agent-a", source_user="u1", source_session="s1",
        created_at=None, updated_at=None, version=1,
        to_dict=lambda: {
            "experience_id": "e-ts", "title": "t", "content": "c",
            "confidence": 0.8, "is_generalizable": True,
        },
    )
    asyncio.run(engine._save_experience(_Exp))

    line = (tmp_path / "evolution" / "experiences" / "approved.jsonl"
            ).read_text(encoding="utf-8").splitlines()[-1]
    saved = json.loads(line)
    assert saved.get("created_at"), "落盘记录缺 created_at"
    assert saved.get("status") == "approved"
    # 时间尺子必须能吃下这个字段，而不是退回中性权重
    assert age_days(saved) is not None
    assert freshness(saved) > 0.99


def test_missing_file_is_logged_as_warning_once(caplog, tmp_path):
    """落空必须留声：WARNING 级，且同一路径只提醒一次。"""
    missing = tmp_path / "nope.jsonl"
    with caplog.at_level(logging.DEBUG, logger="coapis.evolution.paths"):
        assert paths.report_readable(missing, "approved experiences") is False
        assert paths.report_readable(missing, "approved experiences") is False

    warns = [r for r in caplog.records if r.levelno >= logging.WARNING]
    assert len(warns) == 1, f"期望恰好 1 条 WARNING，实得 {len(warns)}"
    assert "nope.jsonl" in warns[0].getMessage()


def test_existing_file_reports_readable_and_stays_quiet(caplog, tmp_path):
    good = tmp_path / "ok.jsonl"
    good.write_text("{}", encoding="utf-8")
    with caplog.at_level(logging.DEBUG, logger="coapis.evolution.paths"):
        assert paths.report_readable(good, "approved experiences") is True
    assert not [r for r in caplog.records if r.levelno >= logging.WARNING]


def test_describe_reports_existence(tmp_path, monkeypatch):
    monkeypatch.setenv("COAPIS_EVOLUTION_DIR", str(tmp_path))
    f = paths.approved_experiences_file()
    f.parent.mkdir(parents=True, exist_ok=True)
    f.write_text('{"a":1}\n{"a":2}\n', encoding="utf-8")
    info = paths.describe()
    assert info["approved_experiences"]["exists"] is True
    assert info["approved_experiences"]["lines"] == 2
    assert info["foundation"]["exists"] is False
