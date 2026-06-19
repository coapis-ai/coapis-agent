# -*- coding: utf-8 -*-
# Copyright 2026 蜜蜂 & CoApis Contributors
# Licensed under the Apache License, Version 2.0
from __future__ import annotations
import asyncio, json, logging, os, time, uuid
from pathlib import Path
from typing import Any
from .registry import register_tool

logger = logging.getLogger(__name__)

WF_DIR = Path(os.path.join(os.path.dirname(__file__), "..", "..", "..", "data", "workflows"))


def _ensure_dir():
    WF_DIR.mkdir(parents=True, exist_ok=True)


def _load_workflows() -> dict[str, Any]:
    _ensure_dir()
    wf = WF_DIR / "workflows.json"
    if wf.exists():
        try:
            return json.loads(wf.read_text())
        except Exception:
            pass
    return {"workflows": {}, "runs": {}}


def _save_workflows(data: dict[str, Any]):
    _ensure_dir()
    (WF_DIR / "workflows.json").write_text(json.dumps(data, ensure_ascii=False, indent=2))


def _topological_sort(steps: list[dict]) -> list[list[dict]]:
    """DAG topological sort returning levels (parallel groups)."""
    step_map = {s["id"]: s for s in steps}
    in_degree = {s["id"]: 0 for s in steps}
    for s in steps:
        for dep in s.get("depends_on", []):
            if dep in in_degree:
                in_degree[s["id"]] += 1
    levels = []
    remaining = dict(in_degree)
    while remaining:
        ready = [sid for sid, deg in remaining.items() if deg == 0]
        if not ready:
            break
        levels.append([step_map[sid] for sid in ready])
        for sid in ready:
            del remaining[sid]
            for s2 in steps:
                if sid in s2.get("depends_on", []):
                    remaining[s2["id"]] = remaining.get(s2["id"], 0) - 1
    return levels


async def _execute_step(step: dict, context: dict, timeout: int = 30) -> dict[str, Any]:
    """Execute a workflow step."""
    step_type = step.get("type", "shell")
    start = time.time()
    result = {"step_id": step["id"], "name": step.get("name", ""), "status": "ok"}

    try:
        if step_type == "shell":
            cmd = step.get("command", "echo 'no command'")
            proc = await asyncio.create_subprocess_shell(
                cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE
            )
            stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=timeout)
            result["stdout"] = stdout.decode(errors="replace")[:1000]
            result["stderr"] = stderr.decode(errors="replace")[:500]
            result["returncode"] = proc.returncode
            result["status"] = "ok" if proc.returncode == 0 else "failed"

        elif step_type == "tool":
            tool_name = step.get("tool", "")
            tool_args = step.get("args", {})
            result["tool"] = tool_name
            result["message"] = f"Tool call placeholder: {tool_name}"

        elif step_type == "delay":
            delay = step.get("seconds", 1)
            await asyncio.sleep(min(delay, 60))
            result["delayed"] = delay

        else:
            result["status"] = "skipped"
            result["message"] = f"未知步骤类型: {step_type}"

    except asyncio.TimeoutError:
        result["status"] = "timeout"
    except Exception as e:
        result["status"] = "error"
        result["error"] = str(e)

    result["duration_ms"] = round((time.time() - start) * 1000, 1)
    return result


@register_tool(
    name="workflow_engine",
    description="DAG 工作流编排：定义/运行/追踪工作流，支持依赖解析、并行执行、重试机制。",
    category="builtin",
    tags=["ops", "workflow", "dag", "orchestration"],
    scene="collaboration"
)
async def workflow_engine(
    action: str = "run",
    workflow_name: str = "",
    steps: str = "",
    step_id: str = "",
    max_retries: int = 3,
    parallel: bool = True,
    timeout: int = 300,
    limit: int = 20,
) -> dict[str, Any]:
    """DAG 工作流编排。

    Args:
        action: 操作类型 (create/run/list/get/cancel)
        workflow_name: 工作流名称
        steps: 步骤定义 JSON 数组 [{"id":"s1","type":"shell","command":"ls","depends_on":[]}]
        step_id: 查询特定步骤
        max_retries: 最大重试次数
        parallel: 是否并行执行无依赖步骤
        timeout: 工作流超时秒数
        limit: 列表限制

    Returns:
        执行结果
    """
    _ensure_dir()
    data = _load_workflows()

    if action == "create":
        if not workflow_name.strip():
            return {"error": "workflow_name 不能为空"}
        if not steps.strip():
            return {"error": "steps 不能为空"}
        try:
            steps_list = json.loads(steps)
        except Exception:
            return {"error": "steps JSON 解析失败"}
        data.setdefault("workflows", {})[workflow_name] = {
            "steps": steps_list,
            "created_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        }
        _save_workflows(data)
        return {"action": "created", "name": workflow_name, "steps_count": len(steps_list)}

    elif action == "run":
        if not workflow_name.strip():
            return {"error": "workflow_name 不能为空"}

        if steps.strip():
            steps_list = json.loads(steps)
        elif workflow_name in data.get("workflows", {}):
            steps_list = data["workflows"][workflow_name]["steps"]
        else:
            return {"error": f"工作流不存在: {workflow_name}"}

        run_id = str(uuid.uuid4())[:12]
        run_data = {
            "workflow": workflow_name, "run_id": run_id,
            "status": "running", "steps": steps_list,
            "results": [], "start_time": time.time(),
        }

        levels = _topological_sort(steps_list)

        all_results = []
        failed = False

        for level in levels:
            if failed:
                for step in level:
                    all_results.append({"step_id": step["id"], "name": step.get("name", ""), "status": "skipped", "message": "上游步骤失败"})
                continue

            tasks = [_execute_step(step, {}, timeout) for step in level]
            if parallel:
                level_results = await asyncio.gather(*tasks, return_exceptions=True)
            else:
                level_results = []
                for t in tasks:
                    level_results.append(await t)

            for i, r in enumerate(level_results):
                if isinstance(r, Exception):
                    r = {"step_id": level[i]["id"], "status": "error", "error": str(r)}
                all_results.append(r)
                if r.get("status") in ("failed", "error"):
                    failed = True

        if failed and max_retries > 0:
            for retry_round in range(max_retries):
                retry_needed = [r for r in all_results if r.get("status") in ("failed", "error")]
                if not retry_needed:
                    break
                for r in retry_needed:
                    retry_step = next((s for s in steps_list if s["id"] == r["step_id"]), None)
                    if retry_step:
                        retry_result = await _execute_step(retry_step, {}, timeout)
                        idx = all_results.index(r)
                        all_results[idx] = retry_result
                        if retry_result.get("status") == "ok":
                            failed = False

        total_ms = round((time.time() - run_data["start_time"]) * 1000, 1)
        overall_status = "completed" if not failed else "failed"
        success_count = sum(1 for r in all_results if r.get("status") == "ok")

        run_data["results"] = all_results
        run_data["status"] = overall_status
        run_data["total_ms"] = total_ms

        data.setdefault("runs", {})[run_id] = run_data
        _save_workflows(data)

        return {
            "action": "run", "run_id": run_id, "workflow": workflow_name,
            "status": overall_status, "total_ms": total_ms,
            "steps_total": len(all_results), "steps_ok": success_count,
            "steps_failed": len(all_results) - success_count,
            "results": all_results,
        }

    elif action == "list":
        workflows = data.get("workflows", {})
        runs = data.get("runs", {})
        items = []
        for name, wf in workflows.items():
            wf_runs = [r for r in runs.values() if r.get("workflow") == name]
            items.append({
                "name": name, "steps": len(wf.get("steps", [])),
                "runs": len(wf_runs),
                "last_run": wf_runs[-1].get("status", "") if wf_runs else "",
            })
        return {"action": "list", "count": len(items), "workflows": items[:limit]}

    elif action == "get":
        if not workflow_name.strip():
            return {"error": "workflow_name 不能为空"}
        wf = data.get("workflows", {}).get(workflow_name)
        if not wf:
            return {"error": f"工作流不存在: {workflow_name}"}
        return {"action": "get", "name": workflow_name, **wf}

    elif action == "cancel":
        if not step_id.strip():
            return {"error": "step_id (run_id) 不能为空"}
        run = data.get("runs", {}).get(step_id)
        if not run:
            return {"error": f"运行不存在: {step_id}"}
        run["status"] = "cancelled"
        _save_workflows(data)
        return {"action": "cancelled", "run_id": step_id}

    else:
        return {"error": f"未知操作: {action}，支持 create/run/list/get/cancel"}
