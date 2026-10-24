# -*- coding: utf-8 -*-
"""C1 回归：本轮产出/引用资源必须写进 assistant 消息 metadata（刷新回放）。

背景（方案 §12.2/§12.3，验收项 5「刷新后还在」）：产出卡、引用资源、知识库
来源此前只挂在 SSE ``completed`` 事件上，assistant 消息里没有 ``resources``
字段 → 刷新页面后整块消失。落库时写进最后一条 assistant 消息的 metadata，
``get_chat`` 回放经 ``agentscope_msg_to_message`` 透传给前端
（前端读 ``metadata.metadata.resources``）。

锁死五件事：
 1. 有资源 → 写进**最后一条** assistant 消息（多条 assistant 取最后一条）
 2. 只有引用没有产出 → 也要写（引用是独立信息，不能因为没产出就整块丢）
 3. 既有产出又有引用 → 两个键都在同一条消息上
 4. 无产出无引用 → 不写任何键（不制造空壳字段）
 5. 已有 metadata 必须保留（不能整块覆盖掉 original 等既有字段）
 6. 没有 assistant 消息 → 不炸、不写
"""

from __future__ import annotations

from coapis.app.runner.runner import _annotate_turn_resources


class _Msg:
    def __init__(self, role, metadata=None):
        self.role = role
        self.metadata = metadata


def test_writes_resources_to_last_assistant():
    msgs = [
        _Msg("user"),
        _Msg("assistant", {"original_id": "a1"}),
        _Msg("assistant", {"original_id": "a2"}),
    ]
    res = [{"name": "报告.docx", "path": "files/2026-10/报告.docx"}]
    n = _annotate_turn_resources(msgs, res, [])
    assert n == 1
    # 最后一条 assistant 拿到 resources，且保留原有 metadata
    assert msgs[2].metadata["resources"] == res
    assert msgs[2].metadata["original_id"] == "a2"
    # 前一条 assistant 不受影响
    assert "resources" not in msgs[1].metadata


def test_citations_only_still_written():
    """只有知识库引用、本轮没产出文件 → 引用必须落库，不能整块丢。"""
    msgs = [_Msg("user"), _Msg("assistant")]
    cites = [{"doc_name": "员工手册.pdf", "page": 3}]
    n = _annotate_turn_resources(msgs, [], cites)
    assert n == 1
    assert msgs[1].metadata["kb_citations"] == cites
    assert "resources" not in msgs[1].metadata


def test_both_keys_on_same_message():
    msgs = [_Msg("assistant", {})]
    res = [{"name": "a.md"}]
    cites = [{"doc_name": "x.pdf"}]
    n = _annotate_turn_resources(msgs, res, cites)
    assert n == 2
    assert msgs[0].metadata["resources"] == res
    assert msgs[0].metadata["kb_citations"] == cites


def test_nothing_to_write_leaves_metadata_untouched():
    msgs = [_Msg("assistant", {"original_id": "a1"})]
    n = _annotate_turn_resources(msgs, [], [])
    assert n == 0
    assert msgs[0].metadata == {"original_id": "a1"}


def test_existing_metadata_preserved():
    """写入不得覆盖既有 metadata（整块赋值会丢掉回放所需的 original_id）。"""
    msgs = [_Msg("assistant", {"original_id": "a1", "original_name": "agent"})]
    _annotate_turn_resources(msgs, [{"name": "a.md"}], [{"doc_name": "x.pdf"}])
    assert msgs[0].metadata["original_id"] == "a1"
    assert msgs[0].metadata["original_name"] == "agent"
    assert msgs[0].metadata["resources"] == [{"name": "a.md"}]


def test_no_assistant_message_is_safe():
    msgs = [_Msg("user"), _Msg("system")]
    n = _annotate_turn_resources(msgs, [{"name": "a.md"}], [{"doc_name": "x.pdf"}])
    assert n == 0
    for m in msgs:
        assert m.metadata is None


def test_none_metadata_message_gets_dict():
    """metadata 为 None 的消息也要能写入（不能 AttributeError）。"""
    msgs = [_Msg("assistant", None)]
    n = _annotate_turn_resources(msgs, [{"name": "a.md"}], [])
    assert n == 1
    assert msgs[0].metadata == {"resources": [{"name": "a.md"}]}
