# -*- coding: utf-8 -*-
"""EvalRunner: drive real agent instances through benchmark tasks.

Architecture (decided in design review):
* Standalone process inside the dev container (shares server env vars).
* Isolated workspace: the source user's workspace dir is cloned to
  ``workspaces/eval_<ts>`` so model/provider config works out of the box
  while chats/memory start clean.
* In-process driving: ``workspace.core.stream_chat`` — the exact entry
  point the websocket handler uses, so fidelity is maximal.
* Mock tools are injected straight into the eval agent's toolkit (no MCP
  plumbing needed).
* Runs + trajectories are persisted to the shared dev DB.

Usage (inside container, package mode from /app)::

    python -m coapis.agent_eval.runner --category tool_collab --source-user admin
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import shutil
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

from .checker import CheckerSuite
from .dataset.loader import load_tasks
from .judge import LLMJudge
from .mocks import MOCK_TOOLS, arm_flaky_once, reset_flaky
from .telemetry import TelemetryInstaller


class EvalRunner:
    def __init__(
        self,
        workspaces_root: Path,
        source_user: str = "admin",
        agent_id: str = "eval_bot",
        use_judge: bool = True,
    ) -> None:
        self.workspaces_root = Path(workspaces_root)
        self.source_user = source_user
        self.agent_id = agent_id
        self.use_judge = use_judge
        self.turn_timeout = int(os.environ.get("COAPIS_EVAL_TURN_TIMEOUT", "120"))
        self.eval_ws_dir: Optional[Path] = None
        self.manager = None
        self.workspace = None
        self.agent = None
        self.installer = None
        self.chat_counter = 0

    # ------------------------------------------------------------------ #
    # provisioning
    # ------------------------------------------------------------------ #
    async def prepare(self) -> None:
        from ..app.multi_agent_manager import MultiAgentManager

        # 固定命名，必须与 derive_workspace_dir(agent_id, username=agent_id)
        # 推导路径一致：workspaces/<agent_id>/agents/<agent_id>
        self.eval_ws_dir = (
            self.workspaces_root / self.agent_id / "agents" / self.agent_id
        )
        if self.eval_ws_dir.exists():
            shutil.rmtree(self.eval_ws_dir)
        src = self.workspaces_root / self.source_user
        if not src.exists():
            raise FileNotFoundError(f"source workspace not found: {src}")
        # skip Chromium user-data dirs (sockets/dangling symlinks, huge,
        # irrelevant to eval) and tolerate vanished entries during copy
        shutil.copytree(
            src, self.eval_ws_dir,
            ignore=shutil.ignore_patterns("user_data_*"),
            ignore_dangling_symlinks=True,
        )
        # wipe chat history so runs start clean (keep config/memory dirs)
        for name in ("chats", "sessions"):
            d = self.eval_ws_dir / name
            if d.exists():
                shutil.rmtree(d)
        # Controlled environment: strip the source agent's persona files so
        # the benchmark measures model + tools, not persona habits (shell
        # exploration, roleplay, ...). Memory artifacts stay intact because
        # the memory_* category tests cross-session recall.
        for persona_file in ("AGENTS.md", "SOUL.md", "PROFILE.md"):
            pf = self.eval_ws_dir / persona_file
            if pf.is_file():
                pf.unlink()
        # rewrite identity fields in agent.json
        cfg_path = self.eval_ws_dir / "agent.json"
        cfg = json.loads(cfg_path.read_text(encoding="utf-8"))
        cfg["id"] = f"user:{self.agent_id}"
        cfg["name"] = self.agent_id
        cfg["owner"] = self.agent_id
        cfg["workspace_dir"] = str(self.eval_ws_dir)  # 关键：指向克隆出的评测工作区
        cfg_path.write_text(json.dumps(cfg, ensure_ascii=False, indent=2),
                            encoding="utf-8")

        self.manager = MultiAgentManager(base_dir=self.workspaces_root)
        ws = await self.manager.create_agent(
            self.agent_id, config=cfg, username=self.agent_id
        )
        self.workspace = await self.manager.get_agent(
            self.agent_id, username=self.agent_id
        )
        self.agent = self.workspace.core
        # Inject deterministic mock tools into this workspace's ToolRegistry
        # (native convention: plain-dict return values, schema from docstrings).
        for fn in MOCK_TOOLS:
            await self.workspace.tools.register(
                fn.__name__, fn, description=(fn.__doc__ or "").strip()
            )
        # Controlled environment, part 2:
        #  - neutral system prompt (persona files already removed above)
        #  - only the benchmark's mock tools stay registered; built-in
        #    tools (shell, file ops, ...) are dropped so the model cannot
        #    sidestep the measured behaviour.
        self.agent.system_prompt = (
            "你是一名专业的办公助理，负责准确、高效地完成用户交代的任务。\n"
            "规则：\n"
            "1) 需要外部数据（如OA审批、邮件、文档、日程等）时，必须调用对应的"
            "工具获取，严禁编造数据。\n"
            "2) 获取数据后用简洁、完整的中文作答，直接给出结果。\n"
            "3) 不要执行与任务无关的操作。"
        )
        mock_names = {fn.__name__ for fn in MOCK_TOOLS}
        for name in list(self.workspace.tools._tools.keys()):
            if name not in mock_names:
                self.workspace.tools.unregister(name)

        # Instance-local telemetry: tool chokepoint = registry.call,
        # LLM chokepoint = client.chat.completions.create (covers both the
        # streaming stream_chat path and the non-streaming _call_llm path).
        self.installer = TelemetryInstaller(self.agent, self.workspace.tools)
        self.installer.install()

    async def cleanup(self) -> None:
        try:
            if self.installer:
                self.installer.uninstall()
            if self.manager:
                # MCP clients sometimes stall in a reconnect handshake on
                # shutdown; cap the teardown so the harness always exits
                # (os._exit in main() reaps the rest).
                try:
                    await asyncio.wait_for(self.manager.stop_all(), timeout=30)
                except asyncio.TimeoutError:
                    print("    ! stop_all timed out; forcing exit", flush=True)
        finally:
            reset_flaky()

    # ------------------------------------------------------------------ #
    # chat helpers
    # ------------------------------------------------------------------ #
    async def _send_turn(self, chat_id: str, text: str) -> str:
        """Send one user turn via the same path the WebSocket UI uses.

        Mirrors ``app/routers/websocket.py``: build/reuse the chat context,
        append the user message, consume ``core.stream_chat`` chunks, then
        append the assistant reply. Chunks are ``ResponseBlock`` objects —
        only ``type == "text"`` carries the visible answer.

        A per-turn timeout guards against the agent pausing on a
        confirmation prompt that nobody answers.
        """
        context = await self.workspace._get_chat_context(chat_id)
        context.add_message("user", text)
        # Hermetic isolation: drop any stale compression-cache state left by a
        # previous task's chat (the product-level fix in ContextCompressor
        # guards this; belt & braces for benchmark integrity).
        try:
            self.workspace.core.compressor.clear_cache()
        except AttributeError:
            pass
        collected: list[str] = []

        async def _consume() -> None:
            # ``tools=`` is mandatory: without it stream_chat sends no tool
            # schemas to the LLM, so no tool call can ever happen (this was
            # the zero-score root cause in the first E2E run).
            async for chunk in self.workspace.core.stream_chat(
                text, context, tools=self.workspace.tools, show_tool_details=True
            ):
                if isinstance(chunk, str):
                    collected.append(chunk)
                elif getattr(chunk, "type", None) == "text":
                    collected.append(getattr(chunk, "content", "") or "")

        try:
            await asyncio.wait_for(_consume(), timeout=self.turn_timeout)
        except asyncio.TimeoutError:
            raise RuntimeError(
                f"turn timed out after {self.turn_timeout}s "
                "(agent likely paused awaiting user confirmation)"
            )
        full = "".join(collected)
        context.add_message("assistant", full)
        return full

    # ------------------------------------------------------------------ #
    # task execution
    # ------------------------------------------------------------------ #
    async def run_task(self, task: dict[str, Any]) -> dict[str, Any]:
        from ..foundation.db.engine import get_session_factory
        from ..foundation.db.models import AgentRun, AgentTask, AgentTrajectory

        if task.get("uid") == "pl-06":
            arm_flaky_once()

        # Fresh recording window per task: the recorder is shared across the
        # whole batch, so without a reset every task would inherit the
        # previous task's tool calls / LLM counts.
        self.installer.recorder.reset()

        chat_id = f"eval-{task['uid']}"
        final_answer = ""
        for turn in task["user_turns"]:
            final_answer = await self._send_turn(chat_id, turn)

        # cross-session follow-up: fresh chat, same workspace/memory
        if task.get("cross_session"):
            cs_id = f"eval-{task['uid']}-cs"
            for turn in task.get("followup_turns", []):
                final_answer = await self._send_turn(cs_id, turn)

        rec = self.installer.recorder
        judge = None
        if self.use_judge and task.get("rubric"):
            judge = LLMJudge(make_model_fn(self.agent))
        suite = CheckerSuite(judge=judge.score if judge else None)
        result = await suite.evaluate(
            task,
            final_answer=final_answer,
            tool_call_names=rec.tool_call_names,
            llm_calls=rec.llm_calls,
        )

        now = time.time()
        factory = get_session_factory()
        with factory() as session:
            # Re-runs reuse the task row (task_uid is UNIQUE); each run is a
            # new row so the table doubles as an evolution history.
            trow = session.query(AgentTask).filter_by(
                task_uid=task["uid"]
            ).first()
            if trow is None:
                trow = AgentTask(
                    task_uid=task["uid"], title=task["title"],
                    category=task["category"], difficulty=task["difficulty"],
                    spec=json.dumps(task, ensure_ascii=False), created_at=now,
                )
                session.add(trow)
            traj = AgentTrajectory(
                run_id=0,
                steps=len(rec.steps),
                tool_calls=len(rec.tool_calls),
                llm_calls=rec.llm_calls,
                input_tokens=rec.input_tokens,
                output_tokens=rec.output_tokens,
                cost_cents=0.0,
                trace=json.dumps(rec.steps, ensure_ascii=False),
                final_answer=final_answer[:8000],
                duration_ms=int(rec.duration_ms),
                created_at=now,
            )
            run = AgentRun(
                task_uid=task["uid"], agent_id=self.agent_id,
                started_at=rec.started_at, finished_at=now,
                duration_ms=rec.duration_ms,
                success=result["success"], score=result["score"],
                verdict=result["verdict"],
                metrics=json.dumps(result, ensure_ascii=False),
                trajectory_id=None, notes="",
            )
            session.add(trow)
            session.add(run)
            session.add(traj)
            session.flush()
            traj.run_id = run.id
            run.trajectory_id = traj.id
            session.commit()
            run_id = run.id
        return {"task_uid": task["uid"], "run_id": run_id, **result,
                "final_answer": final_answer[:500]}

    # ------------------------------------------------------------------ #
    # batch
    # ------------------------------------------------------------------ #
    async def run_batch(self, tasks: list[dict[str, Any]]) -> list[dict[str, Any]]:
        assert self.workspace is not None, "call prepare() first"
        results = []
        for i, task in enumerate(tasks, 1):
            print(f"[{i}/{len(tasks)}] {task['uid']} {task['title']}", flush=True)
            try:
                res = await self.run_task(task)
            except Exception as exc:  # noqa: BLE001 - keep batch alive
                res = {"task_uid": task["uid"], "run_id": None, "score": 0.0,
                       "verdict": "error", "success": False,
                       "final_answer": f"RUNNER ERROR: {exc}"}
            results.append(res)
            detail = ""
            if res["verdict"] == "error":
                fa = str(res.get("final_answer") or "")
                detail = f" [{fa[:100]}]"
            print(f"    -> {res['verdict']} ({res['score']}){detail}", flush=True)
        return results


def make_model_fn(agent: Any):
    """Build an async (system, prompt) -> str callable on the agent's model.

    Goes through ``AgentCore._call_llm`` — the same low-level call the agent
    itself uses — so the judge runs on the identical model/provider config.
    """
    async def model_fn(system: str, prompt: str) -> str:
        core = agent.core if hasattr(agent, "core") else agent
        resp = await core._call_llm(
            system, [{"role": "user", "content": prompt}], None
        )
        content = resp.get("content") if isinstance(resp, dict) else resp
        return str(content or "")
    return model_fn


async def amain(argv: Optional[list[str]] = None) -> int:
    ap = argparse.ArgumentParser(description="Run agent eval benchmark")
    ap.add_argument("--category", help="restrict to one category")
    ap.add_argument("--tasks", nargs="*", help="explicit task uids")
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--source-user", default="admin")
    ap.add_argument("--workspaces-root", default="/apps/ai/coapis/workspaces")
    ap.add_argument("--no-judge", action="store_true")
    args = ap.parse_args(argv)

    tasks = load_tasks(args.category)
    if args.tasks:
        tasks = [t for t in tasks if t["uid"] in set(args.tasks)]
    if args.limit:
        tasks = tasks[: args.limit]
    if not tasks:
        print("no tasks matched", file=sys.stderr)
        return 2

    runner = EvalRunner(Path(args.workspaces_root), args.source_user,
                        use_judge=not args.no_judge)
    t_prepare = time.monotonic()
    try:
        await runner.prepare()
        print(f"[timing] prepare {time.monotonic() - t_prepare:.1f}s", flush=True)
        t_run = time.monotonic()
        results = await runner.run_batch(tasks)
        print(f"[timing] run_batch {time.monotonic() - t_run:.1f}s", flush=True)
    finally:
        t_clean = time.monotonic()
        await runner.cleanup()
        print(f"[timing] cleanup {time.monotonic() - t_clean:.1f}s", flush=True)

    passed = sum(1 for r in results if r["verdict"] == "pass")
    avg = sum(r["score"] for r in results) / len(results)
    print(f"\n== SUMMARY: {passed}/{len(results)} pass, avg score {avg:.3f}")
    for r in results:
        print(f"  {r['task_uid']:8s} {r['verdict']:8s} {r['score']:.3f}")
    # Hard-exit here, BEFORE asyncio.run's task-cancellation sweep: the MCP
    # reconnect loop swallows CancelledError and would otherwise hold the
    # event loop hostage (observed: run killed by the 280s wall-clock
    # timeout with the summary never flushed).
    sys.stdout.flush()
    sys.stderr.flush()
    os._exit(0)


def main() -> None:
    # os._exit: leftover non-daemon threads (MCP clients, schedulers) would
    # otherwise keep the process alive long after the run finished.
    try:
        rc = asyncio.run(amain())
    except BaseException:  # noqa: BLE001 - report, then hard-exit
        import traceback
        traceback.print_exc()
        sys.stdout.flush()
        sys.stderr.flush()
        os._exit(1)
    sys.stdout.flush()
    sys.stderr.flush()
    os._exit(rc)


if __name__ == "__main__":
    main()
