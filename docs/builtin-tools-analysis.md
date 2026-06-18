# CoApis 内置工具全景分析

## 一、工具总览

共 **19 个内置工具**，分 **8 大类**，在 agent 启动时通过 `_auto_register.py` **始终注册**，不依赖技能触发。

```
auto_register.py → register_all_builtin_tools()
    ↓
  19 个工具全部进入 _registry（category="builtin"）
    ↓
  react_agent._create_toolkit() 从 registry 取出 → 注入 Toolkit
    ↓
  Agent 可直接调用，无需 on-demand 触发
```

## 二、工具分类与功能

### 📁 文件 I/O（4 个）— `file_io.py`

| 工具 | 功能 | 触发场景 | 路径解析 |
|------|------|----------|----------|
| `read_file` | 读取文件内容，支持行号范围 | "帮我看看这个文件"、"读取 xxx" | 相对路径 → workspace_dir |
| `write_file` | 创建或覆盖写入文件 | "保存为 md"、"写入 xxx" | 相对路径 → workspace_dir |
| `edit_file` | 查找替换（全量替换） | "把 A 改成 B"、"修改 xxx" | 相对路径 → workspace_dir |
| `append_file` | 追加内容到文件末尾 | "在末尾加上 xxx" | 相对路径 → workspace_dir |

**路径解析逻辑**（`_resolve_file_path`）：
- 绝对路径 → 直接使用
- 相对路径 → `get_current_workspace_dir() / file_path`
- workspace_dir 有 `files/` symlink → 实际写入 `workspaces/{user}/files/`

**安全防护**：
- `FilePathToolGuardian` 阻止读写 `.coapis.secret` 等敏感目录
- `WorkspaceGuard` 检查路径是否在 workspace 范围内

---

### 🔍 文件搜索（2 个）— `file_search.py`

| 工具 | 功能 | 触发场景 |
|------|------|----------|
| `grep_search` | 正则搜索文件内容 | "搜索 xxx"、"grep xxx" |
| `glob_search` | glob 模式查找文件 | "找所有 .py 文件" |

---

### 🖥️ Shell（1 个）— `shell.py`

| 工具 | 功能 | 触发场景 |
|------|------|----------|
| `execute_shell_command` | 执行 shell 命令（Linux: /bin/sh, Windows: cmd.exe） | 需要运行命令、安装包、编译等 |

**安全防护（三层）**：
1. **ShellEvasionGuardian** — 检测 shell 逃逸攻击（如 `$(...)`、反引号、管道到 shell 等）
2. **RuleBasedToolGuardian** — YAML 正则规则匹配（`rm -rf`、`chmod 777`、`curl|sh` 等）
3. **WorkspaceGuard** — 白名单/黑名单 + 危险模式正则

---

### 🌐 浏览器（1 个）— `browser_control.py`

| 工具 | 功能 | 触发场景 |
|------|------|----------|
| `browser_use` | 控制浏览器（30+ action） | "打开网页"、"截图"、"自动填表" |

**支持的 action**：
- `start` / `stop` — 启动/关闭浏览器
- `open` / `navigate` / `navigate_back` — 页面导航
- `click` / `type` / `fill_form` / `press_key` — 页面交互
- `snapshot` — 页面快照（Accessibility Tree）
- `eval` / `evaluate` — 执行 JavaScript
- `handle_dialog` — 处理弹窗
- `file_upload` — 文件上传
- `drag` — 拖拽
- `network_requests` — 网络请求监控
- `run_code` — 运行 Python 代码
- `install` — 安装浏览器
- `resize` — 调整窗口大小
- `console_messages` — 控制台日志

---

### 📸 桌面截图（1 个）— `desktop_screenshot.py`

| 工具 | 功能 | 触发场景 |
|------|------|----------|
| `desktop_screenshot` | 捕获桌面截图 | "截个屏"、"看看桌面" |

---

### 🖼️ 媒体查看（2 个）— `view_media.py`

| 工具 | 功能 | 触发场景 |
|------|------|----------|
| `view_image` | 查看/描述图片（支持多模态） | "看看这张图"、"描述图片" |
| `view_video` | 查看/描述视频（支持多模态） | "看看这个视频" |

**多模态探测**：首次使用时自动探测模型是否支持图片/视频理解。

---

### 📤 文件发送（1 个）— `send_file.py`

| 工具 | 功能 | 触发场景 |
|------|------|----------|
| `send_file_to_user` | 向用户发送文件 | "把文件发给我"、"下载 xxx" |

---

### ⏰ 时间（2 个）— `get_current_time.py`

| 工具 | 功能 | 触发场景 |
|------|------|----------|
| `get_current_time` | 获取当前时间 | "现在几点"、"今天日期" |
| `set_user_timezone` | 设置用户时区 | "我的时区是 UTC+8" |

---

### 📊 Token 用量（1 个）— `get_token_usage.py`

| 工具 | 功能 | 触发场景 |
|------|------|----------|
| `get_token_usage` | 查询当前会话的 token 消耗 | "用了多少 token"、"消耗统计" |

---

### 🤖 Agent 管理（5 个）— `agent_management.py` + `delegate_external_agent.py`

| 工具 | 功能 | 触发场景 |
|------|------|----------|
| `list_agents` | 列出所有已配置的 agent | "有哪些 agent"、"查看代理列表" |
| `chat_with_agent` | 同步发送消息给另一个 agent 并等待回复 | "问一下 xxx agent" |
| `submit_to_agent` | 异步提交任务给另一个 agent | "让 xxx 帮我处理" |
| `check_agent_task` | 检查异步任务状态 | "xxx 任务完成了吗" |
| `delegate_external_agent` | 委托外部 ACP agent 执行任务 | "调用外部 agent" |

---

## 三、触发机制

### 3.1 注册流程

```python
# _auto_register.py
from .registry import register_tool

# 启动时自动注册所有内置工具
register_tool(name="read_file", category="builtin")(read_file)
register_tool(name="write_file", category="builtin")(write_file)
# ... 19 个工具全部注册
```

### 3.2 调用流程

```
用户消息 → Agent.reply()
    ↓
_load_on_demand_skills(query)  ← 仅加载 on-demand 技能（文件工具不走这里）
    ↓
ReActAgent._reasoning()  ← LLM 推理决定是否调用工具
    ↓
ToolGuardMixin._acting()  ← 安全拦截检查
    ↓
  ├─ FilePathToolGuardian   → 文件路径安全
  ├─ RuleBasedToolGuardian  → 正则规则匹配
  ├─ ShellEvasionGuardian   → Shell 逃逸检测
  └─ WorkspaceGuard         → 工作空间边界检查
    ↓
工具执行 → 返回结果给 LLM
```

### 3.3 关键点

- **所有 19 个工具始终注册**，不需要"触发"
- **LLM 自主决策**是否调用哪个工具（ReAct 模式）
- **安全拦截在执行前**，不合规的调用会被 deny/guard/approve
- **技能 ≠ 工具**：技能是行为指导（SKILL.md），工具是原子操作

## 四、安全防护体系

### 4.1 三层守卫（ToolGuardMixin）

| 守卫 | 目标工具 | 防护内容 |
|------|----------|----------|
| `FilePathToolGuardian` | read_file, write_file, edit_file, append_file | 阻止读写 `.coapis.secret`、`auth.json` 等敏感文件 |
| `RuleBasedToolGuardian` | 所有工具 | YAML 正则规则匹配（`rm -rf`、`curl\|sh`、`chmod 777` 等） |
| `ShellEvasionGuardian` | execute_shell_command | 检测 shell 逃逸攻击（`$(...)`、反引号、管道注入等） |

### 4.2 WorkspaceGuard

- `is_within_workspace()` — 检查路径是否在 workspace 范围内
- 支持 symlink 穿透检查
- 白名单/黑名单机制（shell 命令）
- 危险模式正则匹配

### 4.3 执行级别（ToolExecutionLevel）

| 级别 | 行为 |
|------|------|
| `AUTO` | 所有工具自动执行 |
| `SMART` | INFO/LOW 自动，MEDIUM+ 需审批 |
| `STRICT` | 所有工具需审批 |
| `OFF` | 禁用工具守卫 |

## 五、总结

| 维度 | 现状 |
|------|------|
| 工具数量 | 19 个，8 大类 |
| 注册方式 | 启动时自动注册，始终可用 |
| 调用方式 | LLM ReAct 推理自主决策 |
| 安全防护 | 三层守卫 + WorkspaceGuard + 执行级别 |
| 与技能的关系 | 工具是原子操作，技能是行为指导，互不干扰 |
| 路径解析 | 相对路径 → workspace_dir，通过 symlink 落到用户目录 |
