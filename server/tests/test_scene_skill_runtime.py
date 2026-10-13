#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""场景技能优先触发 —— 运行时（注册/安全门/上限/幽灵）测试。

覆盖实施计划 B3.3 的运行时部分：
  R1 场景声明的技能即使不在用户启用清单里，也注册为核心（S1 必载注册）
  R2 幽灵技能（声明但未安装）被跳过并记录，不阻断注册
  R3 核心上限 MAX_SCENE_CORE_SKILLS：超出部分降级为按需技能
  R4 安全扫描拦截：扫描不通过的场景技能不注册（S5 安全边界）
  R5 场景技能进入 SkillSelector 索引并带 scene_priority 标记

运行方式（容器内，需要 coapis 包可导入）：
    docker cp server/tests/test_scene_skill_runtime.py coapis-server-dev:/tmp/r.py
    docker exec coapis-server-dev python3 /tmp/r.py
"""
import pathlib
import sys
import tempfile

import coapis.agents.react_agent as ra
from coapis.agents.react_agent import CoApisAgent, MAX_SCENE_CORE_SKILLS


class FakeToolkit:
    """记录注册行为的假 Toolkit。"""

    def __init__(self):
        self.skills = {}
        self.registered = []

    def register_agent_skill(self, path):
        self.registered.append(str(path))
        self.skills[pathlib.Path(path).name] = {"name": pathlib.Path(path).name}


def write_skill(root: pathlib.Path, name: str, keywords):
    d = root / name
    d.mkdir(parents=True, exist_ok=True)
    fm = [
        "---",
        f"name: {name}",
        f"description: {name} 处理专用材料",
        "trigger_keywords: [" + ", ".join(keywords) + "]",
        "---",
        "",
        f"# {name}",
        "正文",
    ]
    (d / "SKILL.md").write_text("\n".join(fm), encoding="utf-8")
    return d


def make_agent(workspace: pathlib.Path, scene_skills):
    """绕过 __init__ 构造一个只带 _register_skills 所需属性的假 agent。"""
    agent = object.__new__(CoApisAgent)
    agent._workspace_dir = workspace
    agent.agent_id = "agent-x"
    agent._request_context = {
        "channel": "console",
        "scene_skills": scene_skills,
        "scene_name": "测试场景",
        "scene_id": "scene-test",
        "session_id": "sess",
        "workspace_id": "ws",
        "user_id": "u1",
        "username": "tester",
        "agent_id": "agent-x",
    }
    return agent


def run(scene_skills, block=None):
    """在临时工作区跑一次 _register_skills，返回 (agent, toolkit)。

    ``block`` 为技能名集合时，这些技能的扫描结果被强制判为不安全。
    """
    tmp = pathlib.Path(tempfile.mkdtemp(prefix="scene-skill-"))
    (tmp / "skills").mkdir(exist_ok=True)
    for n in scene_skills:
        if n.endswith("ghost"):
            continue  # 幽灵：声明但未安装
        write_skill(tmp / "skills", n, [n[:4]])

    real_scan = ra.scan_skill_directory
    if block:
        def scan(path, *, skill_name=None, **kw):
            if skill_name in block:
                return type("R", (), {"is_safe": False, "findings": [1], "max_severity": type(
                    "S", (), {"value": "HIGH"})()})()
            return real_scan(path, skill_name=skill_name, **kw)
        ra.scan_skill_directory = scan
    try:
        agent = make_agent(tmp, scene_skills)
        tk = FakeToolkit()
        agent._register_skills(tk)
        return agent, tk
    finally:
        if block:
            ra.scan_skill_directory = real_scan


def r1_scene_skills_registered():
    """R1: 场景技能注册为核心（不依赖用户启用清单）。"""
    agent, tk = run(["alpha", "beta"])
    assert set(agent._scene_core_skills) == {"alpha", "beta"}, agent._scene_core_skills
    assert "alpha" in tk.skills and "beta" in tk.skills, tk.skills
    assert agent._core_skills.get("alpha"), "场景核心技能应进入 _core_skills"
    print("R1 场景必载注册: PASS")


def r2_ghost_skipped():
    """R2: 幽灵技能被跳过并记录，其余照常注册。"""
    agent, tk = run(["alpha", "not-installed-ghost"])
    assert agent._scene_ghost_skills == ["not-installed-ghost"], agent._scene_ghost_skills
    assert agent._scene_core_skills == ["alpha"], agent._scene_core_skills
    assert "alpha" in tk.skills
    print("R2 幽灵过滤: PASS")


def r3_core_cap():
    """R3: 超出 MAX_SCENE_CORE_SKILLS 的场景技能降级为按需。"""
    n = MAX_SCENE_CORE_SKILLS + 2
    names = [f"s{i:02d}" for i in range(n)]
    agent, tk = run(names)
    assert len(agent._scene_core_skills) == MAX_SCENE_CORE_SKILLS, (
        f"核心数应为 {MAX_SCENE_CORE_SKILLS}, got={len(agent._scene_core_skills)}")
    assert len(agent._scene_overflow_skills) == 2, agent._scene_overflow_skills
    # 溢出技能仍可被关键词触发（在按需池里）
    for s in agent._scene_overflow_skills:
        assert s in agent._on_demand_skills, f"{s} 应在按需池"
    print("R3 核心上限降级: PASS")


def r4_scan_gate():
    """R4: 安全扫描拦截的场景技能不得成为场景核心，并记入幽灵清单。"""
    agent, tk = run(["alpha", "evil"], block={"evil"})
    assert "evil" not in agent._scene_core_skills, (
        f"被拦截的技能不应成为场景核心: {agent._scene_core_skills}")
    assert "evil" not in agent._scene_overflow_skills, (
        f"被拦截的技能不应进入按需池: {agent._scene_overflow_skills}")
    assert "evil" in agent._scene_ghost_skills, agent._scene_ghost_skills
    assert agent._scene_core_skills == ["alpha"], agent._scene_core_skills
    print("R4 安全扫描拦截: PASS")


def r5_selector_index():
    """R5: 场景技能进入 SkillSelector 索引并带优先级标记。"""
    agent, tk = run(["alpha", "beta"])
    sel = agent._skill_selector
    assert sel is not None, "SkillSelector 索引应构建"
    assert sel.scene_skills == ["alpha", "beta"], sel.scene_skills
    assert agent._skill_meta["alpha"].get("scene_priority") is True
    assert agent._skill_meta["alpha"]["scene_priority_rank"] == 1
    # 场景声明技能在关键词平局时排在前
    got = sel.select("alpha 处理专用材料")
    assert got[0] == "alpha", got
    print("R5 索引与优先级标记: PASS")


if __name__ == "__main__":
    tests = [r1_scene_skills_registered, r2_ghost_skipped, r3_core_cap,
             r4_scan_gate, r5_selector_index]
    failed = 0
    for t in tests:
        try:
            t()
        except AssertionError as e:
            failed += 1
            print(f"{t.__name__}: FAIL — {e}")
        except Exception as e:
            failed += 1
            print(f"{t.__name__}: ERROR — {type(e).__name__}: {e}")
    print(f"\n{len(tests) - failed}/{len(tests)} passed")
    sys.exit(1 if failed else 0)
