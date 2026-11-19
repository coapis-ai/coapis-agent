"""v28 · 方案A —— 本轮资源「台账 ∪ 采集器」合流的契约测试。

钉住四件事（全部对应小蜜蜂 2026-11-19 投诉的「本轮只有引用、产出整组消失」）：

① 台账与采集器**合流**，不再 ``or`` 二选一；
② 归属尺子与会话面板一致：优先 ChatSpec.user_id，回退登录名；
③ 同一条资源两侧口径冲突时 producer 压过 reference；
④ 会话后台补扫真的跑扫描，不再自我投递。
"""
import asyncio

import pytest

from coapis.app.runner import runner as R


@pytest.fixture
def stub(monkeypatch):
    """把两个取数口换成可编程的桩，返回可写状态。"""
    state = {"ledger": [], "collector": [], "ledger_calls": []}

    def _ledger(chat_id, username, **kw):
        state["ledger_calls"].append((chat_id, username))
        return [dict(x) for x in state["ledger"]]

    monkeypatch.setattr(R, "_turn_resources_from_ledger", _ledger)
    monkeypatch.setattr(R, "_take_turn_resources", lambda: [dict(x) for x in state["collector"]])
    return state


def test_merges_instead_of_choosing_one_side(stub):
    """台账只有引用、采集器有产出 → 两组都要在（旧实现会只剩一边）。"""
    stub["ledger"] = [{"kind": "file", "path": "files/media/a.pptx", "role": "reference"}]
    stub["collector"] = [{"kind": "file", "path": "files/plan.md", "role": "producer"}]
    out = R._finalize_turn_resources("chat-1", "wangjing")
    by_role = {r["role"] for r in out}
    assert by_role == {"producer", "reference"}, out
    assert {r["path"] for r in out} == {"files/media/a.pptx", "files/plan.md"}


def test_empty_ledger_keeps_collector(stub):
    stub["ledger"] = []
    stub["collector"] = [{"kind": "file", "path": "files/a.md", "role": "producer"}]
    assert [r["path"] for r in R._finalize_turn_resources("chat-1", "u")] == ["files/a.md"]


def test_empty_collector_keeps_ledger(stub):
    stub["ledger"] = [{"kind": "file", "path": "files/a.md", "role": "producer"}]
    stub["collector"] = []
    assert [r["path"] for r in R._finalize_turn_resources("chat-1", "u")] == ["files/a.md"]


def test_producer_beats_reference_on_same_file(stub):
    """同一份文件：台账登记成 reference，采集器说是 producer → 产出身份优先。"""
    stub["ledger"] = [{"kind": "file", "path": "files/out.md", "role": "reference",
                       "size_bytes": 12}]
    stub["collector"] = [{"kind": "file", "path": "files/out.md", "role": "producer"}]
    out = R._finalize_turn_resources("chat-1", "u")
    assert len(out) == 1, out
    assert out[0]["role"] == "producer"
    # 台账侧独有的展示位不能被采集器抹掉
    assert out[0]["size_bytes"] == 12


def test_abs_and_rel_path_are_one_file(stub):
    """台账存相对路径、采集器存绝对路径 → 去重尺子必须认得是同一份。"""
    stub["ledger"] = [{"kind": "file", "path": "files/report.md", "role": "producer"}]
    stub["collector"] = [{
        "kind": "file",
        "path": "/apps/ai/coapis/workspaces/zrsz_189/files/report.md",
        "role": "producer",
    }]
    out = R._finalize_turn_resources("chat-1", "u")
    assert len(out) == 1, out


def test_owner_ruler_follows_chat_spec(stub):
    """归属用会话属主（工作区属主），不是登录名——分裂账号不再读空台账。"""
    R._finalize_turn_resources("chat-1", "wangjing", "zrsz_189")
    assert stub["ledger_calls"] == [("chat-1", "zrsz_189")]


def test_owner_falls_back_to_username(stub):
    R._finalize_turn_resources("chat-1", "wangjing", "")
    assert stub["ledger_calls"] == [("chat-1", "wangjing")]


def test_web_refs_keyed_by_url(stub):
    """网络引用没有 path：按 URL 去重，别和文件混成一桶。"""
    stub["ledger"] = [{"kind": "web", "url": "https://x.cn/a", "role": "reference"}]
    stub["collector"] = [{"kind": "web", "url": "https://x.cn/A", "role": "reference"}]
    out = R._finalize_turn_resources("chat-1", "u")
    assert len(out) == 1, out


def test_backfill_task_scans_once_not_itself(monkeypatch):
    """后台补扫必须真的调扫描函数。

    旧实现在协程里 ``create_task`` 调自己：扫描一次都没跑、任务链永不停歇。
    """
    calls = []

    def _fake_scan(chat_id, username):
        calls.append((chat_id, username))

    monkeypatch.setattr(R, "_session_backfill_resources", _fake_scan)
    asyncio.run(asyncio.wait_for(
        R._session_backfill_resources_task("chat-9", "u9"), timeout=5,
    ))
    assert calls == [("chat-9", "u9")]


def test_backfill_task_swallows_scan_error(monkeypatch):
    def _boom(chat_id, username):
        raise RuntimeError("scan failed")

    monkeypatch.setattr(R, "_session_backfill_resources", _boom)
    # 扫描失败不得把异常抛回主链（本轮消息照常落库）
    asyncio.run(asyncio.wait_for(
        R._session_backfill_resources_task("chat-9", "u9"), timeout=5,
    ))
