#!/usr/bin/env python3
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

"""Give every skill a one-line *trigger* in the system-prompt index.

Why: the index line the model sees on every turn is built from
``index_hint`` when present, otherwise a 60-char truncation of
``description`` (see ``SKILL_INDEX_HINT_CHARS`` in
``coapis/skills/manager.py``).  Truncating a description cuts off mid-sentence
— measured on dev, 19 skills produced 0 authored hints, so the model was
reading clipped prose like "专业的党政机关公文写作指南。当用户需要撰写、修改或审核党"
and had to guess the boundary.

An authored hint says *when to use the skill*, which is the only thing the
index has to say; the body is read on demand.

The skill pool is runtime data (``get_skill_pool_dir()``), not repo content,
so this script is the reproducible record of the change: run it against any
pool and every environment gets the same hints.  It is idempotent — a skill
that already declares ``index_hint`` is left untouched, so author edits always
win.

Usage::

    python scripts/apply_skill_index_hints.py --pool /path/to/skill_pool            # apply
    python scripts/apply_skill_index_hints.py --pool /path/to/skill_pool --dry-run  # preview
    python scripts/apply_skill_index_hints.py --pool /path/to/skill_pool --backup DIR

A timestamped copy of every touched SKILL.md is written to ``--backup``
(default ``<pool>/.index_hint_backup/<UTC timestamp>/``) so the change is
reversible without deleting anything.
"""

from __future__ import annotations

import argparse
import datetime
import shutil
import sys
from pathlib import Path

#: Skill → trigger line.  Kept short (≤ ~40 CJK chars) because the index pays
#: on *every* turn; "when to use" only, never a feature list.
INDEX_HINTS: dict[str, str] = {
    "browser-anything": "当用户要打开/浏览网页、网页截图、点击填表、登录、抓取网页时使用。",
    "channel_message": "当用户要主动给用户、会话或频道发消息、推送通知时使用。",
    "co-agent": "当任务需要其他智能体帮忙、咨询、协作、委托或跑后台任务时使用。",
    "coapis_code_checked": "当用户要求审查代码、定位 bug 或报错、分析代码质量、重构时使用。",
    "coapis_qa_guidance": "当用户询问 CoApis 怎么安装、配置、使用、能做什么时使用。",
    "cron": "当用户要定时或周期执行任务、设置提醒、管理定时任务时使用。",
    "dingtalk_channel": "当用户要接入或配置钉钉、钉钉机器人、钉钉频道时使用。",
    "docx": "当用户要创建、读取、编辑 Word 文档（.docx），写报告、信函、模板时使用。",
    "expense-reimbursement-assistant": "当用户要报销费用、处理发票、出差报销、匹配发票与支付记录时使用。",
    "file_reader": "当用户要读取、查看、摘要文本类文件内容时使用。",
    "himalaya": "当用户要收发、阅读、搜索邮件（IMAP/SMTP 邮箱）时使用。",
    "make_plan": "当用户要制定分步骤执行计划、规划任务、要一份可落地方案时使用。",
    "news": "当用户要查新闻、最新消息、热点或头条摘要时使用。",
    "official-document-writing": "当用户要撰写、修改、审核党政机关公文（请示、通知、函、纪要）时使用。",
    "pdf": "当用户要读取、合并、拆分、加水印、加密 PDF，或 OCR 扫描件、PDF 转图片时使用。",
    "pptx": "当用户要创建、读取、编辑 PPT、演示文稿、幻灯片时使用。",
    "rural-land-market-scheme": "当用户要起草、修改、审核农村集体经营性建设用地入市方案及配套公文时使用。",
    "web-search": "当用户要搜索网页、查找资料、搜一下或查一下某个主题时使用。",
    "xlsx": "当用户要创建、编辑、分析 Excel 或 CSV 电子表格数据时使用。",

    # Skills installed into agent workspaces (the directories SkillManager
    # actually reads: workspaces/{user}/skills/, agents/{agent_id}/skills/).
    # The skill pool above is the catalogue; these are what gets loaded.
    "guidance": "当用户询问 CoApis 安装、配置、使用、架构、故障排查或产品介绍时使用。",
    "attribute-structure-processor": "当用户要从 GIS 属性结构 Word 文档提取属性表、解析图层并生成标准化 Excel 时使用。",
    "gdb-creator-from-excel": "当用户要从 Excel 属性结构表创建 GIS 数据（FileGDB、Shapefile、要素类、坐标系）时使用。",
    "multi_source_research_workflow": "当任务需要多源资料收集：联网搜索、本地文件检索、网页抓取并综合分析时使用。",
    "plan-writing-assistant": "当用户要撰写全域土地综合整治实施方案、项目策划文档初稿时使用。",
    "test--ad-default": "当用户要求代码审查、定位 bug 或报错、代码走读、架构评审、修复问题时使用。",
    "markdown-clean-body": "当用户要清洗 markdown 正文，去除网页头部、导航、广告、友情链接时使用。",
    # --- 2026-10-21: the rest of the pools.  Measured on dev, 56 loaded skills
    # had no authored trigger line at all (index lines came from truncated
    # descriptions, 9 of them empty because ``description: >`` was never
    # parsed), so the model had a name and nothing to match a request against.
    "QA_source_index": "当用户询问 CoApis 功能的实现位置、配置项或源码索引时使用。",
    "aux-agent-growing": "当用户要求智能体自我成长、复盘沉淀经验、优化自身能力时使用。",
    "axu-code-checked": "当用户要求代码审查、排查报错、定位问题根因、评审重构方案时使用。",
    "axu-data-analysis": "当用户要求整理数据、统计分析、做图表、分析数据趋势时使用。",
    "axu-policy-interpretation": "当用户要求解读政策文件、法规合规要求、提炼政策落地要点时使用。",
    "axu-report-writing": "当用户要求写报告、汇报材料、工作总结、调研分析报告时使用。",
    "axu-requirements-analysis": "当用户要求分析需求、拆解问题、梳理痛点、编写需求文档时使用。",
    "axu-solution-design": "当用户要求出方案、架构设计、规划实施路径、可行性评估时使用。",
    "axu-text-polishing": "当用户要求润色文字、改写措辞、调整语气、去除 AI 味时使用。",
    "browser_use": "当用户要打开网页、点击填表、截图抓取、做浏览器自动化时使用。",
    "browser-use": "当用户要打开网页、点击填表、截图抓取、做浏览器自动化时使用。",
    "browser_cdp": "当用户要求连接本机 Chrome、接管已有浏览器、使用 CDP 调试时使用。",
    "browser_visible": "当用户要求打开可见浏览器窗口、有头模式演示、界面录制时使用。",
    "chat_with_agent": "当用户点名要某个智能体参与，或需要咨询其他智能体、寻求帮助时使用。",
    "coapis_source_index": "当用户询问 CoApis 功能、配置、架构、源码位置需要快速定位文档时使用。",
    "dingtalk_channel_connect": "当用户要求接入钉钉、配置钉钉机器人、处理钉钉渠道消息时使用。",
    "env_manager": "当用户要求部署、重建容器、重启服务、更新开发或生产环境时使用。",
    "humanizer-academic-zh": "当用户要求把中文文本改得自然、降低 AI 味、降低 AIGC 检测率时使用。",
    "long-running-agent-harness": "当任务需要长时间运行、多阶段推进、断点续跑、生成执行报告时使用。",
    "make-skill": "当用户要求把当前流程、方法、经验固化成可复用技能时使用。",
    "markitdown": "当用户要求把本地文档（docx、pdf、xlsx、pptx）转成 Markdown 时使用。",
    "multi_agent_collaboration": "当用户要求多智能体协作，或需要其他智能体的专长、上下文时使用。",
    "self-improvement": "当用户要求总结经验教训、改进智能体工作方式、沉淀长期改进项时使用。",
    "skill-creator": "当用户要求创建、改进、评测一个技能包时使用。",
    "skill-vetter": "当用户要求安装或引入第三方技能时，先用本技能做安全审查。",
    "superpowers-factory-bridge": "当用户发起较大开发任务，需要 TDD、工厂流程编排时使用。",
    "using-superpowers": "当用户询问技能如何调用、有哪些技能可用、如何组合技能工作时使用。",
}


def _split_frontmatter(content: str) -> tuple[str, str, str] | None:
    """Return (head, frontmatter, tail) for a SKILL.md, or None if it has no
    parseable ``---`` frontmatter block."""
    if not content.startswith("---"):
        return None
    parts = content.split("---", 2)
    if len(parts) < 3:
        return None
    return parts[0], parts[1], parts[2]


def apply_hint(md_file: Path, hint: str) -> str:
    """Insert ``index_hint`` into one SKILL.md.

    Returns ``"applied"``, ``"skipped"`` (already declared) or ``"no-frontmatter"``.
    """
    content = md_file.read_text(encoding="utf-8", errors="replace")
    split = _split_frontmatter(content)
    if split is None:
        return "no-frontmatter"
    _head, front, tail = split
    for line in front.split("\n"):
        if line.startswith("index_hint:"):
            return "skipped"
    new_front = front.rstrip("\n") + f'\nindex_hint: "{hint}"\n'
    md_file.write_text("---" + new_front + "---" + tail, encoding="utf-8")
    return "applied"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--pool", required=True, help="skill pool directory")
    parser.add_argument("--dry-run", action="store_true", help="preview only")
    parser.add_argument(
        "--backup",
        default=None,
        help="directory for timestamped copies of touched SKILL.md files",
    )
    args = parser.parse_args(argv)

    pool = Path(args.pool)
    if not pool.is_dir():
        print(f"pool not found: {pool}", file=sys.stderr)
        return 2

    stamp = datetime.datetime.now(datetime.timezone.utc).strftime("%Y%m%d_%H%M%S")
    backup_dir = Path(args.backup) if args.backup else pool / ".index_hint_backup" / stamp

    counts = {"applied": 0, "skipped": 0, "no-frontmatter": 0, "missing": 0}
    for name, hint in sorted(INDEX_HINTS.items()):
        md_file = pool / name / "SKILL.md"
        if not md_file.exists():
            counts["missing"] += 1
            print(f"  MISSING  {name}")
            continue
        if args.dry_run:
            # Report what *would* happen without writing.
            content = md_file.read_text(encoding="utf-8", errors="replace")
            split = _split_frontmatter(content)
            has = split is not None and any(
                line.startswith("index_hint:") for line in split[1].split("\n")
            )
            print(f"  {'HAS' if has else 'ADD '}  {name}: {hint}")
            counts["skipped" if has else "applied"] += 1
            continue
        backup_dir.mkdir(parents=True, exist_ok=True)
        shutil.copy2(md_file, backup_dir / f"{name}.SKILL.md")
        result = apply_hint(md_file, hint)
        counts[result] += 1
        print(f"  {result:15} {name}")

    print()
    print(
        "applied={applied} skipped={skipped} no-frontmatter={no-frontmatter} "
        "missing={missing}".format(**counts),
    )

    # Report every skill the pool contains that the index will render from a
    # truncated description, so the gap is visible instead of silent.
    uncovered = []
    for skill_dir in sorted(p for p in pool.iterdir() if p.is_dir()):
        md_file = skill_dir / "SKILL.md"
        if not md_file.exists():
            continue
        content = md_file.read_text(encoding="utf-8", errors="replace")
        split = _split_frontmatter(content)
        has_hint = split is not None and any(
            line.startswith("index_hint:") for line in split[1].split("\n")
        )
        if not has_hint:
            uncovered.append(skill_dir.name)
    if uncovered:
        print(f"no index_hint ({len(uncovered)}): {', '.join(uncovered)}")
    else:
        print("no index_hint: none — every skill in this pool has a trigger line")

    if not args.dry_run and counts["applied"]:
        print(f"backup: {backup_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
