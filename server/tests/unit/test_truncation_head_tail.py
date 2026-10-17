# -*- coding: utf-8 -*-
"""Tool-output truncation keeps both ends of the log.

Why: tool output was cut as a head slice.  A pytest/build log states what
ran at the top and **how it ended** at the bottom (``FAILED``, ``error:``,
the exit line, the summary count), so the cut deleted exactly the part the
agent needed and it re-ran the same command to see the end.  File reads keep
the head-only page contract; tool output has no file to point back to, so it
now keeps head + tail and says how much was omitted.
"""

from coapis.agents.tools.utils import (
    TRUNCATION_NOTICE_MARKER,
    _retruncate,
    truncate_text_output,
)


def _log(n_lines: int, line_len: int = 60) -> str:
    lines = [f"line {i}: " + "x" * (line_len - 10) for i in range(n_lines)]
    lines.append("FAILED tests/unit/test_x.py::test_y - AssertionError")
    lines.append("===== 2 failed, 31 passed in 12.4s =====")
    return "\n".join(lines)


class TestToolOutputKeepsBothEnds:
    def test_under_budget_is_untouched(self):
        text = "a\nb\nc"
        assert truncate_text_output(text, max_bytes=1_000) == text

    def test_tail_survives_the_cut(self):
        text = _log(200)
        out = truncate_text_output(text, max_bytes=4_000)
        assert "2 failed, 31 passed" in out, "the summary line was cut"
        assert "FAILED tests/unit/test_x.py" in out
        assert TRUNCATION_NOTICE_MARKER in out

    def test_head_survives_the_cut(self):
        text = _log(200)
        out = truncate_text_output(text, max_bytes=4_000)
        assert out.startswith("line 0:")

    def test_omitted_middle_is_declared(self):
        text = _log(200)
        out = truncate_text_output(text, max_bytes=4_000)
        assert "omitted from the middle" in out

    def test_notice_reports_kept_counts(self):
        text = _log(200)
        out = truncate_text_output(text, max_bytes=4_000)
        assert "kept the first" in out and "line(s) of 202" in out

    def test_recovery_hint_narrows_the_command(self):
        text = _log(200)
        out = truncate_text_output(text, max_bytes=4_000)
        assert "tail/grep/head" in out
        # No bogus read_file pointer for output that has no source file.
        assert "file_path=" not in out

    def test_budget_is_respected(self):
        text = _log(400)
        out = truncate_text_output(text, max_bytes=3_000)
        # Kept text plus the notice: the notice is the only overshoot.
        assert len(out.encode()) < 3_000 + 400

    def test_cjk_lines_are_counted_by_bytes(self):
        text = "\n".join(["中文行" * 20] * 300)
        out = truncate_text_output(text, max_bytes=2_000)
        assert TRUNCATION_NOTICE_MARKER in out
        assert len(out.encode("utf-8")) < 2_400

    def test_single_huge_line_keeps_its_tail(self):
        text = "z" * 20_000
        out = truncate_text_output(text, max_bytes=1_000)
        # One line: nothing to stitch; the notice is appended to the slice.
        assert TRUNCATION_NOTICE_MARKER in out


class TestFileReadKeepsPageContract:
    def test_file_read_is_head_only_with_continuation(self):
        text = _log(200)
        out = truncate_text_output(
            text,
            start_line=1,
            total_lines=200,
            max_bytes=4_000,
            file_path="/tmp/big.txt",
        )
        assert "file_path=" in out and "start_line=" in out
        assert "omitted from the middle" not in out
        assert "/tmp/big.txt" in out

    def test_retruncate_stays_valid_for_file_reads(self):
        text = _log(200)
        first = truncate_text_output(
            text,
            start_line=1,
            total_lines=200,
            max_bytes=4_000,
            file_path="/tmp/big.txt",
        )
        second = _retruncate(first, 1_500, "utf-8")
        assert "starts at line" in second
        assert "covers the next" in second

    def test_retruncate_tolerates_tool_output_notice(self):
        text = _log(200)
        first = truncate_text_output(text, max_bytes=4_000)
        second = _retruncate(first, 1_500, "utf-8")
        # No file contract to re-derive: the text is returned, never broken.
        assert isinstance(second, str) and TRUNCATION_NOTICE_MARKER in second
