# CoApis 文件写入行为修复方案

## 一、问题诊断

### 1.1 根因定位

**核心结论：问题不在技能触发机制，而在 Agent 行为层。**

经过代码分析，文件写入工具（`write_file`、`edit_file`）是**内置工具**，在 agent 启动时通过 `_auto_register.py` **始终注册**，无需触发。Agent 有能力写文件，但选择了"建议路径"而不是"执行操作"。

**三层原因：**

| 层级 | 问题 | 代码位置 |
|------|------|----------|
| **提示词层** | AGENTS.md 缺少"用户要求保存文件时必须执行写入"的强制指令 | `build_system_prompt_from_working_dir()` |
| **路径约定层** | 没有明确的默认保存路径约定，Agent 不知道该存哪里 | 无统一规范 |
| **工具可用性层** | 工具已注册但 Agent 未被引导主动使用 | `_register_skills()` + `_load_on_demand_skills()` |

### 1.2 架构现状

```
用户请求 "保存为md文件"
        │
        ▼
Agent reply() → _load_on_demand_skills(query)  ← 仅匹配 on-demand 技能
        │                                          (文件工具是 builtin，不走这里)
        ▼
super().reply() → ReActAgent 决定是否调用工具
        │
        ▼  ← 问题出在这里：Agent 选择了"给建议"而非"调工具"
Agent 返回文本："建议保存到 files/xxx.md"
```

### 1.3 Workspace 路径体系

```
workspaces/
├── {username}/
│   ├── files/          ← 用户"我的空间"文件目录（真实存储）
│   ├── skills/         ← 用户级技能
│   ├── agents/         ← 用户级 agent
│   └── MEMORY.md
└── admin/
    └── files/

Agent workspace (e.g., agents/{agent_id}/):
├── files/ → workspaces/{username}/files/   ← symlink，Agent 可通过相对路径访问
├── AGENTS.md
├── SOUL.md
└── ...
```

文件 I/O 工具的路径解析逻辑（`file_io.py:_resolve_file_path`）：
- 绝对路径 → 直接使用
- 相对路径 → 从 `get_current_workspace_dir()` 解析（即 agent workspace）
- Agent workspace 有 `files/` symlink → 实际写入 `workspaces/{user}/files/`

---

## 二、修复方案

### 方案 A：修改 AGENTS.md（推荐，最小侵入）

在各用户的 `AGENTS.md` 中添加文件操作指令块。这是**用户空间**的修改，不影响系统代码。

**需要在默认 AGENTS.md 模板中添加的内容：**

```markdown
## 文件操作

当用户要求你保存、创建、写入任何文件时：

1. **必须执行操作**，不要只给路径建议。调用 `write_file` 工具实际创建文件。
2. **默认保存路径**：`files/`（即"我的空间"下的文件目录）。
   - 如果用户没有指定具体路径，使用 `files/` 作为默认根目录。
   - 例如：保存报告 → `files/report.md`，保存图片 → `files/images/xxx.png`。
3. **路径选择优先级**：
   - 用户明确指定的路径 > 用户暗示的合理路径 > `files/` 默认路径
4. **不要说"建议保存到..."**，直接保存，然后告诉用户文件已保存的位置。

示例：
- 用户："帮我把这段内容保存为md文件" → 直接调用 write_file，保存到 files/
- 用户："保存到 docs/ 目录" → 调用 write_file，路径为 files/docs/xxx.md
- 用户："帮我写一份报告" → 写完后直接保存，不问用户要不要保存
```

### 方案 B：系统级 Prompt 注入（适合所有用户）

在 `prompt.py` 的 `build_system_prompt_from_working_dir()` 中，**追加一段系统级指令**，确保所有 agent 都遵循文件操作规范。

**代码修改位置：** `server/coapis/agents/prompt.py`

```python
# 在 build_system_prompt_from_working_dir() 末尾，return prompt 之前追加：

_FILE_OPERATION_DIRECTIVE = """

## [系统指令] 文件操作规范

当用户要求你保存、创建、写入文件，或你的回复中包含需要持久化的内容（如代码、报告、分析结果）时：

1. **必须调用 write_file 工具执行写入**，不要只给出路径建议。
2. **默认保存路径为 `files/`**（用户"我的空间"目录）。
   - 用户未指定路径 → `files/{合理文件名}`
   - 用户指定相对路径 → `files/{用户路径}`
   - 用户指定绝对路径 → 按用户指定（在 workspace 安全检查内）
3. **文件命名**：使用有意义的文件名（如 `项目分析报告.md`），不要用 `untitled.md`。
4. **保存后告知**：告诉用户文件已保存到的具体路径。
5. **深度工作产物**：当完成复杂的分析、代码编写、报告撰写后，
   **主动保存**工作成果到 `files/`，不要等用户要求。
"""
```

### 方案 C：深度思考过程文件保存

在系统提示词中添加"过程文件"保存策略：

```markdown
## 过程文件保存

当你在处理复杂任务（多步骤分析、代码开发、报告编写）时：

1. **阶段产物保存**：每个关键阶段完成后，将中间产物保存到 `files/.temp/` 目录。
   - 例如：`files/.temp/analysis-draft.md`、`files/.temp/code-scaffold.py`
2. **最终产物保存**：任务完成时，将最终结果保存到 `files/` 并清理临时文件。
3. **不阻塞交互**：过程文件保存不应打断与用户的对话流，
   在工具调用中静默完成。
```

---

## 三、安全考量

### 3.1 现有安全机制（已完备）

| 防护层 | 机制 | 代码位置 |
|--------|------|----------|
| **工具守卫** | ToolGuardMixin 拦截敏感调用 | `tool_guard_mixin.py` |
| **文件守卫** | 阻止访问 `.coapis.secret` 等敏感目录 | `file_guardian.py` |
| **工作区守卫** | `is_within_workspace()` 路径检查（支持 symlink） | `workspace_guard.py` |
| **Shell 守卫** | 白名单/黑名单/危险模式匹配 | `workspace_guard.py` |

### 3.2 修复方案的安全性

- **方案 A**（AGENTS.md 修改）：纯提示词层，零安全风险。
- **方案 B**（系统指令注入）：在 prompt 层面约束，不绕过任何安全检查。`write_file` 工具本身受 `file_guardian` 和 `workspace_guard` 保护，写入 `files/` 是安全操作。
- **方案 C**（过程文件）：`.temp/` 目录在 workspace 内，受现有安全机制保护。建议在 `CleanupManager` 中添加 `.temp/` 的定期清理规则。

### 3.3 建议增加的防护

```python
# 在 file_guardian.py 的默认 deny list 中确认：
# files/ 目录是允许写入的（不在 deny list 中）
# .temp/ 子目录也在 workspace 内，安全可控
```

---

## 四、实施步骤

### 第一步：修改默认 AGENTS.md 模板（立即可做）

修改 `server/coapis/agents/utils/setup_utils.py` 中的默认 AGENTS.md 模板，添加文件操作指令。

### 第二步：系统级 Prompt 注入（推荐）

修改 `server/coapis/agents/prompt.py`，在 `build_system_prompt_from_working_dir()` 中追加文件操作规范。

### 第三步：CleanupManager 添加 .temp/ 清理

修改 `server/coapis/cleanup_manager.py`，添加 `files/.temp/` 的过期清理规则（默认 1 天）。

### 第四步：验证

1. 向 agent 发送"帮我把这段内容保存为 md 文件"
2. 验证 agent 是否调用 `write_file` 实际保存
3. 验证文件是否出现在 `workspaces/{user}/files/` 目录
4. 验证安全守卫未被绕过

---

## 五、总结

| 问题 | 根因 | 修复方案 | 侵入性 |
|------|------|----------|--------|
| 文件写入技能未触发 | Agent 有工具但未被引导使用 | AGENTS.md + 系统 prompt 指令 | 低 |
| 默认保存路径不明 | 无统一约定 | 明确 `files/` 为默认路径 | 低 |
| 过程文件未保存 | 缺少策略指引 | 添加过程文件保存指令 | 低 |
| 安全性 | 已完备，无需修改 | 确认即可 | 无 |

**核心修复：在提示词层建立"文件操作 = 必须执行"的行为约束，同时明确 `files/` 为默认保存路径。**
