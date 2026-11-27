# -*- coding: utf-8 -*-
"""evolution.sediment 测试：重要事项自动固化进 AGENTS.md（D3 自动写入）。

治的病：反复验证过的稳定做法只躺在经验池里靠检索碰运气，AGENTS.md 长期
不更新；同时防止"自己注入自己计数"那种自我强化的假门槛。
"""

import datetime

from coapis.evolution import sediment


def _exp(title, content, *, conf=0.95, etype="preference", days=1, agent="a1"):
    now = datetime.datetime.now(datetime.timezone.utc)
    return {
        "title": title,
        "content": content,
        "confidence": conf,
        "experience_type": etype,
        "agent_ids": [agent],
        "created_at": (now - datetime.timedelta(days=days)).isoformat(),
    }


def _repeat(title, content, n, **kw):
    return [_exp(title + str(i) if False else title, content, **kw) for i in range(n)]


# ── 门槛 ──────────────────────────────────────────────────────────
def test_below_occurrence_threshold_is_rejected():
    rows = _repeat("语言偏好", "一律用中文回答", 2)
    assert sediment.candidates(rows) == []


def test_repeated_high_confidence_becomes_candidate():
    rows = _repeat("语言偏好", "一律用中文回答", 3)
    got = sediment.candidates(rows)
    assert len(got) == 1
    assert got[0]["occurrences"] == 3
    assert "中文" in got[0]["text"]


def test_low_confidence_repeated_still_rejected():
    rows = _repeat("猜的", "可能要先重启容器", 5, conf=0.6)
    assert sediment.candidates(rows) == []


def test_skill_type_not_sedimented():
    rows = _repeat("某个技巧", "先跑 env_sync_check", 6, etype="skill")
    assert sediment.candidates(rows) == []


def test_secret_looking_content_never_sediments():
    rows = _repeat("部署", "把 API token 换成 abc123 再重启", 4)
    assert sediment.candidates(rows) == []


def test_cap_limits_entries():
    rows = []
    for i in range(40):
        rows.extend(_repeat(f"规则{i}", f"必须做第{i}件事", 3))
    got = sediment.candidates(rows, cap=5)
    assert len(got) == 5


def test_same_topic_variants_merge_into_one_cluster():
    # 标题只差标点/大小写 → 同簇，凑够次数才算重要
    rows = [
        _exp("语言偏好", "一律用中文回答", days=10),
        _exp("语言偏好！", "回答一律用中文", days=5),
        _exp("语言偏好", "一律用中文回答", days=1),
    ]
    got = sediment.candidates(rows)
    assert len(got) == 1
    assert got[0]["occurrences"] == 3


def test_newest_content_wins_inside_cluster():
    rows = [
        _exp("端口", "开发入口是 4200", days=200),
        _exp("端口", "开发入口是 4300", days=1),
        _exp("端口", "开发入口是 4300", days=1),
    ]
    got = sediment.candidates(rows)
    assert len(got) == 1
    assert "4300" in got[0]["text"]


# ── 渲染与合并 ─────────────────────────────────────────────────────
def test_render_block_single_line_each():
    rows = _repeat("语言偏好", "一律用中文\n回答", 3)
    items = sediment.candidates(rows)
    block = sediment.render_block(items)
    body = [ln for ln in block.splitlines() if ln.startswith("- ")]
    assert len(body) == 1
    assert block.count(sediment.MARK_START) == 1
    assert block.count(sediment.MARK_END) == 1


def test_merge_creates_block_once_and_is_idempotent():
    md = "# 工作约定\n\n## 安全\n- 不要泄密\n"
    items = [{"text": "一律用中文回答", "occurrences": 3, "confidence": 0.95}]
    once = sediment.merge_block(md, sediment.render_block(items))
    twice = sediment.merge_block(once, sediment.render_block(items))
    assert once.count(sediment.BLOCK_TITLE) == 1
    assert twice == once
    assert "- 不要泄密" in twice


def test_merge_replaces_old_block_without_duplication():
    items_a = [{"text": "旧规则", "occurrences": 3, "confidence": 0.95}]
    items_b = [{"text": "新规则", "occurrences": 7, "confidence": 0.99}]
    md = "# 约定\n\n正文\n"
    step1 = sediment.merge_block(md, sediment.render_block(items_a))
    step2 = sediment.merge_block(step1, sediment.render_block(items_b))
    assert "旧规则" not in step2
    assert "新规则" in step2
    assert step2.count(sediment.BLOCK_TITLE) == 1
    assert "正文" in step2


def test_empty_block_removes_only_own_section():
    md = "# 约定\n\n正文\n\n" + sediment.render_block(
        [{"text": "旧规则", "occurrences": 3, "confidence": 0.95}]) + "\n"
    out = sediment.merge_block(md, "")
    assert "旧规则" not in out
    assert "正文" in out
    assert sediment.MARK_START not in out


# ── IO 幂等 ────────────────────────────────────────────────────────
def test_sediment_writes_once_and_skips_when_unchanged(tmp_path):
    rows = _repeat("语言偏好", "一律用中文回答", 3)
    first = sediment.sediment(tmp_path, experiences=rows)
    assert first["written"] is True
    assert first["entries"] == 1
    assert "中文" in (tmp_path / "AGENTS.md").read_text(encoding="utf-8")

    second = sediment.sediment(tmp_path, experiences=rows)
    assert second["written"] is False
    assert second.get("skipped") == "unchanged"


def test_sediment_keeps_existing_content(tmp_path):
    (tmp_path / "AGENTS.md").write_text(
        "# 我的约定\n\n## 铁律\n- 提交前跑测试\n", encoding="utf-8")
    sediment.sediment(tmp_path, experiences=_repeat("端口", "开发入口 4300", 3))
    md = (tmp_path / "AGENTS.md").read_text(encoding="utf-8")
    assert "提交前跑测试" in md
    assert "开发入口 4300" in md


def test_dry_run_does_not_touch_disk(tmp_path):
    res = sediment.sediment(tmp_path, experiences=_repeat("端口", "开发入口 4300", 3),
                            dry_run=True)
    assert res["written"] is False
    assert res.get("skipped") == "dry_run"
    assert not (tmp_path / "AGENTS.md").exists()


def test_read_experiences_skips_broken_lines(tmp_path):
    f = tmp_path / "approved.jsonl"
    f.write_text(
        '{"title":"a","content":"b","confidence":0.9,"experience_type":"lesson"}\n'
        "not-json\n"
        "\n"
        '{"title":"c","content":"d","confidence":0.9,"experience_type":"lesson"}\n',
        encoding="utf-8",
    )
    rows = sediment.read_experiences(f)
    assert len(rows) == 2
