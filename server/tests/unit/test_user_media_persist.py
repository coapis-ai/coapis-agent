# -*- coding: utf-8 -*-
"""落库时保住用户媒体块（图片缩略图刷新后不蒸发）。

对应症状：聊天里引用图片发送 → 刷新/重载历史后图片没了。
根因链：_persist_chat_messages 把用户消息 content 压成纯字符串
（``_first_msg.content = user_text``），媒体块随之丢失 → 前端读历史时
拿不到任何 image 块，无从渲染 Images 卡片。

这里锁住 _rebuild_user_content_with_media 的契约：
  1. 无媒体 → 原样返回字符串（绝大多数纯文本轮次零行为变化）
  2. 有媒体 → [text, *媒体块]，媒体块原封不动（source 形态留给
     agentscope_msg_to_message / 前端 resolveContentItemUrl 去解析）
  3. 注入用的「已下载到」文本块不跟着落库（那是给模型的临时提示）
  4. 非 list content / 脏块不得抛异常
"""

from __future__ import annotations

import pytest

from coapis.app.runner.runner import (
    _rebuild_user_content_with_media,
    _USER_MEDIA_BLOCK_TYPES,
)


def _image_block(url: str = "file:///ws/admin/files/media/x.png") -> dict:
    return {"type": "image", "source": {"type": "url", "url": url}}


def test_no_media_returns_plain_string():
    """纯文本轮次必须保持既有行为：返回字符串，不是 list。"""
    content = [{"type": "text", "text": "你好"}]
    out = _rebuild_user_content_with_media("你好", content)
    assert out == "你好"
    assert isinstance(out, str)


def test_empty_string_content_passthrough():
    assert _rebuild_user_content_with_media("hi", "hi") == "hi"
    assert _rebuild_user_content_with_media("hi", None) == "hi"


def test_image_block_is_kept():
    block = _image_block()
    content = [{"type": "text", "text": "这是什么颜色"}, block]
    out = _rebuild_user_content_with_media("这是什么颜色", content)
    assert isinstance(out, list)
    assert out[0] == {"type": "text", "text": "这是什么颜色"}
    assert out[1] is block  # 原封不动，不改 source 形态
    assert len(out) == 2


def test_download_notice_text_block_not_kept():
    """process_file_and_media_blocks_in_message 会插一条「用户上传文件，已经下载到 X」。

    那是给模型的临时提示，不该进历史（前端已有文件 chip 呈现）。
    """
    content = [
        {"type": "text", "text": "看这张图"},
        _image_block(),
        {
            "type": "text",
            "text": "用户上传文件，已经下载到 /ws/admin/files/media/x.png",
        },
    ]
    out = _rebuild_user_content_with_media("看这张图", content)
    texts = [b.get("text") for b in out if b.get("type") == "text"]
    assert texts == ["看这张图"]
    assert len(out) == 2  # text + image


def test_video_and_audio_kept():
    content = [
        {"type": "video", "source": {"type": "url", "url": "file:///a.mp4"}},
        {"type": "audio", "source": {"type": "url", "url": "file:///a.wav"}},
    ]
    out = _rebuild_user_content_with_media("听一下", content)
    assert len(out) == 3
    assert out[0]["type"] == "text"
    assert {b["type"] for b in out[1:]} == {"video", "audio"}


def test_file_block_not_treated_as_media():
    """file 块不在媒体集合里：后端已给它 file_url 供前端下载链接，
    气泡走 Files 卡片，不需要（也不该）当媒体块保住。"""
    content = [{"type": "file", "source": {"type": "url", "url": "file:///a.xlsx"}}]
    out = _rebuild_user_content_with_media("看下表格", content)
    assert out == "看下表格"


def test_media_types_match_agent_side_set():
    """落库侧的媒体集合必须与 react_agent._MEDIA_BLOCK_TYPES 的媒体子集一致，
    否则「送模时被剥、落库时没保住」会出现口径漂移。"""
    from coapis.agents.react_agent import CoApisAgent

    agent_media = set(CoApisAgent._MEDIA_BLOCK_TYPES)
    assert set(_USER_MEDIA_BLOCK_TYPES) <= agent_media
    # file 由 _MEDIA_BLOCK_TYPES 管（送模前剥），落库侧刻意不保（Files 卡片自渲染）
    assert "file" not in _USER_MEDIA_BLOCK_TYPES


def test_non_dict_blocks_tolerated():
    content = ["raw string block", None, 42, _image_block()]
    out = _rebuild_user_content_with_media("x", content)
    assert isinstance(out, list)
    assert len(out) == 2
    assert out[1]["type"] == "image"


def test_text_block_shape_has_type_key():
    """TextBlock() 造的 {'text': ...} 没有 'type'，会打断 get_text_content()。
    落库用的 text 块必须显式带 type。"""
    out = _rebuild_user_content_with_media("甲", [_image_block()])
    assert out[0].get("type") == "text"
    assert out[0].get("text") == "甲"


def test_get_text_content_still_works_on_list_form():
    """_persist_chat_messages 的去重逻辑靠 get_text_content() 比对文本，
    改成 list 形态后必须仍能取到原文。"""
    from agentscope.message import Msg

    msg = Msg(name="user", content=[_image_block()], role="user")
    msg.content = _rebuild_user_content_with_media("原文在此", msg.content)
    assert msg.get_text_content() == "原文在此"


def test_agentscope_msg_to_message_emits_image_url():
    """读历史链路：落库形态必须能被 agentscope_msg_to_message 转成带
    image_url 的 ImageContent，前端才拿得到东西渲染缩略图。"""
    from agentscope.message import Msg

    from coapis.app.runner.utils import agentscope_msg_to_message

    msg = Msg(name="user", content=[_image_block()], role="user")
    msg.content = _rebuild_user_content_with_media("图呢", msg.content)

    messages = agentscope_msg_to_message([msg])
    contents = [c.model_dump() for m in messages for c in m.content]
    images = [c for c in contents if c.get("type") == "image"]
    assert len(images) == 1, f"未转出 image 内容：{contents}"
    assert images[0].get("image_url"), "image_url 为空，前端无从渲染"
    texts = [c.get("text") for c in contents if c.get("type") == "text"]
    assert "图呢" in texts


@pytest.mark.parametrize("ext", ["png", "jpg", "jpeg", "gif", "webp"])
def test_image_extensions_roundtrip(ext):
    block = _image_block(f"file:///ws/admin/files/media/x.{ext}")
    out = _rebuild_user_content_with_media("图", [block])
    assert out[1]["source"]["url"].endswith(f".{ext}")
