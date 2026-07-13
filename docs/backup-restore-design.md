# 备份与恢复方案设计

> **本文档涵盖两个层面的备份与恢复**：
> - **系统管理层**：管理员操作，备份整个系统
> - **用户层面**：普通用户操作，只备份自己的数据

---

# 第一部分：系统管理层备份与恢复

## 一、备份范围分析

### 1.1 当前备份范围

| 项目 | 路径 | 状态 | 说明 |
|------|------|------|------|
| 智能体工作空间 | `workspaces/` | ✅ 已备份 | 每个用户的智能体数据 |
| 全局配置 | `config.json` | ❌ 路径错误 | 应为 `system/config.json` |
| 密钥目录 | `secrets/` | ✅ 已备份 | 敏感信息（可选） |
| 技能池 | `skill_pool/` | ✅ 已备份 | 技能配置 |

### 1.2 遗漏的关键数据

#### 🔴 关键数据（必须备份）

| 文件 | 路径 | 说明 |
|------|------|------|
| `users.json` | `system/users.json` | 用户账号数据 |
| `permissions.json` | `system/permissions.json` | 权限配置 |
| `auth.json` | `system/auth.json` | 认证配置 |
| `config.json` | `system/config.json` | 全局配置 |
| `user_system.db` | `system/user_system.db` | 用户数据库（企业版） |

#### 🟡 重要数据（建议备份）

| 文件 | 路径 | 说明 |
|------|------|------|
| `audit_logs.json` | `system/audit_logs.json` | 审计日志 |
| `audit_chain.jsonl` | `system/audit_chain.jsonl` | 审计链 |
| `user_preferences.json` | `system/user_preferences.json` | 用户偏好 |
| `token_usage_details.json` | `system/token_usage_details.json` | Token 使用详情 |
| `global_defaults.json` | `system/global_defaults.json` | 全局默认值 |
| `input_guard_rules.yaml` | `system/input_guard_rules.yaml` | 输入保护规则 |
| `tool_guard.yaml` | `system/tool_guard.yaml` | 工具保护规则 |
| `api_keys.json` | `system/api_keys.json` | API 密钥 |

#### 🟢 可选数据

| 文件 | 路径 | 说明 |
|------|------|------|
| `heartbeat.json` | `system/heartbeat.json` | 心跳数据 |
| `skill_metrics.json` | `system/skill_metrics.json` | 技能指标 |
| `migration_report.json` | `system/migration_report.json` | 迁移报告 |
| `templates/` | `system/templates/` | 模板目录 |
| `evolution/` | `system/evolution/` | 进化数据 |

---

## 二、备份格式设计

### 2.1 ZIP 内部结构

```
{backup_id}.zip
├── meta.json                    # 备份元数据
├── data/
│   ├── config.json              # 全局配置（来自 system/config.json）
│   ├── workspaces/              # 智能体工作空间
│   │   ├── {agent_id}/
│   │   │   ├── chats.json
│   │   │   ├── config.json
│   │   │   ├── files/
│   │   │   └── ...
│   │   └── ...
│   ├── secrets/                 # 密钥目录（可选）
│   │   └── .master_key
│   ├── skill_pool/              # 技能池
│   │   └── {skill_name}/
│   │       └── config.json
│   ├── system/                  # 🆕 系统数据目录
│   │   ├── users.json           # 用户账号
│   │   ├── permissions.json     # 权限配置
│   │   ├── auth.json            # 认证配置
│   │   ├── audit_logs.json      # 审计日志
│   │   ├── user_preferences.json
│   │   ├── token_usage_details.json
│   │   ├── global_defaults.json
│   │   ├── input_guard_rules.yaml
│   │   ├── tool_guard.yaml
│   │   ├── api_keys.json        # 可能不存在
│   │   └── .secret/             # 密钥子目录
│   │       └── ...
│   └── token_usage.json         # 🆕 Token 统计
```

### 2.2 元数据格式（meta.json）

```json
{
  "id": "coapis-1-20260713043000-abc12345",
  "name": "生产环境备份",
  "description": "每周自动备份",
  "created_at": "2026-07-13T04:30:00Z",
  "version": "2",
  "scope": {
    "include_agents": true,
    "include_global_config": true,
    "include_secrets": false,
    "include_skill_pool": true,
    "include_system": true,
    "include_token_usage": true
  },
  "agent_count": 25,
  "coapis_version": "0.9.12",
  "system_info": {
    "os": "Linux",
    "python_version": "3.11.0",
    "backup_tool_version": "2"
  },
  "file_stats": {
    "workspaces": {
      "files": 1234,
      "size": 567890
    },
    "system": {
      "files": 15,
      "size": 12345
    }
  }
}
```

### 2.3 版本兼容性

| 版本 | 说明 |
|------|------|
| `1` | 原始版本（无 system 目录） |
| `2` | 新版本（包含 system 目录和 token_usage） |

**向后兼容**：
- 版本 `2` 的备份可以被版本 `1` 的恢复代码读取
- 版本 `1` 的备份可以被版本 `2` 的恢复代码读取
- 恢复时根据备份中实际存在的文件决定恢复内容

---

## 三、恢复策略设计

### 3.1 恢复模式

#### 模式一：Full（完全替换）

**适用场景**：迁移到新服务器、灾难恢复

**行为**：
1. **system/ 目录**：直接替换
   - `users.json` → 覆盖
   - `permissions.json` → 覆盖
   - `auth.json` → 覆盖
   - `config.json` → 覆盖
   - 其他文件 → 覆盖

2. **workspaces/ 目录**：
   - 删除现有工作空间
   - 恢复备份中的工作空间

3. **skill_pool/ 目录**：
   - 删除现有技能池
   - 恢复备份中的技能池

4. **secrets/ 目录**（如果包含）：
   - 提示用户确认
   - 覆盖现有密钥

#### 模式二：Custom（选择性恢复）

**适用场景**：部分恢复、合并数据

**行为**：

1. **system/ 目录**：智能合并

| 文件 | 合并策略 |
|------|----------|
| `users.json` | **合并**：保留现有用户，更新备份中的用户，新增备份中的用户 |
| `permissions.json` | **合并**：保留现有权限，更新备份中的权限 |
| `auth.json` | **替换**：认证配置通常是全局的 |
| `config.json` | **合并**：保留 `agents.profiles`，其他字段从备份覆盖 |
| `audit_logs.json` | **追加**：保留现有日志，追加备份中的新日志（按时间戳去重） |
| `token_usage_details.json` | **合并**：保留现有数据，追加备份中的新数据（按时间戳去重） |
| `user_preferences.json` | **合并**：按用户 ID 合并 |
| `global_defaults.json` | **替换**：全局默认值 |
| `input_guard_rules.yaml` | **替换**：输入保护规则 |
| `tool_guard.yaml` | **替换**：工具保护规则 |
| `api_keys.json` | **合并**：按 key ID 合并 |

2. **workspaces/ 目录**：
   - 只恢复 `agent_ids` 中指定的智能体
   - 其他智能体保持不变

3. **skill_pool/ 目录**：
   - 只恢复备份中存在的技能
   - 现有技能保持不变

### 3.2 合并算法

#### users.json 合并算法

```python
def merge_users(local: list, backup: list) -> list:
    """合并用户列表
    
    策略：
    1. 以 username 为主键
    2. 保留本地独有的用户
    3. 更新备份中存在的用户（备份优先）
    4. 新增备份中独有的用户
    """
    local_map = {u["username"]: u for u in local}
    backup_map = {u["username"]: u for u in backup}
    
    result = {}
    
    # 保留本地用户
    for username, user in local_map.items():
        if username not in backup_map:
            result[username] = user
    
    # 更新/新增备份用户
    for username, user in backup_map.items():
        result[username] = user
    
    return list(result.values())
```

#### audit_logs.json 合并算法

```python
def merge_audit_logs(local: list, backup: list) -> list:
    """合并审计日志
    
    策略：
    1. 按时间戳去重
    2. 保留所有日志条目
    3. 按时间戳排序
    """
    seen = set()
    result = []
    
    for entry in local + backup:
        ts = entry.get("timestamp")
        if ts and ts not in seen:
            seen.add(ts)
            result.append(entry)
    
    return sorted(result, key=lambda x: x.get("timestamp", ""))
```

### 3.3 冲突处理

| 冲突类型 | 处理方式 |
|----------|----------|
| 用户 ID 冲突 | 备份优先（覆盖本地） |
| 智能体 ID 冲突 | 备份优先（覆盖本地） |
| 密钥冲突 | 提示用户选择（保留本地/使用备份/合并） |
| 配置字段冲突 | 按 `mode` 决定（full 替换，custom 合并） |

---

## 四、恢复后刷新机制

### 4.1 需要刷新的组件

| 组件 | 刷新方式 | 触发条件 |
|------|----------|----------|
| **用户系统** | 重载 `users.json` | 恢复了 `include_system` |
| **权限系统** | 重载 `permissions.json` | 恢复了 `include_system` |
| **全局配置** | 重载 `config.json` | 恢复了 `include_global_config` |
| **密钥存储** | 重载 `.master_key` | 恢复了 `include_secrets` |
| **智能体工作空间** | 重启相关 Agent | 恢复了 `include_agents` |
| **技能池** | 重载技能配置 | 恢复了 `include_skill_pool` |
| **Token 统计** | 重载 `token_usage.json` | 恢复了 `include_token_usage` |

### 4.2 刷新实现

```python
async def refresh_after_restore(scope: BackupScope) -> None:
    """恢复后刷新各组件"""
    
    # 1. 刷新用户系统
    if scope.include_system:
        # 重载用户数据
        from coapis.user_system.database import reload_all
        reload_all()
        
        # 重载权限
        from coapis.security.permissions import reload_permissions
        reload_permissions()
        
        # 重载认证配置
        from coapis.security.auth import reload_auth_config
        reload_auth_config()
    
    # 2. 刷新全局配置
    if scope.include_global_config:
        from coapis.config.utils import reload_config
        reload_config()
    
    # 3. 刷新密钥
    if scope.include_secrets:
        from coapis.security.secret_store import reload_master_key_from_disk
        reload_master_key_from_disk()
    
    # 4. 刷新智能体工作空间
    if scope.include_agents:
        # 重启所有 Agent
        from coapis.app.multi_agent_manager import multi_agent_manager
        await multi_agent_manager.restart_all()
    
    # 5. 刷新技能池
    if scope.include_skill_pool:
        from coapis.skills.skill_pool import reload_skill_pool
        reload_skill_pool()
    
    # 6. 刷新 Token 统计
    if scope.include_token_usage:
        from coapis.app.routers.token_usage import reload_token_usage
        reload_token_usage()
```

### 4.3 刷新优先级

```
1. 密钥存储（其他组件依赖）
   ↓
2. 全局配置（其他组件依赖）
   ↓
3. 用户系统 + 权限（认证相关）
   ↓
4. 技能池（智能体可能依赖）
   ↓
5. 智能体工作空间（最后重启）
   ↓
6. Token 统计（独立组件）
```

---

## 五、实施计划

### 5.1 修改文件清单

| 文件 | 修改内容 |
|------|----------|
| `backup/models.py` | 添加 `include_system`、`include_token_usage` 字段 |
| `backup/_utils/constants.py` | 添加 `PREFIX_SYSTEM`、`PREFIX_TOKEN_USAGE` 常量 |
| `backup/_ops/create_helpers.py` | 添加 `add_system_dir()`、`add_token_usage()` 函数 |
| `backup/_ops/create.py` | 调用新增的备份函数 |
| `backup/_ops/restore_helpers.py` | 添加 `restore_system_dir()`、合并算法 |
| `backup/_ops/restore.py` | 调用新增的恢复函数，实现刷新机制 |
| `constant.py` | 添加 `TOKEN_USAGE_FILE` 常量 |

### 5.2 测试用例

1. **备份测试**
   - 全量备份
   - 选择性备份（只备份 system）
   - 验证备份文件结构

2. **恢复测试**
   - Full 模式恢复
   - Custom 模式恢复
   - 合并算法测试（用户冲突、日志去重）

3. **刷新测试**
   - 验证各组件正确重载
   - 验证智能体正确重启
   - 验证用户登录正常

### 5.3 兼容性保证

- 新版本可以恢复旧版本备份
- 旧版本备份缺少 system 目录时，跳过 system 恢复
- 元数据版本号用于兼容性判断

---

## 六、安全考虑

### 6.1 敏感数据处理

| 数据 | 处理方式 |
|------|----------|
| `secrets/.master_key` | 默认不备份，需显式启用 |
| `auth.json` | 默认备份，但包含敏感信息 |
| `api_keys.json` | 默认备份，但包含敏感信息 |

### 6.2 备份文件权限

- 备份文件权限：`0600`（仅所有者可读写）
- 备份目录权限：`0700`（仅所有者可访问）

### 6.3 恢复前验证

- 验证备份文件完整性
- 验证备份版本兼容性
- 验证签名（可选）

---

## 七、错误处理

### 7.1 备份错误

| 错误 | 处理 |
|------|------|
| 磁盘空间不足 | 提前检查，提示用户 |
| 文件权限错误 | 跳过文件，记录警告 |
| 文件被占用 | 重试 3 次，失败后跳过 |

### 7.2 恢复错误

| 错误 | 处理 |
|------|------|
| 备份文件损坏 | 拒绝恢复，提示用户 |
| 版本不兼容 | 拒绝恢复，提示用户 |
| 恢复中途失败 | 回滚到临时目录，不污染生产环境 |
| 刷新失败 | 记录错误，提示用户手动重启 |

### 7.3 原子性保证

```
1. 解压到临时目录
2. 验证完整性
3. 执行合并/替换操作
4. 刷新组件
5. 清理临时目录
```

如果任何步骤失败，回滚到步骤 1 之前的状态。

---

# 第二部分：用户层面备份与恢复

## 一、用户数据范围分析

### 1.1 用户工作空间结构

```
workspaces/{username}/
├── agent.json              # 智能体配置
├── config.json             # 用户配置
├── skill.json              # 技能配置
├── mcp_installed.json      # MCP 安装记录
│
├── chat/                   # 聊天记录
│   └── chats.json
├── chats/                  # 聊天记录（另一位置）
│   └── chats.json
├── sessions/               # 会话数据
│   └── {session_id}.json
├── dialog/                 # 对话记录（JSONL）
│   └── {date}.jsonl
├── history.db              # 历史数据库
│
├── files/                  # 用户上传文件
│   └── {file_name}
├── uploads/                # 上传目录
│
├── memory/                 # 记忆文件
│   └── {date}.md
├── MEMORY.md               # 长期记忆
│
├── skills/                 # 技能目录
│   └── {skill_name}/
│       └── config.json
│
├── crons/                  # 定时任务
│   └── jobs.json
│
├── workflows/              # 工作流
├── knowledge_flow/         # 知识流
├── evolution/              # 进化数据
│
├── PROFILE.md              # 用户资料
├── AGENTS.md               # 智能体说明
├── SOUL.md                 # 灵魂文件
├── BOOTSTRAP.md            # 引导文件
│
├── backups/                # 用户备份目录
├── tmp/                    # 临时文件
├── downloads/              # 下载文件
└── tool_results/           # 工具结果
```

### 1.2 数据分类与备份策略

#### 🔴 核心数据（必须备份）

| 数据 | 路径 | 说明 |
|------|------|------|
| 智能体配置 | `agent.json` | 智能体定义 |
| 用户配置 | `config.json` | 用户设置 |
| 技能配置 | `skill.json` | 技能列表 |
| 聊天记录 | `chat/chats.json` | 聊天会话 |
| 会话数据 | `sessions/*.json` | 会话状态 |
| 上传文件 | `files/` | 用户文件 |

#### 🟡 重要数据（建议备份）

| 数据 | 路径 | 说明 |
|------|------|------|
| 对话记录 | `dialog/*.jsonl` | 完整对话 |
| 记忆文件 | `memory/`, `MEMORY.md` | 智能体记忆 |
| 技能目录 | `skills/` | 自定义技能 |
| 定时任务 | `crons/jobs.json` | 定时任务 |
| MCP 安装 | `mcp_installed.json` | MCP 配置 |

#### 🟢 可选数据

| 数据 | 路径 | 说明 |
|------|------|------|
| 工作流 | `workflows/` | 工作流配置 |
| 知识流 | `knowledge_flow/` | 知识流数据 |
| 进化数据 | `evolution/` | 进化记录 |
| 个性化文件 | `PROFILE.md`, `AGENTS.md`, `SOUL.md` | 用户定制 |
| 引导文件 | `BOOTSTRAP.md`, `.bootstrap_state` | 引导配置 |

#### ⚪ 不备份

| 数据 | 路径 | 原因 |
|------|------|------|
| 临时文件 | `tmp/` | 可重新生成 |
| 工具结果 | `tool_results/` | 可重新生成 |
| 下载文件 | `downloads/` | 临时缓存 |
| 历史数据库 | `history.db` | 可从其他数据重建 |

---

## 二、用户备份格式设计

### 2.1 ZIP 内部结构

```
user-backup-{username}-{timestamp}.zip
├── meta.json                    # 备份元数据
├── agent.json                   # 智能体配置
├── config.json                  # 用户配置
├── skill.json                   # 技能配置
├── mcp_installed.json           # MCP 安装记录（可选）
│
├── chat/
│   └── chats.json
├── sessions/
│   └── {session_id}.json
├── dialog/
│   └── {date}.jsonl
│
├── files/                       # 用户文件
│   └── {file_name}
│
├── memory/
│   └── {date}.md
├── MEMORY.md
│
├── skills/                      # 技能目录
│   └── {skill_name}/
│
├── crons/
│   └── jobs.json
│
├── workflows/                   # 可选
├── knowledge_flow/              # 可选
├── evolution/                   # 可选
│
├── PROFILE.md
├── AGENTS.md
└── SOUL.md
```

### 2.2 元数据格式（meta.json）

```json
{
  "id": "user-backup-admin-20260713043000",
  "type": "user_backup",
  "username": "admin",
  "name": "我的备份",
  "description": "手动备份",
  "created_at": "2026-07-13T04:30:00Z",
  "version": "1",
  "scope": {
    "include_chats": true,
    "include_files": true,
    "include_memory": true,
    "include_skills": true,
    "include_crons": true,
    "include_workflows": false,
    "include_knowledge_flow": false,
    "include_evolution": false
  },
  "stats": {
    "chats": 10,
    "files": 25,
    "skills": 3,
    "size_bytes": 12345678
  },
  "coapis_version": "0.9.12"
}
```

---

## 三、用户恢复策略设计

### 3.1 恢复模式

#### 模式一：完全恢复（Full）

**行为**：删除现有数据，完全恢复备份

**适用场景**：
- 用户迁移到新账号
- 数据损坏需要恢复
- 回滚到之前的状态

**流程**：
```
1. 验证备份文件
2. 清空现有工作空间（保留 backups/ 目录）
3. 解压备份到工作空间
4. 验证恢复结果
5. 刷新智能体状态
```

#### 模式二：合并恢复（Merge）

**行为**：保留现有数据，合并备份数据

**适用场景**：
- 合并多个设备的数据
- 选择性恢复部分数据

**合并策略**：

| 数据类型 | 合并策略 |
|----------|----------|
| 聊天记录 | **追加**：保留现有聊天，追加备份中的新聊天（按 chat_id 去重） |
| 会话数据 | **覆盖**：备份优先 |
| 文件 | **保留现有**：现有文件优先，只添加不存在的文件 |
| 记忆 | **合并**：按日期合并，保留所有记忆 |
| 技能 | **合并**：按技能名合并，备份优先 |
| 定时任务 | **追加**：按任务 ID 去重 |

### 3.2 冲突处理

| 冲突类型 | 处理方式 |
|----------|----------|
| chat_id 冲突 | 保留现有（用户可能正在使用） |
| 文件名冲突 | 保留现有文件 |
| 技能名冲突 | 备份优先（用户明确选择恢复） |
| 会话 ID 冲突 | 备份优先 |

### 3.3 恢复后刷新

```python
async def refresh_user_workspace(username: str) -> None:
    """恢复后刷新用户工作空间"""
    
    # 1. 重载智能体配置
    from coapis.agents.agent_loader import reload_agent_config
    reload_agent_config(username)
    
    # 2. 重载技能
    from coapis.skills.skill_manager import reload_skills
    reload_skills(username)
    
    # 3. 重载定时任务
    from coapis.crons.cron_manager import reload_crons
    reload_crons(username)
    
    # 4. 重载 MCP 配置
    from coapis.mcp.mcp_manager import reload_mcp
    reload_mcp(username)
    
    # 5. 刷新聊天缓存
    from coapis.chat.chat_manager import invalidate_cache
    invalidate_cache(username)
```

---

## 四、API 设计

### 4.1 用户备份 API

#### 创建备份

```http
POST /api/user/backups
Content-Type: application/json

{
  "name": "我的备份",
  "description": "手动备份",
  "scope": {
    "include_chats": true,
    "include_files": true,
    "include_memory": true,
    "include_skills": true,
    "include_crons": true
  }
}
```

**响应**：
```json
{
  "id": "user-backup-admin-20260713043000",
  "name": "我的备份",
  "created_at": "2026-07-13T04:30:00Z",
  "download_url": "/api/user/backups/user-backup-admin-20260713043000/download"
}
```

#### 列出备份

```http
GET /api/user/backups
```

**响应**：
```json
[
  {
    "id": "user-backup-admin-20260713043000",
    "name": "我的备份",
    "created_at": "2026-07-13T04:30:00Z",
    "size": 12345678,
    "scope": { ... }
  }
]
```

#### 下载备份

```http
GET /api/user/backups/{backup_id}/download
```

**响应**：ZIP 文件下载

#### 上传/导入备份

```http
POST /api/user/backups/import
Content-Type: multipart/form-data

file: {backup.zip}
```

#### 恢复备份

```http
POST /api/user/backups/{backup_id}/restore
Content-Type: application/json

{
  "mode": "merge",  // 或 "full"
  "scope": {
    "include_chats": true,
    "include_files": true,
    "include_memory": true
  }
}
```

#### 删除备份

```http
DELETE /api/user/backups/{backup_id}
```

### 4.2 权限控制

| API | 权限 |
|-----|------|
| 创建备份 | 用户本人 |
| 列出备份 | 用户本人 |
| 下载备份 | 用户本人 |
| 导入备份 | 用户本人 |
| 恢复备份 | 用户本人 |
| 删除备份 | 用户本人 |

**实现方式**：
- API 路径包含用户身份（从 JWT token 获取）
- 只能操作自己的备份数据
- 管理员可以查看但不能操作用户备份

---

## 五、存储设计

### 5.1 存储位置

```
workspaces/{username}/backups/
├── user-backup-admin-20260713043000.zip
├── user-backup-admin-20260714053000.zip
└── ...
```

### 5.2 存储限制

| 限制项 | 默认值 | 说明 |
|--------|--------|------|
| 单个备份大小 | 500 MB | 超出提示用户清理文件 |
| 备份数量 | 10 个 | 超出提示删除旧备份 |
| 保留时间 | 30 天 | 可配置 |

### 5.3 自动清理

```python
async def cleanup_old_backups(username: str, max_count: int = 10) -> None:
    """清理旧备份"""
    backups_dir = WORKSPACES_DIR / username / "backups"
    backups = sorted(backups_dir.glob("user-backup-*.zip"))
    
    while len(backups) > max_count:
        oldest = backups.pop(0)
        oldest.unlink()
        logger.info(f"Deleted old backup: {oldest.name}")
```

---

## 六、安全考虑

### 6.1 数据隔离

- 用户只能访问自己的备份
- 备份文件存储在用户工作空间内
- 下载链接包含临时 token，有效期 1 小时

### 6.2 敏感数据

| 数据 | 处理方式 |
|------|----------|
| 聊天记录 | 包含用户对话，需用户确认下载 |
| 文件 | 用户上传的文件，原样备份 |
| MCP 配置 | 可能包含 API 密钥，提示用户 |

### 6.3 传输安全

- 下载链接使用 HTTPS
- 支持端到端加密（可选）

---

## 七、与系统备份的关系

### 7.1 对比

| 维度 | 系统备份 | 用户备份 |
|------|----------|----------|
| **操作者** | 管理员 | 普通用户 |
| **范围** | 全系统 | 单用户 |
| **存储位置** | `{WORKING_DIR}/.backups/` | `{WORKSPACES_DIR}/{username}/backups/` |
| **权限** | `admin:admin` | 用户本人 |
| **包含系统配置** | ✅ | ❌ |
| **包含其他用户数据** | ✅ | ❌ |
| **可下载** | ✅ | ✅ |
| **可导入导出** | ✅ | ✅ |

### 7.2 协同工作

1. **系统备份包含用户备份**
   - 系统备份时，可以选择是否包含用户的个人备份
   - 默认不包含（避免重复）

2. **用户数据恢复优先级**
   - 如果系统备份和用户备份都存在
   - 优先使用用户备份（更近、更精确）

3. **迁移场景**
   - 用户导出自己的备份 → 在新系统导入
   - 或管理员恢复系统备份

---

## 八、实施计划

### 8.1 用户层面备份

#### 新增文件

| 文件 | 说明 |
|------|------|
| `server/coapis/user_backup/models.py` | 用户备份数据模型 |
| `server/coapis/user_backup/operations.py` | 备份/恢复操作 |
| `server/coapis/app/routers/user_backups.py` | 用户备份 API |
| `client/src/pages/User/Backups/` | 用户备份页面 |

#### 修改文件

| 文件 | 修改内容 |
|------|----------|
| `server/coapis/app/_app.py` | 注册用户备份路由 |
| `client/src/layouts/Sidebar.tsx` | 添加用户备份菜单项 |

### 8.2 系统管理层备份

#### 修改文件

| 文件 | 修改内容 |
|------|----------|
| `backup/models.py` | 添加 `include_system`、`include_token_usage` |
| `backup/_utils/constants.py` | 添加 `PREFIX_SYSTEM`、`PREFIX_TOKEN_USAGE` |
| `backup/_ops/create_helpers.py` | 添加 `add_system_dir()`、`add_token_usage()` |
| `backup/_ops/restore_helpers.py` | 添加合并算法 |
| `backup/_ops/restore.py` | 实现恢复和刷新机制 |

### 8.3 测试计划

#### 用户备份测试

1. 创建备份（各种 scope 组合）
2. 下载备份
3. 导入备份
4. Full 模式恢复
5. Merge 模式恢复
6. 删除备份
7. 自动清理测试

#### 系统备份测试

1. 备份包含 system 目录
2. 恢复 system 目录
3. 合并算法测试
4. 刷新机制测试

---

## 九、实施进度

### 9.1 第一阶段（系统管理层）✅ 已完成

| 任务 | 状态 | 说明 |
|------|------|------|
| 修复 config.json 路径错误 | ✅ | `SYSTEM_DIR/config.json` |
| 添加 system 目录备份 | ✅ | 用户、权限、审计等关键数据 |
| 实现恢复后刷新机制 | ✅ | 清除缓存 + 重启智能体 |

**修改的文件**：
- `server/coapis/backup/models.py`
- `server/coapis/backup/_utils/constants.py`
- `server/coapis/backup/_ops/create_helpers.py`
- `server/coapis/backup/_ops/restore_helpers.py`
- `server/coapis/backup/_ops/restore.py`

**备份版本**：`1` → `2`

### 9.2 第二阶段（用户层面）📋 规划中

> **说明**：用户层面的备份与恢复功能规划为**企业版特性**，开源版本暂不实现。

**企业版规划**：
- 用户个人备份创建/下载/导入
- 用户数据选择性恢复
- 合并恢复策略
- 存储限制与自动清理

**技术储备**：
- 设计方案已完成（见本文档第二部分）
- 实现路径已明确
- 需要企业版许可证机制配合

---

## 十、总结

### 已实现（开源版本）

✅ 系统管理层完整备份与恢复
- 备份：workspaces、system、secrets、skill_pool、token_usage
- 恢复：Full（替换）/ Custom（合并）两种模式
- 刷新：恢复后自动刷新各组件

### 未来规划（企业版本）

📋 用户层面备份与恢复
- 用户自助备份
- 个人数据导出/导入
- 跨设备数据同步
