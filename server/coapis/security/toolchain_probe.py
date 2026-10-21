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
"""Toolchain probe - self-check for the sandboxed node/python tool chain.

Why this exists: the sandbox applies ``RLIMIT_AS`` (virtual address space) to
every child process, and V8 reserves far more virtual space than it touches.
A 512 MB cap made ``node`` abort at startup ("Cannot allocate a 536870912
byte reservation") so the pptx skill reported "node environment not
supported" while the container in fact had node v22 and pptxgenjs installed -
and the failure was invisible to ``/health``.

The probe therefore does not ask "is node on PATH"; it runs node **under the
same resource limits the real tools use**, which is the only check that
catches this class of problem.
"""

from __future__ import annotations

import logging
import shutil
import subprocess
import sys
import tempfile
import threading
import time
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)

_PROBE_TTL_SECONDS = 60.0
_PROBE_TIMEOUT_SECONDS = 25

_lock = threading.Lock()
_cache: Dict[str, Any] = {}
_cache_at: float = 0.0

# Minimal pptxgenjs workload: proves node starts, V8 allocates, the global
# pptxgenjs package resolves, and a real .pptx lands on disk.
_PPTX_SNIPPET = """
const pptxgen = require('pptxgenjs');
const pres = new pptxgen();
pres.defineLayout({ name: 'A4', width: 8.27, height: 11.69 });
pres.layout = 'A4';
pres.addSlide().addText('toolchain probe', { x: 0.5, y: 0.5, w: 7, h: 1, fontSize: 24 });
pres.writeFile('%(out)s').then(() => {
  console.log('OK size=' + require('fs').statSync('%(out)s').size);
  process.exit(0);
}).catch((e) => { console.log('ERR ' + e.message); process.exit(1); });
"""


def _sandbox_limits() -> Any:
    """The exact preexec_fn the real sandbox tools install.

    Imported lazily so the probe degrades gracefully when the tool layer is
    unavailable, and never crashes the health endpoint.
    """
    try:
        from coapis.agents.tools.code_exec import _set_child_resource_limits

        return _set_child_resource_limits
    except Exception:  # noqa: BLE001 - probe must never break health
        return None


def _run(cmd: list, preexec_fn: Any = None, timeout: int = 10) -> Dict[str, Any]:
    try:
        proc = subprocess.run(
            cmd, capture_output=True, text=True, preexec_fn=preexec_fn,
            timeout=timeout, cwd=tempfile.gettempdir(),
        )
        out = (proc.stdout + "\n" + proc.stderr).strip()
        return {
            "ok": proc.returncode == 0,
            "rc": proc.returncode,
            "output": out[-400:],
        }
    except FileNotFoundError as exc:
        return {"ok": False, "rc": -1, "output": "not found: %s" % exc}
    except subprocess.TimeoutExpired:
        return {"ok": False, "rc": -1, "output": "timeout after %ss" % timeout}
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "rc": -1, "output": "%s: %s" % (type(exc).__name__, exc)}


def probe_toolchain(force: bool = False) -> Dict[str, Any]:
    """Run (or return cached) toolchain self-check.

    Runs blocking subprocesses - call from a thread executor, not the event loop.
    """
    global _cache, _cache_at
    now = time.time()
    with _lock:
        if not force and _cache and (now - _cache_at) < _PROBE_TTL_SECONDS:
            return dict(_cache, cached=True)

    from coapis.security.resource_limiter import sandbox_mem_mb

    preexec_fn = _sandbox_limits()
    result: Dict[str, Any] = {
        "cached": False,
        "sandbox_mem_mb": sandbox_mem_mb(),
        "sandbox_mem_unlimited": sandbox_mem_mb() == 0,
        "python": sys.version.split()[0],
    }

    node_path = shutil.which("node")
    result["node_path"] = node_path
    if not node_path:
        result["status"] = "error"
        result["reason"] = "node not on PATH"
    else:
        ver = _run([node_path, "-v"])
        result["node_version"] = ver["output"].strip()
        # The decisive check: node under the real sandbox limits.
        with tempfile.NamedTemporaryFile(suffix=".pptx", delete=False) as fh:
            out_path = fh.name
        snippet = _PPTX_SNIPPET % {"out": out_path}
        script = "%s/probe_pptx.js" % tempfile.gettempdir()
        try:
            with open(script, "w", encoding="utf-8") as fh:
                fh.write(snippet)
            sandbox_run = _run(
                [node_path, script], preexec_fn=preexec_fn,
                timeout=_PROBE_TIMEOUT_SECONDS,
            )
        except Exception as exc:  # noqa: BLE001
            sandbox_run = {"ok": False, "rc": -1, "output": str(exc)}
        finally:
            for path in (out_path, script):
                try:
                    import os

                    os.unlink(path)
                except OSError:
                    pass
        result["pptx_under_sandbox"] = sandbox_run
        result["status"] = "ok" if sandbox_run["ok"] else "degraded"
        if not sandbox_run["ok"]:
            result["reason"] = (
                "node exists but fails under sandbox RLIMIT_AS=%s - raise "
                "COAPIS_SANDBOX_MEM_MB or set 0 for unlimited"
                % ("unlimited" if result["sandbox_mem_unlimited"]
                   else result["sandbox_mem_mb"])
            )

    npm_path = shutil.which("npm")
    result["npm_path"] = npm_path
    if npm_path:
        pkgs = _run([npm_path, "ls", "-g", "--depth=0"], timeout=20)
        result["npm_global_packages"] = pkgs["output"][-600:]
        result["pptxgenjs_installed"] = "pptxgenjs" in pkgs["output"]

    with _lock:
        _cache = dict(result)
        _cache_at = time.time()
        result["cached_at"] = _cache_at
    logger.info(
        "toolchain probe: node=%s sandbox_mem_mb=%s pptx_ok=%s",
        result.get("node_version"), result.get("sandbox_mem_mb"),
        (result.get("pptx_under_sandbox") or {}).get("ok"),
    )
    return result


def get_toolchain_status(max_age: Optional[float] = None) -> Dict[str, Any]:
    """Return the last probe result without running anything (cheap)."""
    with _lock:
        if not _cache:
            return {"status": "unknown", "reason": "probe not run yet"}
        age = time.time() - _cache_at
        if max_age is not None and age > max_age:
            return dict(_cache, stale=True, age_seconds=round(age, 1))
        return dict(_cache, age_seconds=round(age, 1))
