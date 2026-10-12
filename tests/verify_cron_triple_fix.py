"""Standalone Batch-A verification (runs inside the dev container, no pytest).

Usage:  docker exec -i coapis-server-dev python3 - < verify_cron_triple_fix.py
Exit code 0 = all green.
"""
import asyncio
import json
import os
import sys
import tempfile

PASS = []
FAIL = []


def check(name, cond, detail=""):
    if cond:
        PASS.append(name)
        print(f"  PASS  {name}")
    else:
        FAIL.append(name)
        print(f"  FAIL  {name}  {detail}")


class FakeWS:
    def __init__(self, delay=0.01):
        self.status = "stopped"
        self.start_count = 0
        self.delay = delay
        self.manager = None

    async def start(self):
        self.start_count += 1
        await asyncio.sleep(self.delay)
        self.status = "running"

    def set_manager(self, mam):
        self.manager = mam


class FakeMgr:
    def __init__(self):
        self.stop_count = 0

    async def stop(self):
        self.stop_count += 1


async def main():
    from coapis.app.multi_agent_manager import MultiAgentManager
    from coapis.app.crons.registry import CronManagerRegistry, get_registry
    from coapis.app.agent_context import (
        set_current_username, reset_current_username,
    )
    from coapis.agents.tools.cron_scheduler import cron_scheduler

    # ---- T1: concurrent _ensure_workspace_started => exactly one start ----
    print("[T1] concurrent start coordination (5 callers)")
    with tempfile.TemporaryDirectory() as td:
        mam = MultiAgentManager(base_dir=__import__("pathlib").Path(td))
        ws = FakeWS()
        mam._workspaces["user:alice"] = ws
        results = await asyncio.gather(
            *[mam._ensure_workspace_started(ws, "user:alice") for _ in range(5)]
        )
        check("T1.single_start", ws.start_count == 1, f"count={ws.start_count}")
        check("T1.same_instance", all(r is ws for r in results))
        check("T1.pending_cleaned", "user:alice" not in mam._pending_starts)

    # ---- T2: R2 race — cached unstarted instance + concurrent readers ----
    print("[T2] fast-path race (registered before start completes)")
    with tempfile.TemporaryDirectory() as td:
        mam = MultiAgentManager(base_dir=__import__("pathlib").Path(td))
        ws = FakeWS(delay=0.05)

        async def starter():
            mam._workspaces["user:bob"] = ws
            await mam._ensure_workspace_started(ws, "user:bob")

        async def reader(i):
            await asyncio.sleep(0.01 * i)
            w = mam._workspaces.get("user:bob")
            if w is not None and w.status != "running":
                return await mam._ensure_workspace_started(w, "user:bob")
            return w

        await asyncio.gather(starter(), reader(1), reader(2), reader(3))
        check("T2.single_start", ws.start_count == 1, f"count={ws.start_count}")
        check("T2.running", ws.status == "running")
        check("T2.bound_manager", ws.manager is mam)

    # ---- T3: register_manager retires the superseded manager ----
    print("[T3] registry retires superseded manager")
    reg = CronManagerRegistry(runner=object(), agent_id="t")
    a, b = FakeMgr(), FakeMgr()
    reg.register_manager("carol", a)
    reg.register_manager("carol", b)
    await asyncio.sleep(0.05)
    check("T3.current_is_b", reg.get("carol") is b)
    check("T3.old_stopped", a.stop_count == 1, f"a={a.stop_count}")
    check("T3.new_alive", b.stop_count == 0)

    # ---- T4/T5: cron tool lands in caller's own jobs.json; hard-fail w/o ctx ----
    print("[T4] cron tool -> caller's own jobs.json")
    import coapis.app.crons.registry as regmod

    with tempfile.TemporaryDirectory() as td:
        regmod.WORKSPACES_DIR = __import__("pathlib").Path(td)
        regmod._registry_instance = None
        regmod.set_registry(CronManagerRegistry(runner=object(), agent_id="t"))
        try:
            tok = set_current_username("alice")
            try:
                res = await cron_scheduler(
                    action="add", name="alice-job", schedule="*/5 * * * *",
                    prompt="ping", task_type="agent", channel="console",
                )
            finally:
                reset_current_username(tok)
            check("T4.success", bool(res.get("success")), str(res)[:200])
            af = __import__("pathlib").Path(td) / "alice" / "crons" / "jobs.json"
            check("T4.alice_file_exists", af.exists())
            if af.exists():
                jobs = json.loads(af.read_text())["jobs"]
                check("T4.job_present", [j["name"] for j in jobs] == ["alice-job"])
            bf = __import__("pathlib").Path(td) / "bob" / "crons" / "jobs.json"
            check("T4.no_leakage", not bf.exists())

            print("[T5] cron tool hard-fails without user context")
            regmod._registry_instance = None
            regmod.set_registry(CronManagerRegistry(runner=object(), agent_id="t"))
            try:
                await cron_scheduler(
                    action="add", name="ghost-job",
                    schedule="*/5 * * * *", prompt="ping",
                )
                check("T5.raises", False, "no exception raised")
            except Exception as e:
                check("T5.raises", "unknown owner" in str(e), str(e)[:200])
        finally:
            regmod._registry_instance = None

    print()
    print(f"RESULT: {len(PASS)} passed, {len(FAIL)} failed")
    if FAIL:
        print("FAILED:", ", ".join(FAIL))
        sys.exit(1)
    print("ALL_GREEN")
    sys.exit(0)


asyncio.run(main())
