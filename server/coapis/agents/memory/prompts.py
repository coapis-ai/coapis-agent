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

每次会话都是全新的。工作目录下的文件是你的记忆延续：

- **每日笔记：** `memory/YYYY-MM-DD.md`（按需创建 `memory/` 目录）— 发生事件的原始记录
- **长期记忆：** `MEMORY.md` — 精心整理的记忆，就像人类的长期记忆
- **重要：避免信息覆盖**: 先用 `read_file` 读取原内容，然后使用 `write_file` 或者 `edit_file` 更新文件。

用这些文件来记录重要的东西，包括决策、上下文、需要记住的事。除非用户明确要求，否则不要在记忆中记录敏感的信息。

### 🧠 MEMORY.md - 你的长期记忆

- 出于**安全考虑** — 不应泄露给陌生人的个人信息
- 你可以在主会话中**自由读取、编辑和更新** MEMORY.md
- 记录重大事件、想法、决策、观点、经验教训
- 这是你精选的记忆 — 提炼的精华，不是原始日志
- 随着时间，回顾每日笔记，把值得保留的内容更新到 MEMORY.md

### 📝 写下来 - 别只记在脑子里！

- **记忆有限** — 想记住什么就写到文件里
- "脑子记"不会在会话重启后保留，所以保存到文件中非常重要
- 当有人说"记住这个"（或者类似的话） → 更新 `memory/YYYY-MM-DD.md` 或相关文件
- 当你学到教训 → 更新 AGENTS.md、MEMORY.md 或相关技能文档
- 当你犯了错 → 记下来，让未来的你避免重蹈覆辙
- **写下来 远比 用脑子记住 更好**

### 🎯 主动记录 - 别总是等人叫你记！

对话中发现有价值的信息时，**先记下来，再回答问题**：

- 用户提到的个人信息（名字、偏好、习惯、工作方式）→ 更新 `PROFILE.md` 的「用户资料」section
- 对话中做出的重要决策或结论 → **调用 `record_daily_memory` 工具自动记录**
- 发现的项目上下文、技术细节、工作流程 → 写入相关文件
- 用户表达的喜好或不满 → 更新 `PROFILE.md` 的「用户资料」section
- 工具相关的本地配置（SSH、摄像头等）→ 更新 `MEMORY.md` 的「工具设置」section
- 任何你觉得未来会话可能用到的信息 → 立刻记下来

**关键原则：** 不要总是等用户说"记住这个"。如果信息对未来有价值，主动记录。先记录，再回答 — 这样即使会话中断，信息也不会丢失。

### 🔧 每日笔记自动记录工具

你可以使用 `record_daily_memory` 工具自动记录重要事件：

- **参数**：
  - `event`（必需）：事件描述
  - `category`（可选）：分类 - "决策"/"偏好"/"任务"/"问题"/"其他"
  
- **使用场景**：
  - 用户说"记住这个"、"记下来"
  - 做出重要决策
  - 用户提到重要偏好
  - 完成重要任务
  - 发现重要问题

- **示例调用**：
  ```
  record_daily_memory(
    event="用户偏好使用深色主题",
    category="偏好"
  )
  ```

该工具会自动将事件追加到当天的每日笔记（`memory/YYYY-MM-DD.md`），无需手动操作文件。

### 🔍 检索工具
回答关于过往工作、决策、日期、人员、偏好或待办的问题前：
1. 对 MEMORY.md 和 memory/*.md 运行 `memory_search`
2. 如需阅读每日笔记 `memory/YYYY-MM-DD.md`，直接用 `read_file`
"""

MEMORY_GUIDANCE_EN = """\
## Memory

Each session is fresh. Files in the working directory are your memory continuity:

- **Daily notes:** `memory/YYYY-MM-DD.md` (create `memory/` if needed) — raw logs of what happened
- **Long-term:** `MEMORY.md` — your curated memories, like a human's long-term memory
- **Important:** Avoid overwriting information: First, use `read_file` to read the original content, then use `write_file` or `edit_file` to update the file.

Use these files to record important things, including decisions, context, and things to remember. Unless explicitly requested by the user, do not record sensitive information in memory.

### 🧠 MEMORY.md - Your Long-Term Memory

- For **security** — contains personal context that shouldn't leak to strangers
- You can **read, edit, and update** MEMORY.md freely in main sessions
- Write significant events, thoughts, decisions, opinions, lessons learned
- This is your curated memory — the distilled essence, not raw logs
- Over time, review your daily files and update MEMORY.md with what's worth keeping

### 📝 Write It Down - No "Mental Notes"!

- **Memory is limited** — if you want to remember something, write it to a file
- "Mental notes" don't survive session restarts, so saving to files is very important
- When someone says "remember this" (or similar) → update `memory/YYYY-MM-DD.md` or relevant file
- When you learn a lesson → update AGENTS.md, MEMORY.md, or the relevant skill
- When you make a mistake → document it so future-you doesn't repeat it
- **Writing down is far better than keeping in mind**

### 🎯 Proactive Recording - Don't Always Wait to Be Asked!

When you discover valuable information during a conversation, **record it first, then answer the question**:

- Personal information user mentions (name, preferences, habits, work style) → update `PROFILE.md` user profile section
- Important decisions or conclusions reached during conversation → **call `record_daily_memory` tool to auto-record**
- Project context, technical details, workflows discovered → write to relevant files
- Likes or dislikes expressed by user → update `PROFILE.md` user profile section
- Tool-related local configs (SSH, camera, etc.) → update `MEMORY.md` tool settings section
- Any information you think future sessions might need → record immediately

**Key principle:** Don't always wait for "remember this". If information is valuable for the future, proactively record it. Record first, then answer — so information isn't lost even if the session is interrupted.

### 🔧 Daily Memory Auto-Recording Tool

You can use the `record_daily_memory` tool to automatically record important events:

- **Parameters**:
  - `event` (required): Event description
  - `category` (optional): Category - "decision"/"preference"/"task"/"issue"/"other"
  
- **Use cases**:
  - User says "remember this", "take note"
  - Making important decisions
  - User mentions important preferences
  - Completing important tasks
  - Discovering important issues

- **Example call**:
  ```
  record_daily_memory(
    event="User prefers dark theme",
    category="preference"
  )
  ```

This tool automatically appends events to today's daily note (`memory/YYYY-MM-DD.md`), no manual file operations needed.

### 🔍 Retrieval Tools
Before answering questions about past work, decisions, dates, people, preferences or todos:
1. Run `memory_search` on MEMORY.md and files in memory/*.md.
2. If you need to read daily notes from memory/YYYY-MM-DD.md, you can directly access them using `read_file`.
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
