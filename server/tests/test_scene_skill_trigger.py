#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""场景技能优先触发 —— SkillSelector 层测试矩阵（B3.3）。

覆盖计划 §5 的运行时用例（SkillSelector 可独立测试的部分）：
  T1  Stage 0：场景声明技能关键词命中 → 优先入选
  T2  S5 权重：frontmatter 触发词 ×2 胜过描述命中
  T3  场景加权：同分时场景技能排前（决定 5 席归属）
  T4  幽灵技能：声明了池中不存在的技能 → 不崩、不选、记日志
  T5  LLM 兜底候选集限定为场景技能（D3）
  T6  上限：MAX_SKILL_COUNT 生效、去重
  T7  无场景：行为与改造前一致（回归保护）

Run: python3 server/tests/test_scene_skill_trigger.py
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from coapis.agents.utils.skill_selector import SkillSelector


def meta(name, desc, triggers):
    return {
        name: {
            "description": desc,
            "trigger_keywords": triggers,
            "keyword_weights": {k: 2.0 for k in triggers},
        }
    }


def sel(skill_meta, user_input, scene_skills=None, top_k=5):
    s = SkillSelector()
    s.build_index(skill_meta, scene_skills=scene_skills)
    return s.select(user_input, top_k=top_k)


def t1_stage0_scene_priority():
    """场景声明技能即使分数低于其它技能，也因 Stage 0 优先入选。"""
    sm = meta("docx", "生成 Word 文档", ["文档"])
    sm["news"] = {
        "description": "新闻聚合",
        "trigger_keywords": ["新闻", "报道", "头条", "新闻"],
        "keyword_weights": {"新闻": 1.0, "报道": 1.0, "头条": 1.0},
    }
    # 用户输入含"新闻"(news 得 3 分) 与 "文档"(docx 得 2 分)
    got = sel(sm, "帮我写一份新闻文档", scene_skills=["docx"])
    assert got[0] == "docx", f"Stage 0 应把场景技能排在首位, got={got}"
    print("T1 Stage 0 场景优先: PASS")


def t2_weighted_frontmatter_beats_description():
    """frontmatter 触发词(×2) 命中胜过描述命中(×1)。"""
    sm = meta("pdf", "处理 PDF 文件", ["pdf"])
    sm["xlsx"] = {
        "description": "表格与 pdf 相关处理",
        "trigger_keywords": [],
        "keyword_weights": {},
    }
    got = sel(sm, "把这个 pdf 转成表格")
    assert got[0] == "pdf", f"frontmatter ×2 应胜出, got={got}"
    print("T2 S5 权重(触发词×2): PASS")


def t3_scene_boost_tiebreak():
    """同分时场景技能排前 —— 决定 5 席归属。"""
    sm = meta("alpha", "alpha 处理", ["x"])
    sm["beta"] = {
        "description": "beta 处理",
        "trigger_keywords": ["x"],
        "keyword_weights": {"x": 2.0},
    }
    # 两者同为 2.0 分；场景声明 beta → beta 应排前
    got = sel(sm, "x", scene_skills=["beta"])
    assert got[0] == "beta", f"场景加权应让 beta 排前, got={got}"
    print("T3 场景加权 tie-break: PASS")


def t4_ghost_scene_skill_ignored():
    """幽灵技能（池中不存在）不崩、不被选中。"""
    sm = meta("docx", "生成 Word 文档", ["文档"])
    got = sel(sm, "写文档", scene_skills=["ghost-skill", "nonexistent"])
    assert "ghost-skill" not in got and "nonexistent" not in got, got
    assert got == ["docx"], got
    print("T4 幽灵技能不崩不选: PASS")


def t5_llm_candidates_restricted_to_scene():
    """D3: LLM 兜底候选集限定为场景技能。"""
    sm = meta("docx", "生成 Word 文档", ["文档"])
    sm["news"] = {"description": "新闻", "trigger_keywords": [], "keyword_weights": {}}
    s = SkillSelector()
    s.build_index(sm, scene_skills=["docx"])
    captured = {}

    def fake_llm(user_input, candidates):
        captured["candidates"] = candidates
        return ["docx"]

    s._llm_classify_sync = fake_llm
    got = s.select("随便说点什么，没有任何关键词", top_k=5)
    assert captured["candidates"] == ["docx"], captured
    assert got == ["docx"], got
    print("T5 LLM 候选限定场景技能: PASS")


def t6_cap_and_dedupe():
    """上限与去重。"""
    sm = {}
    for i in range(10):
        sm[f"s{i}"] = {
            "description": f"s{i}",
            "trigger_keywords": ["kw"],
            "keyword_weights": {"kw": 2.0},
        }
    got = sel(sm, "kw", scene_skills=["s0", "s0", "s1"])
    assert len(got) <= 5, f"上限 5 应生效, got={got}"
    assert len(set(got)) == len(got), f"应去重, got={got}"
    assert got[0] == "s0" and got[1] == "s1", f"场景技能应排前, got={got}"
    print("T6 上限与去重: PASS")


def t7_no_scene_regression():
    """无场景时行为不变（回归保护）。"""
    sm = meta("docx", "生成 Word 文档", ["文档"])
    got = sel(sm, "写文档")
    assert got == ["docx"], got
    s = SkillSelector()
    s.build_index(sm)
    s._llm_classify_sync = lambda msg, cand: []  # 桩：隔离真实 LLM
    got2 = s.select("完全无关的话")
    assert got2 == [], f"无命中应为空, got={got2}"
    print("T7 无场景回归: PASS")


# ─────────────── Agent 层（S1 必载注册 / S3 提示词分段） ───────────────

import tempfile
from types import SimpleNamespace

import coapis.agents.react_agent as ra


class FakeToolkit:
    def __init__(self):
        self.registered = []

    def register_agent_skill(self, skill_dir):
        self.registered.append(Path(skill_dir).name)


class FakeTracker:
    def __init__(self):
        self.events = []

    def record_trigger_event(self, **kwargs):
        self.events.append(kwargs)
        return len(self.events)


def _fake_self(scan_safe, findings=None, max_severity=None):
    """Patch the module-level scan gate and return the original to restore."""
    orig = ra.scan_skill_directory
    sev = SimpleNamespace(value="high") if not scan_safe else None
    ra.scan_skill_directory = lambda skill_dir, skill_name=None: SimpleNamespace(
        is_safe=scan_safe,
        findings=findings or (["x"] if not scan_safe else []),
        max_severity=sev,
    )
    return orig


def t8_scan_gate_blocks_core_registration():
    orig = _fake_self(scan_safe=False)
    try:
        fake = _FakeSelf()
        ok = ra.CoApisAgent._scan_and_register_skill(
            fake, "evil", Path("/tmp/evil"),
            "keyword", ["evil"], "帮我做evil",
            fake.tracker, {"username": "u", "agent_id": "a"},
        )
        assert ok is False, "被拦截的技能不应注册"
        assert fake._toolkit.registered == [], "拦截后不得注册"
        print("T8 扫描拦截: PASS")
    finally:
        ra.scan_skill_directory = orig


class _FakeSelf:
    def __init__(self):
        self._toolkit = FakeToolkit()
        self.tracker = FakeTracker()


def t9_scan_gate_allows_registration():
    orig = _fake_self(scan_safe=True)
    try:
        fake = _FakeSelf()
        with tempfile.TemporaryDirectory() as td:
            d = Path(td) / "good"
            d.mkdir()
            ok = ra.CoApisAgent._scan_and_register_skill(
                fake, "good", d,
                "scene_core", [], "开会",
                fake.tracker, {"username": "u", "agent_id": "a"},
            )
            assert ok is True, "安全技能应注册"
            assert fake._toolkit.registered == ["good"]
            assert fake.tracker.events[-1]["trigger_method"] == "scene_core"
        print("T9 必载注册+扫描放行: PASS")
    finally:
        ra.scan_skill_directory = orig


def t10_scene_segment_at_prompt_front():
    fake = SimpleNamespace(
        _scene_core_skills=["docx", "pdf"],
        _scene_overflow_skills=["xlsx"],
        _skill_meta={"docx": {"name": "docx", "description": "写文档"},
                     "pdf": {"name": "pdf", "description": "读PDF"},
                     "xlsx": {"name": "xlsx", "description": "表格"}},
        _request_context={},
    )
    seg = ra.CoApisAgent._build_scene_skill_segment(fake)
    assert "场景优先技能" in seg, seg[:60]
    assert seg.lstrip().startswith("##"), "分段必须是 markdown 标题"
    assert "docx" in seg and "pdf" in seg
    assert "xlsx" in seg, "溢出技能应列出"
    print("T10 提示词分段: PASS")


def t11_scene_edit_refreshes_chat_snapshot():
    import asyncio
    from coapis.app.runner.manager import ChatManager
    from coapis.app.runner.models import ChatSpec

    class FakeRepo:
        def __init__(self, chat):
            self.chat = chat
            self.upserts = 0

        async def get_chat(self, chat_id):
            return self.chat if chat_id == self.chat.id else None

        async def upsert_chat(self, spec):
            self.chat = spec
            self.upserts += 1

    chat = ChatSpec(id="c1", name="场景会话", session_id="s1", user_id="u",
                    channel="console",
                    scene_id="sc", scene_config={"id": "sc", "skills": ["pdf"]})
    repo = FakeRepo(chat)
    cm = ChatManager.__new__(ChatManager)
    cm._repo = repo
    cm._lock = asyncio.Lock()

    async def run():
        snap = {"id": "sc", "skills": ["docx", "pdf"]}
        merged = await cm.set_scene_config("c1", snap)
        assert merged.scene_config["skills"] == ["docx", "pdf"], "快照应刷新"
        assert repo.upserts == 1
        assert (await repo.get_chat("c1")).scene_config["skills"] == ["docx", "pdf"]

    asyncio.run(run())
    print("T11 场景编辑刷新快照: PASS")


def t12_snapshot_builder_single_source():
    from coapis.services.scene_agent_service import SceneAgentService
    from coapis.models.scene import SceneConfig, SceneAgentConfig, Capabilities, SceneInfo

    with tempfile.TemporaryDirectory() as td:
        svc = SceneAgentService.__new__(SceneAgentService)
        svc.agents_dir = Path(td) / "agents"
        scene_dir = svc.agents_dir / "scene-sc"
        scene_dir.mkdir(parents=True)
        (scene_dir / "AGENTS.md").write_text("场景提示词", encoding="utf-8")

        scene = SceneConfig(id="sc", name="场景A", skills=["docx"])
        agent = SceneAgentConfig(
            id="sc", name="场景A",
            scene=SceneInfo(id="sc"),
            capabilities=Capabilities(skills=["docx", "pdf"], tools=[], knowledge_bases=[]),
            welcome_message="你好",
        )
        svc.get_scene = lambda sid: scene if sid == "sc" else None
        svc.get_scene_agent = lambda sid: agent if sid == "sc" else None

        snap = svc.build_snapshot("sc")
        assert snap["skills"] == ["docx", "pdf"], snap["skills"]
        assert snap["system_prompt"] == "场景提示词"
        assert snap["id"] == "sc" and snap["welcome_message"] == "你好"
        assert svc.build_snapshot("missing") is None
        print("T12 快照单一构建入口: PASS")


if __name__ == "__main__":
    tests = [
        t1_stage0_scene_priority,
        t2_weighted_frontmatter_beats_description,
        t3_scene_boost_tiebreak,
        t4_ghost_scene_skill_ignored,
        t5_llm_candidates_restricted_to_scene,
        t6_cap_and_dedupe,
        t7_no_scene_regression,
        t8_scan_gate_blocks_core_registration,
        t9_scan_gate_allows_registration,
        t10_scene_segment_at_prompt_front,
        t11_scene_edit_refreshes_chat_snapshot,
        t12_snapshot_builder_single_source,
    ]
    failed = 0
    for t in tests:
        try:
            t()
        except AssertionError as e:
            failed += 1
            print(f"{t.__name__}: FAIL -> {e}")
    print(f"\n{len(tests) - failed}/{len(tests)} passed")
    sys.exit(1 if failed else 0)
