"""经验块必须跟着当前这一轮的问题走。

历史事故：runner 在 reply() 之前 rebuild_sys_prompt()，那时 _current_query
还是上一轮的值，注入的经验块与问题错位；首轮 _current_query 为空，意图过滤
整轮不生效（实测日志里 [P5] 一行都不出现）。
"""
import ast
from pathlib import Path

AGENT = (Path(__file__).resolve().parents[1] / "coapis" / "agents"
         / "react_agent.py")


def _reply_body():
    tree = ast.parse(AGENT.read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if isinstance(node, (ast.AsyncFunctionDef, ast.FunctionDef)) \
                and node.name == "reply":
            return node
        if isinstance(node, ast.ClassDef):
            for sub in node.body:
                if getattr(sub, "name", "") == "reply":
                    return sub
    raise AssertionError("找不到 reply 方法")


def _assigned_before(body, target, anchor):
    """target 属性赋值必须发生在调用 anchor 之前（按源码行号比先后）。"""
    pos_target = None
    pos_anchor = None
    for node in ast.walk(body):
        if isinstance(node, ast.Assign):
            for t in node.targets:
                if isinstance(t, ast.Attribute) and t.attr == target:
                    if pos_target is None or node.lineno < pos_target:
                        pos_target = node.lineno
        if isinstance(node, ast.Call):
            f = node.func
            name = getattr(f, "attr", None) or getattr(f, "id", None)
            if name == anchor:
                if pos_anchor is None or node.lineno < pos_anchor:
                    pos_anchor = node.lineno
    assert pos_target is not None, f"reply 里没有给 {target} 赋值"
    assert pos_anchor is not None, f"reply 里没调用 {anchor}"
    return pos_target < pos_anchor


def test_reply_rebuilds_prompt_after_query_is_set():
    body = _reply_body()
    assert _assigned_before(body, "_current_query", "_build_sys_prompt"), (
        "_build_sys_prompt 必须在 _current_query 赋值之后调用，"
        "否则经验块用的是上一轮的问题")


def test_reply_refreshes_prompt_after_prefetch():
    body = _reply_body()
    assert _assigned_before(body, "_pre_fetched_memories", "_build_sys_prompt"), (
        "语义记忆预取结果也要在重建之前放进 self，否则长期记忆块是空的")


def test_rebuild_failure_does_not_break_reply():
    """重建失败只能降级沿用旧 prompt，不能把整轮问答带崩。"""
    body = _reply_body()
    has_try = any(isinstance(n, ast.Try) for n in ast.walk(body)
                  if any(isinstance(c, ast.Call)
                         and (getattr(c.func, "attr", "") == "_build_sys_prompt")
                         for c in ast.walk(n)))
    assert has_try, "_build_sys_prompt 调用必须包在 try 里"
