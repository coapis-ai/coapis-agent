# -*- coding: utf-8 -*-
"""Unit tests for PlanGate ComplexityClassifier (M1 D1).

Covers:
  - 6 classification-boundary cases (per m1-plan test matrix)
  - 20-sample calibration against hand-labeled real tasks (acceptance: >= 80%)
  - lite-judge graceful degradation (no provider -> rule verdict kept)
"""

import json
import os
import sys
import unittest
from unittest import mock

_HERE = os.path.dirname(os.path.abspath(__file__))
_SERVER_COAPIS = os.path.abspath(os.path.join(_HERE, "..", ".."))
if _SERVER_COAPIS not in sys.path:
    sys.path.insert(0, _SERVER_COAPIS)

try:
    from coapis.agents import plan_gate
    from coapis.agents.plan_gate import (
        COMPLEX, MEDIUM, SIMPLE, ComplexityClassifier,
    )
except (ImportError, ModuleNotFoundError):
    from agents import plan_gate
    from agents.plan_gate import (
        COMPLEX, MEDIUM, SIMPLE, ComplexityClassifier,
    )

_CALIBRATION_PATH = os.path.join(_HERE, "calibration_20.json")


class TestComplexityClassifierBoundaries(unittest.TestCase):
    """6 boundary cases from the m1-plan test matrix."""

    def setUp(self):
        self.cls = ComplexityClassifier(judge_enabled=False)

    def test_1_simple_short_single_intent(self):
        self.assertEqual(self.cls.classify("今天上海天气怎么样？"), SIMPLE)

    def test_2_boundary_len_80_is_simple(self):
        base = "请帮我仔细核查一下今年第一季度的费用报销单据"
        text = base + "细" * (80 - len(base))
        self.assertEqual(len(text), 80)
        self.assertEqual(self.cls.classify(text), SIMPLE)

    def test_3_boundary_len_81_is_medium(self):
        base = "请帮我仔细核查一下今年第一季度的费用报销单据"
        text = base + "细" * (81 - len(base))
        self.assertEqual(len(text), 81)
        self.assertEqual(self.cls.classify(text), MEDIUM)

    def test_4_over_400_chars_is_complex(self):
        text = "请" + "详细核对每一个项目的金额" * 40  # > 400 chars
        self.assertGreater(len(text), 400)
        self.assertEqual(self.cls.classify(text), COMPLEX)

    def test_5_two_seq_markers_is_complex(self):
        text = "先查一下OA待审批，然后写进周报，最后发给组长"
        self.assertEqual(self.cls.classify(text), COMPLEX)

    def test_6_branch_marker_raises_floor_to_medium(self):
        text = "查一下OA待审批事项，如果查不到就换个关键词再搜"
        # 再 is a seq marker (1 kind) + branch marker -> medium, not simple
        self.assertEqual(self.cls.classify(text), MEDIUM)


class TestComplexityClassifierGuards(unittest.TestCase):

    def setUp(self):
        self.cls = ComplexityClassifier(judge_enabled=False)

    def test_empty_text_is_simple(self):
        self.assertEqual(self.cls.classify(""), SIMPLE)
        self.assertEqual(self.cls.classify("   \n "), SIMPLE)

    def test_consec_pipeline_signal_is_at_least_medium(self):
        text = "查一下差旅标准，把结果整理成表格写入文件"
        self.assertEqual(self.cls.classify(text), MEDIUM)

    def test_three_comma_segs_is_complex(self):
        text = "先收集各部门预算数据，再汇总成一张总表，然后导出Excel发给财务"
        self.assertEqual(self.cls.classify(text), COMPLEX)

    def test_colon_params_do_not_inflate_goals(self):
        text = "帮我订一份会议室：下周三下午两点到四点，参加人是我、李四和王五"
        self.assertEqual(self.cls.classify(text), SIMPLE)


class TestCalibration20(unittest.TestCase):
    """D1 acceptance: 20 real tasks hand-labeled, agreement >= 80%."""

    def test_agreement_at_least_80_percent(self):
        with open(_CALIBRATION_PATH, encoding="utf-8") as fh:
            data = json.load(fh)
        cls = ComplexityClassifier(judge_enabled=False)
        mismatches = []
        for s in data["samples"]:
            got = cls.classify(s["text"])
            if got != s["expected"]:
                mismatches.append(f'{s["uid"]} expected={s["expected"]} got={got}')
        ratio = 1 - len(mismatches) / len(data["samples"])
        self.assertGreaterEqual(
            ratio, 0.80,
            f"agreement {ratio:.0%} < 80%; mismatches: {'; '.join(mismatches)}",
        )
        if mismatches:
            print(f"\n[calibration] agreement={ratio:.0%}; known gaps: {'; '.join(mismatches)}")


class TestLiteJudgeDegradation(unittest.IsolatedAsyncioTestCase):

    async def test_no_provider_falls_back_to_rule_verdict(self):
        cls = ComplexityClassifier(judge_enabled=True)
        with mock.patch.object(plan_gate, "_get_judge_provider_config", return_value=None):
            # rule layer says medium -> judge unavailable -> medium kept
            self.assertEqual(await cls.classify_smart("查一下OA待审批事项，按部门统计数量"), MEDIUM)
            # rule layer says simple -> straight-through, no judge call
            self.assertEqual(await cls.classify_smart("今天几点了？"), SIMPLE)

    async def test_judge_failure_keeps_rule_verdict(self):
        cls = ComplexityClassifier(judge_enabled=True, judge_timeout=0.001)
        with mock.patch.object(
            plan_gate, "_get_judge_provider_config",
            return_value={"api_base": "http://127.0.0.1:1", "api_key": "none", "model": "x"},
        ):
            self.assertEqual(await cls.classify_smart("查一下OA待审批事项，按部门统计数量"), MEDIUM)


if __name__ == "__main__":
    unittest.main(verbosity=2)
