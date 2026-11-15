"""B5-C bwrap 沙箱 —— 档位、包装、降级与真实隔离实测。

纪律：
* 默认 **off**，off 时 argv 就是 ``/bin/sh -c cmd`` 且**不许探测**；
* 能不能包只认 :mod:`coapis.security.env_probe` 的**实测**结果；
* auto 探不过 → 降级直跑并留审计；strict 探不过 → 拒绝执行；
* 真隔离测试只在装了 bwrap 的机器上跑（`pytest.mark.skipif`），
  写的边界是「工作区可写、工作区外只读」，用真实命令验证。
"""

from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

import pytest
from coapis.security import env_probe, sandboxed_shell
from coapis.security.sandboxed_shell import (
    SandboxPlan,
    audit_sandbox_event,
    build_argv,
    plan_command,
    refusal_message,
    sandbox_mode,
    sandbox_net_mode,
    writable_roots,
)

HAS_BWRAP = shutil.which("bwrap") is not None


@pytest.fixture(autouse=True)
def _clean(monkeypatch):
    """每个用例都从干净档位开始，并清掉探测缓存。"""
    monkeypatch.delenv("COAPIS_SANDBOX_MODE", raising=False)
    monkeypatch.delenv("COAPIS_SANDBOX_NET", raising=False)
    monkeypatch.delenv("COAPIS_SANDBOX_WRITABLE", raising=False)
    monkeypatch.delenv("COAPIS_SANDBOX_PROBE_FILE", raising=False)
    env_probe.reset_probe_cache()
    yield
    env_probe.reset_probe_cache()


# --------------------------------------------------------------------------- #
# 档位读取
# --------------------------------------------------------------------------- #


def test_mode_defaults_off(monkeypatch):
    assert sandbox_mode() == "off"
    for raw in ("", "  ", "nonsense", "TRUE-ish"):
        monkeypatch.setenv("COAPIS_SANDBOX_MODE", raw)
        assert sandbox_mode() == "off", raw
    for raw in ("off", "auto", "strict", "AUTO", " Strict "):
        monkeypatch.setenv("COAPIS_SANDBOX_MODE", raw)
        assert sandbox_mode() == raw.strip().lower(), raw


def test_net_defaults_allow(monkeypatch):
    assert sandbox_net_mode() == "allow"
    monkeypatch.setenv("COAPIS_SANDBOX_NET", "block")
    assert sandbox_net_mode() == "block"
    monkeypatch.setenv("COAPIS_SANDBOX_NET", "wat")
    assert sandbox_net_mode() == "allow"


# --------------------------------------------------------------------------- #
# off：与现状逐字节一致，且零探测
# --------------------------------------------------------------------------- #


def test_off_mode_does_not_probe_and_runs_direct(monkeypatch, tmp_path):
    def _boom(*a, **kw):
        raise AssertionError("off 模式不许探测")

    monkeypatch.setattr(sandboxed_shell, "probe", _boom)

    plan = plan_command("echo hi", tmp_path)
    assert plan.mode == "off"
    assert plan.use_sandbox is False
    assert plan.degraded is False
    assert plan.argv == ["/bin/sh", "-c", "echo hi"]


# --------------------------------------------------------------------------- #
# auto / strict 的降级与拒绝
# --------------------------------------------------------------------------- #


def _unusable(monkeypatch):
    monkeypatch.setattr(
        sandboxed_shell,
        "probe",
        lambda *a, **kw: {"usable": False, "reason": "这台机器封不住（自测失败）"},
    )


def test_auto_degrades_to_direct_with_audit_trail(monkeypatch, tmp_path):
    _unusable(monkeypatch)
    monkeypatch.setenv("COAPIS_SANDBOX_MODE", "auto")

    plan = plan_command("echo hi", tmp_path)
    assert plan.use_sandbox is False
    assert plan.degraded is True
    assert plan.argv == ["/bin/sh", "-c", "echo hi"]
    assert "封不住" in plan.reason


def test_auto_degraded_is_auditable(monkeypatch, tmp_path):
    """降级不是静默放行：plan 里必须带得出治理所需的元数据。"""
    _unusable(monkeypatch)
    monkeypatch.setenv("COAPIS_SANDBOX_MODE", "auto")

    plan = plan_command("echo hi", tmp_path)
    meta = plan.to_meta()
    assert meta["degraded"] is True
    assert meta["mode"] == "auto"
    assert meta["sandboxed"] is False
    assert "封不住" in meta["reason"]


def test_strict_refuses_when_probe_fails(monkeypatch, tmp_path):
    _unusable(monkeypatch)
    monkeypatch.setenv("COAPIS_SANDBOX_MODE", "strict")

    plan = plan_command("echo hi", tmp_path)
    assert plan.use_sandbox is False
    assert plan.degraded is True
    assert plan.argv == []  # 空 argv = 什么都不许跑
    msg = refusal_message(plan)
    assert "未执行" in msg and "strict" in msg and "封不住" in msg


# --------------------------------------------------------------------------- #
# 包装构造
# --------------------------------------------------------------------------- #


def test_build_argv_shape(monkeypatch, tmp_path):
    writable = writable_roots(tmp_path)
    argv = build_argv("echo hi", cwd=tmp_path, writable=writable, net="allow")

    assert Path(argv[0]).name == "bwrap"
    assert argv[1:4] == ["--ro-bind", "/", "/"]  # 整盘只读打底
    assert "--dev" in argv and "/dev" in argv
    assert "--proc" in argv and "--tmpfs" in argv
    assert "--unshare-all" in argv
    assert "--share-net" in argv
    assert argv[-4:] == ["--", "/bin/sh", "-c", "echo hi"]
    # 每个可写根都以 --bind <root> <root> 的形式出现
    for root in writable:
        target = str(root)
        binds = [i for i, a in enumerate(argv) if a == "--bind"]
        assert any(argv[i + 1] == target and argv[i + 2] == target for i in binds), root


def test_build_argv_block_net_drops_share_net(tmp_path):
    argv = build_argv("echo hi", cwd=tmp_path, writable=[tmp_path], net="block")
    assert "--share-net" not in argv
    assert "--unshare-all" in argv


def test_plan_uses_sandbox_when_probe_usable(monkeypatch, tmp_path):
    monkeypatch.setenv("COAPIS_SANDBOX_MODE", "auto")
    monkeypatch.setattr(sandboxed_shell, "probe", lambda *a, **kw: {"usable": True, "reason": "ok"})

    plan = plan_command("echo hi", tmp_path)
    assert plan.use_sandbox is True
    assert plan.degraded is False
    assert Path(plan.argv[0]).name == "bwrap"
    assert plan.argv[-3:] == ["/bin/sh", "-c", "echo hi"]


def test_writable_roots_contents(tmp_path, monkeypatch):
    """可写集合 = cwd + 临时目录 + 已存在的额外授权目录；不存在的目录不收。"""
    extra = tmp_path / "extra"
    extra.mkdir()
    monkeypatch.setenv("COAPIS_SANDBOX_WRITABLE", str(extra))

    roots = writable_roots(tmp_path)
    assert tmp_path.resolve() in roots
    assert extra.resolve() in roots
    assert Path("/tmp") in roots

    missing = writable_roots(tmp_path / "does-not-exist")
    assert tmp_path / "does-not-exist" not in missing
    assert extra.resolve() in missing


# --------------------------------------------------------------------------- #
# 审计事件
# --------------------------------------------------------------------------- #


def test_audit_skips_off_mode(monkeypatch, tmp_path):
    calls = []

    class _Logger:
        def log_event(self, ev):
            calls.append(ev)

    import sys
    import types

    mod = types.ModuleType("coapis.agents.security.audit_logger")

    def create_audit_event(**kw):
        return kw

    mod.AuditLogger = lambda: _Logger()
    mod.create_audit_event = create_audit_event
    monkeypatch.setitem(sys.modules, "coapis.agents.security.audit_logger", mod)

    plan = plan_command("echo hi", tmp_path)  # off
    audit_sandbox_event(plan, username="bob", command="echo hi")
    assert calls == []

    _unusable(monkeypatch)
    monkeypatch.setenv("COAPIS_SANDBOX_MODE", "auto")
    plan = plan_command("echo hi", tmp_path)
    audit_sandbox_event(plan, username="bob", command="echo hi")
    assert len(calls) == 1
    meta = calls[0]["metadata"]
    assert meta["kind"] == "sandbox_denied"
    assert meta["degraded"] is True
    assert meta["mode"] == "auto"


# --------------------------------------------------------------------------- #
# env_probe
# --------------------------------------------------------------------------- #


def test_probe_persist_and_read_report(tmp_path, monkeypatch):
    monkeypatch.setenv("COAPIS_SANDBOX_PROBE_FILE", str(tmp_path / "probe.json"))

    report = env_probe.probe(force=True, persist=True)
    assert report["facts"]["bwrap_path"] == shutil.which("bwrap")
    assert isinstance(report["usable"], bool)
    assert report["reason"]

    saved = env_probe.read_probe_report()
    assert saved is not None
    assert saved["usable"] == report["usable"]
    assert saved["reason"] == report["reason"]

    # 缓存生效：改环境变量不影响已缓存结论
    monkeypatch.setenv("COAPIS_SANDBOX_PROBE_FILE", str(tmp_path / "other.json"))
    again = env_probe.probe()
    assert again["ts"] == report["ts"]


def test_probe_survives_static_read_failure(monkeypatch, tmp_path):
    monkeypatch.setattr(env_probe, "_static_facts", lambda: {"bwrap_path": None})
    monkeypatch.setenv("COAPIS_SANDBOX_PROBE_FILE", str(tmp_path / "p.json"))
    report = env_probe.probe(force=True, persist=False)
    assert report["usable"] is False
    assert "bwrap" in report["reason"]


def test_probe_live_test_failure_marks_unusable(monkeypatch, tmp_path):
    class _R:
        returncode = 1
        stdout = ""
        stderr = "bwrap: Failed to make setuid: Operation not permitted"

    monkeypatch.setattr(
        env_probe.subprocess,
        "run",
        lambda *a, **kw: _R(),
    )
    monkeypatch.setattr(env_probe.shutil, "which", lambda _: "/usr/bin/bwrap")
    report = env_probe.probe(force=True, persist=False)
    assert report["usable"] is False
    assert report["live_test"]["ran"] is True
    assert "Failed to make setuid" in report["reason"]


# --------------------------------------------------------------------------- #
# 真实隔离实测（装了 bwrap 才跑）
# --------------------------------------------------------------------------- #


@pytest.mark.skipif(not HAS_BWRAP, reason="本机没装 bwrap")
def test_real_sandbox_writes_inside_workspace_only(tmp_path):
    """工作区内可写、工作区外只读、断网 —— 用真命令验，不看代码。"""
    import os

    os.environ["COAPIS_SANDBOX_MODE"] = "strict"
    os.environ["COAPIS_SANDBOX_PROBE_FILE"] = str(tmp_path / "probe.json")
    try:
        report = env_probe.probe(force=True, persist=True)
        if not report["usable"]:
            pytest.skip(f"这台机器 bwrap 自测未通过: {report['reason']}")

        plan = plan_command("true", tmp_path)
        assert plan.use_sandbox is True

        # 1) 工作区内写入应成功
        argv_w = build_argv(
            "echo inside > %s/inside.txt && cat %s/inside.txt"
            % (tmp_path, tmp_path),
            cwd=tmp_path,
            writable=writable_roots(tmp_path),
            net="block",
        )
        r = subprocess.run(argv_w, capture_output=True, text=True, timeout=60)
        assert r.returncode == 0, r.stderr
        assert (tmp_path / "inside.txt").read_text(encoding="utf-8").strip() == "inside"

        # 2) 可写根之外写入必须失败（整盘只读打底）
        victim = Path("/opt/sbx-probe-%d.txt" % os.getpid())
        argv_r = build_argv(
            "echo x > %s" % victim,
            cwd=tmp_path,
            writable=writable_roots(tmp_path),
            net="block",
        )
        r2 = subprocess.run(argv_r, capture_output=True, text=True, timeout=60)
        assert r2.returncode != 0, "沙箱里居然写进了 /opt —— 隔离是假的"
        assert not victim.exists()

        # 3) 断网生效（DNS 解析不了）
        argv_n = build_argv(
            "getent hosts example.com >/dev/null 2>&1",
            cwd=tmp_path,
            writable=writable_roots(tmp_path),
            net="block",
        )
        r3 = subprocess.run(argv_n, capture_output=True, text=True, timeout=60)
        assert r3.returncode != 0
    finally:
        import os as _os

        _os.environ.pop("COAPIS_SANDBOX_MODE", None)
        _os.environ.pop("COAPIS_SANDBOX_PROBE_FILE", None)


@pytest.mark.skipif(not HAS_BWRAP, reason="本机没装 bwrap")
def test_real_sandbox_reads_system(tmp_path):
    """只读打底不是空打底：系统文件读得到（/etc/hostname）。"""
    argv = build_argv(
        "test -r /etc/hostname && echo readable",
        cwd=tmp_path,
        writable=writable_roots(tmp_path),
        net="allow",
    )
    r = subprocess.run(argv, capture_output=True, text=True, timeout=60)
    assert r.returncode == 0, r.stderr
    assert "readable" in r.stdout
