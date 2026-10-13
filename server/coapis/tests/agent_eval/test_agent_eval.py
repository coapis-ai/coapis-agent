# -*- coding: utf-8 -*-
"""Unit tests for the agent capability evaluation system (M0).

Covers: dataset loading, checker suite (deterministic branches), judge
output parsing, mock tool fixtures/flaky behavior, and the report miner
against a throwaway SQLite database.

Import paths are dual-mode: ``coapis.*`` when run from the repo root on a
host with the package installed, bare module names when run inside the
server container (cwd=/app/coapis).
"""

from __future__ import annotations

import asyncio
import json
import os
import tempfile
import unittest

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

os.environ.setdefault("COAPIS_DB_PATH", ":memory:")

try:  # host / installed-package mode
    from coapis.foundation.db.base import Base
    from coapis.foundation.db.models import (
        AgentRun, AgentTask, AgentTrajectory,
    )
    from coapis.agent_eval.dataset.loader import list_categories, load_tasks
    from coapis.agent_eval.checker import (
        PARTIAL_THRESHOLD, PASS_THRESHOLD, CheckerSuite,
    )
    from coapis.agent_eval.judge import parse_judge_output
    from coapis.agent_eval.mocks import (
        arm_flaky_once, mock_oa_doc_search, mock_oa_todo_list, reset_flaky,
    )
    from coapis.agent_eval.report import build_report
except ModuleNotFoundError:  # container mode (cwd = /app/coapis)
    from foundation.db.base import Base
    from foundation.db.models import (
        AgentRun, AgentTask, AgentTrajectory,
    )
    from agent_eval.dataset.loader import list_categories, load_tasks
    from agent_eval.checker import (
        PARTIAL_THRESHOLD, PASS_THRESHOLD, CheckerSuite,
    )
    from agent_eval.judge import parse_judge_output
    from agent_eval.mocks import (
        arm_flaky_once, mock_oa_doc_search, mock_oa_todo_list, reset_flaky,
    )
    from agent_eval.report import build_report


# --------------------------------------------------------------------- #
# dataset
# --------------------------------------------------------------------- #
class DatasetTest(unittest.TestCase):
    def test_total_and_shape(self):
        tasks = load_tasks()
        self.assertEqual(len(tasks), 40)
        for t in tasks:
            self.assertTrue(t["uid"])
            self.assertIn(t["category"], list_categories())
            self.assertGreaterEqual(t["difficulty"], 1)
            self.assertIsInstance(t["user_turns"], list)
            self.assertGreater(len(t["user_turns"]), 0)

    def test_categories_balance(self):
        tasks = load_tasks()
        for cat in list_categories():
            self.assertEqual(
                sum(1 for t in tasks if t["category"] == cat), 8, cat)

    def test_filter(self):
        self.assertEqual(len(load_tasks("planning")), 8)
        self.assertEqual(len(load_tasks("nope")), 0)

    def test_cross_session_flagged(self):
        tasks = load_tasks("memory")
        xs = [t for t in tasks if t["cross_session"]]
        self.assertEqual(len(xs), 1)
        self.assertEqual(xs[0]["uid"], "me-04")
        self.assertTrue(xs[0]["followup_turns"])


# --------------------------------------------------------------------- #
# checker
# --------------------------------------------------------------------- #
class CheckerTest(unittest.TestCase):
    def _suite(self):
        return CheckerSuite(judge=None)

    def _task(self, **kw):
        base = {"uid": "t", "title": "t", "category": "x", "difficulty": 1,
                "user_turns": ["hi"], "expected_tools": [], "forbid_tools": [],
                "checks": {}, "rubric": None}
        base.update(kw)
        return base

    def test_contains_pass(self):
        r = asyncio.run(self._suite().evaluate(
            self._task(checks={"answer_contains": ["星辰科技"]}),
            final_answer="我们公司叫星辰科技", tool_call_names=[], llm_calls=1))
        self.assertEqual(r["verdict"], "pass")
        self.assertEqual(r["score"], 1.0)

    def test_missing_content_fail(self):
        r = asyncio.run(self._suite().evaluate(
            self._task(checks={"answer_contains": ["abc"]}),
            final_answer="nothing here", tool_call_names=[], llm_calls=1))
        self.assertEqual(r["verdict"], "fail")

    def test_expected_tool_enforced(self):
        r = asyncio.run(self._suite().evaluate(
            self._task(expected_tools=["mock_oa_todo_list"]),
            final_answer="ok", tool_call_names=["mock_oa_doc_search"], llm_calls=1))
        self.assertFalse(r["success"])
        self.assertTrue(any(c["check"].startswith("expected_tool:") and
                            not c["passed"] for c in r["checks"]))

    def test_forbidden_tool_penalty(self):
        r = asyncio.run(self._suite().evaluate(
            self._task(forbid_tools=["mock_email_send"]),
            final_answer="ok", tool_call_names=["mock_email_send"], llm_calls=1))
        self.assertEqual(r["verdict"], "fail")

    def test_min_and_max_tool_calls(self):
        ok = asyncio.run(self._suite().evaluate(
            self._task(checks={"min_tool_calls": 2}),
            final_answer="x", tool_call_names=["a", "b"], llm_calls=1))
        bad = asyncio.run(self._suite().evaluate(
            self._task(checks={"max_tool_calls": 0}),
            final_answer="x", tool_call_names=["a"], llm_calls=1))
        self.assertEqual(ok["verdict"], "pass")
        self.assertEqual(bad["verdict"], "fail")

    def test_partial_verdict_boundary(self):
        # one check passes, one fails -> score 0.5 -> partial
        r = asyncio.run(self._suite().evaluate(
            self._task(checks={
                "answer_contains": ["abc"],
                "min_tool_calls": 1,
            }),
            final_answer="abc", tool_call_names=[], llm_calls=1))
        self.assertEqual(r["verdict"], "partial")
        self.assertGreaterEqual(r["score"], PARTIAL_THRESHOLD)
        self.assertLess(r["score"], PASS_THRESHOLD)

    def test_min_answer_length(self):
        r = asyncio.run(self._suite().evaluate(
            self._task(checks={"min_answer_length": 10}),
            final_answer="short", tool_call_names=[], llm_calls=1))
        self.assertEqual(r["verdict"], "fail")

    def _suite_with_judge(self):
        async def judge(question, rubric):
            return 0.9, "good"
        return CheckerSuite(judge=judge)

    def test_rubric_via_judge(self):
        r = asyncio.run(self._suite_with_judge().evaluate(
            self._task(rubric="should be polite"),
            final_answer="您好，已为您处理。", tool_call_names=[], llm_calls=1))
        self.assertEqual(r["verdict"], "pass")
        self.assertIsNotNone(r["rubric_score"])


# --------------------------------------------------------------------- #
# judge parsing
# --------------------------------------------------------------------- #
class JudgeParseTest(unittest.TestCase):
    def test_plain_json(self):
        s, rsn = parse_judge_output('{"score": 0.85, "reason": "ok"}')
        self.assertAlmostEqual(s, 0.85)
        self.assertEqual(rsn, "ok")

    def test_fenced_json(self):
        raw = '好的\n```json\n{"score": 0.5, "reason": "half"}\n```\n谢谢'
        s, rsn = parse_judge_output(raw)
        self.assertAlmostEqual(s, 0.5)

    def test_clamped(self):
        self.assertEqual(parse_judge_output('{"score": 1.7}') [0], 1.0)
        self.assertEqual(parse_judge_output('{"score": -2}') [0], 0.0)

    def test_garbage(self):
        s, _ = parse_judge_output("我不知道该怎么打分")
        self.assertEqual(s, 0.0)

    def test_text_fallback(self):
        s, _ = parse_judge_output('score: 0.62 因为还行')
        self.assertAlmostEqual(s, 0.62)


# --------------------------------------------------------------------- #
# mocks
# --------------------------------------------------------------------- #
class MocksTest(unittest.TestCase):
    def setUp(self):
        reset_flaky()

    def tearDown(self):
        reset_flaky()

    def test_todo_fixture(self):
        payload = json.dumps(mock_oa_todo_list(), ensure_ascii=False)
        self.assertIn('"count": 5', payload)

    def test_flaky_once(self):
        arm_flaky_once()
        with self.assertRaises(RuntimeError):
            mock_oa_todo_list()
        payload = json.dumps(mock_oa_todo_list(), ensure_ascii=False)
        self.assertIn('"count": 5', payload)

    def test_doc_search_hit_and_miss(self):
        hit = json.dumps(mock_oa_doc_search("季度报告"), ensure_ascii=False)
        miss = json.dumps(mock_oa_doc_search("不存在的关键词xyz"), ensure_ascii=False)
        self.assertIn("季度经营分析报告", hit)
        self.assertIn('"results": []', miss)


# --------------------------------------------------------------------- #
# report
# --------------------------------------------------------------------- #
class ReportTest(unittest.TestCase):
    def _factory_with_data(self):
        tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
        tmp.close()
        eng = create_engine(f"sqlite:///{tmp.name}")
        Base.metadata.create_all(eng)
        factory = sessionmaker(bind=eng)
        with factory() as s:
            s.add(AgentTask(task_uid="tc-01", title="t", category="tool_collab",
                            difficulty=1, spec="{}"))
            s.add(AgentTask(task_uid="pl-01", title="t", category="planning",
                            difficulty=3, spec="{}"))
            s.add(AgentRun(task_uid="tc-01", agent_id="eval_bot", success=True,
                           score=0.9, verdict="pass"))
            s.add(AgentRun(task_uid="pl-01", agent_id="eval_bot", success=False,
                           score=0.4, verdict="fail"))
            s.commit()
        return factory, tmp.name

    def test_build_report(self):
        factory, path = self._factory_with_data()
        try:
            rep = build_report(factory)
            self.assertEqual(rep["total_runs"], 2)
            self.assertAlmostEqual(rep["overall_pass_rate"], 0.5)
            self.assertEqual(rep["categories"]["tool_collab"]["pass_rate"], 1.0)
            self.assertEqual(rep["categories"]["planning"]["pass_rate"], 0.0)
            self.assertEqual(rep["weakest_tasks"][0]["task_uid"], "pl-01")
        finally:
            os.unlink(path)


if __name__ == "__main__":
    unittest.main()
