"""Batch-A acceptance tests: triple-execution fix + cross-user isolation.

Covers:
  A1/A2  concurrent workspace start => exactly one start (helper + fast path)
  A3     register_manager retires the superseded manager
  A5     cron_scheduler tool lands jobs in the CALLER's own jobs.json
         and hard-fails without a user context
"""
import asyncio
import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "server"))

from coapis.app.multi_agent_manager import MultiAgentManager  # noqa: E402
from coapis.app.crons.registry import CronManagerRegistry  # noqa: E402
from coapis.app.agent_context import (  # noqa: E402
    set_current_username,
    reset_current_username,
)
from coapis.agents.tools.cron_scheduler import cron_scheduler  # noqa: E402


class FakeWS:
    """Duck-typed Workspace for start-race tests."""

    def __init__(self, delay: float = 0.01):
        self.status = "stopped"
        self.start_count = 0
        self.delay = delay
        self.manager = None

    async def start(self):
        self.start_count += 1
        await asyncio.sleep(self.delay)  # widen the race window
        self.status = "running"

    def set_manager(self, mam):
        self.manager = mam


class FakeMgr:
    def __init__(self):
        self.stop_count = 0

    async def stop(self):
        self.stop_count += 1


@pytest.mark.asyncio
async def test_ensure_workspace_started_exactly_one_start(tmp_path):
    mam = MultiAgentManager(base_dir=tmp_path)
    ws = FakeWS()
    mam._workspaces["user:alice"] = ws
    results = await asyncio.gather(
        *[mam._ensure_workspace_started(ws, "user:alice") for _ in range(5)]
    )
    assert ws.start_count == 1
    assert all(r is ws for r in results)
    assert "user:alice" not in mam._pending_starts  # cleaned up


@pytest.mark.asyncio
async def test_fast_path_cached_unstarted_no_double_start(tmp_path):
    """R2 race simulation: the instance is registered (visible to the fast
    path) BEFORE its start completes; concurrent readers must not start it
    a second time."""
    mam = MultiAgentManager(base_dir=tmp_path)
    ws = FakeWS(delay=0.05)

    async def starter():
        mam._workspaces["user:bob"] = ws
        await mam._ensure_workspace_started(ws, "user:bob")

    async def reader(i: int):
        await asyncio.sleep(0.01 * i)
        w = mam._workspaces.get("user:bob")
        if w is not None and w.status != "running":
            return await mam._ensure_workspace_started(w, "user:bob")
        return w

    await asyncio.gather(starter(), reader(1), reader(2), reader(3))
    assert ws.start_count == 1
    assert ws.status == "running"
    assert ws.manager is mam


@pytest.mark.asyncio
async def test_register_manager_retires_superseded():
    reg = CronManagerRegistry(runner=object(), agent_id="t")
    a, b = FakeMgr(), FakeMgr()
    reg.register_manager("carol", a)
    reg.register_manager("carol", b)
    await asyncio.sleep(0.05)  # let the retire task run
    assert reg.get("carol") is b
    assert a.stop_count == 1
    assert b.stop_count == 0


@pytest.mark.asyncio
async def test_cron_tool_lands_in_caller_own_jobs(tmp_path, monkeypatch):
    import coapis.app.crons.registry as regmod

    monkeypatch.setattr(regmod, "WORKSPACES_DIR", tmp_path)
    monkeypatch.setattr(
        regmod, "_registry_instance",
        CronManagerRegistry(runner=object(), agent_id="t"),
    )

    tok = set_current_username("alice")
    try:
        res = await cron_scheduler(
            action="add",
            name="alice-job",
            schedule="*/5 * * * *",
            prompt="ping",
            task_type="agent",
            channel="console",
        )
    finally:
        reset_current_username(tok)

    assert res.get("success") is True, res
    alice_file = tmp_path / "alice" / "crons" / "jobs.json"
    assert alice_file.exists()
    jobs = json.loads(alice_file.read_text())["jobs"]
    assert [j["name"] for j in jobs] == ["alice-job"]
    # No cross-user leakage
    assert not (tmp_path / "bob" / "crons" / "jobs.json").exists()


@pytest.mark.asyncio
async def test_cron_tool_requires_user_context(tmp_path, monkeypatch):
    import coapis.app.crons.registry as regmod

    monkeypatch.setattr(regmod, "WORKSPACES_DIR", tmp_path)
    monkeypatch.setattr(
        regmod, "_registry_instance",
        CronManagerRegistry(runner=object(), agent_id="t"),
    )
    with pytest.raises(Exception) as ei:
        await cron_scheduler(
            action="add",
            name="ghost-job",
            schedule="*/5 * * * *",
            prompt="ping",
        )
    assert "unknown owner" in str(ei.value)
