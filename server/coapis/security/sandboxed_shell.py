# -*- coding: utf-8 -*-
"""B5-C · 用 bwrap 把 shell 工具真正关进沙箱（默认关，开关才生效）。

现状（实测）：所谓的"沙箱"是**逻辑沙箱** —— 白名单 + 路径前缀检查 +
RLIMIT 资源限制，**没有任何隔离边界**。一次 ``rm -rf`` 只要路径写在对
的树下就能穿透；网络对生产服务全开。

本模块提供真正的隔离包装：``bwrap --ro-bind / /`` 把整盘挂成只读，
只把工作区/临时目录声明为可写，默认断开网络命名空间。

三档开关（``COAPIS_SANDBOX_MODE``，**默认 off = 现状零变化**）：

``off``
    直跑，不探测、不包装 —— 与今天逐字节一致。
``auto``
    探测通过 → 沙箱内跑；探测不通过 → **降级直跑** + 写一条
    ``kind=sandbox_denied`` 审计事件说明"这台机器封不住"。
``strict``
    探测通过 → 沙箱内跑；探测不通过 → **拒绝执行**，把拒绝理由还给用户。

可写边界（其余全部只读）：

* ``cwd`` 与其所属的用户工作区（``WORKSPACES_DIR/<user>``）
* ``/tmp`` 与 ``tempfile.gettempdir()``
* ``COAPIS_SANDBOX_WRITABLE`` 里冒号分隔的额外目录（运维显式授权）

网络（``COAPIS_SANDBOX_NET``，默认 ``allow`` —— 与现状一致，不新增破坏）：
``allow`` 共享网络栈；``block`` 断网（``--unshare-all`` 已含网络命名空间）。

⚠️ 判定纪律：能不能包只看 :mod:`env_probe` 的**实测**结果，不看配置。
"""

from __future__ import annotations

import json
import logging
import os
import shlex
import shutil
import tempfile
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable, Sequence

from .env_probe import probe

logger = logging.getLogger(__name__)

__all__ = [
    "SandboxPlan",
    "sandbox_mode",
    "sandbox_net_mode",
    "writable_roots",
    "build_argv",
    "plan_command",
    "audit_sandbox_event",
]

_ENV_MODE = "COAPIS_SANDBOX_MODE"
_ENV_NET = "COAPIS_SANDBOX_NET"
_ENV_EXTRA_WRITABLE = "COAPIS_SANDBOX_WRITABLE"

_VALID_MODES = ("off", "auto", "strict")
_VALID_NETS = ("allow", "block")

#: 沙箱内跑什么：把整条命令交给 /bin/sh -c，语义与 create_subprocess_shell 一致
_SHELL = "/bin/sh"


def sandbox_mode() -> str:
    """读取沙箱档位（**每次调用都读 env**，支持热开关）。"""
    raw = (os.environ.get(_ENV_MODE) or "").strip().lower()
    return raw if raw in _VALID_MODES else "off"


def sandbox_net_mode() -> str:
    """网络档位：默认 allow（不改变现状），block 才断网。"""
    raw = (os.environ.get(_ENV_NET) or "").strip().lower()
    return raw if raw in _VALID_NETS else "allow"


def _extra_writable() -> list[Path]:
    raw = (os.environ.get(_ENV_EXTRA_WRITABLE) or "").strip()
    if not raw:
        return []
    out = []
    for chunk in raw.split(":"):
        chunk = chunk.strip()
        if chunk:
            out.append(Path(chunk).expanduser())
    return out


def writable_roots(
    cwd: "str | os.PathLike[str] | None" = None,
    *,
    username: str | None = None,
    extra: Iterable["str | os.PathLike[str]"] = (),
) -> list[Path]:
    """沙箱内可写的目录集合（其余全部只读）。

    只收**存在**的目录 —— bwrap 对缺失的 bind 源会直接失败。
    """
    roots: list[Path] = []

    def _add(p: "str | os.PathLike[str] | None") -> None:
        if not p:
            return
        try:
            rp = Path(p).expanduser().resolve()
        except (OSError, RuntimeError):
            return
        if not rp.exists():
            return
        if rp not in roots:
            roots.append(rp)

    _add(cwd)
    _add(Path(tempfile.gettempdir()))
    _add(Path("/tmp"))
    if username:
        try:
            from ..constant import WORKSPACES_DIR

            _add(Path(WORKSPACES_DIR) / username)
        except Exception:  # pragma: no cover
            pass
    for p in extra:
        _add(p)
    for p in _extra_writable():
        _add(p)
    return roots


@dataclass
class SandboxPlan:
    """一次命令的执行计划。"""

    mode: str
    use_sandbox: bool
    argv: list[str]
    reason: str
    degraded: bool = False
    net: str = "allow"
    writable: list[Path] = field(default_factory=list)

    def to_meta(self) -> dict[str, Any]:
        return {
            "mode": self.mode,
            "sandboxed": self.use_sandbox,
            "degraded": self.degraded,
            "net": self.net,
            "reason": self.reason,
            "writable": [str(p) for p in self.writable],
        }


def build_argv(
    cmd: str,
    *,
    cwd: "str | os.PathLike[str] | None" = None,
    writable: Sequence[Path] | None = None,
    net: str = "allow",
    bwrap: str | None = None,
) -> list[str]:
    """构造 bwrap 命令行（``--`` 之后是 ``/bin/sh -c <cmd>``）。"""
    bwrap = bwrap or shutil.which("bwrap") or "bwrap"
    roots = list(writable if writable is not None else writable_roots(cwd))

    argv: list[str] = [bwrap]
    # 整盘只读打底
    argv += ["--ro-bind", "/", "/"]
    argv += ["--dev", "/dev", "--proc", "/proc", "--tmpfs", "/tmp"]
    for root in roots:
        argv += ["--bind", str(root), str(root)]
    # 断掉所有命名空间（含网络），再按需把网络放回来
    argv += ["--unshare-all"]
    if net == "allow":
        argv += ["--share-net"]
    argv += ["--die-with-parent", "--", _SHELL, "-c", cmd]
    return argv


def plan_command(
    cmd: str,
    cwd: "str | os.PathLike[str] | None" = None,
    *,
    username: str | None = None,
    extra_writable: Iterable["str | os.PathLike[str]"] = (),
) -> SandboxPlan:
    """给出这条命令该怎么跑（沙箱 / 直跑 / 拒绝）。"""
    mode = sandbox_mode()
    net = sandbox_net_mode()
    roots = writable_roots(cwd, username=username, extra=extra_writable)

    if mode == "off":
        return SandboxPlan(
            mode=mode,
            use_sandbox=False,
            argv=[_SHELL, "-c", cmd],
            reason="沙箱开关为 off（现状直跑）",
            net=net,
            writable=roots,
        )

    report = probe()
    if not report.get("usable"):
        why = str(report.get("reason") or "沙箱能力探测未通过")
        if mode == "strict":
            return SandboxPlan(
                mode=mode,
                use_sandbox=False,
                argv=[],
                reason=f"strict 模式下拒绝直跑：{why}",
                degraded=True,
                net=net,
                writable=roots,
            )
        return SandboxPlan(
            mode=mode,
            use_sandbox=False,
            argv=[_SHELL, "-c", cmd],
            reason=f"探测未通过，降级直跑：{why}",
            degraded=True,
            net=net,
            writable=roots,
        )

    return SandboxPlan(
        mode=mode,
        use_sandbox=True,
        argv=build_argv(cmd, cwd=cwd, writable=roots, net=net),
        reason="bwrap 自测通过，命令在沙箱内执行",
        net=net,
        writable=roots,
    )


def audit_sandbox_event(
    plan: SandboxPlan,
    *,
    username: str | None,
    command: str,
    session_id: str | None = None,
) -> None:
    """把沙箱侧的治理事件写进既有审计链（失败只告警，不影响执行）。

    只在**非默认路径**上写：降级直跑、strict 拒绝、以及沙箱内执行时
    的 net=block —— 这些都是治理要看的行为；off 模式零事件（热路径安静）。
    """
    if plan.mode == "off":
        return
    if not (plan.degraded or plan.net == "block" or plan.use_sandbox):
        return

    try:
        from ..agents.security.audit_logger import AuditLogger, create_audit_event
    except Exception as exc:  # pragma: no cover
        logger.debug("governance: 沙箱审计不可用: %s", exc)
        return

    kind = "sandbox_denied" if plan.degraded else "sandbox"
    event = create_audit_event(
        category="authorizations",
        event_type="sandbox",
        user_id=username or "unknown",
        resource="shell",
        result="degraded_direct" if plan.degraded else "sandboxed",
        risk_level="medium" if plan.degraded else "info",
        metadata={
            "kind": kind,
            "session_id": session_id,
            "command_preview": (command or "")[:200],
            **plan.to_meta(),
        },
    )
    try:
        AuditLogger().log_event(event)
    except Exception as exc:  # pragma: no cover
        logger.warning("governance: 沙箱审计写入失败: %s", exc)


def refusal_message(plan: SandboxPlan) -> str:
    """strict 模式拒绝执行时给用户的回执。"""
    return (
        f"命令未执行（沙箱 strict 模式）：{plan.reason}\n"
        "沙箱不可用时不允许直跑；可用 COAPIS_SANDBOX_MODE=auto 降级，"
        "或 =off 关闭沙箱。"
    )
