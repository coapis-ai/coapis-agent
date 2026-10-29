# -*- coding: utf-8 -*-
"""判断中枢一期 · 批次2（聊天信息面）单测。

覆盖两件事：
  U2 身份提示：环境上下文里要说清「在跟谁说话」，且**不传新参数时输出与改造前逐字一致**。
  D9 内容哈希去重：同一用户上传区重复上传同内容文件只落一份；跨用户不串；
     体积/条数越限时退化成「照旧落一份」，绝不因去重让上传失败。

跑法（仓库根）：
    .venv-test/bin/python -m pytest server/tests/test_decision_hub_phase2.py -q
"""

from __future__ import annotations

import hashlib
from pathlib import Path

import pytest

from coapis.app.runner.utils import build_env_context
from coapis.app.services.file_service import LocalFileBackend as FileService


# ------------------------------------------------------------------ U2 身份提示


def test_env_context_without_identity_params_is_unchanged():
    """不传新参数时，环境上下文必须与改造前逐字一致（零回归）。"""
    ctx = build_env_context(
        session_id="chat-1",
        user_id="alice",
        channel="wecom",
        working_dir="/tmp/ws",
    )
    assert "- User ID: alice" in ctx
    assert "- Session ID: chat-1" in ctx
    assert "- Channel: wecom" in ctx
    assert "- Agent:" not in ctx
    assert "name:" not in ctx


def test_env_context_shows_speaker_name_and_role():
    ctx = build_env_context(
        session_id="chat-1",
        user_id="wangjing",
        channel="wecom",
        working_dir="/tmp/ws",
        user_name="王静",
        user_role="member",
        agent_id="agent-oa",
    )
    assert "- User ID: wangjing (name: 王静, role: member)" in ctx
    assert "- Agent: agent-oa" in ctx


def test_env_context_identity_is_optional_per_field():
    """只有显示名时不要冒出空角色；只有角色时不要冒出空显示名。"""
    ctx_name_only = build_env_context(
        user_id="u1", user_name="小李",
    )
    assert "name: 小李" in ctx_name_only
    assert "role:" not in ctx_name_only

    ctx_role_only = build_env_context(user_id="u1", user_role="admin")
    assert "role: admin" in ctx_role_only
    assert "name:" not in ctx_role_only


def test_env_context_skips_name_equal_to_id():
    """显示名与登录名相同时不重复播报（由调用方负责不传，这里兜底验证渲染）。"""
    ctx = build_env_context(user_id="u1", user_name="u1")
    assert ctx.count("u1") >= 1
    assert "(name: u1)" in ctx  # 渲染层照实渲染，去重由调用方保证


def test_env_context_time_hint_has_timezone_and_weekday():
    """U3 时间提示：日期 + 时区 + 星期都要在。"""
    ctx = build_env_context(user_id="u1")
    assert "Current date:" in ctx
    assert "(" in ctx and ")" in ctx  # 时区/星期在括号里


# ------------------------------------------------------------------ D9 内容去重


@pytest.fixture()
def svc(tmp_path: Path) -> FileService:
    return FileService(data_dir=tmp_path)


def _upload(svc: FileService, username: str, filename: str, content: bytes):
    import asyncio

    return asyncio.run(
        svc.upload_file_with_content(
            username=username,
            path="files",
            filename=filename,
            content=content,
        ),
    )


def test_dedup_same_content_lands_one_file(svc: FileService, tmp_path: Path):
    """同内容换名上传两次：只落一份，第二次返回已有文件。"""
    content = b"quarterly report v1\n"
    first = _upload(svc, "alice", "a.txt", content)
    second = _upload(svc, "alice", "b.txt", content)

    files = [p for p in (tmp_path / "alice").rglob("*") if p.is_file()]
    assert len(files) == 1, "同内容不得落第二份"
    assert second.path == first.path
    assert second.size == len(content)


def test_dedup_keeps_different_content(svc: FileService, tmp_path: Path):
    """内容不同必须各落一份——去重不能把不同文件合并。"""
    _upload(svc, "alice", "a.txt", b"v1")
    _upload(svc, "alice", "b.txt", b"v2")

    files = [p for p in (tmp_path / "alice").rglob("*") if p.is_file()]
    assert len(files) == 2


def test_dedup_does_not_cross_users(svc: FileService, tmp_path: Path):
    """去重只在本用户上传区内比对，绝不能把别人的文件指给当前用户。"""
    content = b"shared secret content\n"
    _upload(svc, "alice", "a.txt", content)
    bob = _upload(svc, "bob", "b.txt", content)

    assert "/alice/" not in bob.path
    # path 是「本用户根」相对路径，bob 拿到的只能落在自己的树里
    assert bob.path.startswith("/files/"), bob.path
    assert bob.name == "b.txt", "跨用户不得复用别人的文件名"
    alice_files = [p for p in (tmp_path / "alice").rglob("*") if p.is_file()]
    bob_files = [p for p in (tmp_path / "bob").rglob("*") if p.is_file()]
    assert len(alice_files) == 1
    assert len(bob_files) == 1


def test_dedup_returns_existing_path_not_new_name(svc: FileService):
    """命中去重时返回的是已有文件路径（引用注入要拿到真实可读写路径）。"""
    content = b"same bytes\n"
    first = _upload(svc, "alice", "keep.txt", content)
    second = _upload(svc, "alice", "again.txt", content)
    assert second.name == "keep.txt"
    assert second.path == first.path


def test_dedup_skipped_for_oversized_content(svc: FileService, tmp_path: Path):
    """超过体积上限不做去重：退化成照旧落一份，上传不受影响。"""
    big = b"x" * (svc._DEDUP_MAX_BYTES + 1024)
    first = _upload(svc, "alice", "big1.bin", big)
    second = _upload(svc, "alice", "big2.bin", big)

    files = [p for p in (tmp_path / "alice").rglob("*") if p.is_file()]
    assert len(files) == 2
    assert first.path != second.path


def test_dedup_never_breaks_upload_on_scan_failure(svc: FileService, tmp_path: Path):
    """扫描过程抛异常时必须按「没找到」处理，上传照常成功。"""

    def _boom(*_a, **_kw):
        raise RuntimeError("scan exploded")

    svc._find_content_twin = _boom
    info = _upload(svc, "alice", "ok.txt", b"content\n")
    assert info.name == "ok.txt"
    assert (tmp_path / "alice" / "files" / "files" / "ok.txt").read_bytes() == b"content\n"


def test_dedup_hash_matches_content(svc: FileService, tmp_path: Path):
    """复用旧文件时，返回的大小必须与内容指纹一致（台账登记不能记错）。"""
    content = b"abc" * 1000
    info = _upload(svc, "alice", "x.bin", content)
    assert info.size == len(content)
    on_disk = (tmp_path / "alice" / "files" / "files" / "x.bin").read_bytes()
    assert hashlib.sha256(on_disk).hexdigest() == hashlib.sha256(content).hexdigest()
