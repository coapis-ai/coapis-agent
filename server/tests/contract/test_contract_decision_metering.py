"""AST 结构锁：决策模型的两条调用路径都必须进统一台账。

为什么锁结构而不是行为：判官在 dev 里目前多数时候被规则层/开关挡住，
真流量拿不到（decision_events 最近一条真判是 11-16）。没有真流量时，
行为测试会"因为没跑所以通过"，反而放行回归。结构锁不依赖流量。
"""
import ast
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]  # server/（源码树在这里）
GATEWAY = ROOT / "coapis" / "decision" / "gateway.py"


def _meter_call_sites() -> dict[str, list[int]]:
    """{所在函数名: [行号]} —— self._meter_llm_call 的调用点。"""
    tree = ast.parse(GATEWAY.read_text(encoding="utf-8"))
    parents: dict = {}
    for parent in ast.walk(tree):
        for child in ast.iter_child_nodes(parent):
            parents[child] = parent

    sites: dict[str, list[int]] = {}
    for node in ast.walk(tree):
        if not (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)):
            continue
        if node.func.attr != "_meter_llm_call":
            continue
        fn = None
        cur = node
        while cur is not None:
            if isinstance(cur, (ast.FunctionDef, ast.AsyncFunctionDef)):
                fn = cur.name
                break
            cur = parents.get(cur)
        sites.setdefault(str(fn), []).append(node.lineno)
    return sites


def test_main_judge_path_is_metered() -> None:
    """主链（软超时内返回）必须计量。"""
    assert "_run_llm" in _meter_call_sites(), (
        "决策模型主链没接统一台账：判官花的 tokens 不会进 token_usage"
    )


def test_bg_verdict_path_is_metered() -> None:
    """后台补判必须计量。

    主链软超时那条路不计量，tokens 只在后台补判这条路上拿得到。
    本地判官 2.5-15s、软阈值 2s —— 多数调用走的就是这条路。
    漏掉它 = 台账里 source=decision 恒为 0 行。
    """
    sites = _meter_call_sites()
    assert "_judge_bg_complete" in sites, (
        "决策模型后台补判路径没计量：本地判官的多数调用不进统一台账"
    )


def test_meter_helper_uses_decision_source() -> None:
    """计量助手必须打 source=decision，不能混进 chat。"""
    src = GATEWAY.read_text(encoding="utf-8")
    assert "SOURCE_DECISION" in src, "决策模型计量没打 source=decision 标记"
