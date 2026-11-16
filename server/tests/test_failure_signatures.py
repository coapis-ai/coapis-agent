# -*- coding: utf-8 -*-
"""失败签名表 + 循环闸签名闸单测（A1 出口）。

验收对应：
* 通用签名全覆盖（实测 16 类，含兜底）；
* 11 个工具专属规则各有用例；
* 成功输出不误判（read_file 正文里有 "not found" 不算失败）；
* 连击计数 / 冷却 / 触发归零三条语义。
"""
from __future__ import annotations

import os
import sys

import pytest

SERVER = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if SERVER not in sys.path:
    sys.path.insert(0, SERVER)

from coapis.agents.loop_gates import (  # noqa: E402
    GATE_FAIL_SIG,
    GateThresholds,
    LoopGateChain,
)
from coapis.agents.utils.failure_signatures import (  # noqa: E402
    SIGNATURES,
    TOOL_RULES,
    classify_failure,
    hint_text,
    is_retryable,
    looks_like_failure,
    signature_label,
)

# 每个通用签名至少一条真实形态样本
SAMPLES: list[tuple[str, str, str]] = [
    # (签名码, 工具, 输出样本)
    ("file_missing", "read_file", "Error: file not found: /app/nope.py"),
    ("permission", "execute_shell_command", "cp: Permission denied"),
    ("resource", "execute_shell_command", "write error: No space left on device"),
    ("missing_dep", "execute_shell_command", "bash: jq: command not found"),
    ("timeout", "execute_shell_command", "command timed out after 60 seconds"),
    ("exit_nonzero", "execute_shell_command", "make failed: returned non-zero exit status 2"),
    ("network", "web_fetch", "fetch failed: getaddrinfo failed for api.example.com"),
    ("auth", "web_fetch", "request error: 403 Forbidden"),
    ("http_error", "web_fetch", "upstream error: Bad Gateway"),
    ("invalid_arg", "edit_file", "invalid argument: unexpected keyword 'replacements'"),
    ("syntax", "execute_shell_command", "SyntaxError: invalid syntax (x.py, line 3)"),
    ("indent", "execute_shell_command", "IndentationError: unexpected indent"),
    ("db_error", "execute_shell_command", "sqlite3.OperationalError: no such table: foo"),
    ("empty_result", "grep_search", "no matches found for pattern"),
    ("vcs_conflict", "execute_shell_command", "! [rejected] main (non-fast-forward)"),
    ("tool_error", "browser_use", "Traceback (most recent call last): paniced inside"),
]


def test_通用签名全覆盖():
    codes = {c for c, _t, _o in SAMPLES}
    assert codes == set(SIGNATURES), f"签名样本未覆盖: {set(SIGNATURES) - codes}"
    assert len(SIGNATURES) >= 15, "通用签名不得少于 15 类"


@pytest.mark.parametrize("code,tool,output", SAMPLES)
def test_每类签名都能归因(code, tool, output):
    sig = classify_failure(tool, output)
    assert sig is not None, output
    assert sig.code == code, f"{output!r} 归因成 {sig.code}，期望 {code}"
    assert sig.label == signature_label(code)
    assert sig.retryable == is_retryable(code)


def test_工具专属规则_11键各有用例():
    # 表本身 11 个工具键（方案口径），别名不另计
    assert len(TOOL_RULES) == 11, sorted(TOOL_RULES)
    专属 = {
        ("execute_shell_command", "bash: yarn: command not found", "missing_dep"),
        ("execute_shell_command", "df: No space left on device", "resource"),
        ("execute_shell_command", "! [rejected] main (non-fast-forward)", "vcs_conflict"),
        ("read_file", "Error: /app/a is a directory", "invalid_arg"),
        ("write_file", "Error: permission denied writing /etc/hosts", "permission"),
        ("edit_file", "Error: old_text not found in file", "invalid_arg"),
        ("grep_search", "no matches found", "empty_result"),
        ("glob_search", "no files match pattern *.zzz", "empty_result"),
        ("browser_use", "Error: net::ERR_CONNECTION_REFUSED", "network"),
        ("web_fetch", "Error: could not fetch: econnrefused", "network"),
        ("web_search", "Error: rate limit exceeded, too many requests", "resource"),
        ("send_file_to_user", "Error: file not found: /tmp/x.png", "file_missing"),
        ("view_image", "Error: cannot decode, not an image", "invalid_arg"),
    }
    for tool, output, want in 专属:
        got = classify_failure(tool, output)
        assert got is not None and got.code == want, f"{tool} {output!r} -> {got}"


def test_别名工具共用规则():
    for alias in ("view_video", "send_file", "bash"):
        out = "Error: no such file or directory"
        got = classify_failure(alias, out)
        assert got is not None and got.code == "file_missing"


def test_mcp工具走专用规则():
    got = classify_failure("mcp__oa__query", "MCP error -32601: method not found")
    assert got is not None and got.code == "invalid_arg"
    got2 = classify_failure("mcp-server-oa_call", "server not connected")
    assert got2 is not None and got2.code == "network"


def test_成功输出不误判():
    """read_file 正文里出现 "not found" 不算失败——必须先过失败前置闸。"""
    body = "def f():\n    # legacy path not found here\n    return 1"
    assert looks_like_failure(body) is True  # 有 "not found" 字样
    assert classify_failure("read_file", body) is None
    assert classify_failure("execute_shell_command", "total 8\n-rw-r--r-- 1 root root 0") is None
    assert classify_failure("grep_search", "42:3:  匹配成功") is None


def test_端口号里含401不判成鉴权():
    got = classify_failure("execute_shell_command",
                           "Error: connect failed on port 14013")
    assert got is not None and got.code != "auth"


def test_空输出不误判():
    assert classify_failure("execute_shell_command", "") is None
    assert classify_failure("", "Permission denied") is not None


# ---------------------------------------------------------------------------
# 签名闸：连击 / 冷却 / 归零
# ---------------------------------------------------------------------------

def _chain(**kw) -> LoopGateChain:
    th = GateThresholds(fail_gate_enabled=True, fail_streak=2,
                        fail_cooldown_s=kw.get("cooldown", 60))
    return LoopGateChain(thresholds=th, session_id="s-fail",
                         chat_id="c-fail", ledger_enabled=False)


_ERR = "Error: Permission denied: '/app/x'"


def test_同类失败连击达阈值才提示():
    ch = _chain()
    assert ch.observe_failure("execute_shell_command", _ERR) is None
    v = ch.observe_failure("execute_shell_command", _ERR)
    assert v is not None and v.gate == GATE_FAIL_SIG
    assert v.action == "hint"
    assert "权限不足" in v.detail
    assert "已连续 2 次" in v.detail
    assert ch.failure_streaks() == {"execute_shell_command:permission": 2}


def test_冷却期内不重复提示():
    ch = _chain(cooldown=3600)
    ch.observe_failure("execute_shell_command", _ERR)
    assert ch.observe_failure("execute_shell_command", _ERR) is not None
    assert ch.observe_failure("execute_shell_command", _ERR) is None
    assert ch.observe_failure("execute_shell_command", _ERR) is None
    # 计数仍在走，只是不再打扰
    assert ch.failure_streaks()["execute_shell_command:permission"] == 4
    assert ch.hits()[GATE_FAIL_SIG] == 1


def test_成功即归零():
    ch = _chain(cooldown=0)
    ch.observe_failure("execute_shell_command", _ERR)
    assert ch.observe_failure("execute_shell_command", "command output ok") is None
    assert ch.failure_streaks() == {}
    # 归零后重新从第一次算起，不该立刻提示
    assert ch.observe_failure("execute_shell_command", _ERR) is None


def test_换签名各算各的():
    ch = _chain(cooldown=0)
    ch.observe_failure("execute_shell_command", _ERR)
    other = "Error: bash: jq: command not found"
    assert ch.observe_failure("execute_shell_command", other) is None
    assert ch.observe_failure("execute_shell_command", other) is not None
    streaks = ch.failure_streaks()
    assert streaks["execute_shell_command:permission"] == 1
    assert streaks["execute_shell_command:missing_dep"] == 2


def test_关掉总闸就完全静默():
    th = GateThresholds(fail_gate_enabled=False)
    ch = LoopGateChain(thresholds=th, session_id="s-off", ledger_enabled=False)
    for _ in range(5):
        assert ch.observe_failure("execute_shell_command", _ERR) is None
    assert ch.hits()[GATE_FAIL_SIG] == 0


def test_阈值可配_一次就提示():
    ch = LoopGateChain(
        thresholds=GateThresholds(fail_gate_enabled=True, fail_streak=1,
                                 fail_cooldown_s=0),
        session_id="s-one", ledger_enabled=False)
    assert ch.observe_failure("execute_shell_command", _ERR) is not None


def test_env_能改阈值():
    os.environ["COAPIS_LOOP_GATE_FAIL_STREAK"] = "5"
    os.environ["COAPIS_LOOP_GATE_FAIL_COOLDOWN"] = "0"
    try:
        th = GateThresholds.from_env()
        assert th.fail_streak == 5
        assert th.fail_cooldown_s == 0  # 0 合法（=不冷却），不会被吞回默认
    finally:
        for k in ("COAPIS_LOOP_GATE_FAIL_STREAK", "COAPIS_LOOP_GATE_FAIL_COOLDOWN"):
            os.environ.pop(k, None)


def test_提示文案讲人话():
    sig = classify_failure("execute_shell_command", _ERR)
    assert sig is not None
    text = hint_text(sig, 3)
    assert "连续 3 次" in text and "权限不足" in text
    assert "重复同样的调用不会有新结果" in text      # 不可重试签名说得更硬
    ok = classify_failure("execute_shell_command", "Error: command timed out")
    assert ok is not None and "别再原样重试" in hint_text(ok, 2)
