# -*- coding: utf-8 -*-
# flake8: noqa: E501
# pylint: disable=line-too-long
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

"""The shell command tool."""

import asyncio
import locale
import os
import signal
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Optional

from agentscope.message import TextBlock
from agentscope.tool import ToolResponse

from ...constant import WORKING_DIR
from ...config.context import (
    get_current_shell_command_timeout,
    get_current_workspace_dir,
)

# Linux namespace constants (only available on Linux)
try:
    import ctypes
    import ctypes.util
    _libc = ctypes.CDLL(ctypes.util.find_library("c") or "libc.so.6", use_errno=True)
    CLONE_NEWNS = 0x00020000  # New mount namespace
    _HAS_UNSHARE = True
except Exception:
    _HAS_UNSHARE = False


def _make_ns_preexec(writable_dir: str, inner_fn=None):
    """Return a preexec_fn that creates an isolated mount namespace.

    When ``COAPIS_ENABLE_NS=1``, this:
    1. Calls ``unshare(CLONE_NEWNS)`` to create a new mount namespace
    2. Bind-mounts ``writable_dir`` to itself (so it stays writable)
    3. Remounts ``/`` as MS_REC|MS_SLAVE to prevent mount propagation
    4. Remounts ``/`` as MS_RDONLY|MS_REC (read-only root)
    5. Remounts ``writable_dir`` as MS_BIND (writable overlay)

    The inner_fn (e.g. ResourceLimiter._set_unix_limits) is called first
    if provided.

    Falls back gracefully to inner_fn only if unshare is unavailable.
    """
    if not _HAS_UNSHARE:
        return inner_fn

    def _ns_fn():
        # Call inner preexec_fn first (e.g. resource limits)
        if inner_fn is not None:
            inner_fn()

        try:
            import ctypes
            import ctypes.util
            _libc2 = ctypes.CDLL(ctypes.util.find_library("c") or "libc.so.6", use_errno=True)

            # 1. Enter new mount namespace
            ret = _libc2.unshare(CLONE_NEWNS)
            if ret != 0:
                return  # silently fall back if unshare fails

            # Constants
            MS_REMOUNT = 32
            MS_BIND = 4096
            MS_REC = 0x4000
            MS_RDONLY = 1
            MS_SLAVE = 1 << 19

            target = writable_dir.encode("utf-8")

            # 2. Bind-mount writable dir BEFORE making / read-only
            _libc2.mount(target, target, b"", MS_BIND, None)

            # 3. Make / a slave mount (no propagation from parent ns)
            _libc2.mount(b"", b"/", b"", MS_REC | MS_SLAVE, None)

            # 4. Remount / as read-only (writable dir survives as separate mount)
            _libc2.mount(b"/", b"/", b"", MS_REMOUNT | MS_REC | MS_RDONLY, None)

        except Exception:
            pass  # Fail open: namespace isolation is best-effort

    return _ns_fn


def _kill_process_tree_win32(pid: int) -> None:
    """Kill a process and all its descendants on Windows via taskkill.

    Uses ``taskkill /F /T`` which forcefully terminates the entire process
    tree, including grandchild processes that ``Popen.kill()`` would miss.
    """
    try:
        subprocess.call(
            ["taskkill", "/F", "/T", "/PID", str(pid)],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            timeout=10,
        )
    except Exception:
        pass


def _collapse_newlines_outside_quotes(cmd: str) -> str:
    r"""Collapse newlines outside quoted strings; preserve those inside.

    Used only on Unix where sh/bash correctly handles newlines in quotes.
    Handles backslash-newline (line continuation) by removing both chars,
    and treats single-quoted content as fully literal per POSIX.
    """
    result: list[str] = []
    in_single_quote = False
    in_double_quote = False
    i = 0
    length = len(cmd)

    while i < length:
        char = cmd[i]

        # Toggle quote state
        if char == "'" and not in_double_quote:
            in_single_quote = not in_single_quote
            result.append(char)
            i += 1
            continue

        if char == '"' and not in_single_quote:
            in_double_quote = not in_double_quote
            result.append(char)
            i += 1
            continue

        # Inside single quotes: everything is literal (POSIX)
        if in_single_quote:
            result.append(char)
            i += 1
            continue

        # Backslash-newline (line continuation): remove both chars
        if char == "\\" and i + 1 < length and cmd[i + 1] in ("\r", "\n"):
            i += 2
            # \r\n sequence: skip the \n as well
            if i < length and cmd[i - 1] == "\r" and cmd[i] == "\n":
                i += 1
            continue

        # Backslash escape (non-newline): keep both chars
        if char == "\\" and i + 1 < length:
            result.append(char)
            result.append(cmd[i + 1])
            i += 2
            continue

        # Newlines
        if char in ("\r", "\n"):
            if in_double_quote:
                # Preserve newlines inside double quotes
                result.append(char)
            else:
                # Collapse \r\n as a single space
                if char == "\r" and i + 1 < length and cmd[i + 1] == "\n":
                    i += 1
                result.append(" ")
            i += 1
            continue

        result.append(char)
        i += 1

    return "".join(result)


def _collapse_embedded_newlines(cmd: str) -> str:
    r"""Replace embedded newline characters with spaces in a command string.

    LLMs produce tool-call arguments in JSON where ``\n`` is parsed as an
    actual newline character.  In the original shell command the user
    intended the *literal* two-character sequence ``\n`` (e.g. inside a
    ``--content`` flag), but after JSON decoding it becomes a real line
    break.  When passed to a shell:

    * **Windows** ``cmd.exe`` truncates the command at the first newline
      regardless of quoting context — this is a hard limitation of the
      Windows command processor.  All newlines must be collapsed.
    * **Unix** ``sh -c`` treats an unquoted newline as a command separator,
      but correctly handles newlines inside quoted strings.

    On Unix/macOS, newlines inside quoted strings are preserved so that
    downstream commands receive the correct multi-line content (e.g.
    ``--text "Hello\nWorld"``).  On Windows, all newlines are collapsed
    to ensure the command at least executes successfully.
    """
    if "\n" not in cmd:
        return cmd
    if sys.platform == "win32":
        # cmd.exe truncates at newlines regardless of quoting — must
        # collapse all to ensure the command executes at all.
        return cmd.replace("\r\n", " ").replace("\n", " ")
    return _collapse_newlines_outside_quotes(cmd)


def _sanitize_win_cmd(cmd: str) -> str:
    """Fix common LLM escaping artefacts for Windows ``cmd.exe``.

    LLMs sometimes produce commands with backslash-escaped double quotes
    (``\\"``) — valid in bash/JSON but meaningless to ``cmd.exe``.  When
    *every* double-quote in the command is preceded by a backslash, it is
    almost certainly a double-escape artefact, so we strip them.
    """
    if '\\"' in cmd and '"' not in cmd.replace('\\"', ""):
        return cmd.replace('\\"', '"')
    return cmd


def _read_temp_file(path: str) -> str:
    """Read a temporary output file and return its decoded content."""
    try:
        with open(path, "rb") as f:
            return smart_decode(f.read())
    except OSError:
        return ""


# pylint: disable=too-many-branches, too-many-statements
def _execute_subprocess_sync(
    cmd: str,
    cwd: str,
    timeout: float,
    env: dict | None = None,
) -> tuple[int, str, str]:
    """Execute subprocess synchronously in a thread.

    This function runs in a separate thread to avoid Windows asyncio
    subprocess limitations.

    stdout/stderr are redirected to temporary files instead of pipes.
    On Windows, child processes inherit pipe handles and keep them open
    even after the parent exits, which causes ``communicate()`` to block
    until *all* holders close (e.g. a Chrome process launched via
    ``Start-Process``).  With temp-file redirection, ``proc.wait()``
    only waits for the direct child (``cmd.exe``) to exit, so commands
    that spawn background processes return immediately.

    .. note::

       Callers must pre-process *cmd* through
       :func:`_collapse_embedded_newlines` before passing it here.
       ``execute_shell_command`` already does this.

    Args:
        cmd (`str`):
            The shell command to execute (must not contain embedded
            newlines — see note above).
        cwd (`str`):
            The working directory for the command execution.
        timeout (`float`):
            The maximum time (in seconds) allowed for the command to run.
        env (`dict | None`):
            Environment variables for the subprocess.

    Returns:
        `tuple[int, str, str]`:
            A tuple containing the return code, standard output, and
            standard error of the executed command. If timeout occurs, the
            return code will be -1 and stderr will contain timeout information.
    """
    stdout_path: str | None = None
    stderr_path: str | None = None
    stdout_file = None
    stderr_file = None

    try:
        cmd = _sanitize_win_cmd(cmd)
        wrapped = f'cmd /D /S /C "{cmd}"'

        stdout_fd, stdout_path = tempfile.mkstemp(prefix="coapis_out_")
        stderr_fd, stderr_path = tempfile.mkstemp(prefix="coapis_err_")
        stdout_file = os.fdopen(stdout_fd, "wb")
        stderr_file = os.fdopen(stderr_fd, "wb")

        proc = subprocess.Popen(  # pylint: disable=consider-using-with
            wrapped,
            shell=False,
            stdout=stdout_file,
            stderr=stderr_file,
            text=False,
            cwd=cwd,
            env=env,
            creationflags=subprocess.CREATE_NEW_PROCESS_GROUP,
        )

        # Parent copies are no longer needed — the child inherited its own
        # handles via CreateProcess.  Closing here avoids holding the files
        # open longer than necessary.
        stdout_file.close()
        stdout_file = None
        stderr_file.close()
        stderr_file = None

        timed_out = False
        try:
            proc.wait(timeout=timeout)
        except subprocess.TimeoutExpired:
            timed_out = True
            _kill_process_tree_win32(proc.pid)
            try:
                proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                try:
                    proc.kill()
                except OSError:
                    pass

        stdout_str = _read_temp_file(stdout_path)
        stderr_str = _read_temp_file(stderr_path)

        if timed_out:
            timeout_msg = (
                f"Command execution exceeded the timeout of {timeout} seconds."
            )
            if stderr_str:
                stderr_str = f"{stderr_str}\n{timeout_msg}"
            else:
                stderr_str = timeout_msg
            return -1, stdout_str, stderr_str

        returncode = proc.returncode if proc.returncode is not None else -1
        return returncode, stdout_str, stderr_str

    except Exception as e:
        return -1, "", str(e)
    finally:
        for f in (stdout_file, stderr_file):
            if f is not None:
                try:
                    f.close()
                except OSError:
                    pass
        for path in (stdout_path, stderr_path):
            if path is not None:
                try:
                    os.unlink(path)
                except OSError:
                    pass


# pylint: disable=too-many-branches, too-many-statements
async def execute_shell_command(
    command: str,
    timeout: float = 60.0,
    cwd: Optional[Path] = None,
) -> ToolResponse:
    """Execute a shell command and return its output.

    Platform shells: Windows uses cmd.exe; Linux/macOS use /bin/sh or /bin/bash.

    IMPORTANT: Always consider the operating system before choosing commands.

    Args:
        command (`str`):
            The shell command to execute.
        timeout (`float`, defaults to `60.0`):
            The maximum time (in seconds) allowed for the command to run.
            Default is 60.0 seconds.
        cwd (`Optional[Path]`, defaults to `None`):
            The working directory for the command execution.
            If None, defaults to WORKING_DIR.

    Returns:
        `ToolResponse`:
            The tool response containing the return code, standard output, and
            standard error of the executed command. If timeout occurs, the
            return code will be -1 and stderr will contain timeout information.
    """

    cmd = _collapse_embedded_newlines((command or "").strip())

    # ── WorkspaceGuard: shell command validation ──
    try:
        from ..security.workspace_guard import check_command
        check_command(cmd)
    except ValueError as e:
        return ToolResponse(
            content=[TextBlock(type="text", text=f"权限拒绝: {e}")],
        )

    if isinstance(timeout, str):
        try:
            timeout = float(timeout)
        except (ValueError, TypeError):
            timeout = 60.0

    # Apply agent-configured default when the caller used the hardcoded
    # default (60.0).  An explicit LLM-provided value != 60.0 is kept.
    if timeout == 60.0:
        configured = get_current_shell_command_timeout()
        if configured is not None:
            timeout = configured

    # Use current workspace_dir from context, fallback to WORKING_DIR
    if cwd is not None:
        working_dir = cwd
    else:
        working_dir = get_current_workspace_dir() or WORKING_DIR

    # Build filtered environment via ProcessIsolator (prevents leaking
    # HOME/USER/SHELL etc.) while keeping the venv python on PATH.
    try:
        from ...security.process_isolator import ProcessIsolator
        _isolator = ProcessIsolator(base_workspace=str(working_dir))
        env = _isolator._build_env()
    except Exception:
        # Fallback: manual filtering if ProcessIsolator unavailable
        _SAFE_KEYS = {"PATH", "LANG", "LC_ALL", "TERM"}
        env = {k: v for k, v in os.environ.items() if k in _SAFE_KEYS}

    python_bin_dir = str(Path(sys.executable).parent)
    existing_path = env.get("PATH", "")
    if existing_path:
        env["PATH"] = python_bin_dir + os.pathsep + existing_path
    else:
        env["PATH"] = python_bin_dir

    # ── ImportSandbox: static check for inline Python code ──
    # Scan python3 -c / node -e commands for dangerous module imports
    # using ImportSandbox's blocked module list (avoids monkey-patching).
    try:
        import re as _re
        from ...security.import_sandbox import DEFAULT_BLOCKED_MODULES
        _py_inline = _re.match(
            r"^(?:python3?|python)\s+-[ec]\s+[\"'](.*)[\"']$", cmd.strip()
        )
        if _py_inline:
            _code = _py_inline.group(1)
            # Check for import statements of blocked modules
            for _mod in DEFAULT_BLOCKED_MODULES:
                # Match: "import mod", "import mod,", "import mod;"
                #        "from mod import ..."
                if _re.search(
                    rf"(?:^|;\s*|&&\s*)import\s+{_mod}\s*(?:;|,|&&|$|\s)|"
                    rf"(?:^|;\s*|&&\s*)from\s+{_mod}\s+import\s+",
                    _code,
                    _re.MULTILINE,
                ):
                    return ToolResponse(
                        content=[TextBlock(
                            type="text",
                            text=(
                                f"安全拦截: 模块 '{_mod}' 被安全策略禁止导入。"
                                f"请联系管理员。"
                            ),
                        )],
                    )
    except Exception:
        pass

    # ── ASTSandbox: check inline Python code for dangerous patterns ──
    try:
        import re as _re_ast
        _py_inline2 = _re_ast.match(
            r"^(?:python3?|python)\s+-[ec]\s+[\"'](.*)[\"']$", cmd.strip()
        )
        if _py_inline2:
            from ...security.ast_sandbox import ASTSandbox
            _ast = ASTSandbox()
            _result = _ast.check_code(_py_inline2.group(1))
            if not _result.safe:
                return ToolResponse(
                    content=[TextBlock(
                        type="text",
                        text=(
                            f"安全拦截: Python代码包含危险结构。"
                            f"违规项: {'; '.join(_result.violations[:3])}"
                        ),
                    )],
                )
    except Exception:
        pass

    try:
        if sys.platform == "win32":
            # Windows: use thread pool to avoid asyncio subprocess limitations
            returncode, stdout_str, stderr_str = await asyncio.to_thread(
                _execute_subprocess_sync,
                cmd,
                str(working_dir),
                timeout,
                env,
            )
        else:
            # Apply resource limits via preexec_fn (Linux kernel-enforced)
            _preexec_fn = None
            try:
                from ...security.resource_limiter import ResourceLimiter, HAS_RESOURCE
                if HAS_RESOURCE:
                    _rl = ResourceLimiter()
                    _preexec_fn = _rl._set_unix_limits
            except Exception:
                pass

            # Optional: file system namespace isolation via unshare(CLONE_NEWNS)
            # When COAPIS_ENABLE_NS=1, the command runs in its own mount
            # namespace with the working directory writable and / read-only.
            _ns_enabled = os.environ.get("COAPIS_ENABLE_NS", "0") == "1"
            if _ns_enabled:
                _ns_fn = _make_ns_preexec(str(working_dir), _preexec_fn)
                _preexec_fn = _ns_fn

            proc = await asyncio.create_subprocess_shell(
                cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                bufsize=0,
                cwd=str(working_dir),
                env=env,
                start_new_session=True,
                preexec_fn=_preexec_fn,
            )

            try:
                # Apply timeout to communicate directly; wait()+communicate()
                # can hang if descendants keep stdout/stderr pipes open.
                stdout, stderr = await asyncio.wait_for(
                    proc.communicate(),
                    timeout=timeout,
                )
                stdout_str = smart_decode(stdout)
                stderr_str = smart_decode(stderr)
                returncode = proc.returncode

            except asyncio.TimeoutError:
                stderr_suffix = (
                    f"⚠️ TimeoutError: The command execution exceeded "
                    f"the timeout of {timeout} seconds. "
                    f"Please consider increasing the timeout value if this command "
                    f"requires more time to complete."
                )
                returncode = -1
                try:
                    # Kill the entire process group so that child processes
                    # spawned by the shell are also terminated.
                    pgid = os.getpgid(proc.pid)
                    os.killpg(pgid, signal.SIGTERM)
                    try:
                        await asyncio.wait_for(proc.wait(), timeout=2)
                    except asyncio.TimeoutError:
                        os.killpg(pgid, signal.SIGKILL)
                        await asyncio.wait_for(proc.wait(), timeout=2)

                    # Drain remaining output.
                    try:
                        stdout, stderr = await asyncio.wait_for(
                            proc.communicate(),
                            timeout=1,
                        )
                    except asyncio.TimeoutError:
                        stdout, stderr = b"", b""
                    stdout_str = smart_decode(stdout)
                    stderr_str = smart_decode(stderr)
                    if stderr_str:
                        stderr_str += f"\n{stderr_suffix}"
                    else:
                        stderr_str = stderr_suffix
                except (ProcessLookupError, OSError):
                    # Process already gone or pgid lookup failed — fall back
                    # to direct kill on the process itself.
                    try:
                        proc.kill()
                        await proc.wait()
                    except (ProcessLookupError, OSError):
                        pass
                    stdout_str = ""
                    stderr_str = stderr_suffix

        if returncode == 0:
            if stdout_str:
                response_text = stdout_str
            else:
                response_text = "Command executed successfully (no output)."
            if stderr_str:
                response_text += f"\n[stderr]\n{stderr_str}"
        else:
            response_parts = [f"Command failed with exit code {returncode}."]
            if stdout_str:
                response_parts.append(f"\n[stdout]\n{stdout_str}")
            if stderr_str:
                response_parts.append(f"\n[stderr]\n{stderr_str}")
            response_text = "".join(response_parts)

        return ToolResponse(
            content=[
                TextBlock(
                    type="text",
                    text=response_text,
                ),
            ],
        )

    except Exception as e:
        return ToolResponse(
            content=[
                TextBlock(
                    type="text",
                    text=f"Error: Shell command execution failed due to \n{e}",
                ),
            ],
        )


def smart_decode(data: bytes) -> str:
    try:
        decoded_str = data.decode("utf-8")
    except UnicodeDecodeError:
        encoding = locale.getpreferredencoding(False) or "utf-8"
        decoded_str = data.decode(encoding, errors="replace")

    return decoded_str.strip("\n")
