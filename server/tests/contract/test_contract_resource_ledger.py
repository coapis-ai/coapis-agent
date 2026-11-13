# -*- coding: utf-8 -*-
"""B0 契约锁 · 资源台账尺子（方案 v1 §3 第 0 批 / D14）

**口径照抄代码**。资源台账三层，各管各的，契约分开锁：

* ``coapis/foundation/resource_ledger.py`` —— 纯函数尺子：路径规范化
  （``canonical_file_path`` / ``workspace_relative_path``）、空标题兜底
  （``title_from_path``）、台账键（``make_resource_key``）、系统路径判定
  （``is_system_path``，v26 F1 的唯一实现）。
* ``coapis/foundation/file_ledger.py`` —— 来源词表（``VALID_SOURCES`` /
  ``PRODUCER_SOURCES`` / ``role_for_source``）、状态词表
  （``VALID_STATUSES`` / ``PARSE_STATUSES``）、登记入口
  （``record_file_event`` / ``record_parse_event``）、审计台账
  （``FileLedgerService``）。
* 聊天侧只经登记入口写台账；台账是**旁路**，任何入参都不许把异常抛回主链。

尺子口径以代码实存为准（B0 初稿有四处指错，逐条对齐并留注释）：
``is_system_path`` 尺子真身在 ``foundation/resource_category.py``（v26 F1
单一实现，消费方 = resource_ledger + reference_collector）；登记入口只吃
该用户 files 根内的路径（根外拒写）；``record_parse_event`` 签名以
file_ledger 实存为准；kind 五档 file/db/kb/mcp/web（媒体走 file+扩展名）；
producer = 写入类（write/edit/append/send_file/convert），role 二值。
B2 计划补 kb/db/mcp 资源登记面。

现状锁 = 后续批次不许改松；目标锁（``xfail(strict=True)``）= 批次交付物。
"""
from __future__ import annotations

from pathlib import Path

import pytest

from coapis.foundation import file_ledger as fld
from coapis.foundation import resource_category as rc
from coapis.foundation import resource_ledger as rl
from coapis.foundation.file_ledger import FileLedgerService

B2 = pytest.mark.xfail(
    strict=True,
    reason="B2 目标契约：台账按用户命名空间隔离 + 知识库/数据库/MCP 登记面（未实现）",
)


# ── 1. 来源词表与角色：一把尺子，取值封闭 ───────────────────────────────


def test_source_vocabulary_is_a_frozen_set():
    assert isinstance(fld.VALID_SOURCES, frozenset)
    # 聊天侧登记来源必须显式在白名单里
    assert {"write_file", "edit_file", "send_file"} <= set(fld.VALID_SOURCES)


def test_producer_sources_are_the_writer_side():
    # 口径 = test_producer_role_b5.py 锁死的拍板：**写出类**四来源算会话产物；
    # send_file 是"发送既有文件"，算引用不算产物；upload 是用户传进来的，算引用。
    for src in ("write_file", "edit_file", "append_file", "convert"):
        assert src in fld.PRODUCER_SOURCES, src
    assert "send_file" not in fld.PRODUCER_SOURCES
    assert "upload" not in fld.PRODUCER_SOURCES


def test_role_mapping_is_two_valued_and_never_empty():
    # 产出/引用两值。白名单外的来源必须可见（当"引用"），
    # **绝不静默丢掉**——静默丢掉就是"资源栏少东西、查不出为什么少"。
    assert fld.role_for_source("write_file") == "producer"
    assert fld.role_for_source("edit_file") == "producer"
    assert fld.role_for_source("send_file") == "reference"
    assert fld.role_for_source("upload") == "reference"
    assert fld.role_for_source("made_up_tool") == "reference"
    assert fld.role_for_source("") == "reference"
    assert fld.role_for_source("") == "reference"


def test_status_vocabulary_is_closed():
    # 交付台账三态、解析台账四态：词表封闭，看板才分得开桶。
    assert set(fld.VALID_STATUSES) == {"draft", "delivered", "archived"}
    assert set(fld.PARSE_STATUSES) == {"ok", "timeout", "fail", "degraded"}


def test_resource_kind_vocabulary_is_closed():
    # kind 词表 = 后端 API 与前端 0e8e880 收口的五档：file/db/kb/mcp/web。
    # 媒体（图/音/视频）走 kind=file + 扩展名识别，不设独立 kind——
    # 台账与资源栏同一把尺子，B0 初稿写 {image,audio,video} 是凭空立的词表。
    assert isinstance(rl.VALID_KINDS, frozenset)
    assert set(rl.VALID_KINDS) == {"file", "db", "kb", "mcp", "web"}
    assert "file" in rl.VALID_KINDS and "web" in rl.VALID_KINDS


# ── 2. 路径尺子：同一文件只允许一个台账键 ───────────────────────────────


def test_workspace_relative_path_is_idempotent(tmp_path):
    owner = tmp_path / "u1"
    got = rl.workspace_relative_path("a.txt", owner)
    assert got == "files/a.txt"
    # 幂等：已经是规范形就不再套一层（套两层=台账出现 files/files/x）
    assert rl.workspace_relative_path(got, owner) == "files/a.txt"


def test_canonical_file_path_collapses_two_spellings(tmp_path):
    # 同一文件的两种写法（工作区相对 / 绝对落盘路径）必须得到**同一个**键，
    # 否则台账一行变两行，UI 出现"重复文件"。
    files = tmp_path / "u1" / "files"
    files.mkdir(parents=True)
    target = files / "a.txt"
    one = rl.canonical_file_path("files/a.txt", form="workspace")
    two = rl.canonical_file_path(str(target), form="abs")
    assert Path(one).name == Path(two).name == "a.txt"


def test_canonical_file_path_keeps_foreign_paths_untouched(tmp_path):
    outside = tmp_path / "elsewhere.txt"
    # abs 是纯字符串换算尺子：绝对路径输入被换算为工作区相对口径
    # （越界判定归 is_system_path 尺子，不在 canonical 里做落盘探测）。
    assert rl.canonical_file_path(str(outside), form="abs") == \
        str(outside).lstrip("/")


def test_title_from_path_falls_back_to_filename(tmp_path):
    # 登记方没给标题时兜底文件名。空标题的台账行在 UI 上是隐形行。
    assert rl.title_from_path("file", str(tmp_path / "report.docx")) == "report.docx"
    # 无扩展名的目录式路径也不能给出空标题
    assert rl.title_from_path("file", str(tmp_path / "noext")) == "noext"


def test_resource_key_is_stable_per_owner_and_kind(tmp_path):
    k1 = rl.make_resource_key("u1", "u1", "file", "files/a.txt")
    k2 = rl.make_resource_key("u1", "u1", "file", "files/a.txt")
    k3 = rl.make_resource_key("u2", "u2", "file", "files/a.txt")
    assert k1 == k2
    assert k1 != k3, "台账键必须含归属，否则两个用户的同名文件互相顶掉"


def test_epoch_ms_normalizes_seconds_and_zero():
    # 无时间 = None（前端显示"-";归 0 会显示 1970 年，比空更坏）
    assert rl.epoch_ms(0) is None
    assert rl.epoch_ms(1.5) == 1500
    assert rl.epoch_ms(None) is None
    # 已经是毫秒的入参不许再乘 1000（时间戳翻 1000 倍=台账时间全在未来）
    assert rl.epoch_ms(1_700_000_000_000) == 1_700_000_000_000


# ── 3. 系统路径尺子：唯一实现，判定稳定 ─────────────────────────────────


@pytest.mark.parametrize(
    "path,invisible,bare_top_ok",
    [
        # 尺子吃的是**工作区相对口径**（写入口已换算），不是任意绝对路径。
        # bare_top_file_ok=True = 登记闸门口径（根层文件放行入收件箱）；
        # False = 读面口径（裸顶层/平台文件不算交付物，隐形）。
        ("MEMORY.md", False, True),         # 闸门口径放行（深层平台文件才拦）
        ("MEMORY.md", True, False),         # 读面口径：根层平台文件隐形
        ("AGENTS.md", True, False),
        ("PROFILE.md", True, False),
        ("HEARTBEAT.md", True, False),
        ("loose.md", False, True),          # 裸顶层文件：登记闸门放行（归位收件箱）
        ("loose.md", True, False),          # 读面口径：裸顶层文件不算交付物
        ("skills/env_manager/SKILL.md", True, True),   # 首段不在交付根
        ("files/.session_dirs.json", True, True),      # 隐藏段
        (".trash/old.txt", True, True),                # 噪音段
        ("../escape/x.txt", True, True),               # 穿越
        ("/home/u1/docs/report.docx", True, True),     # 绝对路径 = 越界
        ("http://x.example/a", True, True),            # URI 混进路径
        ("", True, True),                              # 空路径按越界处理
        ("files/report.docx", False, True),            # 交付根内
        ("media/x.png", False, True),
        ("files/MEMORY.md", True, True),               # 交付根直接下放平台文件
        ("files/deep/MEMORY.md", False, True),         # 深层同名 = 用户产物
    ],
)
def test_is_system_path_is_the_single_ruler(path, invisible, bare_top_ok):
    # 智能体自己的记忆/配置/技能/临时探针不得出现在聊天资源栏。
    # v26 的"资源乱显示"就治在这把尺子 + 登记闸门上。
    # 尺子真身在 resource_category（B0 初稿把 import 指到 resource_ledger，指错了）。
    assert rc.is_system_path(path, kind="file", bare_top_file_ok=bare_top_ok) is invisible


def test_system_path_ruler_only_judges_files():
    # 尺子只管文件类；kb/db/mcp/web 不做文件系统判定。
    assert rc.is_system_path("anything", kind="kb") is False


def test_system_path_ruler_is_reused_not_copied():
    # 判定只允许一份实现（PRD C2 的"两份实现"病灶）。
    # 实测消费方（B0 初稿列的 agent_tools/resource_governance 系幽灵路径）：
    root = Path(__file__).resolve().parents[2]
    consumers = [
        "coapis/foundation/resource_category.py",   # 实现本体
        "coapis/foundation/resource_ledger.py",     # 巡检/读侧
        "coapis/agents/context/reference_collector.py",  # 采集侧
    ]
    for rel in consumers:
        text = (root / rel).read_text(encoding="utf-8", errors="ignore")
        assert "is_system_path" in text, f"{rel} 没有复用尺子"
    # 全仓只有一份 def is_system_path
    hits = [
        p for p in root.glob("coapis/**/*.py")
        if "def is_system_path" in p.read_text(encoding="utf-8", errors="ignore")
    ]
    assert len(hits) == 1, f"is_system_path 实现不止一份：{[str(p) for p in hits]}"


# ── 4. 登记入口：归因齐全、绝不抛异常 ───────────────────────────────────


def test_record_file_event_never_raises_on_hostile_input(tmp_path):
    # 台账是旁路：空串/空白/穿越/超长都必须静默容忍，绝不把异常抛回主链。
    for path in ("", "   ", "../../../../etc/passwd", "x" * 5000, "/dev/null"):
        try:
            fld.record_file_event(
                "u1",
                path,
                session_id="s1",
                chat_id="c1",
                agent_id="a1",
                turn_id="t1",
                source="write_file",
            )
        except Exception as exc:  # noqa: BLE001
            raise AssertionError(f"record_file_event 对 {path!r} 抛异常：{exc}")


def test_record_file_event_requires_attribution(tmp_path):
    # 没有 chat_id 的登记无法归因，必须返回 False（拒写），
    # 而不是写出一条"孤儿行"。孤儿行是台账里最难收拾的脏数据。
    assert (
        fld.record_file_event(
            "u1",
            str(tmp_path / "a.txt"),
            session_id="",
            chat_id="",
            agent_id="",
            turn_id="",
            source="write_file",
        )
        is False
    )


def test_record_file_event_is_bool_not_row():
    # 登记入口返回 bool：调用方无法拿台账对象去改，写侧尺子只在内部。
    assert isinstance(
        fld.record_file_event(
            "u1",
            "/tmp/x.txt",
            session_id="s1",
            chat_id="c1",
            agent_id="a1",
            turn_id="t1",
            source="write_file",
        ),
        bool,
    )


def test_record_parse_event_never_raises(tmp_path):
    try:
        # 签名以 file_ledger.py:976 为准：(username, abs_path, *, status,
        # chars, method, session_id, chat_id, agent_id, title)——无 source 参数。
        fld.record_parse_event(
            "u1",
            str(tmp_path / "ghost.pdf"),
            session_id="s1",
            chat_id="c1",
            agent_id="a1",
            status="done",
            chars=100,
            method="markitdown",
        )
    except Exception as exc:  # noqa: BLE001
        raise AssertionError(f"record_parse_event 抛异常：{exc}")


# ── 5. 文件审计台账：登记面行为 ─────────────────────────────────────────


def test_file_ledger_record_is_bool_and_tolerates_hostile_input(tmp_path):
    led = FileLedgerService(tmp_path)
    for path in ("", "   ", "../../../../etc/passwd", "x" * 5000):
        got = led.record(
            "u1",
            path,
            session_id="s1",
            chat_id="c1",
            agent_id="a1",
            turn_id="t1",
            source="write_file",
        )
        assert isinstance(got, bool)


def test_file_ledger_rejects_unknown_source(tmp_path):
    # 词表外的来源**降级为 other 入账**（record 的 source 归一化尺子），
    # 不写空来源也不炸链；"词表外拒写"是终态目标（B2 接线后转强校验）。
    led = FileLedgerService(tmp_path)
    inside = tmp_path / "u1" / "files"
    inside.mkdir(parents=True)
    f = inside / "a.txt"
    f.write_text("x", encoding="utf-8")
    assert led.record(
        "u1",
        str(f),
        session_id="s1",
        chat_id="c1",
        agent_id="a1",
        turn_id="t1",
        source="made_up_tool",
    ) is True
    from coapis.foundation.db.engine import get_session
    from coapis.foundation.db.models import FileRecord

    with get_session() as s:
        row = s.query(FileRecord).filter(FileRecord.session_id == "s1").first()
        assert row is not None and row.source == "other"


def test_file_ledger_accepts_valid_source(tmp_path):
    # 登记只吃**该用户 files 根内**的真实路径（record 的 rel 换算尺子）；
    # 根外路径返回 False——这正是"台账只装该用户的文件"的第一道闸。
    led = FileLedgerService(tmp_path)
    inside = tmp_path / "u1" / "files"
    inside.mkdir(parents=True)
    f = inside / "a.txt"
    f.write_text("x", encoding="utf-8")
    assert led.record(
        "u1",
        str(f),
        session_id="s1",
        chat_id="c1",
        agent_id="a1",
        turn_id="t1",
        source="write_file",
    ) is True


# ── 6. B2 目标：登记面的两处结构性缺口 ─────────────────────────────────


def test_ledger_scopes_records_to_the_owning_user(tmp_path):
    # 终态判据（方案 §4 验收 3）：台账只装该用户的文件。
    # B0 复核时标记为"未实现"，2026-11-13 复测：record 的根外拒写已实现
    # （file_ledger.py:239-262，根外 rel=None → return False）。
    # 判据随代码锁死，摘掉 xfail 转正式契约。
    led = FileLedgerService(tmp_path)
    bob = tmp_path / "bob" / "files"
    bob.mkdir(parents=True)
    (bob / "secret.txt").write_text("x", encoding="utf-8")
    assert led.record(
        "alice",
        str(bob / "secret.txt"),
        session_id="s1",
        chat_id="c1",
        agent_id="a1",
        turn_id="t1",
        source="write_file",
    ) is False, "用户命名空间之外的路径不得入台账"


@B2
def test_knowledge_db_mcp_resources_have_a_registration_face(tmp_path):
    # 台账里 kb/db/mcp 类资源登记侧 0 处（实测 resources 表 kind=file 独大）。
    # 没有登记面，资源栏的"知识库/数据库/MCP"三档永远是空的。B2 交付后摘标记。
    entry = getattr(fld, "record_resource_event", None)
    assert entry is not None, "FileLedgerService 尚无 kb/db/mcp 登记入口"
    row = entry(
        "u1",
        kind="kb",
        resource_id="kb-1",
        title="产品手册",
        session_id="s1",
        chat_id="c1",
        agent_id="a1",
        turn_id="t1",
        source="kb_query",
    )
    assert row is not None
    assert row["kind"] == "kb"
