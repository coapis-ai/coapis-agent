# CoApis 前端技术文档

> **目标**：遇到任何 bug 时，30 秒内定位到具体文件和函数。

---

## 1. 页面-组件-API 三层映射

### 1.1 页面目录

```
client/src/pages/
├── Admin/                    # 管理员仪表盘
│   └── index.tsx             # 用户管理、系统概览、配置、审计
├── Agent/                    # 智能体配置（子路由）
│   ├── ACP/index.tsx         # ACP 协议
│   ├── Config/index.tsx      # 智能体配置
│   ├── MCP/index.tsx         # MCP 客户端配置
│   ├── Skills/index.tsx      # 技能管理
│   ├── Tools/index.tsx       # 工具管理
│   └── Workspace/index.tsx   # 工作区管理
├── Chat/                     # 💬 聊天主页面（最复杂）
│   ├── index.tsx             # 主聊天界面（1588 行）
│   ├── ModelSelector/        # 模型选择器
│   │   └── index.tsx         # 全局模型切换
│   ├── sessionApi.ts         # 会话 API 封装
│   ├── OptionsPanel/         # 选项面板
│   │   └── defaultConfig.ts  # 默认配置
│   └── components/
│       ├── ChatActionGroup/  # 操作按钮组
│       ├── ChatHeaderTitle/  # 标题栏
│       ├── ChatSearchDropdown/ # 搜索下拉
│       ├── ChatSessionDropdown/ # 会话下拉
│       ├── ChatSessionHeader/  # 会话头部
│       ├── ChatSessionInitializer/ # 会话初始化
│       ├── ChatSessionItem/    # 会话项
│       ├── SimplifiedResponseCard/ # 简化响应卡片
│       ├── EnhancedToolCallCard/   # 增强工具调用卡片
│       └── CoApisDeepThinking/     # 深度思考展示
├── Control/                  # 控制面板（子路由）
│   ├── Channels/index.tsx    # 频道管理
│   ├── CronJobs/index.tsx    # 定时任务
│   ├── Heartbeat/index.tsx   # 心跳监控
│   └── Sessions/index.tsx    # 会话管理
├── CrossAgent/               # 跨智能体协作
│   └── index.tsx
├── Evolution/                # 进化系统
│   └── index.tsx
├── KnowledgeBase/            # 知识库
│   └── index.tsx
├── Login/                    # 登录页
│   └── index.tsx
├── Monitoring/               # 监控面板
│   └── index.tsx
├── MultiLayerEvolution/      # 多层进化
│   └── index.tsx
├── MySpace/                  # 我的空间（文件管理）
│   └── index.tsx             # 文件浏览、智能体身份面板
├── Settings/                 # ⚙️ 设置中心（子路由）
│   ├── AgentStats/index.tsx  # 智能体统计
│   ├── Agents/index.tsx      # 智能体管理
│   ├── Backups/index.tsx     # 备份管理
│   ├── Debug/index.tsx       # 调试面板
│   ├── Environments/index.tsx # 环境变量
│   ├── Models/index.tsx      # 模型管理（Provider 配置）
│   ├── Security/index.tsx    # 安全设置
│   ├── SkillPool/index.tsx   # 技能池
│   ├── TokenUsage/index.tsx  # Token 用量
│   └── VoiceTranscription/index.tsx # 语音转写
├── SSO/                      # SSO 单点登录
│   └── index.tsx
├── UserProfile/              # 用户资料
│   └── index.tsx
└── UserSystem/               # 用户系统管理
    └── index.tsx
```

### 1.2 页面 → API 模块映射

| 页面 | 使用的 API 模块 | 主要后端端点 |
|------|----------------|-------------|
| **Chat** | `chatApi`, `providerApi`, `userModelPrefsApi`, `commandsApi`, `planApi`, `agentsApi` | `/chats/*`, `/models/*`, `/models/available`, `/commands/*`, `/plan/*`, `/agents` |
| **Admin** | `adminApi`, `userSystemApi`, `permissionsApi` | `/admin/users/*`, `/admin/system/*`, `/admin/config`, `/permissions/*` |
| **Settings/Models** | `providerApi` | `/models/*`, `/models/active`, `/models/custom-providers/*` |
| **Settings/Agents** | `agentsApi` | `/agents/*`, `/agent/*` |
| **Settings/SkillPool** | `skillApi` | `/skills/pool/*`, `/skills/builtin/*` |
| **Settings/Backups** | `backupApi` | `/backups/*` |
| **Settings/Security** | `securityApi` | `/security/*` |
| **Settings/TokenUsage** | `tokenUsageApi` | `/token-usage/*` |
| **Settings/Environments** | `envApi` | `/envs/*` |
| **Settings/AgentStats** | `agentStatsApi` | `/agent-stats/*` |
| **Settings/VoiceTranscription** | (内联 fetch) | `/voice/*` |
| **Settings/Debug** | (内联 fetch) | `/console/*` |
| **Control/Channels** | `channelApi` | `/channels/*` |
| **Control/CronJobs** | `cronJobApi` | `/cron/*` |
| **Control/Heartbeat** | `heartbeatApi` | `/heartbeat/*` |
| **Control/Sessions** | `sessionApi` | `/sessions/*` |
| **MySpace** | `api` (通用), `agentsApi` | `/myfiles/*`, `/agent/*` |
| **Login** | `authApi` | `/auth/login`, `/auth/register`, `/auth/status` |
| **CrossAgent** | `crossAgentApi` | `/cross-agent/*` |
| **Evolution** | `evolutionApi` | `/evolution/*` |
| **MultiLayerEvolution** | `multiLayerEvolutionApi` | `/multi-layer-evolution/*` |
| **KnowledgeBase** | `knowledgeApi` | `/knowledge/*` |
| **UserSystem** | `userSystemApi` | `/users/*`, `/tokens/*` |
| **UserProfile** | `authApi` | `/auth/update-profile` |
| **SSO** | (内联 fetch) | `/sso/*` |
| **Monitoring** | (内联 fetch) | `/monitoring/*` |

---

## 2. API 调用链：前端 → 后端完整映射

### 2.1 API 层架构

```
client/src/api/
├── index.ts          # 导出统一 api 对象（合并所有模块）
├── request.ts        # 基础 HTTP 请求封装
├── config.ts         # getApiUrl() / getApiToken()
├── authHeaders.ts    # buildAuthHeaders() - Bearer token 注入
├── types/            # TypeScript 类型定义
│   ├── index.ts      # 统一导出
│   ├── agents.ts     # AgentSummary, AgentProfileConfig 等
│   └── ...
└── modules/          # ⭐ 各功能模块 API
    ├── root.ts       # 根路由
    ├── auth.ts       # 认证（直接 fetch，不走 request）
    ├── chat.ts       # 聊天（文件上传、会话 CRUD）
    ├── provider.ts   # Provider/模型管理
    ├── agents.ts     # 智能体 CRUD
    ├── skill.ts      # 技能管理（带缓存）
    ├── admin.ts      # 管理员 API
    ├── admin_providers.ts  # 管理员 Provider
    ├── user_system.ts      # 用户系统
    ├── user_model_prefs.ts # 用户模型偏好
    ├── permissions.ts      # 权限管理
    ├── security.ts         # 安全设置
    ├── tools.ts            # 工具管理
    ├── mcp.ts              # MCP 客户端
    ├── env.ts              # 环境变量
    ├── backup.ts           # 备份管理
    ├── channel.ts          # 频道管理
    ├── cronjob.ts          # 定时任务
    ├── console.ts          # 控制台
    ├── commands.ts         # 命令系统
    ├── tokenUsage.ts       # Token 用量
    ├── agentStats.ts       # 智能体统计
    ├── evolution.ts        # 进化系统
    ├── multi_layer_evolution.ts # 多层进化
    ├── cross_agent.ts      # 跨智能体
    ├── plan.ts             # 计划系统
    ├── plugin.ts           # 插件管理
    ├── knowledge.ts        # 知识库
    ├── localModel.ts       # 本地模型
    ├── workspace.ts        # 工作区
    ├── root.ts             # 根路由
    ├── heartbeat.ts        # 心跳
    ├── acp.ts              # ACP 协议
    ├── language.ts         # 语言设置
    ├── userTimezone.ts     # 时区设置
    ├── cleanup.ts          # 清理/归档
    ├── debug.ts            # 调试
    └── user_me.ts          # 用户信息
```

### 2.2 核心 API 映射表

| 前端 API 模块 | 前端函数 | 后端路由 | 后端端点 |
|-------------|---------|---------|---------|
| **auth.ts** | `authApi.login()` | `routers/auth.py` | `POST /api/auth/login` |
| | `authApi.register()` | `routers/auth.py` | `POST /api/auth/register` |
| | `authApi.getStatus()` | `routers/auth.py` | `GET /api/auth/status` |
| | `authApi.updateProfile()` | `routers/auth.py` | `POST /api/auth/update-profile` |
| **chat.ts** | `chatApi.listChats()` | `routers/chats.py` | `GET /api/chats` |
| | `chatApi.createChat()` | `routers/chats.py` | `POST /api/chats` |
| | `chatApi.deleteChat()` | `routers/chats.py` | `DELETE /api/chats/{id}` |
| | `chatApi.uploadFile()` | `routers/console.py` | `POST /api/myfiles/upload` |
| | `chatApi.filePreviewUrl()` | 静态文件 | `GET /api/files/preview/{path}` |
| **provider.ts** | `providerApi.listProviders()` | `routers/providers.py` | `GET /api/models` |
| | `providerApi.getActiveModels()` | `routers/providers.py` | `GET /api/models/active` |
| | `providerApi.setActiveLlm()` | `routers/providers.py` | `PUT /api/models/active` |
| | `providerApi.configureProvider()` | `routers/providers.py` | `PUT /api/models/{id}/config` |
| | `providerApi.createCustomProvider()` | `routers/providers.py` | `POST /api/models/custom-providers` |
| | `providerApi.deleteCustomProvider()` | `routers/providers.py` | `DELETE /api/models/custom-providers/{id}` |
| **agents.ts** | `agentsApi.listAgents()` | `routers/agents.py` | `GET /api/agents` |
| | `agentsApi.getAgent()` | `routers/agents.py` | `GET /api/agents/{id}` |
| | `agentsApi.createAgent()` | `routers/agents.py` | `POST /api/agents` |
| | `agentsApi.updateAgent()` | `routers/agents.py` | `PUT /api/agents/{id}` |
| | `agentsApi.deleteAgent()` | `routers/agents.py` | `DELETE /api/agents/{id}` |
| | `agentsApi.reorderAgents()` | `routers/agents.py` | `PUT /api/agents/order` |
| | `agentsApi.toggleAgentEnabled()` | `routers/agents.py` | `PATCH /api/agents/{id}/toggle` |
| | `agentsApi.listWorkingFiles()` | `routers/agent.py` | `GET /api/agent/files` (X-Agent-Id) |
| | `agentsApi.readWorkingFile()` | `routers/agent.py` | `GET /api/agent/files/{name}` (X-Agent-Id) |
| | `agentsApi.writeWorkingFile()` | `routers/agent.py` | `PUT /api/agent/files/{name}` (X-Agent-Id) |
| **skill.ts** | `skillApi.listSkills()` | `routers/skills.py` | `GET /api/skills` |
| | `skillApi.installSkill()` | `routers/skills.py` | `POST /api/skills/install` |
| | `skillApi.uninstallSkill()` | `routers/skills.py` | `DELETE /api/skills/{name}` |
| | `skillApi.getPoolSkills()` | `routers/skills.py` | `GET /api/skills/pool` |
| | `skillApi.getBuiltinNotice()` | `routers/skills.py` | `GET /api/skills/pool/builtin-notice` |
| **admin.ts** | `adminApi.getSystemOverview()` | `admin/admin_system.py` | `GET /api/admin/system/overview` |
| | `adminApi.listUsers()` | `admin/admin_users.py` | `GET /api/admin/users` |
| | `adminApi.createUser()` | `admin/admin_users.py` | `POST /api/admin/users` |
| | `adminApi.updateUser()` | `admin/admin_users.py` | `PUT /api/admin/users/{username}` |
| | `adminApi.deleteUser()` | `admin/admin_users.py` | `DELETE /api/admin/users/{id}` |
| | `adminApi.getGlobalConfig()` | `admin/admin_config.py` | `GET /api/admin/config` |
| | `adminApi.updateGlobalConfig()` | `admin/admin_config.py` | `PUT /api/admin/config` |
| | `adminApi.getAuditLogs()` | `admin/admin_audit.py` | `GET /api/admin/audit` |
| | `adminApi.getTemplates()` | `admin/admin_templates.py` | `GET /api/admin/templates` |
| | `adminApi.updateTemplate()` | `admin/admin_templates.py` | `PUT /api/admin/templates/{name}` |
| **user_model_prefs.ts** | `userModelPrefsApi.getAvailableModels()` | `routers/user_model_prefs.py` | `GET /api/models/available` |
| | `userModelPrefsApi.getModelPrefs()` | `routers/user_model_prefs.py` | `GET /api/user/model-prefs` |
| | `userModelPrefsApi.updateModelPrefs()` | `routers/user_model_prefs.py` | `PUT /api/user/model-prefs` |
| **user_system.ts** | `getUsersConfig()` | `user_system/routers` | `GET /api/users/config` |
| | `registerUser()` | `user_system/routers` | `POST /api/users/register` |
| | `loginUser()` | `user_system/routers` | `POST /api/users/login` |
| | `getCurrentUser()` | `user_system/routers` | `GET /api/users/me` |
| | `getTokenSummary()` | `user_system/routers` | `GET /api/tokens/summary` |
| | `recordTokenUsage()` | `user_system/routers` | `POST /api/tokens/record` |
| **permissions.ts** | `permissionsApi.listRoles()` | `routers/permissions.py` | `GET /api/permissions/roles` |
| | `permissionsApi.updateRole()` | `routers/permissions.py` | `PUT /api/permissions/roles/{role}` |
| | `permissionsApi.listModules()` | `routers/permissions.py` | `GET /api/permissions/modules` |
| **security.ts** | `securityApi.getSettings()` | `routers/security.py` | `GET /api/security/settings` |
| | `securityApi.updateSettings()` | `routers/security.py` | `PUT /api/security/settings` |
| **env.ts** | `envApi.listEnvs()` | `routers/envs.py` | `GET /api/envs` |
| | `envApi.updateEnv()` | `routers/envs.py` | `PUT /api/envs` |
| **backup.ts** | `backupApi.listBackups()` | `routers/backup.py` | `GET /api/backups` |
| | `backupApi.createBackup()` | `routers/backup.py` | `POST /api/backups` |
| | `backupApi.restoreBackup()` | `routers/backup.py` | `POST /api/backups/{id}/restore` |
| **cronjob.ts** | `cronJobApi.listJobs()` | `crons/api.py` | `GET /api/cron` |
| | `cronJobApi.createJob()` | `crons/api.py` | `POST /api/cron` |
| **channel.ts** | `channelApi.listChannels()` | `channels/registry` | `GET /api/channels` |
| | `channelApi.sendMessage()` | `channels/registry` | `POST /api/channels/send` |
| **tokenUsage.ts** | `tokenUsageApi.getSummary()` | `routers/token_usage.py` | `GET /api/token-usage/summary` |
| | `tokenUsageApi.getHistory()` | `routers/token_usage.py` | `GET /api/token-usage/history` |
| **mcp.ts** | `mcpApi.listClients()` | `routers/mcp.py` | `GET /api/mcp` |
| | `mcpApi.addClient()` | `routers/mcp.py` | `POST /api/mcp` |
| **tools.ts** | `toolsApi.listTools()` | `routers/tools.py` | `GET /api/tools` |
| | `toolsApi.addTool()` | `routers/tools.py` | `POST /api/tools` |
| **localModel.ts** | `localModelApi.listModels()` | `routers/local_models.py` | `GET /api/local-models` |
| | `localModelApi.startModel()` | `routers/local_models.py` | `POST /api/local-models/{id}/start` |
| **workspace.ts** | `workspaceApi.getConfig()` | `routers/workspace.py` | `GET /api/workspace` |
| **evolution.ts** | `evolutionApi.listEvolutions()` | `routers/evolution.py` | `GET /api/evolution` |
| **multi_layer_evolution.ts** | (多层进化 API) | `routers/multi_layer_evolution.py` | `/api/multi-layer-evolution/*` |
| **cross_agent.ts** | (跨智能体 API) | `routers/cross_agent.py` | `/api/cross-agent/*` |
| **plan.ts** | (计划 API) | `routers/plan.py` | `/api/plan/*` |
| **knowledge.ts** | (知识库 API) | (知识库路由) | `/api/knowledge/*` |
| **heartbeat.ts** | (心跳 API) | (心跳路由) | `/api/heartbeat/*` |
| **acp.ts** | (ACP API) | (ACP 路由) | `/api/acp/*` |
| **root.ts** | `rootApi.getInfo()` | `routers/root.py` | `GET /api/` |
| **cleanup.ts** | (清理 API) | `cleanup_api.py` | `/api/cleanup/*` |
| **commands.ts** | (命令 API) | `routers/commands.py` | `/api/commands/*` |
| **console.ts** | (控制台 API) | `routers/console.py` | `/api/console/*` |
| **plugin.ts** | (插件 API) | `routers/plugins.py` | `/api/plugins/*` |
| **debug.ts** | (调试 API) | (调试路由) | `/api/debug/*` |
| **agentStats.ts** | (智能体统计) | `routers/agent_stats.py` | `/api/agent-stats/*` |
| **user_me.ts** | (用户信息) | `user/user_me.py` | `/api/user/me` |

### 2.3 API 请求链路

```
前端组件调用 api.xxx()
  ↓
modules/xxx.ts（业务 API 封装）
  ↓
request.ts（统一 HTTP 请求）
  → getApiUrl(path)        # 拼接 BASE_URL + /api + path
  → buildAuthHeaders()     # 注入 Authorization: Bearer {token}
  → fetch()                # 实际请求
  ↓
后端 FastAPI App
  → /api/* 路由匹配
```

**特殊**：`auth.ts` 直接用 `fetch()` 而非 `request()`，因为登录时可能没有 token。

---

## 3. 状态管理

### 3.1 Zustand Store

**文件**：`client/src/stores/agentStore.ts`

```typescript
interface AgentStore {
  selectedAgent: string;           // 当前选中的 agent ID
  agents: AgentSummary[];          // 所有 agent 列表
  lastChatIdByAgent: Record<string, string>; // 每个 agent 最后活跃的 chat ID
  
  setSelectedAgent: (agentId: string) => void;
  setAgents: (agents: AgentSummary[]) => void;
  addAgent: (agent: AgentSummary) => void;
  removeAgent: (agentId: string) => void;
  updateAgent: (agentId: string, updates: Partial<AgentSummary>) => void;
  setLastChatId: (agentId: string, chatId: string) => void;
  getLastChatId: (agentId: string) => string | undefined;
}
```

**持久化策略**：
- `sessionStorage`：当前 tab 的状态（per-tab）
- `localStorage` (`coapis-agent-storage`)：跨 tab 共享
- `localStorage` (`coapis-last-used-agent`)：记住上次选择的 agent

**初始值优先级**：
1. `sessionStorage`（返回已选 agent 的 tab）
2. `localStorage` lastUsedAgent（新 tab 继承上次选择）
3. `localStorage` 共享状态
4. `"default"`（兜底）

### 3.2 其他状态管理

| 状态 | 管理方式 | 文件 |
|------|---------|------|
| 用户认证 | `localStorage` + `UserContext` | `contexts/UserContext.tsx` |
| 主题 | `ThemeContext` | `contexts/ThemeContext.tsx` |
| 审批状态 | `ApprovalContext` | `contexts/ApprovalContext.tsx` |
| 插件 | `PluginContext` | `plugins/PluginContext.tsx` |
| 国际化 | `i18next` | `i18n/` 目录 |
| 路由状态 | `react-router-dom` | `App.tsx` |

### 3.3 API 缓存

**文件**：`client/src/api/modules/skill.ts`（示例）

```typescript
const CACHE_TTL_MS = 30000; // 30 秒
const apiCache = new Map<string, { data: unknown; timestamp: number }>();

// provider.ts 中也有类似缓存
let listProvidersPromise: Promise<ProviderInfo[]> | null = null;
const activeModelPromises = new Map<string, Promise<ActiveModelsInfo>>();
```

**缓存失效**：`invalidateSkillCache()` 支持按 agentId/workspaces/pool 精确失效。

---

## 4. 关键修复点（按问题类型分类）

### 4.1 模型选择/显示问题

| 层级 | 文件 | 函数/位置 | 说明 |
|------|------|----------|------|
| 前端 | `pages/Chat/ModelSelector/index.tsx` | `fetchAvailableModels()` (L55-85) | 调用 `userModelPrefsApi.getAvailableModels()` |
| 前端 | `pages/Chat/ModelSelector/index.tsx` | `fetchActiveModel()` (L90-100) | 调用 `providerApi.getActiveModels()` |
| 前端 | `pages/Settings/Models/.../RemoteProviderCard.tsx` | `isConfigured` 判断 (L45-58) | Provider 可用状态显示 |
| 前端 | `api/modules/user_model_prefs.ts` | `getAvailableModels()` | `GET /api/models/available` |
| 前端 | `api/modules/provider.ts` | `getActiveModels()` | `GET /api/models/active` |
| 后端 | `routers/admin_providers.py` | `_get_available_models_for_users()` | 可用模型池构建 |

### 4.2 智能体名称显示不一致

| 层级 | 文件 | 函数 | 说明 |
|------|------|------|------|
| 前端 | `utils/agentDisplayName.ts` | `getAgentDisplayName()` | **统一入口** |
| 前端 | `Chat/ModelSelector/index.tsx` | 侧边栏下拉 | 应使用统一函数 |
| 前端 | `Settings/Agents/index.tsx` | 智能体管理 | 应使用统一函数 |
| 前端 | `Admin/index.tsx` | 管理员面板 | 应使用统一函数 |

### 4.3 登录/认证问题

| 层级 | 文件 | 函数 | 说明 |
|------|------|------|------|
| 前端 | `api/modules/auth.ts` | `authApi.login()` | 直接 fetch（无 token） |
| 前端 | `api/authHeaders.ts` | `buildAuthHeaders()` | Bearer token 注入 |
| 前端 | `api/config.ts` | `getApiToken()` | 从 localStorage 读取 |
| 前端 | `pages/Login/index.tsx` | 登录表单 | 登录逻辑 |
| 后端 | `app/auth.py` | `authenticate()` | 密码校验 |
| 后端 | `app/user_store.py` | `authenticate_user()` | JSON 用户存储 |

### 4.4 文件上传/预览

| 层级 | 文件 | 函数 | 说明 |
|------|------|------|------|
| 前端 | `api/modules/chat.ts` | `chatApi.uploadFile()` | FormData 上传 |
| 前端 | `api/modules/chat.ts` | `chatApi.filePreviewUrl()` | 预览 URL 构建（防重复前缀） |
| 前端 | `pages/MySpace/index.tsx` | 文件管理 | `/myfiles/*` API |
| 后端 | `routers/console.py` | 文件上传端点 | `POST /api/myfiles/upload` |

### 4.5 技能管理

| 层级 | 文件 | 函数 | 说明 |
|------|------|------|------|
| 前端 | `api/modules/skill.ts` | `skillApi.*` | 带缓存的技能 API |
| 前端 | `api/modules/skill.ts` | `invalidateSkillCache()` | 缓存失效 |
| 前端 | `pages/Agent/Skills/index.tsx` | 技能管理页面 | 智能体级别技能 |
| 前端 | `pages/Settings/SkillPool/index.tsx` | 技能池管理 | 全局技能池 |
| 后端 | `routers/skills.py` | 所有端点 | 73 个端点，最大路由文件 |

### 4.6 备份/恢复

| 层级 | 文件 | 函数 | 说明 |
|------|------|------|------|
| 前端 | `api/modules/backup.ts` | `backupApi.*` | 备份 API |
| 前端 | `pages/Settings/Backups/index.tsx` | 备份管理页面 | UI |
| 后端 | `routers/backup.py` | `/backups/*` | 备份操作 |
| 后端 | `routers/backups.py` | 备份辅助 | 辅助端点 |

---

## 5. 文件速查表：常见报错 → 对应文件 → 修复方向

| 报错/问题 | 对应前端文件 | 对应后端文件 | 修复方向 |
|----------|------------|------------|---------|
| 登录后页面白屏 | `api/authHeaders.ts`, `api/config.ts` | `app/auth.py` | 检查 token 存储和注入 |
| 模型下拉为空 | `Chat/ModelSelector/index.tsx` | `routers/user_model_prefs.py` | 检查 `/models/available` 响应 |
| Provider 显示"未配置" | `Settings/Models/.../RemoteProviderCard.tsx` | `routers/providers.py` | 检查 `is_configured` 判断逻辑 |
| 智能体名称显示 ID | `utils/agentDisplayName.ts` | `routers/agents.py` | 统一使用 `getAgentDisplayName()` |
| 聊天发送无响应 | `Chat/index.tsx` → `sessionApi.ts` | `routers/console.py` | 检查 WebSocket/HTTP 连接 |
| 文件上传失败 | `api/modules/chat.ts` → `uploadFile()` | `routers/console.py` | 检查 `/myfiles/upload` 端点 |
| 文件预览 404 | `api/modules/chat.ts` → `filePreviewUrl()` | 静态文件路由 | 检查 URL 前缀拼接逻辑 |
| 技能安装按钮无反应 | `api/modules/skill.ts` → `installSkill()` | `routers/skills.py` | 检查权限 `skills:write` |
| 权限矩阵不生效 | `api/modules/permissions.ts` | `permissions/manager.py` | 检查 `config/permissions.json` |
| 备份列表为空 | `api/modules/backup.ts` | `routers/backup.py` | 检查 `WORKSPACES_DIR` 路径 |
| Token 用量显示 0 | `api/modules/tokenUsage.ts` | `routers/token_usage.py` | 检查 token 记录写入 |
| 环境变量不保存 | `api/modules/env.ts` | `routers/envs.py` | 检查 `envs.json` 文件权限 |
| 502 Bad Gateway | 所有 API 调用 | Docker 环境 | **重建后端后必须重启 nginx** |
| 页面路由 404 | `App.tsx` 路由配置 | N/A | 检查路由定义 |
| i18n 翻译缺失 | `i18n/` 目录 | N/A | 添加对应语言文件 |
| SSE 流式响应中断 | `Chat/index.tsx` SSE 逻辑 | `app/auth_middleware.py` | 检查 SSE 中间件兼容性 |
| 跨域请求被拒 | `api/request.ts` | `_app.py` CORS 配置 | 检查 `CORS_ORIGINS` 常量 |
| 本地模型启动失败 | `api/modules/localModel.ts` | `routers/local_models.py` | 检查本地模型依赖 |
| MCP 客户端连接失败 | `api/modules/mcp.ts` | `routers/mcp.py` | 检查 MCP 配置 |
| 定时任务不执行 | `api/modules/cronjob.ts` | `crons/api.py` | 检查 cron 调度器状态 |
| 频道消息收不到 | `api/modules/channel.ts` | `channels/registry.py` | 检查频道注册和配置 |

---

## 6. 工具函数

| 文件 | 函数 | 用途 |
|------|------|------|
| `utils/agentDisplayName.ts` | `getAgentDisplayName(agent, t)` | 统一智能体名称显示 |
| `utils/error.ts` | 错误处理工具 | 统一错误格式化 |
| `utils/formatNumber.ts` | `formatNumber()` | 数字格式化（千分位等） |
| `utils/markdown.ts` | Markdown 渲染 | 聊天消息 Markdown 处理 |
| `utils/lazyWithRetry.ts` | `lazyWithRetry()` | 带重试的懒加载 |
| `utils/scanError.ts` | 错误扫描 | 扫描错误信息 |
| `utils/skill.ts` | 技能工具函数 | 技能相关辅助 |
| `utils/saveBlobToDisk.ts` | `saveBlobToDisk()` | Blob 文件保存 |
| `utils/freeModelSwitchWarning.tsx` | 免费模型切换警告 | 模型切换提示 |

---

## 7. 组件库

项目使用 `@agentscope-ai/design` 作为 UI 组件库，基于 Ant Design 封装。

关键组件：
- `Card`, `Button`, `Modal`, `Input`, `Select`, `Table`, `Tabs` — 基础 UI
- `IconButton` — 图标按钮
- `AgentScopeRuntimeWebUI` — 聊天运行时 UI（`@agentscope-ai/chat`）

---

## 8. 路由结构

**文件**：`client/src/App.tsx`（推断）

```
/                        → Chat（默认）
/login                   → Login
/admin                   → Admin
/agent/:id/config        → Agent/Config
/agent/:id/skills        → Agent/Skills
/agent/:id/tools         → Agent/Tools
/agent/:id/mcp           → Agent/MCP
/agent/:id/acp           → Agent/ACP
/agent/:id/workspace     → Agent/Workspace
/settings/models         → Settings/Models
/settings/agents         → Settings/Agents
/settings/skills         → Settings/SkillPool
/settings/backups        → Settings/Backups
/settings/security       → Settings/Security
/settings/token-usage    → Settings/TokenUsage
/settings/environments   → Settings/Environments
/settings/agent-stats    → Settings/AgentStats
/settings/debug          → Settings/Debug
/settings/voice          → Settings/VoiceTranscription
/control/channels        → Control/Channels
/control/cronjobs        → Control/CronJobs
/control/heartbeat       → Control/Heartbeat
/control/sessions        → Control/Sessions
/myspace                 → MySpace
/cross-agent             → CrossAgent
/evolution               → Evolution
/multi-layer-evolution   → MultiLayerEvolution
/knowledge               → KnowledgeBase
/user-system             → UserSystem
/user-profile            → UserProfile
/sso                     → SSO
/monitoring              → Monitoring
```
