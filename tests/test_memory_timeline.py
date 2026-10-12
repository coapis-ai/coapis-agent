# -*- coding: utf-8 -*-
"""Tests for the memory timeline repository + signal extractor.

Run (container):  cd /app && python -m pytest tests/test_memory_timeline.py -v
Run (host):       python tests/test_memory_timeline.py
"""

import json
import os
import sys
import tempfile
import time
import unittest
from pathlib import Path
from types import ModuleType

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "server"))

try:
    import dotenv  # noqa: F401
except ImportError:
    _fake_dotenv = ModuleType("dotenv")
    _fake_dotenv.load_dotenv = lambda *args, **kwargs: None
    sys.modules["dotenv"] = _fake_dotenv

from coapis.foundation.db.engine import reset_engine
from coapis.foundation.memory_timeline import TimelineEntry
from coapis.foundation.repository_factory import RepositoryFactory
from coapis.agents.memory.signal_extractor import (
    classify,
    extract_signals_from_session,
)


def _iso(ts: float) -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%S+00:00", time.gmtime(ts))


class TimelineRepoBase(unittest.TestCase):
    def setUp(self):
        # D-9: the DB file must live inside WORKING_DIR. A relative URL
        # resolves against WORKING_DIR (never CWD), so it passes the
        # resolve_db_path guard in both host and container environments.
        self._db_rel = f"system/test_tl_{os.getpid()}_{time.monotonic_ns()}.db"
        self._prev = os.environ.get("COAPIS_DATABASE_URL")
        os.environ["COAPIS_DATABASE_URL"] = f"sqlite:///{self._db_rel}"
        RepositoryFactory.reset()
        reset_engine()
        RepositoryFactory.initialize()
        self.repo = RepositoryFactory.get_memory_timeline_repository()

    def tearDown(self):
        RepositoryFactory.reset()
        reset_engine()
        if self._prev is None:
            os.environ.pop("COAPIS_DATABASE_URL", None)
        else:
            os.environ["COAPIS_DATABASE_URL"] = self._prev
        # Clean up the test DB file (WAL/SHM companions included).
        from coapis.constant import WORKING_DIR
        base = (Path(WORKING_DIR) / self._db_rel).resolve()
        for suffix in ("", "-wal", "-shm", "-journal"):
            p = Path(str(base) + suffix)
            if p.exists():
                p.unlink()


class TestTimelineAppendQuery(TimelineRepoBase):
    def test_append_and_query_newest_first(self):
        now = time.time()
        for i, stype in enumerate(["decision", "goal", "preference"]):
            self.repo.append(TimelineEntry(
                user_id="u1", signal_type=stype,
                content=f"句子{i}：关于{i}号的讨论",
                created_at=now + i,
            ))
        rows, total = self.repo.query(user_id="u1")
        self.assertEqual(total, 3)
        self.assertEqual([r["signal_type"] for r in rows],
                         ["preference", "goal", "decision"])

    def test_filter_by_signal_type(self):
        self.repo.append(TimelineEntry(user_id="u1", signal_type="decision",
                                       content="决定采用方案A"))
        self.repo.append(TimelineEntry(user_id="u1", signal_type="goal",
                                       content="下月交付看板"))
        rows, total = self.repo.query(user_id="u1", signal_type="decision")
        self.assertEqual(total, 1)
        self.assertEqual(rows[0]["content"], "决定采用方案A")

    def test_user_isolation(self):
        self.repo.append(TimelineEntry(user_id="u1", signal_type="goal",
                                       content="u1的目标"))
        self.repo.append(TimelineEntry(user_id="u2", signal_type="goal",
                                       content="u2的目标"))
        _, total_u1 = self.repo.query(user_id="u1")
        _, total_u2 = self.repo.query(user_id="u2")
        self.assertEqual(total_u1, 1)
        self.assertEqual(total_u2, 1)

    def test_pagination(self):
        for i in range(5):
            self.repo.append(TimelineEntry(
                user_id="u1", signal_type="goal",
                content=f"分页条目{i}", created_at=time.time() + i,
            ))
        rows, total = self.repo.query(user_id="u1", limit=2, offset=0)
        self.assertEqual(total, 5)
        self.assertEqual(len(rows), 2)
        rows2, _ = self.repo.query(user_id="u1", limit=2, offset=4)
        self.assertEqual(len(rows2), 1)


class TestTimelineDedup(TimelineRepoBase):
    def test_duplicate_does_not_create_row(self):
        kw = dict(user_id="u1", signal_type="decision", content="决定采用方案A")
        id1 = self.repo.append(TimelineEntry(importance=0.5, **kw))
        id2 = self.repo.append(TimelineEntry(importance=0.9, **kw))
        self.assertEqual(id1, id2)
        _, total = self.repo.query(user_id="u1")
        self.assertEqual(total, 1)
        rows, _ = self.repo.query(user_id="u1")
        self.assertAlmostEqual(rows[0]["importance"], 0.9)

    def test_whitespace_insensitive_dedup(self):
        self.repo.append(TimelineEntry(user_id="u1", signal_type="decision",
                                       content="决定 采用 方案A"))
        self.repo.append(TimelineEntry(user_id="u1", signal_type="decision",
                                       content="决定采用方案A"))
        _, total = self.repo.query(user_id="u1")
        self.assertEqual(total, 1)

    def test_same_content_different_type_kept(self):
        self.repo.append(TimelineEntry(user_id="u1", signal_type="decision",
                                       content="同一句话"))
        self.repo.append(TimelineEntry(user_id="u1", signal_type="goal",
                                       content="同一句话"))
        _, total = self.repo.query(user_id="u1")
        self.assertEqual(total, 2)


class TestTimelineRecentMaintain(TimelineRepoBase):
    def test_recent_window(self):
        now = time.time()
        self.repo.append(TimelineEntry(user_id="u1", signal_type="goal",
                                       content="新鲜信号", created_at=now))
        self.repo.append(TimelineEntry(user_id="u1", signal_type="goal",
                                       content="两天前的信号",
                                       created_at=now - 2 * 86400))
        items = self.repo.recent(user_id="u1", hours=24)
        self.assertEqual(len(items), 1)
        self.assertEqual(items[0]["content"], "新鲜信号")

    def test_maintain_prunes_only_expired(self):
        now = time.time()
        self.repo.append(TimelineEntry(user_id="u1", signal_type="goal",
                                       content="过期信号",
                                       created_at=now - 100 * 86400))
        self.repo.append(TimelineEntry(user_id="u1", signal_type="goal",
                                       content="新鲜信号", created_at=now))
        pruned = self.repo.maintain(retention_days=90)
        self.assertEqual(pruned, 1)
        _, total = self.repo.query(user_id="u1")
        self.assertEqual(total, 1)


class TestSignalExtractor(unittest.TestCase):
    def _write_session(self, messages) -> Path:
        f = Path(tempfile.mktemp(suffix=".json"))
        payload = {"agent": {"memory": {"content": [[m] for m in messages]}}}
        f.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
        self.addCleanup(lambda: f.unlink(missing_ok=True))
        return f

    def _msg(self, role, text):
        return {"role": role, "content": [{"type": "text", "text": text}]}

    def test_classify_keywords(self):
        self.assertEqual(classify("我们决定采用方案A"), "decision")
        self.assertEqual(classify("以后都用中文回复我"), "preference")
        self.assertEqual(classify("下个月要交付这个模块"), "goal")
        self.assertIsNone(classify("今天天气不错"))

    def test_extract_from_session_file(self):
        f = self._write_session([
            self._msg("user", "好的，那就决定用 SQLite 吧。另外下周要上线。"),
            self._msg("assistant", "明白，已记录。"),
            self._msg("user", "对了，以后都把日志打到文件里。"),
        ])
        sigs = extract_signals_from_session(f)
        types = {s["signal_type"] for s in sigs}
        self.assertIn("decision", types)
        self.assertIn("goal", types)
        self.assertIn("preference", types)

    def test_caps_respected(self):
        msg = self._msg(
            "user",
            "。".join([f"第{i}条决定要用方案{i}" for i in range(30)]),
        )
        f = self._write_session([msg])
        sigs = extract_signals_from_session(f)
        self.assertLessEqual(len(sigs), 20)
        decisions = [s for s in sigs if s["signal_type"] == "decision"]
        self.assertLessEqual(len(decisions), 3)

    def test_missing_file_returns_empty(self):
        self.assertEqual(extract_signals_from_session(Path("/nonexistent/x.json")), [])

    def test_corrupt_file_returns_empty(self):
        f = Path(tempfile.mktemp(suffix=".json"))
        f.write_text("{not json", encoding="utf-8")
        self.addCleanup(lambda: f.unlink(missing_ok=True))
        self.assertEqual(extract_signals_from_session(f), [])


class TestTimelinePromotion(TimelineRepoBase):
    """Design §6: promotion timeline → memories, guarded by promoted_at."""

    def _seed(self, **kw):
        base = dict(user_id="u1", agent_id="a1", session_id="s1",
                    signal_type="decision", content="X", source="session_scan")
        base.update(kw)
        return self.repo.append(TimelineEntry(**base))

    def test_candidate_filters(self):
        # eligible: promotable type, importance >= 0.6, fresh, not promoted
        self._seed(content="eligible", importance=0.7)
        # ineligible: importance too low
        self._seed(content="low-importance", importance=0.4, dedup_key="k-low")
        # ineligible: conversation type
        self._seed(content="chatter", signal_type="conversation",
                   importance=0.9, dedup_key="k-chat")
        # ineligible: stale (> 7 days)
        self._seed(content="stale", importance=0.9, dedup_key="k-stale",
                   created_at=time.time() - 8 * 86400)
        # ineligible: already promoted
        promo = self._seed(content="already", importance=0.8, dedup_key="k-already")
        self.repo.mark_promoted([promo], time.time())

        got = self.repo.promotion_candidates(user_id="u1")
        self.assertEqual([c["content"] for c in got], ["eligible"])
        self.assertTrue(all(c["promoted_at"] is None for c in got))

    def test_mark_promoted_is_idempotent_guard(self):
        e = self._seed(content="once", importance=0.8, dedup_key="k-once")
        t0 = time.time()
        self.assertEqual(self.repo.mark_promoted([e], t0), 1)
        # guard: already-promoted rows are not re-stamped
        self.assertEqual(self.repo.mark_promoted([e], t0 + 5), 0)
        rows, _total = self.repo.query(user_id="u1")
        self.assertEqual(rows[0]["promoted_at"], t0)
        # no longer a candidate after promotion
        self.assertEqual(self.repo.promotion_candidates(user_id="u1"), [])

    def test_signal_to_category_mapping(self):
        from coapis.agents.memory.signal_extractor import signal_to_category
        self.assertEqual(signal_to_category("decision"), "decision")
        self.assertEqual(signal_to_category("preference"), "preference")
        self.assertEqual(signal_to_category("goal"), "goal")
        self.assertEqual(signal_to_category("conversation"), "note")
        self.assertEqual(signal_to_category(None), "note")
        self.assertEqual(signal_to_category("???"), "note")


if __name__ == "__main__":
    unittest.main()
