"""③→④ 接线回归测试：失败签名 → 提示进工具结果 → 新签名请顾问开处方。

这一层的价值不在"能不能归出码"（那是 test_failure_signatures 的事），而在
**归出来的东西有没有真送到该收的地方**：提示进模型看得见的工具结果、新形状
才惊动顾问、坏结果形状不伪造。闸再准，没接线就等于没装。
"""
import sys
from pathlib import Path

import pytest

SERVER = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SERVER))

from coapis.agents.loop_gates import LoopGateChain  # noqa: E402
from coapis.agents.tool_guard_mixin import (  # noqa: E402
    ToolGuardMixin,
    _append_guard_note,
)
from coapis.decision.config import DecisionHubConfig  # noqa: E402
from coapis.decision.hub_advisor import should_advise  # noqa: E402

_PERM = "exit code 1\n[stderr] Permission denied (publickey)\n"


class _Agent(ToolGuardMixin):
    """最小宿主：只给接线需要的两样东西（闸链、无台账副作用）。"""

    def __init__(self) -> None:
        self._chain = LoopGateChain(ledger_enabled=False, session_id="wire-test")

    def _loop_gates(self):
        return self._chain


def _result(text: str):
    return {"content": [{"type": "text", "text": text}]}


def _texts(result) -> list[str]:
    return [b.get("text", "") for b in result.get("content", [])]


def test_同签名第一次不烦人_第二次提示进工具结果():
    agent = _Agent()
    first = _result("命令执行失败")
    agent._observe_loop_failure("execute_shell_command", _PERM, first)
    assert not any("[循环闸提示]" in t for t in _texts(first))

    second = _result("命令执行失败")
    agent._observe_loop_failure("execute_shell_command", _PERM, second)
    notes = [t for t in _texts(second) if "[循环闸提示]" in t]
    assert len(notes) == 1, f"提示应恰好一条，实际 {notes}"
    assert "权限不足" in notes[0] and "连续" in notes[0]


def test_新签名达阈才记一次请顾问_且请求只消费一次():
    agent = _Agent()
    agent._observe_loop_failure("execute_shell_command", _PERM, _result("x"))
    assert not getattr(agent, "_loop_advise_pending", False)  # 第一次不惊动顾问
    agent._observe_loop_failure("execute_shell_command", _PERM, _result("x"))
    assert agent._loop_advise_pending is True
    assert agent._take_loop_advice_request() is True
    # 消费即清空：顾问岗关着时这个请求会一直躺着，不能攒成"下次连开三次"
    assert agent._take_loop_advice_request() is False


def test_成功输出不记账不提示不惊动顾问():
    agent = _Agent()
    for _ in range(3):
        agent._observe_loop_failure(
            "read_file", "def f():\n    return 1\n", _result("ok"),
        )
    assert not getattr(agent, "_loop_advise_pending", False)


def test_两种失败各自算账_旧签名冷却不连坐新签名():
    """连击与冷却都按 ``工具:签名`` 独立——这是失败闸的安全边界。

    反例（本轮曾经的误判）：以为"换了签名就该重新数起"。真那么改，模型在同两
    条坏路之间来回切换就能把连击永远压在阈值下，失败闸被**永久绕过**——而那
    恰恰是最该拦的振荡形状。同理，旧签名进了冷却也不该挡住新签名的提示，
    否则模型换个错误形状就能躲过所有提示。
    """
    dep = "Error: bash: jq: command not found"
    agent = _Agent()
    # permission 连击到阈值 → 提示一次，随后进冷却
    agent._observe_loop_failure("execute_shell_command", _PERM, _result("p1"))
    hit = _result("p2")
    agent._observe_loop_failure("execute_shell_command", _PERM, hit)
    assert [t for t in _texts(hit) if "[循环闸提示]" in t], "第 2 次该提示"

    # 冷却期内再撞同一条：只计数，不刷屏
    cold = _result("p3")
    agent._observe_loop_failure("execute_shell_command", _PERM, cold)
    assert not any("[循环闸提示]" in t for t in _texts(cold))

    # 换成另一种失败形状：各自从第一次数起，达阈值照样提示（冷却不串门）
    agent._observe_loop_failure("execute_shell_command", dep, _result("d1"))
    dep_hit = _result("d2")
    agent._observe_loop_failure("execute_shell_command", dep, dep_hit)
    notes = [t for t in _texts(dep_hit) if "[循环闸提示]" in t]
    assert len(notes) == 1, f"新签名该独立提示一次，实际 {notes}"
    assert "依赖或命令缺失" in notes[0]
    # 两种失败各自记账，互不吞并
    streaks = agent._chain.failure_streaks()
    assert streaks["execute_shell_command:permission"] == 3
    assert streaks["execute_shell_command:missing_dep"] == 2


@pytest.mark.parametrize("bad", [None, "not a dict", {"content": "字符串"}])
def test_结果形状不认识就放弃_绝不伪造(bad):
    assert _append_guard_note(bad, "提示") is None


def test_force_只跳取整节奏_不越岗位与起判轮次():
    hub = DecisionHubConfig.from_dict(
        {"advisor_min_iters": 5, "advisor_every_iters": 5},
    )
    # 没到起判轮次：force 也开不了口子（否则"新签名"会变成绕过一切的理由）
    assert should_advise(hub, 4, force=True) is False
    # 到了起判轮次但没凑满取整：正常该等，拿得出证据就该问
    assert should_advise(hub, 6) is False
    assert should_advise(hub, 6, force=True) is True

    off = DecisionHubConfig.from_dict({"posts": {"advisor": False}})
    assert should_advise(off, 99, force=True) is False


def test_接线点存在且被调用():
    """调用点写在 _acting 的 try 块里；这里锁住"名字存在 + 签名对得上"。"""
    assert hasattr(_Agent, "_observe_loop_failure")
    assert hasattr(_Agent, "_take_loop_advice_request")
    src = (SERVER / "coapis" / "agents" / "tool_guard_mixin.py").read_text(
        encoding="utf-8",
    )
    assert "self._observe_loop_failure(tool_name, result_text, result)" in src
    agent_src = (SERVER / "coapis" / "agents" / "react_agent.py").read_text(
        encoding="utf-8",
    )
    assert '_adv_scope["advise_now"] = self._take_loop_advice_request()' in agent_src
