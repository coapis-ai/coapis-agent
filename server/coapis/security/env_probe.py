# -*- coding: utf-8 -*-
"""B5-C · 沙箱环境探测（内核 / user namespace / bwrap 能力）。

沙箱能不能用不是"配了就行"，它取决于**这台机器**：内核是否放开非特权
user namespace、AppArmor 有没有把非特权 userns 锁掉、bwrap 装没装。
这些只能**实测**，猜出来的结论会直接决定一次隔离是真隔离还是假隔离。

设计：

* 探测 = 静态读（内核参数 / 可执行文件）+ **一次真实自测**（起一个最小
  bwrap 沙箱跑 ``/bin/true``，并验网络阻断是否生效）。
* 结果进程内缓存（探测要起子进程，热路径不能每次都探），TTL 由
  ``COAPIS_SANDBOX_PROBE_TTL``（秒，默认 300）控制。
* 报告落盘到 ``COAPIS_SANDBOX_PROBE_FILE``
  （默认 ``AUDIT_LOG_DIR/sandbox_probe.json``）供治理侧只读查看。
* 任何一步失败都不抛异常 —— 探测的产物是**结论**，不是异常。

⚠️ 判定纪律：``usable`` 只有在**真跑通** bwrap 自测后才为 True；
只看文件存在（``which bwrap``）不算可用。
"""

from __future__ import annotations

import json
import logging
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

__all__ = ["probe", "sandbox_probe_path", "read_probe_report"]

_ENV_TTL = "COAPIS_SANDBOX_PROBE_TTL"
_ENV_FILE = "COAPIS_SANDBOX_PROBE_FILE"

_CACHE: dict[str, Any] = {}
_CACHE_AT: float = 0.0


def _ttl() -> float:
    raw = (os.environ.get(_ENV_TTL) or "").strip()
    if not raw:
        return 300.0
    try:
        val = float(raw)
    except ValueError:
        return 300.0
    return max(0.0, val)


def sandbox_probe_path() -> Path:
    """探测报告的落盘位置（治理侧只读）。"""
    raw = (os.environ.get(_ENV_FILE) or "").strip()
    if raw:
        return Path(raw).expanduser()
    from ..constant import AUDIT_LOG_DIR

    return Path(AUDIT_LOG_DIR) / "sandbox_probe.json"


def read_probe_report() -> dict[str, Any] | None:
    """读上一次落盘的探测报告；没有/坏了返回 None。"""
    try:
        data = json.loads(sandbox_probe_path().read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return None
    return data if isinstance(data, dict) else None


# ── 静态部分 ──────────────────────────────────────────────────────


def _read_int(path: str) -> int | None:
    try:
        return int(Path(path).read_text(encoding="utf-8").strip())
    except (OSError, ValueError):
        return None


def _read_str(path: str) -> str | None:
    try:
        return Path(path).read_text(encoding="utf-8").strip()
    except OSError:
        return None


def _bwrap_version(bwrap: str) -> str | None:
    try:
        out = subprocess.run(
            [bwrap, "--version"],
            capture_output=True,
            text=True,
            timeout=5,
            check=False,
        )
        text = (out.stdout or "") + (out.stderr or "")
        return text.strip().splitlines()[0] if text.strip() else None
    except (OSError, subprocess.SubprocessError):
        return None


def _static_facts() -> dict[str, Any]:
    bwrap = shutil.which("bwrap")
    facts: dict[str, Any] = {
        "os": os.name,
        "python": sys.version.split()[0],
        "kernel": None,
        "bwrap_path": bwrap,
        "bwrap_version": _bwrap_version(bwrap) if bwrap else None,
        "userns_max": _read_int("/proc/sys/user/max_user_namespaces"),
        "unprivileged_userns_clone": _read_str("/proc/sys/kernel/unprivileged_userns_clone"),
        "apparmor_restrict_unprivileged_userns": _read_str(
            "/proc/sys/kernel/apparmor_restrict_unprivileged_userns",
        ),
    }
    try:
        facts["kernel"] = os.uname().release
    except AttributeError:  # 非 POSIX
        pass
    return facts


# ── 实测部分 ──────────────────────────────────────────────────────


def _live_test(facts: dict[str, Any]) -> dict[str, Any]:
    """真起一个最小沙箱跑通才算数。"""
    bwrap = facts.get("bwrap_path")
    if not bwrap:
        return {"ran": False, "ok": False, "msg": "bwrap 未安装"}
    if os.name != "posix":
        return {"ran": False, "ok": False, "msg": "非 POSIX 平台，bwrap 不适用"}

    base = [
        bwrap,
        "--ro-bind",
        "/",
        "/",
        "--dev",
        "/dev",
        "--proc",
        "/proc",
        "--tmpfs",
        "/tmp",
        "--unshare-all",
    ]
    try:
        run = subprocess.run(
            base + ["--share-net", "--", "/bin/sh", "-c", "echo bwrap-ok"],
            capture_output=True,
            text=True,
            timeout=20,
            check=False,
        )
        ok = run.returncode == 0 and "bwrap-ok" in (run.stdout or "")
        msg = "" if ok else (run.stderr or run.stdout or "").strip()[:400]
    except (OSError, subprocess.SubprocessError) as exc:
        return {"ran": True, "ok": False, "msg": f"自测异常: {exc}"}

    net_blocked_ok: bool | None = None
    if ok:
        # 网络阻断是否真生效（有网才测；测不通不判死，只记录）
        try:
            blocked = subprocess.run(
                base + ["--", "/bin/sh", "-c", "getent hosts example.com >/dev/null 2>&1"],
                capture_output=True,
                text=True,
                timeout=20,
                check=False,
            )
            net_blocked_ok = blocked.returncode != 0
        except (OSError, subprocess.SubprocessError):
            net_blocked_ok = None

    return {
        "ran": True,
        "ok": ok,
        "net_blocked_ok": net_blocked_ok,
        "msg": msg or None,
    }


def _reason(facts: dict[str, Any], live: dict[str, Any]) -> str:
    if not facts.get("bwrap_path"):
        return "未安装 bwrap"
    if not live.get("ran"):
        return str(live.get("msg") or "自测未执行")
    if not live.get("ok"):
        return f"bwrap 自测失败: {live.get('msg') or '未知原因'}"
    return "bwrap 自测通过"


def probe(*, force: bool = False, persist: bool = True) -> dict[str, Any]:
    """探测沙箱能力（进程内缓存）。

    ``force=True`` 忽略缓存重探；``persist=False`` 不落盘（单测用）。
    """
    global _CACHE, _CACHE_AT
    now = time.time()
    ttl = _ttl()
    if _CACHE and not force and (now - _CACHE_AT) <= ttl:
        return dict(_CACHE)

    facts = _static_facts()
    live = _live_test(facts)
    usable = bool(live.get("ok"))
    report = {
        "ts": now,
        "usable": usable,
        "reason": _reason(facts, live),
        "facts": facts,
        "live_test": live,
    }
    _CACHE = dict(report)
    _CACHE_AT = now

    if persist:
        try:
            path = sandbox_probe_path()
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(
                json.dumps(report, ensure_ascii=False, indent=2, default=str),
                encoding="utf-8",
            )
        except OSError as exc:
            logger.warning("governance: 沙箱探测报告落盘失败: %s", exc)

    return dict(report)


def reset_probe_cache() -> None:
    """清空进程内缓存（测试与运维改环境后用）。"""
    global _CACHE, _CACHE_AT
    _CACHE = {}
    _CACHE_AT = 0.0
