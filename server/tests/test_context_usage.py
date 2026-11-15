"""B4c 上下文消费对账（治理可读层）—— 只读端点与聚合层测试。

覆盖四件事：
  1. ``GET /api/memory/context-usage``：真实台账行 → 利用率数字/会话数正确、无鉴权 401、days 越界 400；
  2. ``POST /api/memory/compress-preview``：计划数字 + dry_run 自证（before==after、writes_performed=0），
     且调用前后盘上文件哈希逐个相等；
  3. ``dry_run=False`` → 400；
  4. 窗口未知时不编数字（``used_pct`` 为 None 且给出原因说明）。

会话目录一律在 ``tmp_path`` 里造，绝不碰真实数据卷。
"""

from __future__ import annotations

import hashlib
import json
import time
from pathlib import Path

import pytest
from coapis.app.auth import get_current_user
from coapis.app.routers import memory as memory_router
from coapis.foundation.db.base import Base
from coapis.foundation.db.engine import get_engine, init_engine, reset_engine
from coapis.foundation.db.models import TokenUsage
from coapis.governance import context_usage
from fastapi import FastAPI
from fastapi.testclient import TestClient

MODEL = "test-window-model"
WINDOW = 12_000  # provider 自报窗口；经 resolve_window 的 0.7 安全系数 → 8400 effective


# ---------------------------------------------------------------------------
# fixtures / helpers
# ---------------------------------------------------------------------------


@pytest.fixture()
def engine(tmp_path):
    """临时库：真实模型建表（列名全来自 TokenUsage，不造幽灵列）。"""
    url = f"sqlite:///{(tmp_path / 'ctx_usage.db').as_posix()}"
    init_engine(url)
    Base.metadata.create_all(get_engine())
    yield get_engine()
    reset_engine()


def _seed(engine, rows: list[dict]) -> None:
    """按真实列写台账行（created_at 是 Float epoch 秒，与生产一致）。"""
    from sqlalchemy.orm import Session

    now = time.time()
    with Session(engine) as session:
        for i, row in enumerate(rows):
            session.add(
                TokenUsage(
                    user_id=row.get("user_id", "admin"),
                    username=row.get("username", "admin"),
                    agent_id=row.get("agent_id", "default"),
                    model=row.get("model", MODEL),
                    provider_id=row.get("provider_id", "test-provider"),
                    input_tokens=int(row.get("input_tokens", 0)),
                    output_tokens=int(row.get("output_tokens", 0)),
                    total_tokens=int(row.get("input_tokens", 0))
                    + int(row.get("output_tokens", 0)),
                    created_at=row["created_at"]
                    if row.get("created_at") is not None
                    else now - i,
                    session_id=row.get("session_id", "sess-a"),
                    chat_id=row.get("chat_id", "chat-a"),
                    turn_index=i,
                ),
            )
        session.commit()


def _fake_window(requests: list[str] | None = None):
    """替掉 provider 注册表取数：给已知模型一个自报窗口，未知模型返回 None。"""

    def _lookup(model_name, base_url=None):
        if requests is not None:
            requests.append(model_name)
        if model_name == MODEL:
            return ("test-provider", WINDOW)
        return (None, None)

    return _lookup


def _client(user: dict | None, monkeypatch, *, window_lookup=True):
    """挂 memory 路由的最小 app；``user=None`` 时不覆盖鉴权 → 无 token 应 401。"""
    if window_lookup:
        monkeypatch.setattr(
            "coapis.agents.context.window_source.reported_window_for_model_name",
            _fake_window(),
        )
    app = FastAPI()
    # memory 路由自带 prefix="/memory"（memory.py:30），这里不再叠前缀
    app.include_router(memory_router.router)
    if user is not None:
        app.dependency_overrides[get_current_user] = lambda: user
    return TestClient(app)


def _write_session(root: Path, username: str, session_id: str, rows: list[dict]) -> Path:
    """在 tmp_path 里造一个会话状态文件（结构与 dev 实测会话文件一致）。"""
    sessions = root / username / "sessions"
    sessions.mkdir(parents=True, exist_ok=True)
    path = sessions / f"{username}_{session_id}.json"
    path.write_text(
        json.dumps(
            {
                "agent": {
                    "memory": {
                        "content": [[msg, []] for msg in rows],
                        "_compressed_summary": "",
                    },
                },
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    return path


def _hash_dir(directory: Path) -> dict[str, str]:
    return {
        str(p.relative_to(directory)): hashlib.sha256(p.read_bytes()).hexdigest()
        for p in sorted(directory.rglob("*"))
        if p.is_file()
    }


# ---------------------------------------------------------------------------
# 1) context-usage
# ---------------------------------------------------------------------------


def test_context_usage_utilization_and_counts(engine, monkeypatch):
    """利用率数字、会话数、可测会话数都要对得上账。"""
    _seed(
        engine,
        [
            # 会话 A：窗口 12000，峰值 6000 → 50%；均值 (6000+3000)/2=4500 → 37.5%
            {"session_id": "sess-a", "chat_id": "chat-a", "input_tokens": 6000},
            {"session_id": "sess-a", "chat_id": "chat-a", "input_tokens": 3000},
            # 会话 B：峰值 1200 → 10%
            {"session_id": "sess-b", "chat_id": "chat-b", "input_tokens": 1200},
        ],
    )
    client = _client({"username": "admin", "role": "admin", "id": "1"}, monkeypatch)

    resp = client.get("/memory/context-usage?days=7&limit=100")
    assert resp.status_code == 200, resp.text
    body = resp.json()
    usage = body["usage"]

    assert usage["session_count"] == 2
    assert usage["measurable_sessions"] == 2
    assert usage["window_tokens"] == WINDOW
    # summarize_usage 的利用率口径是百分数（0~100），这里照它断言，不自己换算
    assert usage["peak_used_pct_max"] == 50.0
    assert usage["peak_used_pct_avg"] == pytest.approx((50.0 + 10.0) / 2)

    by_id = {s["session_id"]: s for s in usage["sessions"]}
    assert sorted(by_id) == ["sess-a", "sess-b"]
    assert by_id["sess-a"]["input_tokens_max"] == 6000
    assert by_id["sess-a"]["input_tokens_avg"] == 4500
    assert by_id["sess-a"]["calls"] == 2
    assert by_id["sess-a"]["peak_used_pct"] == 50.0
    assert by_id["sess-a"]["avg_used_pct"] == 37.5
    assert by_id["sess-a"]["window_source"] == "provider_registry_report"
    # 台账按 created_at 倒序返回，所以逐次明细是「新 → 旧」
    assert by_id["sess-a"]["input_tokens_per_call"] == [6000, 3000]
    assert by_id["sess-b"]["peak_used_pct"] == pytest.approx(10.0)

    # 档位快照与开关状态（尺子来自 context_recon，不另造）
    assert body["tier"]["targets"]
    assert isinstance(body["tier"]["compact_enabled"], bool)
    assert body["rows_scanned"] == 3


def test_context_usage_requires_auth(monkeypatch):
    client = _client(None, monkeypatch)
    assert client.get("/memory/context-usage").status_code == 401


def test_context_usage_days_and_limit_out_of_range_400(monkeypatch):
    client = _client({"username": "admin", "role": "admin", "id": "1"}, monkeypatch)
    assert client.get("/memory/context-usage?days=0").status_code == 400
    assert client.get("/memory/context-usage?days=99999").status_code == 400
    assert client.get("/memory/context-usage?limit=0").status_code == 400
    assert client.get("/memory/context-usage?limit=99999").status_code == 400


def test_context_usage_scopes_non_admin(engine, monkeypatch):
    """非管理员只能看自己的账（按 token_usage.user_id 收窄）。"""
    _seed(
        engine,
        [
            {"user_id": "admin", "session_id": "sess-admin", "input_tokens": 5000},
            {"user_id": "worker", "session_id": "sess-worker", "input_tokens": 1000},
        ],
    )
    client = _client({"username": "worker", "role": "user", "id": "2"}, monkeypatch)
    resp = client.get("/memory/context-usage?days=7&limit=100")
    assert resp.status_code == 200, resp.text
    usage = resp.json()["usage"]
    assert [s["session_id"] for s in usage["sessions"]] == ["sess-worker"]


def test_window_unknown_never_invents_numbers(engine, monkeypatch):
    """窗口取不到 → used_pct 必须是 None 并说明原因，绝不编一个窗口值。"""
    # 只替换取数函数：所有模型都取不到窗口
    monkeypatch.setattr(
        "coapis.agents.context.window_source.reported_window_for_model_name",
        lambda model_name, base_url=None: (None, None),
    )
    rows = [
        {"session_id": "sess-a", "chat_id": "chat-a", "input_tokens": 6000},
        {"session_id": "sess-b", "chat_id": "chat-b", "input_tokens": 100},
    ]
    _seed(engine, rows)
    # 纯函数层（可被直接调用）
    ledger = context_usage.usage_rows(7, 100)
    assert len(ledger) == 2
    summary = context_usage.session_windows(ledger)
    assert summary["session_count"] == 2
    assert summary["measurable_sessions"] == 0
    assert summary["peak_used_pct_max"] is None
    assert summary["peak_used_pct_avg"] is None
    for item in summary["sessions"]:
        assert item["peak_used_pct"] is None
        assert item["mean_used_pct"] is None
        assert item["utilization_note"]
        assert "不猜" in item["utilization_note"]
    assert summary["unknown_window_models"] == [MODEL]
    assert "窗口自报值缺失" in summary["window_note"]

    # 端点层给同样的答案（不是空壳成功）
    client = _client(
        {"username": "admin", "role": "admin", "id": "1"},
        monkeypatch,
        window_lookup=False,
    )
    resp = client.get("/memory/context-usage?days=7&limit=100")
    assert resp.status_code == 200, resp.text
    body = resp.json()["usage"]
    assert body["measurable_sessions"] == 0
    assert body["peak_used_pct_max"] is None
    assert all(s["peak_used_pct"] is None for s in body["sessions"])
    assert all(s["utilization_note"] for s in body["sessions"])


# ---------------------------------------------------------------------------
# 2) compress-preview
# ---------------------------------------------------------------------------


def _preview_rows(count: int = 30, size: int = 4000) -> list[dict]:
    rows = [{"id": "m0", "name": "system", "role": "system", "content": "S" * 300}]
    for i in range(count):
        rows.append(
            {
                "id": f"u{i}",
                "name": "user",
                "role": "user",
                "content": f"u{i} " + ("x" * size),
            },
        )
    return rows


def test_compress_preview_plan_and_self_proof(engine, tmp_path, monkeypatch):
    """计划数字 + 自证字段 before==after + writes_performed=0 + 盘上哈希逐个相等。"""
    _seed(engine, [{"session_id": "sess-p", "chat_id": "chat-p", "input_tokens": 9000}])

    session_id = "sess-p"
    path = _write_session(tmp_path, "admin", session_id, _preview_rows())
    sessions_dir = path.parent
    hashes_before = _hash_dir(sessions_dir)
    ledger_before = context_usage.ledger_counts()

    monkeypatch.setattr("coapis.constant.WORKSPACES_DIR", tmp_path)
    client = _client({"username": "admin", "role": "admin", "id": "1"}, monkeypatch)

    resp = client.post(
        "/memory/compress-preview",
        json={"session_id": session_id, "tier": "full", "dry_run": True},
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()

    # ---- 计划数字（来自现成计量层的纯计算）--------------------------------
    plan, measure = body["plan"], body["measure"]
    assert plan["feasible"] is True
    assert plan["planned_drop_count"] > 0
    assert plan["planned_keep_count"] >= 1
    assert (
        plan["planned_keep_count"] + plan["planned_drop_count"]
        == measure["row_count"]
    )
    assert measure["current_tokens"] > measure["target_budget_tokens"]
    assert 0 < plan["preview_tokens_after"] <= measure["target_budget_tokens"]
    assert plan["fits_budget"] is True
    assert measure["target_budget_tokens"] > 0
    assert body["window"]["reported_tokens"] == WINDOW
    # 窗口对象由现成的 resolve_window 造，source 就是它自己的口径
    assert body["window"]["source"] == "model_self_report"
    assert body["window"]["effective_tokens"] == 8400
    assert body["tier"]["tier"] == "full"
    assert isinstance(body["tier"]["compact_enabled"], bool)

    # ---- 自证字段 ----------------------------------------------------------
    proof = body["self_proof"]
    assert proof["writes_performed"] == 0
    assert proof["ledger_rows"]["before"] == proof["ledger_rows"]["after"]
    assert proof["ledger_rows"]["equal"] is True
    assert proof["session_dir"]["equal"] is True
    assert proof["session_dir"]["files_before"] == proof["session_dir"]["files_after"]
    assert proof["ledger_rows"]["before"]["token_usage"] == ledger_before["token_usage"]

    # ---- 盘上真值：调用前后逐个哈希相等（独立于响应里的自证）--------------
    hashes_after = _hash_dir(sessions_dir)
    assert hashes_after == hashes_before
    assert len(hashes_after) == 1
    assert proof["session_dir"]["file_count"] == len(hashes_after)
    assert {f["path"]: f["sha256"] for f in proof["session_dir"]["files_after"]} == hashes_after

    # ---- 台账没被动过（行数一致）-----------------------------------------
    assert context_usage.ledger_counts()["token_usage"] == ledger_before["token_usage"]


def test_compress_preview_dry_run_false_is_400(engine, tmp_path, monkeypatch):
    """预览端点拒绝写盘：dry_run=False 必须 400 + 中文说明。"""
    _seed(engine, [{"session_id": "sess-p2", "chat_id": "chat-p2", "input_tokens": 100}])
    _write_session(tmp_path, "admin", "sess-p2", _preview_rows(3, 200))
    monkeypatch.setattr("coapis.constant.WORKSPACES_DIR", tmp_path)
    client = _client({"username": "admin", "role": "admin", "id": "1"}, monkeypatch)

    resp = client.post(
        "/memory/compress-preview",
        json={"session_id": "sess-p2", "dry_run": False},
    )
    assert resp.status_code == 400
    assert "不落盘" in resp.json()["detail"]


def test_compress_preview_missing_session_is_404(engine, tmp_path, monkeypatch):
    """会话不存在 → 404 明说，不返回空壳假装成功。"""
    monkeypatch.setattr("coapis.constant.WORKSPACES_DIR", tmp_path)
    client = _client({"username": "admin", "role": "admin", "id": "1"}, monkeypatch)
    resp = client.post(
        "/memory/compress-preview",
        json={"session_id": "no-such-session"},
    )
    assert resp.status_code == 404
    assert "会话不存在" in resp.json()["detail"]


def test_compress_preview_empty_session_is_422(engine, tmp_path, monkeypatch):
    """会话存在但没消息 → 422 明说。"""
    _seed(engine, [{"session_id": "sess-e", "chat_id": "chat-e", "input_tokens": 10}])
    _write_session(tmp_path, "admin", "sess-e", [])
    monkeypatch.setattr("coapis.constant.WORKSPACES_DIR", tmp_path)
    client = _client({"username": "admin", "role": "admin", "id": "1"}, monkeypatch)
    resp = client.post(
        "/memory/compress-preview",
        json={"session_id": "sess-e"},
    )
    assert resp.status_code == 422
    assert "没有可用消息" in resp.json()["detail"]


def test_compress_preview_window_unknown_is_422_not_fake_numbers(
    engine,
    tmp_path,
    monkeypatch,
):
    """窗口自报值取不到 → 422 说明原因；不编窗口、不给假预算。"""
    _seed(engine, [{"session_id": "sess-w", "chat_id": "chat-w", "input_tokens": 10}])
    _write_session(tmp_path, "admin", "sess-w", _preview_rows(3, 200))
    monkeypatch.setattr("coapis.constant.WORKSPACES_DIR", tmp_path)
    client = _client(
        {"username": "admin", "role": "admin", "id": "1"},
        monkeypatch,
        window_lookup=False,  # 真实注册表里没有这个模型 → 窗口未知
    )
    resp = client.post(
        "/memory/compress-preview",
        json={"session_id": "sess-w"},
    )
    assert resp.status_code == 422
    assert "窗口自报值缺失" in resp.json()["detail"]


def test_preview_compaction_is_pure_and_writes_nothing(tmp_path):
    """聚合层直调：纯计算，不改入参、不碰盘。"""
    from coapis.agents.context.window_source import WindowInfo

    rows = _preview_rows()
    snapshot = json.dumps(rows, ensure_ascii=False, sort_keys=True)
    window = WindowInfo(
        reported_tokens=WINDOW,
        effective_tokens=8400,
        source="unit_test",
        chars_per_token=3.0,
    )
    out = context_usage.preview_compaction(rows, window=window, tier="full")
    assert out["writes_performed"] == 0
    assert out["plan"]["planned_drop_count"] > 0
    # 入参没被改（计量层内部 deepcopy，预览层自己也 deepcopy）
    assert json.dumps(rows, ensure_ascii=False, sort_keys=True) == snapshot
    # 盘上没有任何文件被创建
    assert list(tmp_path.iterdir()) == []
