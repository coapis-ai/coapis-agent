# -*- coding: utf-8 -*-
# Copyright 2026 蜜蜂 & CoApis Contributors
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU Affero General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU Affero General Public License for more details.
#
# You should have received a copy of the GNU Affero General Public License
# along with this program.  If not, see <https://www.gnu.org/licenses/>.

"""Skill trigger chain: index cache, Chinese matching, regex patterns.

Covers the 2026-10-21 repair of the skill trigger chain.  The measured
baseline on dev was: 19 skills discovered, **index length 0 chars** on every
turn after the first, Chinese queries falling back to the full catalogue, and
every ``triggers.patterns`` declaration unable to fire because it was compared
as a literal substring.
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from coapis.agents.utils.skill_selector import SkillSelector  # noqa: E402
from coapis.skills.manager import SkillManager, has_trigger_sentence  # noqa: E402

sys.path.insert(
    0,
    str(Path(__file__).resolve().parents[2].parent / "scripts"),
)

from apply_skill_index_hints import apply_hint  # noqa: E402


def write_skill(
    root: Path,
    name: str,
    *,
    description: str = "A skill.",
    frontmatter: str = "",
    body: str = "Do the thing.",
) -> Path:
    skill_dir = root / name
    skill_dir.mkdir(parents=True, exist_ok=True)
    (skill_dir / "SKILL.md").write_text(
        f"---\nname: {name}\ndescription: {description}\n{frontmatter}---\n{body}\n",
        encoding="utf-8",
    )
    return skill_dir


def manager_with(root: Path) -> SkillManager:
    mgr = SkillManager(root)
    asyncio.run(mgr.discover())
    return mgr


# ---------------------------------------------------------------- B1: cache


def test_compact_index_is_not_empty_after_discover(tmp_path):
    """The regression: discover() ends with apply_descriptions_from_pack(),
    which calls invalidate_index_cache(); the "" sentinel it wrote counted as
    a valid cached value, so the compact index stayed empty forever."""
    write_skill(tmp_path, "alpha", description="处理表格数据。")
    write_skill(tmp_path, "beta", description="读取邮件内容。")
    mgr = manager_with(tmp_path)

    compact = mgr.get_index_prompt(compact=True)
    assert compact, "compact index must not be empty with skills present"
    assert "alpha" in compact and "beta" in compact


def test_index_rebuilds_after_invalidate(tmp_path):
    """Invalidation must mean *no cache*, not *cached empty*."""
    write_skill(tmp_path, "alpha", description="处理表格数据。")
    mgr = manager_with(tmp_path)
    assert mgr.get_index_prompt()
    mgr.invalidate_index_cache()
    assert not mgr._query_index_cache
    assert mgr.get_index_prompt()
    assert mgr.get_index_prompt(compact=True)


def test_empty_skill_dir_yields_empty_index(tmp_path):
    mgr = manager_with(tmp_path)
    assert mgr.get_index_prompt() == ""
    assert mgr.get_index_prompt(compact=True) == ""
    # An empty result is a legitimate cached value; it must not poison the
    # non-empty path of the other mode.
    assert mgr.get_index_prompt(compact=True) == ""


def test_query_cache_key_is_full_query_not_a_hash(tmp_path):
    """Keys used to be ``hash(query) % 10000``: one session could serve
    another session's skill set on a collision."""
    write_skill(tmp_path, "xlsx", description="电子表格。")
    write_skill(tmp_path, "pdf", description="PDF 文档。")
    mgr = manager_with(tmp_path)

    a = mgr.get_index_prompt(query="做个表格")
    b = mgr.get_index_prompt(query="合并PDF")
    assert a != b
    assert "xlsx" in a and "pdf" not in a
    assert "pdf" in b and "xlsx" not in b
    # Distinct queries must coexist as distinct keys.
    assert len(mgr._query_index_cache) == 2


def test_query_cache_is_bounded_lru(tmp_path):
    write_skill(tmp_path, "xlsx", description="电子表格。")
    mgr = manager_with(tmp_path)
    for i in range(SkillManager.QUERY_CACHE_CAP + 25):
        mgr.get_index_prompt(query=f"查询 {i}")
    assert len(mgr._query_index_cache) <= SkillManager.QUERY_CACHE_CAP


def test_broad_query_match_degrades_to_names_only(tmp_path):
    """A match that catches everything must not re-inflate the index."""
    for i in range(SkillManager.INDEX_DETAIL_CAP + 3):
        write_skill(tmp_path, f"skill{i}", description="通用技能 数据 分析")
    mgr = manager_with(tmp_path)
    index = mgr.get_index_prompt(query="数据分析")
    assert len(mgr.match_skills_by_query("数据分析")) > SkillManager.INDEX_DETAIL_CAP
    assert index.startswith("skill0")  # comma-joined names, no "- **name**"
    assert "Available Skills:" not in index


def test_full_index_keeps_trigger_lines(tmp_path):
    """First-turn index is where the model learns *when* to use a skill; it
    must not collapse to bare names."""
    for i in range(SkillManager.INDEX_DETAIL_CAP + 3):
        write_skill(tmp_path, f"skill{i}", description="通用技能 数据 分析")
    mgr = manager_with(tmp_path)
    full = mgr.get_index_prompt()
    assert "Available Skills:" in full
    assert "- **skill0**" in full


# ------------------------------------------------- B2: declared trigger words


def test_parse_trigger_keywords_reads_all_declarations(tmp_path):
    md = tmp_path / "SKILL.md"
    md.write_text(
        "---\n"
        "name: demo\n"
        "description: d\n"
        "trigger_keywords:\n"
        "  - 表格\n"
        "triggers:\n"
        "  keywords: [电子表格]\n"
        "  intent_hints: [做报表]\n"
        "  patterns: ['^导出.*csv$']\n"
        "trigger: 创建表格，统计\n"
        "---\n"
        "body\n",
        encoding="utf-8",
    )
    words = SkillManager._parse_trigger_keywords(md.read_text(encoding="utf-8"))
    assert "表格" in words
    assert "电子表格" in words
    assert "做报表" in words
    assert "创建表格" in words
    assert "统计" in words
    # Regexes must not leak into the literal channel.
    assert not any("^导出" in w for w in words)


def test_declared_keywords_drive_matching_without_trigger_map(tmp_path):
    """The prompt layer used to consult only the hard-coded English
    _TRIGGER_MAP, so Chinese declarations had no effect there."""
    write_skill(
        tmp_path,
        "myxlsx",
        description="电子表格处理。",
        frontmatter="trigger_keywords:\n  - 做报表\n  - 数据透视\n",
    )
    mgr = manager_with(tmp_path)
    assert mgr.match_skills_by_query("帮我做报表") == ["myxlsx"]
    assert mgr.match_skills_by_query("数据透视分析") == ["myxlsx"]


def test_trigger_keywords_survive_load_and_hot_reload(tmp_path):
    write_skill(
        tmp_path,
        "alpha",
        description="表格。",
        frontmatter="trigger_keywords:\n  - 报表\n",
    )
    mgr = manager_with(tmp_path)
    assert "报表" in mgr.get_skill("alpha")["trigger_keywords"]


# ------------------------------------------------------- B3: Chinese matching


def test_query_tokens_produces_cjk_bigrams():
    tokens = SkillManager._query_tokens("读取文档")
    assert "读取" in tokens
    assert "文档" in tokens
    assert "读取文档" in tokens
    latin = SkillManager._query_tokens("merge the PDF file")
    assert "merge" in latin and "pdf" in latin


def test_chinese_query_matches_by_description(tmp_path):
    write_skill(tmp_path, "pdf", description="PDF 文件的读取、合并、拆分。")
    write_skill(tmp_path, "news", description="查找最新新闻并摘要。")
    mgr = manager_with(tmp_path)
    assert mgr.match_skills_by_query("读取文档") == ["pdf"]
    assert mgr.match_skills_by_query("最新新闻") == ["news"]


def test_no_match_fallback_is_not_the_full_catalogue(tmp_path):
    """Fallback used to return every enabled skill, which made the
    query-filtered index as big as the unfiltered one."""
    for i in range(SkillManager.FALLBACK_SKILL_CAP + 6):
        write_skill(tmp_path, f"zzskill{i}", description="专有领域技能")
    mgr = manager_with(tmp_path)
    matched = mgr.match_skills_by_query("完全无关的火星话")
    assert matched, "fallback must still offer something"
    assert len(matched) <= SkillManager.FALLBACK_SKILL_CAP
    assert len(matched) < len(mgr.list_skills())


def test_empty_query_uses_fallback_not_everything(tmp_path):
    for i in range(SkillManager.FALLBACK_SKILL_CAP + 6):
        write_skill(tmp_path, f"zzskill{i}", description="专有领域技能")
    mgr = manager_with(tmp_path)
    assert 0 < len(mgr.match_skills_by_query("")) < len(mgr.list_skills())


# ------------------------------------------------- B5: regex pattern channel


def test_patterns_are_collected_as_regexes_not_keywords(tmp_path):
    skill_dir = write_skill(
        tmp_path,
        "cron",
        description="定时任务。",
        frontmatter="triggers:\n  patterns:\n    - '^定时.*任务$'\n    - '每周.*提醒'\n",
    )
    sel = SkillSelector()
    sel.build_index([{"name": "cron", "dir": str(skill_dir), "description": "定时任务。"}])
    assert sel.skill_patterns["cron"] == ["^定时.*任务$", "每周.*提醒"]
    # And they are gone from the literal keyword weights.
    weights = sel._kw_weight["cron"]
    assert not any("^" in k for k in weights)


def test_pattern_regex_channel_scores(tmp_path):
    skill_dir = write_skill(
        tmp_path,
        "cron",
        description="定时任务。",
        frontmatter="triggers:\n  patterns:\n    - '每周.*提醒'\n",
    )
    sel = SkillSelector()
    sel.build_index([{"name": "cron", "dir": str(skill_dir), "description": "定时任务。"}])
    # Only the regex can produce this match: no literal keyword is present.
    assert sel._score_skill("每周给我一次提醒", "cron") > 0
    assert sel._score_skill("完全无关的句子", "cron") == 0


def test_invalid_pattern_is_dropped_not_fatal(tmp_path):
    skill_dir = write_skill(
        tmp_path,
        "broken",
        description="x",
        frontmatter="triggers:\n  patterns:\n    - '[unclosed'\n    - '正常模式'\n",
    )
    sel = SkillSelector()
    sel.build_index([{"name": "broken", "dir": str(skill_dir), "description": "x"}])
    assert sel.skill_patterns["broken"] == ["正常模式"]


def test_build_index_clears_patterns(tmp_path):
    skill_dir = write_skill(
        tmp_path,
        "cron",
        description="定时任务。",
        frontmatter="triggers:\n  patterns:\n    - '提醒'\n",
    )
    sel = SkillSelector()
    sel.build_index([{"name": "cron", "dir": str(skill_dir), "description": "定时任务。"}])
    assert sel.skill_patterns
    sel.build_index([])
    assert sel.skill_patterns == {}


# ------------------------------------------- B6: index_hint authoring script


def test_house_style_hint_is_a_trigger():
    """Authored hints are written "当…做X时使用。" (26 of them in
    scripts/apply_skill_index_hints.py), so the marker list has to accept that
    phrasing and not only "当用户…": dev flagged co-agent as silent on
    2026-10-21 because "当任务需要其他智能体帮忙时使用" matched no marker."""
    assert has_trigger_sentence(
        {"index_hint": "当任务需要其他智能体帮忙、咨询、协作、委托时使用。"},
    )
    assert has_trigger_sentence(
        {"description": "抓取网页数据。当页面需要登录时使用。"},
    )
    assert not has_trigger_sentence({"description": "Tools for PDF work."})


def test_apply_hint_inserts_and_is_idempotent(tmp_path):
    md = tmp_path / "SKILL.md"
    md.write_text("---\nname: x\ndescription: d\n---\nbody\n", encoding="utf-8")
    assert apply_hint(md, "当用户要测试时使用。") == "applied"
    content = md.read_text(encoding="utf-8")
    assert 'index_hint: "当用户要测试时使用。"' in content
    assert content.startswith("---\n") and "\n---\nbody" in content
    # Second run must not add a second hint.
    assert apply_hint(md, "当用户要测试时使用。") == "skipped"
    assert content.count("index_hint:") == 1


def test_apply_hint_rejects_files_without_frontmatter(tmp_path):
    md = tmp_path / "SKILL.md"
    md.write_text("no frontmatter here\n", encoding="utf-8")
    assert apply_hint(md, "x") == "no-frontmatter"


def test_authored_hint_wins_in_index(tmp_path):
    write_skill(
        tmp_path,
        "alpha",
        description="很长的描述" * 20,
        frontmatter='index_hint: "当用户要甲事时使用。"\n',
    )
    mgr = manager_with(tmp_path)
    index = mgr.get_index_prompt()
    assert "当用户要甲事时使用。" in index
    assert "很长的描述" * 20 not in index


# ------------------------------------------------- B7: index vs loadable set


def test_extra_dirs_bring_pool_skills_into_the_index(tmp_path):
    """The loader resolves skills from pool + user + agent manifests, while
    SkillManager scanned skills_dir only: 5 skills in the index, 21 loadable."""
    ws = tmp_path / "ws"
    pool = tmp_path / "pool"
    write_skill(ws, "own_skill", description="本地技能。")
    write_skill(pool, "xlsx", description="电子表格。")
    write_skill(pool, "pdf", description="PDF 文档。")
    mgr = SkillManager(ws, extra_dirs=[pool])
    asyncio.run(mgr.discover())
    names = {s["name"] for s in mgr.list_skills()}
    assert names == {"own_skill", "xlsx", "pdf"}


def test_workspace_skill_overrides_pool_copy(tmp_path):
    ws = tmp_path / "ws"
    pool = tmp_path / "pool"
    write_skill(ws, "xlsx", description="工作区版本描述。")
    write_skill(pool, "xlsx", description="技能池版本描述。")
    mgr = SkillManager(ws, extra_dirs=[pool])
    asyncio.run(mgr.discover())
    # skills_dir is scanned last, so the workspace copy wins.  Compare path,
    # not description: apply_descriptions_from_pack() rewrites descriptions by
    # skill name as part of discover().
    assert Path(mgr.get_skill("xlsx")["path"]) == ws / "xlsx"


def test_only_filter_restricts_index_to_loadable_skills(tmp_path):
    ws = tmp_path / "ws"
    pool = tmp_path / "pool"
    write_skill(ws, "own_skill", description="本地技能。")
    write_skill(pool, "xlsx", description="电子表格。")
    mgr = SkillManager(ws, extra_dirs=[pool])
    asyncio.run(mgr.discover())

    index = mgr.get_index_prompt(only={"own_skill"})
    assert "own_skill" in index
    assert "xlsx" not in index


def test_only_filter_changes_are_not_served_from_cache(tmp_path):
    """One manager instance is reused across turns; a turn whose loadable set
    changed must not get the previous set's cached index."""
    ws = tmp_path / "ws"
    pool = tmp_path / "pool"
    write_skill(ws, "own_skill", description="本地技能。")
    write_skill(pool, "xlsx", description="电子表格。")
    mgr = SkillManager(ws, extra_dirs=[pool])
    asyncio.run(mgr.discover())

    assert "xlsx" not in mgr.get_index_prompt(only={"own_skill"})
    assert "xlsx" in mgr.get_index_prompt(only={"own_skill", "xlsx"})


def test_missing_extra_dir_is_ignored(tmp_path):
    ws = tmp_path / "ws"
    write_skill(ws, "own_skill", description="本地技能。")
    mgr = SkillManager(ws, extra_dirs=[tmp_path / "nope"])
    asyncio.run(mgr.discover())
    assert {s["name"] for s in mgr.list_skills()} == {"own_skill"}


def test_core_passes_loadable_set_to_the_index():
    """Guard the wiring: the prompt layer must filter by toolkit.skills."""
    src = (
        Path(__file__).resolve().parents[2] / "coapis" / "agents" / "core.py"
    ).read_text(encoding="utf-8")
    assert "toolkit.skills.keys()" in src
    assert "only=loadable" in src


def test_skills_service_runs_discover_on_startup():
    """``discover()`` had no call site in the whole repo, so _skills stayed
    empty and [AVAILABLE SKILLS] was empty on every turn.  Guard the
    post_init wiring so it cannot silently regress."""
    src = (
        Path(__file__).resolve().parents[2] / "coapis" / "agents" / "workspace.py"
    ).read_text(encoding="utf-8")
    assert "post_init=lambda ws, mgr: mgr.discover()" in src
    assert "extra_dirs=_skill_scan_extra_dirs(ws)" in src


# ------------------------------------------- B8: YAML frontmatter semantics


def _write_raw(root: Path, name: str, frontmatter: str) -> Path:
    skill_dir = root / name
    skill_dir.mkdir(parents=True, exist_ok=True)
    (skill_dir / "SKILL.md").write_text(
        f"---\n{frontmatter}---\nbody\n", encoding="utf-8"
    )
    return skill_dir


def test_folded_description_reaches_the_index(tmp_path):
    """``description: >`` is a YAML block scalar: the value is on the lines
    *below* the key.  The line scanner read it as an empty string, so 9 of 56
    real skills had **no index line at all** -- the model saw a bare name."""
    _write_raw(
        tmp_path,
        "demo-report",
        "name: demo-report\n"
        "description: >\n"
        "  撰写工作汇报与分析材料。\n"
        "  当用户需要整理材料成文时使用。\n",
    )
    mgr = manager_with(tmp_path)
    skill = mgr.get_skill("demo-report")
    assert skill is not None
    assert "撰写工作汇报" in skill["description"]
    assert skill["has_trigger"] is True
    index = mgr.get_index_prompt()
    assert "撰写工作汇报" in index


def test_literal_description_is_parsed(tmp_path):
    _write_raw(
        tmp_path,
        "factory",
        "name: factory\n"
        "description: |\n"
        "  第一行\n"
        "  第二行\n",
    )
    mgr = manager_with(tmp_path)
    desc = mgr.get_skill("factory")["description"]
    assert "第一行" in desc and "第二行" in desc


def test_block_scalar_index_hint_is_parsed(tmp_path):
    _write_raw(
        tmp_path,
        "alpha",
        "name: alpha\n"
        "description: 描述。\n"
        "index_hint: >\n"
        "  当用户要编排开发流程时使用。\n",
    )
    mgr = manager_with(tmp_path)
    assert mgr.get_skill("alpha")["index_hint"] == "当用户要编排开发流程时使用。"
    assert "当用户要编排开发流程时使用。" in mgr.get_index_prompt()


def test_broken_yaml_falls_back_to_the_line_scan(tmp_path):
    """A frontmatter the YAML parser rejects must not delete the skill: the
    old line scan is kept as the fallback path."""
    _write_raw(
        tmp_path,
        "demo",
        'name: demo\ndescription: "unclosed quote\n',
    )
    mgr = manager_with(tmp_path)
    skill = mgr.get_skill("demo")
    assert skill is not None
    assert skill["name"] == "demo"


def test_non_string_description_does_not_leak_yaml_structure(tmp_path):
    """``description:`` with nested keys parses to a dict; str() of it would
    put ``{'zh': ...}`` into the system prompt."""
    _write_raw(
        tmp_path,
        "demo",
        "name: demo\ndescription:\n  zh: 中文描述\n  en: english\n",
    )
    mgr = manager_with(tmp_path)
    skill = mgr.get_skill("demo")
    assert skill["name"] == "demo"
    assert skill["description"] == ""
    assert "zh:" not in mgr.get_index_prompt()


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-q"]))
