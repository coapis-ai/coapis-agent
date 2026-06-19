# -*- coding: utf-8 -*-
# Copyright 2026 蜜蜂 & CoApis Contributors
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

"""Deploy helper — Docker build/run/stop and docker-compose operations.

Wraps Docker CLI commands for safe, structured deployment operations.
"""

from __future__ import annotations

import asyncio
import logging
import time
from pathlib import Path
from typing import Any

from .registry import register_tool

logger = logging.getLogger(__name__)

_TIMEOUT = 120  # seconds


def _get_workspace() -> Path:
    """Get workspace directory."""
    try:
        from ...config.context import get_current_workspace_dir
        ws = get_current_workspace_dir()
        if ws:
            return Path(ws)
    except Exception:
        pass
    return Path.cwd()


async def _run_cmd(
    cmd: list[str], cwd: str, timeout: int = _TIMEOUT
) -> dict[str, Any]:
    """Run a shell command with timeout."""
    start = time.time()
    try:
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            cwd=cwd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=timeout)
        elapsed = round(time.time() - start, 2)
        return {
            "returncode": proc.returncode,
            "stdout": stdout.decode(errors="replace")[-6000:],
            "stderr": stderr.decode(errors="replace")[-3000:],
            "elapsed": elapsed,
        }
    except asyncio.TimeoutError:
        return {"returncode": -1, "stdout": "", "stderr": f"Timeout after {timeout}s", "elapsed": timeout}
    except FileNotFoundError:
        return {"returncode": -1, "stdout": "", "stderr": f"Command not found: {cmd[0]}", "elapsed": 0}
    except Exception as e:
        return {"returncode": -1, "stdout": "", "stderr": str(e), "elapsed": 0}


@register_tool(
    name="deploy_helper",
    description="部署助手：Docker 构建/运行/停止/状态查看，docker-compose up/down/ps/logs。",
    category="builtin",
    tags=["deploy", "docker", "ops"],
    scene="ops"
)
async def deploy_helper(
    action: str = "status",
    target: str = "",
    service: str = "",
    tag: str = "",
    ports: str = "",
    env: str = "",
    compose_file: str = "",
    detach: bool = True,
    timeout: int = 120,
) -> dict[str, Any]:
    """部署助手。

    Docker 和 docker-compose 操作的封装。

    Actions:
    - status: 查看 Docker 状态（docker info / docker ps）
    - build: 构建镜像 (docker build)
    - run: 运行容器 (docker run)
    - stop: 停止容器 (docker stop)
    - remove: 移除容器 (docker rm)
    - images: 列出镜像 (docker images)
    - compose_up: docker-compose up -d
    - compose_down: docker-compose down
    - compose_ps: docker-compose ps
    - compose_logs: docker-compose logs

    Args:
        action: 操作类型
        target: 镜像名/容器名/路径
        service: docker-compose 服务名
        tag: 镜像标签（build 时使用）
        ports: 端口映射，如 "8080:80,3000:3000"
        env: 环境变量，如 "NODE_ENV=production,DEBUG=true"
        compose_file: docker-compose 文件路径
        detach: 是否后台运行，默认 True
        timeout: 超时秒数，默认 120

    Returns:
        操作结果
    """
    workspace = str(_get_workspace())

    if action == "status":
        r1 = await _run_cmd(["docker", "info", "--format", "{{.ServerVersion}}"], workspace, timeout=10)
        r2 = await _run_cmd(["docker", "ps", "--format", "table {{.Names}}\t{{.Image}}\t{{.Status}}\t{{.Ports}}"], workspace, timeout=10)
        return {
            "docker_version": r1["stdout"].strip() if r1["returncode"] == 0 else "N/A",
            "running_containers": r2["stdout"].strip() if r2["returncode"] == 0 else "None",
            "available": r1["returncode"] == 0,
        }

    elif action == "build":
        if not target.strip():
            return {"error": "target（构建路径或 Dockerfile 所在目录）不能为空"}
        cmd = ["docker", "build", "-t", (tag or target.split("/")[-1]).strip()]
        cmd.append(target.strip())
        r = await _run_cmd(cmd, workspace, timeout=timeout)
        return {
            "action": "build",
            "success": r["returncode"] == 0,
            "image": (tag or target.split("/")[-1]).strip(),
            "elapsed": r["elapsed"],
            "output": r["stdout"][-2000:] if r["stdout"] else "",
            "error": r["stderr"][-1000:] if r["stderr"] and r["returncode"] != 0 else "",
        }

    elif action == "run":
        if not target.strip():
            return {"error": "target（镜像名）不能为空"}
        cmd = ["docker", "run"]
        if detach:
            cmd.append("-d")
        # Ports
        if ports.strip():
            for p in ports.split(","):
                p = p.strip()
                if p:
                    cmd.extend(["-p", p])
        # Env
        if env.strip():
            for e in env.split(","):
                e = e.strip()
                if e:
                    cmd.extend(["-e", e])
        # Container name from tag or image
        name = (tag or target.split("/")[-1]).replace(":", "-").replace("/", "-")
        cmd.extend(["--name", name])
        cmd.append(target.strip())
        r = await _run_cmd(cmd, workspace, timeout=timeout)
        container_id = r["stdout"].strip()[:12] if r["returncode"] == 0 else ""
        return {
            "action": "run",
            "success": r["returncode"] == 0,
            "container": name,
            "container_id": container_id,
            "image": target.strip(),
            "elapsed": r["elapsed"],
            "error": r["stderr"][-500:] if r["stderr"] and r["returncode"] != 0 else "",
        }

    elif action == "stop":
        if not target.strip():
            return {"error": "target（容器名/ID）不能为空"}
        cmd = ["docker", "stop", target.strip()]
        r = await _run_cmd(cmd, workspace, timeout=30)
        return {
            "action": "stop",
            "success": r["returncode"] == 0,
            "container": target.strip(),
            "error": r["stderr"][-500:] if r["stderr"] and r["returncode"] != 0 else "",
        }

    elif action == "remove":
        if not target.strip():
            return {"error": "target（容器名/ID）不能为空"}
        cmd = ["docker", "rm", target.strip()]
        r = await _run_cmd(cmd, workspace, timeout=30)
        return {
            "action": "remove",
            "success": r["returncode"] == 0,
            "container": target.strip(),
            "error": r["stderr"][-500:] if r["stderr"] and r["returncode"] != 0 else "",
        }

    elif action == "images":
        cmd = ["docker", "images", "--format", "table {{.Repository}}\t{{.Tag}}\t{{.Size}}\t{{.CreatedAt}}"]
        r = await _run_cmd(cmd, workspace, timeout=15)
        return {
            "action": "images",
            "success": r["returncode"] == 0,
            "images": r["stdout"].strip() if r["returncode"] == 0 else "None",
        }

    elif action in ("compose_up", "compose_down", "compose_ps", "compose_logs"):
        # Determine compose command
        compose_cmd = ["docker-compose"]
        # Check if docker compose v2 is available
        check = await _run_cmd(["docker", "compose", "version"], workspace, timeout=5)
        if check["returncode"] == 0:
            compose_cmd = ["docker", "compose"]

        if compose_file.strip():
            compose_cmd.extend(["-f", compose_file.strip()])

        if action == "compose_up":
            compose_cmd.extend(["up", "-d"])
            if service.strip():
                compose_cmd.append(service.strip())
        elif action == "compose_down":
            compose_cmd.extend(["down"])
        elif action == "compose_ps":
            compose_cmd.extend(["ps"])
        elif action == "compose_logs":
            compose_cmd.extend(["logs", "--tail=50"])
            if service.strip():
                compose_cmd.append(service.strip())

        r = await _run_cmd(compose_cmd, workspace, timeout=timeout)
        return {
            "action": action,
            "success": r["returncode"] == 0,
            "command": " ".join(compose_cmd),
            "output": r["stdout"][-3000:] if r["stdout"] else "",
            "error": r["stderr"][-1000:] if r["stderr"] and r["returncode"] != 0 else "",
        }

    else:
        return {"error": f"未知操作: {action}，支持 status/build/run/stop/remove/images/compose_up/compose_down/compose_ps/compose_logs"}
