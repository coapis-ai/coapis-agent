# -*- coding: utf-8 -*-
# pylint: disable=too-many-return-statements
# -*- coding: utf-8 -*-
# Copyright 2026 蜜蜂 & CoApis Contributors
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU Affero General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU Affero General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
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

"""
Bridge between channels and AgentApp process: factory to build
ProcessHandler from runner. Shared helpers for channels (e.g. file URL).

Also provides on-demand dependency management for channels with
optional PyPI packages (e.g. wecom-aibot-python-sdk, discord.py).
"""
from __future__ import annotations

import importlib
import logging
import os
import re
import subprocess
import sys
from typing import Any, List, Optional
from urllib.parse import urlparse
from urllib.request import url2pathname

_FENCE_RE = re.compile(r"^(`{3,}|~{3,})")

logger = logging.getLogger(__name__)

# PIP command — prefer python -m pip for venv compatibility
_PIP_CMD = [sys.executable, "-m", "pip", "install"]


def _is_windows_drive(netloc: str) -> bool:
    """Check if netloc looks like a Windows drive letter.

    Handles both the legacy single-letter form (``C``, from
    ``file://C/path``) and the colon form (``C:``, from
    ``file://C:/path``).
    """
    if os.name != "nt" or not netloc:
        return False
    if len(netloc) == 1 and netloc[0].isalpha():
        return True
    if len(netloc) == 2 and netloc[0].isalpha() and netloc[1] == ":":
        return True
    return False


def split_text(text: str, max_len: int = 3000) -> List[str]:
    """Split text into chunks that fit within max_len characters.

    Splits at newline boundaries to preserve formatting. If a single
    line exceeds max_len it is hard-split at max_len.

    Markdown code fences are tracked so that a chunk ending inside an
    open fence gets a closing fence appended and the next chunk gets
    a matching opening fence prepended, keeping code blocks rendered
    correctly across split messages.
    """
    if len(text) <= max_len:
        return [text]

    chunks: List[str] = []
    current: List[str] = []
    current_len = 0
    fence_open: str = ""

    def _flush() -> None:
        nonlocal fence_open
        body = "".join(current).rstrip("\n")
        if fence_open:
            body += "\n```"
        chunks.append(body)
        current.clear()

    for line in text.split("\n"):
        line_with_nl = line + "\n"
        stripped = line.strip()

        if _FENCE_RE.match(stripped):
            if fence_open:
                fence_open = ""
            else:
                fence_open = stripped

        if current and current_len + len(line_with_nl) > max_len:
            saved_fence = fence_open
            _flush()
            current_len = 0
            if saved_fence:
                fence_open = saved_fence
                reopener = saved_fence + "\n"
                current.append(reopener)
                current_len += len(reopener)

        if len(line_with_nl) > max_len:
            for i in range(0, len(line), max_len):
                chunks.append(line[i : i + max_len])
        else:
            current.append(line_with_nl)
            current_len += len(line_with_nl)

    if current:
        chunks.append("".join(current).rstrip("\n"))

    return [c for c in chunks if c.strip()]


def file_url_to_local_path(url: str) -> Optional[str]:
    """Convert file:// URL or plain local path to local path string.

    Supports:
    - file:// URL (all platforms): file:///path, file://D:/path,
      file://D:\\path (Windows two-slash).
    - Plain local path: D:\\path, /tmp/foo (no scheme). Pass-through after
      stripping whitespace; no existence check (caller may use Path().exists).

    Returns None only when url is clearly not a local file (e.g. http(s) URL)
    or file URL could not be resolved to a non-empty path.
    """
    if not url or not isinstance(url, str):
        return None
    s = url.strip()
    if not s:
        return None
    parsed = urlparse(s)
    if parsed.scheme == "file":
        path = url2pathname(parsed.path)
        if not path and parsed.netloc:
            path = url2pathname(parsed.netloc.replace("\\", "/"))
        elif (
            path and parsed.netloc and _is_windows_drive(netloc=parsed.netloc)
        ):
            # netloc may be "C:" (new format) or "C" (legacy format)
            drive = (
                parsed.netloc if ":" in parsed.netloc else f"{parsed.netloc}:"
            )
            path = f"{drive}{path}"
        elif path and parsed.netloc and os.name == "nt":
            # UNC: file://server/share/… → \\server\share\…
            path = f"\\\\{parsed.netloc}{path}"
        return path if path else None
    if parsed.scheme in ("http", "https"):
        return None
    if not parsed.scheme:
        return s
    if (
        os.name == "nt"
        and len(parsed.scheme) == 1
        and parsed.path.startswith("\\")
    ):
        return s
    return None


def make_process_from_runner(runner: Any):
    """
    Use runner.stream_query as the channel's process.

    Each channel does: native -> build_agent_request_from_native()
        -> process(request) -> send on each completed message.
    process is runner.stream_query, same as AgentApp's /process endpoint.

    Usage::
        process = make_process_from_runner(runner)
        manager = ChannelManager.from_env(process)
    """
    return runner.stream_query


# ═══════════════════════════════════════════════════════════════════
# On-demand dependency management
# ═══════════════════════════════════════════════════════════════════


def _normalize_import_name(package_spec: str) -> tuple[str, str]:
    """Normalize a PyPI package name to its importable name.

    Returns:
        (import_name, package_spec) — import_name is what you
        actually `import`, package_spec is what you `pip install`.
    """
    pkg = package_spec.split(">=")[0].split("<=")[0].split("==")[0].split("[")[0].strip()

    # ── Known mappings: PyPI name → import name ──
    _MAPPINGS: dict[str, str] = {
        "wecom-aibot-python-sdk": "aibot",
        "python-telegram-bot": "telegram",
        "alibabacloud-dingtalk": "alibabacloud_dingtalk",
        "alibabacloud-tea-openapi": "alibabacloud_tea_openapi",
        "alibabacloud-tea-util": "alibabacloud_tea_util",
        "dingtalk-stream": "dingtalk_stream",
        "lark-oapi": "lark_oapi",
        "wechatpy": "wechatpy",
        "matrix-nio": "nio",
        "mattermostdriver": "mattermostdriver",
        "paho-mqtt": "paho.mqtt.client",
        "pygobot": "pygobot",
        "napcat-api": "napcat_api",
        "pyatv": "pyatv",
        "twilio": "twilio",
        "pyvoip": "pyvoip",
        "discord.py": "discord",
    }

    import_name = _MAPPINGS.get(pkg, pkg.replace("-", "_"))
    return (import_name, package_spec)


def is_package_installed(package_spec: str) -> bool:
    """Check if a PyPI package is installed.

    Args:
        package_spec: PyPI package specifier (e.g. "wecom-aibot-python-sdk>=1.0.0").

    Returns:
        True if the package is importable.
    """
    try:
        import_name, _ = _normalize_import_name(package_spec)
        importlib.import_module(import_name)
        return True
    except ImportError:
        return False


def install_package(package_spec: str, timeout: int = 300) -> bool:
    """Install a PyPI package.

    Args:
        package_spec: PyPI package specifier.
        timeout: Max seconds to wait for pip to complete.

    Returns:
        True if installation succeeded.
    """
    try:
        logger.info("Installing optional dependency: %s", package_spec)
        result = subprocess.run(
            _PIP_CMD + [package_spec],
            capture_output=True,
            text=True,
            timeout=timeout,
        )
        if result.returncode == 0:
            logger.info("Successfully installed: %s", package_spec)
            return True
        else:
            logger.error(
                "Failed to install %s: %s",
                package_spec,
                result.stderr.strip()[-500:],  # Last 500 chars
            )
            return False
    except subprocess.TimeoutExpired:
        logger.error(
            "Installation of %s timed out after %ds",
            package_spec,
            timeout,
        )
        return False
    except Exception as e:
        logger.error(
            "Exception during installation of %s: %s",
            package_spec,
            e,
        )
        return False


def ensure_packages_installed(
    package_specs: list[str],
    timeout: int = 300,
) -> bool:
    """Check and install missing packages from a list.

    Args:
        package_specs: List of PyPI package specifiers.
        timeout: Max seconds per package installation.

    Returns:
        True if all packages are installed (already were or just installed).
    """
    if not package_specs:
        return True

    all_ok = True
    for spec in package_specs:
        if not is_package_installed(spec):
            if not install_package(spec, timeout=timeout):
                all_ok = False
        else:
            logger.debug("Package already installed: %s", spec)

    return all_ok


def check_channel_dependencies(channel_key: str, timeout: int = 300) -> bool:
    """Check and install dependencies for a specific channel.

    This is the main entry point called from ChannelManager.from_config.

    Args:
        channel_key: Channel key (e.g. 'wecom').
        timeout: Max seconds per package installation.

    Returns:
        True if all dependencies are installed.
    """
    from .dependencies import get_channel_dependencies, SHARED_DEPENDENCIES

    pkg_specs = get_channel_dependencies(channel_key)
    if not pkg_specs:
        return True

    # Install shared dependencies first (only once)
    if SHARED_DEPENDENCIES:
        ensure_packages_installed(SHARED_DEPENDENCIES, timeout=timeout)

    return ensure_packages_installed(pkg_specs, timeout=timeout)
