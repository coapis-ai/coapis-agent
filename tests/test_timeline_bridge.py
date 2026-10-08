# -*- coding: utf-8 -*-
"""批次 1 桥接测试：时间线摘要注入 + memory_search 双轨融合。

覆盖：
  A. timeline_digest.build_timeline_digest：空用户/异常/空数据/正常渲染/
     重要性星标/长度截断/空内容跳过；
  B. ReMeLightMemoryManager.memory_search 双轨：台账命中追加补充段、
     台账为空原样返回、台账异常优雅降级、中文二元组分词。

独立运行：python tests/test_timeline_bridge.py
"""

import asyncio
import importlib
import sys
import types
from pathlib import Path
from unittest.mock import MagicMock, patch

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "server"))

RESULTS: list = []


def check(name: str, cond: bool, detail: str = ""):
    RESULTS.append((name, bool(cond), detail))
    print(f"[{'PASS' if cond else 'FAIL'}] {name}" + (f"  ({detail})" if detail and not cond else ""))


def _stub_missing_deps():
    """Stub agentscope bits when the real package is absent (standalone run)."""
    try:
        importlib.import_module("agentscope.message")
        importlib.import_module("agentscope.tool")
        return
    except Exception:  # noqa: BLE001
        pass
    ag = types.ModuleType("agentscope")
    msg = types.ModuleType("agentscope.message")
    tool = types.ModuleType("agentscope.tool")

    class TextBlock(dict):
        def __init__(self, type: str = "text", text: str = ""):
            super().__init__(type=type, text=text)

    class ToolResponse:
        def __init__(self, content=None):
            self.content = content or []

        def get_message_content(self):
            return self.content

    msg.TextBlock = TextBlock
    msg.Msg = TextBlock
    tool.TextBlock = TextBlock
    tool.ToolResponse = ToolResponse
    ag.message = msg
    ag.tool = tool
    sys.modules.setdefault("agentscope", ag)
    sys.modules["agentscope.message"] = msg
    sys.modules["agentscope.tool"] = tool


_stub_missing_deps()

from coapis.foundation import timeline_digest  # noqa: E402
from coapis.agents.memory.reme_light_memory_manager import (  # noqa: E402
    ReMeLightMemoryManager,
)


# ---------------------------------------------------------------- A. digest
def test_digest_empty_user():
    check("A1 空user_id返回空串", timeline_digest.build_timeline_digest(user_id="") == "")
    check("A2 None user_id返回空串", timeline_digest.build_timeline_digest(user_id=None) == "")


def test_digest_repo_failure():
    fake = MagicMock()
    fake.recent.side_effect = RuntimeError("boom")
    with patch(
        "coapis.foundation.repository_factory.RepositoryFactory.get_memory_timeline_repository",
        return_value=fake,
    ):
        out = timeline_digest.build_timeline_digest(user_id="alice")
    check("A3 仓库异常降级为空串", out == "")


def test_digest_no_rows():
    fake = MagicMock()
    fake.recent.return_value = []
    with patch(
        "coapis.foundation.repository_factory.RepositoryFactory.get_memory_timeline_repository",
        return_value=fake,
    ):
        out = timeline_digest.build_timeline_digest(user_id="alice")
    check("A4 无数据返回空串", out == "")


def test_digest_render():
    rows = [
        {"signal_type": "decision", "content": "选用方案B", "importance": 0.9, "created_at": 1},
        {"signal_type": "fact", "content": "生产版本1.0.9", "importance": 0.5, "created_at": 2},
        {"signal_type": "todo", "content": "部署生产", "importance": 0.7, "created_at": 3},
    ]
    fake = MagicMock()
    fake.recent.return_value = rows
    with patch(
        "coapis.foundation.repository_factory.RepositoryFactory.get_memory_timeline_repository",
        return_value=fake,
    ):
        out = timeline_digest.build_timeline_digest(user_id="alice")
    check("A5 含头部标记", "[近期记忆台账]" in out)
    check("A6 决策标签渲染", "[决策]" in out)
    check("A7 高重要性星标", "★选用方案B" in out)
    check("A8 低重要性无星标", "- [事实] 生产版本1.0.9" in out)
    fake.recent.assert_called_once_with(user_id="alice", hours=72, limit=30)
    check("A9 默认72h/30条参数", True)


def test_digest_truncation_and_empty_content():
    rows = [{"signal_type": "fact", "content": "x" * 2000, "importance": 0.1, "created_at": 1}]
    fake = MagicMock()
    fake.recent.return_value = rows
    with patch(
        "coapis.foundation.repository_factory.RepositoryFactory.get_memory_timeline_repository",
        return_value=fake,
    ):
        out = timeline_digest.build_timeline_digest(user_id="alice")
    check("A10 超长截断到600+", len(out) <= 601, f"len={len(out)}")
    check("A11 截断带省略号", out.endswith("…"))

    fake.recent.return_value = [{"signal_type": "fact", "content": "  ", "importance": 0.1, "created_at": 1}]
    out2 = timeline_digest.build_timeline_digest(user_id="alice")
    check("A12 全空内容返回空串", out2 == "")


# ------------------------------------------------------- B. dual-track search
def _make_manager(username="alice"):
    mgr = ReMeLightMemoryManager.__new__(ReMeLightMemoryManager)
    mgr.working_dir = "/tmp/nonexistent-ws"
    mgr.username = username
    mgr._username = username
    mgr._reme_light = MagicMock()
    mgr._memory_manager = MagicMock()
    return mgr


def _file_response(text="file-hit"):
    from agentscope.message import TextBlock
    from agentscope.tool import ToolResponse

    return ToolResponse(content=[TextBlock(type="text", text=text)])


def _patch_ledger(tl_rows, mem_entries=()):
    tl = MagicMock()
    tl.recent.return_value = tl_rows
    mem = MagicMock()
    mem.list_entries.return_value = list(mem_entries)
    rf = MagicMock()
    rf.get_memory_timeline_repository.return_value = tl
    rf.get_memory_repository.return_value = mem
    return patch(
        "coapis.foundation.repository_factory.RepositoryFactory", rf
    ), tl, mem


def test_search_ledger_hit_appended():
    mgr = _make_manager()
    async def _fake_a(**kw):
        return _file_response("file-hit")

    mgr._file_based_search = _fake_a

    entry = MagicMock(title="部署记录", content="生产已部署1.0.9", importance=0.9)
    p, _, _ = _patch_ledger(
        [{"signal_type": "decision", "content": "选用方案B部署", "importance": 0.9}],
        (entry,),
    )
    with p:
        resp = _run(mgr.memory_search("部署 方案B", max_results=5))
    text = _resp_text(resp)
    check("B1 文件结果保留", "file-hit" in text)
    check("B2 台账补充段存在", "[记忆台账补充（数据库）]" in text)
    check("B3 时间线命中进入", "[台账-decision] 选用方案B部署" in text)
    check("B4 记忆条目命中进入", "[记忆条目] 部署记录: 生产已部署1.0.9" in text)


def test_search_ledger_empty_passthrough():
    mgr = _make_manager()
    async def _fake_b(**kw):
        return _file_response("only-file")

    mgr._file_based_search = _fake_b
    p, _, _ = _patch_ledger([])
    with p:
        resp = _run(mgr.memory_search("无关查询xyz", max_results=5))
    text = _resp_text(resp)
    check("B5 无命中不加补充段", "[记忆台账补充（数据库）]" not in text)
    check("B6 原文件结果不变", text == "only-file")


def test_search_ledger_exception_degrades():
    mgr = _make_manager()
    async def _fake_c(**kw):
        return _file_response("safe")

    mgr._file_based_search = _fake_c
    rf = MagicMock()
    rf.get_memory_timeline_repository.side_effect = RuntimeError("db down")
    with patch("coapis.foundation.repository_factory.RepositoryFactory", rf):
        resp = _run(mgr.memory_search("任意查询", max_results=5))
    text = _resp_text(resp)
    check("B7 台账异常优雅降级", text == "safe")


def test_weak_semantics_scoring():
    # Batch 3: lexical overlap replaced by hash cosine (D3 always-on).
    from coapis.foundation.hash_similarity import (
        PROMOTE_SIM_THRESHOLD,
        text_similarity,
    )
    s_close = text_similarity("部署 方案B", "选用方案B部署")
    s_far = text_similarity("部署 方案B", "数据库连接池超时设置")
    check("B8 近似文本高分", s_close > 0.5, f"close={s_close:.3f}")
    check("B9 相异文本更低分", s_far < s_close, f"far={s_far:.3f} close={s_close:.3f}")
    check("B10 晋升阈值=0.85(D2)", PROMOTE_SIM_THRESHOLD == 0.85)


def _run(coro):
    return asyncio.get_event_loop_policy().new_event_loop().run_until_complete(coro)


def _resp_text(resp):
    blocks = list(getattr(resp, "content", None) or [])
    return "".join(
        b.get("text", "") for b in blocks if isinstance(b, dict)
    )


def main():
    test_digest_empty_user()
    test_digest_repo_failure()
    test_digest_no_rows()
    test_digest_render()
    test_digest_truncation_and_empty_content()
    test_search_ledger_hit_appended()
    test_search_ledger_empty_passthrough()
    test_search_ledger_exception_degrades()
    test_weak_semantics_scoring()
    failed = [r for r in RESULTS if not r[1]]
    print(f"\n{len(RESULTS) - len(failed)}/{len(RESULTS)} passed")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
