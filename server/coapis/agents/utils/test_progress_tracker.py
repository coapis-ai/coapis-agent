# -*- coding: utf-8 -*-
"""Unit tests for ProgressTracker (P0/P3)."""

import sys
from pathlib import Path

# 直接导入模块，绕过 __init__.py 的相对导入
import importlib.util as _ilu
_pt_path = str(Path(__file__).resolve().parent / "progress_tracker.py")
_spec = _ilu.spec_from_file_location("progress_tracker", _pt_path)
_mod = _ilu.module_from_spec(_spec)
sys.modules["progress_tracker"] = _mod
_spec.loader.exec_module(_mod)
ToolCallRecord = _mod.ToolCallRecord
ProgressTrackerConfig = _mod.ProgressTrackerConfig
ProgressTracker = _mod.ProgressTracker


class TestProgressTrackerConfig:
    """Test ProgressTrackerConfig."""

    def test_defaults(self):
        cfg = ProgressTrackerConfig()
        assert cfg.enabled is False
        assert cfg.inject_threshold == 4
        assert cfg.strong_threshold == 6
        assert cfg.hard_limit == 10
        assert cfg.duplicate_ratio_threshold == 0.5
        assert cfg.result_min_len == 20

    def test_enabled(self):
        cfg = ProgressTrackerConfig(enabled=True)
        assert cfg.enabled is True

    def test_custom_values(self):
        cfg = ProgressTrackerConfig(inject_threshold=2, hard_limit=5)
        assert cfg.inject_threshold == 2
        assert cfg.hard_limit == 5


class TestToolCallRecord:
    """Test ToolCallRecord data class."""

    def test_create_record(self):
        rec = ToolCallRecord(
            tool_name="read_file",
            params_hash="abc123",
            params_summary="/tmp/x",
            result_summary="content here",
            result_quality="good",
            result_len=12,
            timestamp=1000.0,
        )
        assert rec.tool_name == "read_file"
        assert rec.result_quality == "good"


class TestProgressTracker:
    """Test ProgressTracker main class."""

    def _make_tracker(self, **kwargs):
        cfg = ProgressTrackerConfig(enabled=True, **kwargs)
        return ProgressTracker(cfg)

    def test_record_and_count(self):
        t = self._make_tracker()
        t.record("read_file", {"path": "/tmp/1"}, "content1" * 10)
        t.record("read_file", {"path": "/tmp/2"}, "content2" * 10)
        assert len(t.records) == 2

    def test_should_inject_after_threshold(self):
        t = self._make_tracker(inject_threshold=2)
        assert t.should_inject() is False
        t.record("read_file", {"path": "/tmp/1"}, "content" * 10)
        assert t.should_inject() is False
        t.record("read_file", {"path": "/tmp/2"}, "content" * 10)
        assert t.should_inject() is True

    def test_should_not_inject_before_threshold(self):
        t = self._make_tracker(inject_threshold=5)
        t.record("a", {}, "result" * 10)
        t.record("b", {}, "result" * 10)
        assert t.should_inject() is False

    def test_has_reached_hard_limit(self):
        t = self._make_tracker(hard_limit=2)
        t.record("a", {}, "r" * 10)
        assert t.has_reached_hard_limit() is False
        t.record("b", {}, "r" * 10)
        assert t.has_reached_hard_limit() is True

    def test_build_summary_contains_stats(self):
        t = self._make_tracker(inject_threshold=2)
        t.record("read_file", {"path": "/tmp/1"}, "content" * 10)
        t.record("exec", {"cmd": "ls"}, "output" * 10)
        summary = t.build_summary()
        assert "进度摘要" in summary
        assert "2次工具调用" in summary
        assert "read_file" in summary
        assert "exec" in summary

    def test_build_summary_empty_when_no_records(self):
        t = self._make_tracker()
        assert t.build_summary() == ""

    def test_reset(self):
        t = self._make_tracker()
        t.record("a", {}, "r" * 10)
        t.reset()
        assert len(t.records) == 0
        assert t.should_inject() is False

    def test_disabled_tracker(self):
        """enabled=False 只是配置标记，不阻止 record（启用检查在调用方）。"""
        cfg = ProgressTrackerConfig(enabled=False)
        t = ProgressTracker(cfg)
        assert t._config.enabled is False
        # should_inject 和 has_reached_hard_limit 基于 records 长度，与 enabled 无关
        assert t.should_inject() is False
        assert t.has_reached_hard_limit() is False
        assert t.build_summary() == ""

    def test_get_stats(self):
        t = self._make_tracker()
        t.record("read_file", {"p": "1"}, "ok" * 10)
        t.record("exec", {"cmd": "ls"}, "output" * 10)
        stats = t.get_stats()
        assert stats["total_calls"] == 2
        assert "read_file" in stats["tool_counts"]
        assert stats["tool_counts"]["read_file"] == 1
        assert stats["tool_counts"]["exec"] == 1

    def test_quality_empty_for_short_result(self):
        t = self._make_tracker(result_min_len=20)
        t.record("exec", {}, "short")
        assert t.records[-1].result_quality == "empty"

    def test_quality_good_for_long_result(self):
        t = self._make_tracker(result_min_len=5)
        t.record("read_file", {"path": "/tmp/1"}, "this is a long enough result")
        assert t.records[-1].result_quality == "good"

    def test_quality_duplicate_for_repeated_params(self):
        t = self._make_tracker(result_min_len=1)
        t.record("read_file", {"path": "/tmp/a"}, "content" * 10)
        t.record("read_file", {"path": "/tmp/a"}, "content" * 10)
        assert t.records[-1].result_quality == "duplicate"

    def test_quality_empty_for_none_result(self):
        t = self._make_tracker()
        t.record("exec", {}, None)
        assert t.records[-1].result_quality == "empty"

    def test_hard_limit_suggestion_in_summary(self):
        t = self._make_tracker(inject_threshold=2, strong_threshold=4, hard_limit=2)
        t.record("a", {}, "r" * 10)
        t.record("b", {}, "r" * 10)
        summary = t.build_summary()
        assert "上限" in summary

    def test_duplicate_warning_in_summary(self):
        t = self._make_tracker(inject_threshold=2, result_min_len=1, duplicate_ratio_threshold=0.3)
        t.record("read_file", {"path": "/tmp/a"}, "content" * 10)
        t.record("read_file", {"path": "/tmp/a"}, "content" * 10)
        t.record("read_file", {"path": "/tmp/a"}, "content" * 10)
        summary = t.build_summary()
        assert "重复" in summary

    def test_stats_when_empty(self):
        t = self._make_tracker()
        stats = t.get_stats()
        assert stats["total_calls"] == 0

    def test_quality_counts_in_stats(self):
        t = self._make_tracker(result_min_len=20)
        t.record("a", {}, "short")  # empty (len < 20)
        t.record("b", {}, "this is long enough result text")  # good (len >= 20)
        stats = t.get_stats()
        assert "quality_counts" in stats
        assert stats["quality_counts"].get("empty", 0) >= 1


def run_all():
    """Run all tests and report results."""
    test_classes = [TestProgressTrackerConfig, TestToolCallRecord, TestProgressTracker]
    total = 0
    passed = 0
    failed = 0
    errors = []
    for cls in test_classes:
        instance = cls()
        for method_name in dir(instance):
            if not method_name.startswith("test_"):
                continue
            total += 1
            method = getattr(instance, method_name)
            try:
                method()
                passed += 1
                print(f"  ✓ {cls.__name__}.{method_name}")
            except Exception as e:
                failed += 1
                errors.append((f"{cls.__name__}.{method_name}", e))
                print(f"  ✗ {cls.__name__}.{method_name}: {e}")

    print(f"\n{'='*50}")
    print(f"Results: {passed}/{total} passed, {failed} failed")
    if errors:
        print("\nFailed tests:")
        for name, err in errors:
            print(f"  - {name}: {err}")
    return failed == 0


if __name__ == "__main__":
    success = run_all()
    sys.exit(0 if success else 1)
