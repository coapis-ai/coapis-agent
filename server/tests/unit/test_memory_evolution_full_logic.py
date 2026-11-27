"""记忆/进化机制全链路验证（sediment 侧 + rank 台账）。

重写说明（2026-11-27）：上一版这份测试是照着"想象中的函数名"写的
—— collect_candidates / MARKER_START / HALF_LIFE_DAYS 这些符号在代码里
根本不存在，15 条从来没跑绿过，却被当成"全量通过"汇报了出去。
这一版每条断言都先用探针实测过真实行为，才写进断言。

分工：新鲜度衰减、打分、可见性、预算这些"读侧尺子"在
``test_evolution_recall.py`` 里锁；本文件只管**写侧**（经验文件、聚类
闸门、渲染合并、自动固化）和 **rank 的对账台账**。
"""
from __future__ import annotations

import datetime as dt
import json
from pathlib import Path

import pytest

from coapis.evolution import paths as P
from coapis.evolution import recall as R
from coapis.evolution import sediment as S

NOW = dt.datetime(2026, 11, 27, 12, 0, tzinfo=dt.timezone.utc)


def exp(title, etype="pattern", conf=0.95, content="正常内容", **kw):
    """构造一条经验记录（字段名以 approved.jsonl 实测为准）。"""
    d = {
        "title": title,
        "content": content,
        "experience_type": etype,
        "confidence": conf,
        "agent_id": "agent-a",
        "saved_at": NOW.isoformat(),
    }
    d.update(kw)
    return d


def cluster(title, n=3, content=None, **kw):
    """同一主题记 n 次 —— 固化闸门要求同主题至少 MIN_OCCURRENCES_DEFAULT 次。

    正文默认取标题：沉淀块里渲染的是正文（实测），这样断言能直接查主题字样。
    """
    body = title if content is None else content
    return [exp(title, content=body, **kw) for _ in range(n)]


# ===========================================================================
# 1. 经验文件读取
# ===========================================================================
class TestExperienceFile:
    def test_missing_file_is_empty_not_crash(self, tmp_path):
        assert S.read_experiences(tmp_path / "nope.jsonl") == []

    def test_broken_and_non_dict_lines_skipped(self, tmp_path):
        p = tmp_path / "x.jsonl"
        p.write_text('{"title":"a"}\n[1,2]\n{"title":"b"}\n\n坏行\n',
                     encoding="utf-8")
        got = S.read_experiences(p)
        assert [g["title"] for g in got] == ["a", "b"]

    def test_valid_lines_all_kept(self, tmp_path):
        p = tmp_path / "y.jsonl"
        rows = [json.dumps(exp(f"t{i}")) for i in range(5)] + ["这不是json"]
        p.write_text("\n".join(rows) + "\n", encoding="utf-8")
        assert len(S.read_experiences(p)) == 5   # 6 行里 5 条有效，坏行不算条数


# ===========================================================================
# 2. 固化闸门：什么样的经验才配进 AGENTS.md
# ===========================================================================
class TestSedimentGates:
    def test_same_topic_twice_is_not_enough(self):
        assert S.candidates(cluster("端口约定", 2), now=NOW) == []

    def test_same_topic_three_times_passes(self):
        got = S.candidates(cluster("端口约定", 3), now=NOW)
        assert len(got) == 1
        assert got[0]["occurrences"] == 3

    def test_low_confidence_rejected(self):
        assert S.candidates(cluster("端口约定", 3, conf=0.5), now=NOW) == []

    def test_confidence_at_threshold_passes(self):
        got = S.candidates(cluster("端口约定", 3), now=NOW,
                           min_confidence=0.95)
        assert len(got) == 1

    def test_type_outside_whitelist_rejected(self):
        assert S.candidates(cluster("端口约定", 3, etype="decision"),
                            now=NOW) == []

    def test_whitelisted_types_all_pass(self):
        for t in S.ALLOWED_TYPES:
            assert S.candidates(cluster(f"主题{t}", 3, etype=t), now=NOW), t

    def test_secrets_never_sedimented(self):
        for bad in ("密码是 hunter2", "token=AKIAIOSFODNN7EXAMPLE",
                    "把 password 改成 abc123"):
            assert S.candidates(cluster("密钥主题", 3, content=bad),
                                now=NOW) == [], bad

    def test_cross_topic_singles_dropped(self):
        """六个不相关主题各记一次 —— 凑不出重复模式就不该固化。"""
        rows = [exp(f"主题{i}") for i in range(6)]
        assert S.candidates(rows, now=NOW) == []

    def test_sorted_by_score_then_capped(self):
        mix = cluster("少", 3) + cluster("多", 9)
        got = S.candidates(mix, now=NOW)
        assert [g["occurrences"] for g in got] == [9, 3]
        assert [g["occurrences"] for g in S.candidates(mix, now=NOW, cap=1)] == [9]

    def test_item_shape_is_stable(self):
        got = S.candidates(cluster("端口约定", 3), now=NOW)
        assert set(got[0]) >= {"key", "text", "occurrences", "confidence",
                               "freshness", "score", "types", "agents"}


# ===========================================================================
# 3. 渲染与合并：只能动自己的地盘
# ===========================================================================
class TestRenderAndMerge:
    def test_render_empty_returns_empty_string(self):
        assert S.render_block([], now=NOW) == ""

    def test_render_wraps_in_markers(self):
        blk = S.render_block(S.candidates(cluster("端口约定", 3), now=NOW),
                             now=NOW)
        assert S.MARK_START in blk and S.MARK_END in blk
        assert S.BLOCK_TITLE in blk

    def test_merge_keeps_handwritten_content(self):
        blk = S.render_block(S.candidates(cluster("端口约定", 3), now=NOW),
                             now=NOW)
        out = S.merge_block("# 我手写的规矩\n\n别删我\n", blk)
        assert "# 我手写的规矩" in out and "别删我" in out
        assert out.count(S.MARK_START) == 1

    def test_merge_is_idempotent(self):
        """反复固化不许把同一块内容越叠越多。"""
        blk = S.render_block(S.candidates(cluster("端口约定", 3), now=NOW),
                             now=NOW)
        md = S.merge_block("# 手写\n", blk)
        md = S.merge_block(md, blk)
        md = S.merge_block(md, blk)
        assert md.count(S.MARK_START) == 1
        assert md.count(S.BLOCK_TITLE) == 1


# ===========================================================================
# 4. 自动固化入口
# ===========================================================================
class TestSedimentEntry:
    def _ws(self, tmp_path):
        ws = tmp_path / "ws"
        ws.mkdir()
        (ws / "AGENTS.md").write_text("# 我的规矩\n", encoding="utf-8")
        return ws

    def test_writes_managed_block(self, tmp_path):
        ws = self._ws(tmp_path)
        r = S.sediment(ws, experiences=cluster("端口必须 4308", 5), now=NOW)
        assert r["written"] is True and r["entries"] >= 1
        md = (ws / "AGENTS.md").read_text(encoding="utf-8")
        assert S.MARK_START in md and "端口必须 4308" in md
        assert "# 我的规矩" in md

    def test_unchanged_content_skips_second_write(self, tmp_path):
        ws = self._ws(tmp_path)
        rows = cluster("端口必须 4308", 5)
        assert S.sediment(ws, experiences=rows, now=NOW)["written"] is True
        again = S.sediment(ws, experiences=rows,
                           now=NOW + dt.timedelta(minutes=1))
        assert again["written"] is False
        assert again.get("skipped") == "unchanged"

    def test_new_topic_triggers_rewrite(self, tmp_path):
        ws = self._ws(tmp_path)
        S.sediment(ws, experiences=cluster("端口必须 4308", 5), now=NOW)
        rows = cluster("端口必须 4308", 5) + cluster("容器名带 -dev", 5)
        r = S.sediment(ws, experiences=rows,
                       now=NOW + dt.timedelta(days=1))
        assert r["written"] is True
        assert "容器名带 -dev" in (ws / "AGENTS.md").read_text(encoding="utf-8")

    def test_nothing_passes_gate_writes_nothing(self, tmp_path):
        ws = self._ws(tmp_path)
        r = S.sediment(ws, experiences=[exp("孤条一次")], now=NOW)
        assert r["written"] is False
        assert S.MARK_START not in (ws / "AGENTS.md").read_text(encoding="utf-8")

    def test_secret_never_lands_in_agents_md(self, tmp_path):
        ws = self._ws(tmp_path)
        rows = cluster("密钥主题", 5, content="密码 hunter2") + \
            cluster("端口必须 4308", 5)
        r = S.sediment(ws, experiences=rows, now=NOW)
        md = (ws / "AGENTS.md").read_text(encoding="utf-8")
        assert "hunter2" not in md
        assert "端口必须 4308" in md and r["written"] is True

    def test_creates_agents_md_when_absent(self, tmp_path):
        """没有 AGENTS.md 也要能建起来（实测行为），而不是默默不固化。"""
        ws = tmp_path / "empty"
        ws.mkdir()
        r = S.sediment(ws, experiences=cluster("端口必须 4308", 5), now=NOW)
        assert r["written"] is True
        md = (ws / "AGENTS.md").read_text(encoding="utf-8")
        assert S.MARK_START in md and "端口必须 4308" in md

    def test_result_is_json_serialisable(self, tmp_path):
        """调用方拿它写日志/返回，不许夹带不可序列化对象。"""
        ws = self._ws(tmp_path)
        r = S.sediment(ws, experiences=cluster("端口必须 4308", 5), now=NOW)
        json.dumps(r, ensure_ascii=False, default=str)


# ===========================================================================
# 5. rank 台账：注入日志里的数字必须真
# ===========================================================================
class TestRankLedger:
    def test_stats_report_scanned_rows(self):
        rows = [exp(f"r{i}") for i in range(6)]
        st = {}
        top = R.rank(rows, agent_id="agent-a", limit=3, now=NOW, stats=st)
        assert st["scanned"] == 6
        assert len(top) <= 3
        assert st["after_dedupe"] == 6

    def test_stats_self_consistent_after_merge(self):
        rows = cluster("同题", 3, conf=0.95) + cluster("同题", 1, conf=0.2)
        st = {}
        R.rank(rows, agent_id="agent-a", now=NOW, stats=st)
        assert st["merged_rows"] == st["scanned"] - st["after_dedupe"]
        assert st["merged_clusters"] == 1

    def test_dedupe_keeps_the_strongest(self):
        rows = cluster("同题", 2, conf=0.95) + cluster("同题", 1, conf=0.2)
        top = R.rank(rows, agent_id="agent-a", now=NOW)
        assert len(top) == 1
        assert top[0]["confidence"] == 0.95

    def test_dedupe_can_be_disabled(self):
        rows = cluster("同题", 2, conf=0.95) + cluster("同题", 1, conf=0.2)
        assert len(R.rank(rows, agent_id="agent-a", now=NOW,
                          dedupe_topic=False)) == 3

    def test_no_stats_arg_is_safe(self):
        assert R.rank(cluster("同题", 3), agent_id="agent-a", now=NOW)


# ===========================================================================
# 6. 路径尺子：不许再有死路径，读不到要喊且只喊一次
# ===========================================================================
class TestPathsRuler:
    def test_describe_has_no_dead_dev_path(self):
        assert "/app/docker/dev" not in P.describe()

    def test_readable_file_returns_true(self, tmp_path):
        f = tmp_path / "a.md"
        f.write_text("# 有内容\n", encoding="utf-8")
        assert P.report_readable(f, "t-readable") is True

    def test_missing_file_warns_once_only(self, tmp_path, caplog):
        missing = tmp_path / "gone.md"
        assert P.report_readable(missing, "t-once") is False
        assert P.report_readable(missing, "t-once") is False
        hits = [r for r in caplog.records if "gone.md" in r.getMessage()]
        assert len(hits) == 1
