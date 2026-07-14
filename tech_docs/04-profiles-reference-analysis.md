# config.agents.profiles 引用点分析

> 重构子任务0产出物，2026-07-06

## 统计

| 分类 | 文件数 | 引用数 |
|------|--------|--------|
| 核心定义 | 1 | 23 |
| 核心运行时 | 3 | 22 |
| 用户注册 | 1 | 6 |
| 管理API | 3 | 9 |
| 迁移/备份 | 4 | 34 |
| CLI工具 | 5 | 37 |
| 其他 | 3 | 4 |
| **合计** | **21** | **135** |

---

## 模块A：核心定义（重构/删除）

### A1. `config/config.py` — 23处引用

| 行号 | 用途 | 修改方案 |
|------|------|----------|
| 945 | `class AgentProfileRef` 定义 | **删除整个类**，改用 agent.json 的字段直接读取 |
| 1089-1091 | `AgentsConfig.profiles: Dict[str, AgentProfileRef]` | **删除字段**，AgentsConfig 不再持有 profiles |
| 1653-1688 | `get_agent_config()` — 从 profiles 查 agent_ref 获取 workspace_dir | **重构**：改为直接 `derive_workspace_dir(agent_id, username)` |
| 1733-1770 | `load_agent_config()` — 从 profiles 查 agent_ref，支持动态注册 | **重构**：改为磁盘扫描 agent.json |
| 1835-1878 | `save_agent_config()` — 从 profiles 查 agent_ref | **重构**：直接写入 workspace_dir |
| 1955-2034 | `_migrate_profiles_v2()` — 旧格式迁移 | **删除**（新结构不再需要此迁移） |

**修改方案：** 删除 `AgentProfileRef` 类、`AgentsConfig.profiles` 字段及其默认值。`get/load/save_agent_config` 改为接受 `username` 参数直接推导路径。

### A2. `config/utils.py` — 2处引用

| 行号 | 用途 | 修改方案 |
|------|------|----------|
| 656 | `register_dynamic_agent()` — 动态注册 agent 到 profiles | **删除函数**，改为直接在 workspace 目录创建 agent.json |
| 680 | 访问 `agents.profiles` | 随函数删除 |

**修改方案：** 删除 `register_dynamic_agent()`，调用方改为直接写文件。

---

## 模块B：核心运行时（重构）

### B1. `multi_agent_manager.py` — 9处引用

| 行号 | 用途 | 修改方案 |
|------|------|----------|
| 233-234 | `destroy_agent` — 从 profiles 删除 agent | **删除**（不再写 profiles） |
| 449-466 | `load_default_agents` — 遍历 profiles 加载 agent | **重写**：改为磁盘扫描 workspaces/ 和 agents/ |
| 534 | `get_agent` — 从 profiles 查 agent_ref | **重构**：改为从 workspace 目录读 agent.json |
| 574-583 | `get_agent` — fallback 模式查 profiles | **重构**：删除 fallback，只用磁盘扫描 |
| 698 | `list_agents` — 遍历 profiles | **重构**：改为磁盘扫描用户目录 |
| 707 | `list_agents` — 统计 profiles 数量 | **重构**：统计磁盘扫描结果 |

**修改方案：** `load_default_agents` 改为 `scan_workspaces()`：扫描 `workspaces/*/agent.json` + `workspaces/*/agents/*/agent.json` + `agents/*/agent.json`。

### B2. `agent_context.py` — 2处引用

| 行号 | 用途 | 修改方案 |
|------|------|----------|
| 122 | `get_agent_for_request` — 检查 agent_id 是否在 profiles | **重构**：改为检查 agent.json 是否存在 |
| 128 | 从 profiles 获取 agent_ref 的 username | **重构**：从 agent.json 读 owner 字段 |

**修改方案：** ownership 校验改为 `derive_workspace_dir` + 文件存在性检查 + agent.json 的 owner 字段。

### B3. `runner/runner.py` — 间接依赖

runner 通过 workspace 加载 agent.json，不直接访问 profiles。**无需修改。**

---

## 模块C：用户注册（重构）

### C1. `user_provisioning.py` — 6处引用

| 行号 | 用途 | 修改方案 |
|------|------|----------|
| 22, 43, 65 | 文档注释和导入 | **更新注释**，删除 AgentProfileRef 导入 |
| 220-234 | `_register_agent_in_config()` — 写 profiles | **删除整个函数** |
| 228 | 检查是否已注册 | 随函数删除 |

**修改方案：** 删除 `_register_agent_in_config()`。`init_user_workspace` 只创建目录 + agent.json + config.json，不再写 profiles。

---

## 模块D：管理API（重构）

### D1. `routers/admin/admin_global_agents.py` — 5处引用

| 行号 | 用途 | 修改方案 |
|------|------|----------|
| 448-452 | `create_global_agent` — 写 profiles | **重构**：改为在 `agents/{id}/` 目录创建 agent.json |
| 501-502 | `delete_global_agent` — 从 profiles 删除 | **重构**：改为删除 `agents/{id}/` 目录 |

**修改方案：** 全局智能体 CRUD 改为操作 `agents/` 目录。

### D2. `routers/agents.py` — 3处引用

| 行号 | 用途 | 修改方案 |
|------|------|----------|
| 107 | 本地 `AgentProfileRef` 定义（重复） | **删除** |
| 434 | `list_agents` fallback — 遍历 profiles | **重构**：只用磁盘扫描 |
| 474 | `create_agent` 文档注释 | 更新 |

**修改方案：** `list_agents` 只扫描用户 workspace 目录，删除 profiles fallback。

### D3. `routers/mcp.py` — 1处引用

| 行号 | 用途 | 修改方案 |
|------|------|----------|
| 235 | 检查 agent_id 是否在 profiles | **重构**：改为检查 agent.json 存在性 |

### D4. `routers/multi_layer_evolution.py` — 1处引用

| 行号 | 用途 | 修改方案 |
|------|------|----------|
| 67 | 直接返回 `config.agents.profiles` | **重构**：改为返回磁盘扫描结果 |

### D5. `routers/workspace_config.py` — 1处引用

| 行号 | 用途 | 修改方案 |
|------|------|----------|
| 388-389 | 从 profiles 获取 agent_ref 的 username | **重构**：从 agent.json 读 owner |

---

## 模块E：迁移/备份（适配/保留）

### E1. `migration.py` — 21处引用

**修改方案：** 保留迁移代码用于从旧版本升级，但新安装不再触发。添加版本检查，如果是新安装（无 profiles 数据）则跳过。

### E2. `backup/` — 15处引用

| 文件 | 用途 | 修改方案 |
|------|------|----------|
| `_ops/create.py:111` | 创建备份时从 profiles 获取 agent 信息 | 改为从 workspace 读取 |
| `_ops/restore.py:115-564` | 恢复时重建 profiles | 改为恢复 workspace 文件 |
| `_ops/restore_helpers.py:52-59` | 辅助函数引用 AgentProfileRef | 更新类型 |
| `models.py:112-116` | 备份模型文档 | 更新注释 |

**修改方案：** 备份改为备份 workspace 目录结构，恢复改为恢复 workspace 文件。不再操作 profiles。

---

## 模块F：CLI工具（适配）

### F1. `cli/doctor_checks.py` — 18处引用

全部是诊断检查：遍历 profiles 检查 agent 配置一致性。

**修改方案：** 改为扫描 `workspaces/*/agent.json` + `agents/*/agent.json`。

### F2. `cli/doctor_fix_runner.py` — 9处引用

修复工具：遍历 profiles 修复配置。

**修改方案：** 改为扫描 workspace 目录。

### F3. `cli/agents_cmd.py` — 7处引用

CLI 智能体管理命令。

**修改方案：** 改为操作 workspace 目录和 agent.json。

### F4. `cli/skills_cmd.py` — 2处引用

CLI 技能管理，从 profiles 获取 agent 信息。

**修改方案：** 改为从 agent.json 读取。

### F5. `cli/daemon_cmd.py` — 2处引用

守护进程启动，从 profiles 加载 agent。

**修改方案：** 改为磁盘扫描。

### F6. `cli/doctor_connectivity.py` — 1处引用

连接性检查，遍历 profiles。

**修改方案：** 改为磁盘扫描。

---

## 模块G：其他

### G1. `agents/skills_manager.py` — 1处引用

| 行号 | 用途 | 修改方案 |
|------|------|----------|
| 1644 | 遍历 profiles 获取所有 agent 的技能 | **重构**：改为扫描 workspace 目录 |

---

## 修改优先级

| 优先级 | 模块 | 文件 | 说明 |
|--------|------|------|------|
| P0 | A | config.py | 核心定义，删除 AgentProfileRef 和 profiles |
| P0 | B | multi_agent_manager.py, agent_context.py | 核心运行时，改为磁盘扫描 |
| P0 | C | user_provisioning.py | 用户注册，删除写 profiles |
| P1 | D | routers/*.py | 管理API，适配新结构 |
| P1 | A2 | config/utils.py | 删除 register_dynamic_agent |
| P2 | E | migration.py, backup/ | 保留迁移能力，适配备份 |
| P3 | F | cli/*.py | CLI工具，最后适配 |
| P3 | G | skills_manager.py | 低优先级 |

## 新增代码

| 文件 | 内容 |
|------|------|
| `config/config.py` | `UserProfileConfig` 模型 + `load_user_config()` / `save_user_config()` |
| `config/config.py` | `scan_agents_on_disk()` — 磁盘扫描发现所有智能体 |
| `migrate_v0.9.5.py` | 迁移脚本：profiles → workspace 文件 |
