# -*- coding: utf-8 -*-
# Copyright 2026 蜜蜂 & CoApis Contributors
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU Affero General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU Affero General Public License for more details.
#
# You should have received a copy of the GNU Affero General Public License
# along with this program.  If not, see <https://www.gnu.org/licenses/>.

"""Install runtime dependencies into the shared runtime pool."""

import asyncio
import logging
import os
import subprocess
from datetime import datetime
from pathlib import Path
from typing import Literal, Optional

from agentscope.message import TextBlock
from agentscope.tool import ToolResponse

from .registry import register_tool

logger = logging.getLogger(__name__)


def _shared_runtime_dir() -> Path:
    """Return the shared runtime directory from the environment."""
    return Path(os.environ.get("COAPIS_SHARED_RUNTIME_DIR", "/opt/coapis/shared_runtime"))


def _write_install_log(
    manager: str,
    package: str,
    version: Optional[str],
    success: bool,
    output: str,
) -> None:
    """Append an audit entry to the shared runtime install log."""
    log_file = _shared_runtime_dir() / "state" / "install.log"
    try:
        log_file.parent.mkdir(parents=True, exist_ok=True)
        with open(log_file, "a", encoding="utf-8") as f:
            f.write(
                f"{datetime.now().isoformat()} "
                f"[{'success' if success else 'failed'}] "
                f"{manager}: {package}"
                f"{f'=={version}' if version and manager == 'pip' else ''}"
                f"{f'@{version}' if version and manager == 'npm' else ''}\n"
                f"{output}\n---\n"
            )
    except Exception as e:
        logger.warning("Failed to write install log: %s", e)


@register_tool(
    name="install_dependency",
    description="安装 Python 或 Node 包到共享运行时池，安装后所有用户/容器可复用。",
    category="builtin",
    tags=["dependency", "package", "mcp", "runtime"],
)
async def install_dependency(
    package: str,
    manager: Literal["pip", "npm"] = "pip",
    version: Optional[str] = None,
    global_install: bool = True,
) -> ToolResponse:
    """Install a dependency into the shared runtime pool.

    Args:
        package: Package name, e.g. "requests" or "@gitee/mcp-server-gitee".
        manager: Package manager, either "pip" or "npm".
        version: Optional version, e.g. "1.1.0".
        global_install: For npm only, install globally so all users can use it.
            Ignored for pip because pip always installs to the shared user site.

    Returns:
        ToolResponse with the installation result and command output.
    """
    if manager not in ("pip", "npm"):
        return ToolResponse(
            content=[
                TextBlock(
                    type="text",
                    text="不支持的包管理器，仅支持 pip 或 npm。",
                ),
            ],
        )

    if not package or not isinstance(package, str):
        return ToolResponse(
            content=[
                TextBlock(
                    type="text",
                    text="包名必须是非空字符串。",
                ),
            ],
        )

    if manager == "pip":
        spec = f"{package}=={version}" if version else package
        cmd = ["pip", "install", "--user", spec]
    else:
        if version:
            spec = f"{package}@{version}"
        else:
            spec = package
        if global_install:
            cmd = ["npm", "install", "-g", spec]
        else:
            cmd = ["npm", "install", spec]

    logger.info("Installing dependency: %s", cmd)
    try:
        result = await asyncio.to_thread(
            subprocess.run,
            cmd,
            capture_output=True,
            text=True,
            timeout=300,
            check=False,
            env=os.environ,
        )
    except subprocess.TimeoutExpired:
        output = "Installation timed out after 300 seconds."
        _write_install_log(manager, package, version, False, output)
        return ToolResponse(
            content=[TextBlock(type="text", text=output)],
        )
    except Exception as e:
        output = f"Installation error: {e!s}"
        _write_install_log(manager, package, version, False, output)
        return ToolResponse(
            content=[TextBlock(type="text", text=output)],
        )

    stdout = result.stdout or ""
    stderr = result.stderr or ""
    output = f"STDOUT:\n{stdout}\nSTDERR:\n{stderr}"
    success = result.returncode == 0
    _write_install_log(manager, package, version, success, output)

    if success:
        text = f"成功安装 {spec}（通过 {manager}）。\n{output}"
    else:
        text = f"安装 {spec} 失败（通过 {manager}）。\n{output}"

    return ToolResponse(
        content=[TextBlock(type="text", text=text)],
    )
