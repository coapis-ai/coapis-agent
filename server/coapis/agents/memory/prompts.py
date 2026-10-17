# -*- coding: utf-8 -*-
# flake8: noqa: E501
# pylint: disable=line-too-long
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

"""Dream memory optimization prompts."""

# Memory guidance prompts - explains how agent should use memory files
MEMORY_GUIDANCE_ZH = """\
## 记忆

每次会话都是全新的，工作目录下的文件是你的记忆延续：

- `memory/YYYY-MM-DD.md`：当日原始记录；`MEMORY.md`：精选的长期记忆
- 更新先 `read_file` 再 `write_file`/`edit_file`，**不要覆盖**
- 不主动记录敏感信息

**主动记录**——别等用户说"记住这个"。用户画像与偏好 → 更新 `PROFILE.md`；
决策/结论/任务进展/踩过的坑 → 调 `record_daily_memory(event, category)`
写入当日笔记（category：决策/偏好/任务/问题/其他）。

**检索**——回答涉及过往工作、决策、日期、人物、偏好、待办的问题前，先
`memory_search`；要读某天笔记，直接 `read_file` 读 `memory/YYYY-MM-DD.md`。
"""

MEMORY_GUIDANCE_EN = """\
## Memory

Every session starts fresh; the files in your working directory are your continuity:

- `memory/YYYY-MM-DD.md`: raw daily log; `MEMORY.md`: curated long-term memory
- Update with `read_file` then `write_file`/`edit_file` — **never overwrite blindly**
- Do not proactively record sensitive information

**Record proactively** — do not wait for "remember this". User profile and preferences →
update `PROFILE.md`; decisions, conclusions, task progress, pitfalls hit → call
`record_daily_memory(event, category)` (category: decision/preference/task/issue/other).

**Search** — before answering about prior work, decisions, dates, people, preferences or
todos, call `memory_search`; to read a day's notes, `read_file` `memory/YYYY-MM-DD.md`.
"""

# Dream optimization prompts - instructs agent to consolidate memories
DREAM_OPTIMIZATION_ZH = """\
现在进入梦境状态，对长期记忆进行优化整理。请读取今日日志与现有长期记忆，在梦境中提炼高价值增量信息并去重合并，最终覆写至 `MEMORY.md`，确保长期记忆文件保持最新、精简、无冗余。

当前日期: {current_date}

【梦境优化原则】
1. 极简去冗：严禁记录流水账、Bug修复细节或单次任务。仅保留"核心业务决策"、"确认的用户偏好"与"高价值可复用经验"。
2. 状态覆写：若发现状态变更（如技术栈更改、配置更新），必须用新状态替换旧状态，严禁新旧矛盾信息并存。
3. 归纳整合：主动将零碎的相似规则提炼、合并为通用性强的独立条目。
4. 废弃剔除：主动删除已被证伪的假设或不再适用的陈旧条目。

【梦境执行步骤】
步骤 1 [加载]：调用 `read` 工具，读取根目录下的 `MEMORY.md` 以及当天的日志文件 `memory/YYYY-MM-DD.md`。
步骤 2 [梦境提纯]：在梦境中对比新旧内容，严格按照【梦境优化原则】进行去重、替换、剔除和合并，生成一份全新的记忆内容。
步骤 3 [落盘]：调用 `write` 或 `edit` 工具，将整理后全新的 Markdown 内容覆盖写入到 `MEMORY.md` 中（请保持清晰的层级与列表结构）。
步骤 4 [苏醒汇报]：从梦境中苏醒后，在对话中向我简短汇报：1) 新增/沉淀了哪些核心记忆；2) 修正/删除了哪些过期内容。"""

DREAM_OPTIMIZATION_EN = """\
Enter dream state for memory optimization. Read today's logs and existing long-term memory, extract high-value incremental information in your dream state, deduplicate and merge, and ultimately overwrite `MEMORY.md`. Ensure the long-term memory file remains up-to-date, concise, and non-redundant.

Current date: {current_date}

[Dream Optimization Principles]
1. Extreme Minimalism: Strictly forbid recording daily routines, specific bug-fix details, or one-off tasks. Retain ONLY 'core business decisions', 'confirmed user preferences', and 'high-value reusable experiences'.
2. State Overwrite: If a state change is detected (e.g., tech stack changes, config updates), you MUST replace the old state with the new one. Contradictory old and new information must not coexist.
3. Inductive Consolidation: Proactively distill and merge fragmented, similar rules into highly universal, independent entries.
4. Deprecation: Proactively delete hypotheses that have been proven false or outdated entries that no longer apply.

[Dream Execution Steps]
Step 1 [Load]: Invoke the `read` tool to read `MEMORY.md` in the root directory and today's log file `memory/YYYY-MM-DD.md`.
Step 2 [Dream Purification]: Compare the old and new content in your dream state. Strictly follow the [Dream Optimization Principles] to deduplicate, replace, remove, and merge, generating entirely new memory content.
Step 3 [Save]: Invoke the `write` or `edit` tool to overwrite the newly organized Markdown content into `MEMORY.md` (maintain clear hierarchy and list structures).
Step 4 [Awake Report]: After waking from your dream, briefly report to me in the chat: 1) What core memories were newly added/consolidated; 2) What outdated content was corrected/deleted."""
