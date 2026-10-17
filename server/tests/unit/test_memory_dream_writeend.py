#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""守卫：记忆写入端 + LLM 调用范式（dream 闭环的三条命门）。

对应实测抓到的三个真缺陷：
1. reme_light 直传 Msg 给 chat_model → OpenAI 层拒（messages 期望 list）
2. ChatResponse 是 dict 子类且无 get_text_content → 连 hasattr 都抛 KeyError
3. 没有任何代码写 memory/YYYY-MM-DD.md → dream 恒 SKIPPED、MEMORY.md 永不更新
"""

from __future__ import annotations

import asyncio
import json
import time
from pathlib import Path

import pytest

from coapis.agents.memory.reme_light_memory_manager import (
    ReMeLightMemoryManager,
    _call_llm,
    _text_of,
)
from coapis.agents.memory.signal_extractor import collect_session_digest


# ── 1. LLM 调用范式 ──────────────────────────────────────────────


class _DictResp(dict):
    """模拟 ChatResponse：dict 子类 + __getattr__ 走 __getitem__。"""

    def __getattr__(self, name: str):
        try:
            return self[name]
        except KeyError as exc:  # 真实 ChatResponse 就是这样炸的
            raise KeyError(name) from exc


def test_text_of_survives_dict_response_without_get_text_content():
    """真缺陷：res.get_text_content() 抛 KeyError，hasattr 也吞不下。"""
    resp = _DictResp(
        {"content": [{"type": "text", "text": "甲"}, {"type": "text", "text": "乙"}]},
    )
    assert _text_of(resp) == "甲乙"
    # 直取属性必须炸（守卫这条路径不能再被使用）
    with pytest.raises(KeyError):
        _ = resp.get_text_content  # noqa: B018


def test_text_of_edge_cases():
    assert _text_of(None) == ""
    assert _text_of("纯文本") == "纯文本"
    assert _text_of({"content": "字符串内容"}) == "字符串内容"
    assert _text_of({"no_content": 1}) == ""
    assert _text_of({"content": [{"type": "tool_use", "name": "x"}]}) == ""


class _FakeFormatter:
    def __init__(self):
        self.seen = None

    async def format(self, msgs):
        self.seen = msgs
        return [{"role": m.role, "content": m.content} for m in msgs]


class _FakeModel:
    def __init__(self, stream=False):
        self.stream = stream
        self.received = None

    async def __call__(self, messages):
        self.received = messages
        if self.stream:
            return self._gen()
        return _DictResp({"content": [{"type": "text", "text": "ok" * 30}]})

    async def _gen(self):
        yield _DictResp({"content": [{"type": "text", "text": "a"}]})
        yield _DictResp({"content": [{"type": "text", "text": "ab"}]})


def test_call_llm_passes_list_not_msg():
    """真缺陷：直传 Msg 会被 OpenAI 层拒绝。"""
    from agentscope.message import Msg

    fmt, model = _FakeFormatter(), _FakeModel()
    msg = Msg(role="user", name="t", content="hi")
    out = asyncio.run(_call_llm(model, fmt, msg))
    assert out == "ok" * 30
    assert isinstance(model.received, list), "必须传 list，不能传 Msg"
    assert fmt.seen == [msg], "formatter 必须先收到 Msg 列表"


def test_call_llm_converges_stream():
    """stream=True 时模型返回 async generator，必须收敛成最后一个 chunk。"""
    from agentscope.message import Msg

    out = asyncio.run(
        _call_llm(
            _FakeModel(stream=True),
            _FakeFormatter(),
            Msg(role="user", name="t", content="hi"),
        ),
    )
    assert out == "ab"


# ── 2. 会话要点抽取 ──────────────────────────────────────────────


def _write_session(path: Path, pairs):
    path.write_text(
        json.dumps(
            {"agent": {"memory": {"content": [
                [{"role": r, "content": c} for r, c in pairs],
            ]}}},
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )


def test_collect_session_digest_head_for_user_tail_for_assistant(tmp_path):
    sess = tmp_path / "s1.json"
    _write_session(sess, [
        ("user", "请分析组件库选型" + "x" * 500),
        ("assistant", "过程叙述" + "y" * 500 + "建议采用 Element Plus"),
        ("system", "系统噪声不应出现"),
    ])
    digest = collect_session_digest(sess)
    assert "用户：请分析组件库选型" in digest
    assert "建议采用 Element Plus" in digest, "助手结论在尾部，必须保留"
    assert "系统噪声不应出现" not in digest
    assert len(digest) <= 2600


def test_collect_session_digest_broken_file(tmp_path):
    bad = tmp_path / "bad.json"
    bad.write_text("{半截", encoding="utf-8")
    assert collect_session_digest(bad) == ""


# ── 3. 写入端：无笔记时从会话生成 ────────────────────────────────


def _mgr(tmp_path: Path) -> ReMeLightMemoryManager:
    return ReMeLightMemoryManager(
        working_dir=str(tmp_path), agent_id="user:tester", username="tester",
    )


def test_ensure_daily_note_respects_agent_written_note(tmp_path):
    """智能体亲手写过的当日笔记不得被覆盖。"""
    mem = tmp_path / "memory"
    mem.mkdir()
    today = mem / "2026-10-17.md"
    today.write_text("我自己写的笔记，别覆盖", encoding="utf-8")
    mgr = _mgr(tmp_path)
    ok = asyncio.run(mgr._ensure_daily_note(
        tmp_path, _FakeModel(), _FakeFormatter(), "zh", "2026-10-17", "",
    ))
    assert ok is True
    assert "别覆盖" in today.read_text(encoding="utf-8")


def test_ensure_daily_note_generates_from_sessions(tmp_path):
    sess_dir = tmp_path / "sessions"
    sess_dir.mkdir()
    sess = sess_dir / "s.json"
    _write_session(sess, [
        ("user", "把 md 转成 docx"),
        ("assistant", "已生成 report.docx，放在 files 目录"),
    ])
    mgr = _mgr(tmp_path)
    ok = asyncio.run(mgr._ensure_daily_note(
        tmp_path, _FakeModel(), _FakeFormatter(), "zh", "2026-10-17", "",
    ))
    assert ok is True
    note = (tmp_path / "memory" / "2026-10-17.md").read_text(encoding="utf-8")
    assert note.strip() == "ok" * 30


def test_ensure_daily_note_without_sessions(tmp_path):
    mgr = _mgr(tmp_path)
    ok = asyncio.run(mgr._ensure_daily_note(
        tmp_path, _FakeModel(), _FakeFormatter(), "zh", "2026-10-17", "",
    ))
    assert ok is False
    assert not (tmp_path / "memory" / "2026-10-17.md").exists()


def test_registry_passes_timezone_to_cron_manager():
    """真缺陷：registry 不传 timezone → 企业版 per-user dream 恒 UTC，
    于是 "0 23 * * *" 实际跑在北京时间早 7 点。"""
    import inspect

    from coapis.app.crons.registry import CronManagerRegistry

    src = inspect.getsource(CronManagerRegistry.get_or_create)
    assert "timezone=" in src, "必须显式传时区，否则恒 UTC"
    assert "normalize_tz" in src
