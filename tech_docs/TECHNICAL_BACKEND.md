# CoApis 后端技术文档

> **目标**：遇到任何 bug 时，30 秒内定位到具体文件和函数。

---

## 1. 模块结构

```
server/coapis/
├── app/
│   ├── _app.py                    # 🚀 FastAPI 应用入口（lifespan、中间件、路由挂载）
│   ├── auth.py                    # 🔐 认证核心（JWT、bcrypt、token 验证/撤销）
│   ├── auth_middleware.py         # 认证中间件（SSE 兼容）
│   ├── multi_agent_manager.py     # 多智能体管理器
│   ├── agent_context.py           # Agent 上下文（X-Agent-Id header 解析）
│   ├── migration.py               # 数据迁移（旧 workspace → 新 agent、QA agent 初始化）
│   ├── user_store.py              # JSON 用户认证存储（登录/注册用）
│   ├── routers/                   # ⭐ 所有 API 路由
│   │   ├── __init__.py            # 路由注册中心（统一 include_router）
│   │   ├── agents.py              # 智能体 CRUD（8 endpoints）
│   │   ├── admin_providers.py     # 管理员 Provider 配置 + 可用模型端点
│   │   ├── auth.py                # /auth/* 认证路由（12 endpoints）
│   │   ├── skills.py              # /skills/* 技能管理（73 endpoints，最大路由）
│   │   ├── providers.py           # /models/* Provider/模型管理（16 endpoints）
│   │   ├── config.py              # /config/* 配置（33 endpoints）
│   │   ├── config_router.py       # 扩展配置路由（17 endpoints）
│   │   ├── chats.py               # 聊天会话管理（7 endpoints）
│   │   ├── console.py             # 控制台（7 endpoints）
│   │   ├── security.py            # 安全设置（14 endpoints）
│   │   ├── permissions.py         # /permissions/* 权限管理（14 endpoints）
│   │   ├── tools.py               # 工具管理（14 endpoints）
│   │   ├── evolution.py           # 进化系统（19 endpoints）
│   │   ├── multi_layer_evolution.py # 多层进化（14 endpoints）
│   │   ├── local_models.py        # 本地模型管理（11 endpoints）
│   │   ├── mcp.py                 # MCP 客户端（7 endpoints）
│   │   ├── cron.py                # 定时任务（9 endpoints）
│   │   ├── backup.py              # /backups/* 备份（7 endpoints）
│   │   ├── voice.py               # 语音转写
│   │   ├── websocket.py           # WebSocket 连接
│   │   ├── approval.py            # /approval/* 审批（3 endpoints）
│   │   ├── messages.py            # /messages/* 消息（1 endpoint）
│   │   ├── settings.py            # 设置（3 endpoints）
│   │   ├── plan.py                # 计划系统（4 endpoints）
│   │   ├── token_usage.py         # Token 用量统计（4 endpoints）
│   │   ├── agent_stats.py         # 智能体统计（1 endpoint）
│   │   ├── health.py              # 健康检查（3 endpoints）
│   │   ├── root.py                # 根路由（2 endpoints）
│   │   ├── init.py                # 初始化（3 endpoints）
│   │   ├── envs.py                # 环境变量（3 endpoints）
│   │   ├── growth.py              # 成长系统（4 endpoints）
│   │   ├── foundation.py          # 基础设施（5 endpoints）
│   │   ├── plugins.py             # /plugins/* 插件（2 endpoints）
│   │   ├── audit.py               # 审计日志（4 endpoints）
│   │   ├── commands.py            # 命令系统（3 endpoints）
│   │   ├── user_model_prefs.py    # 用户模型偏好（7 endpoints）
│   │   ├── workspace.py           # 工作区管理
│   │   ├── skills_stream.py       # 技能流式接口
│   │   └── admin/                 # 管理员子路由
│   │       ├── admin_users.py     # 用户管理（6 endpoints）
│   │       ├── admin_global_agents.py # 全局智能体（12 endpoints）
│   │       ├── admin_config.py    # 全局配置（2 endpoints）
│   │       ├── admin_system.py    # 系统概览（3 endpoints）
│   │       ├── admin_audit.py     # 审计日志（4 endpoints）
│   │       ├── admin_templates.py # 全局模板（4 endpoints）
│   │       └── admin_tools.py     # 系统工具（5 endpoints）
│   ├── user/                      # 用户子路由
│   │   ├── user_me.py             # 个人信息（1 endpoint）
│   │   ├── user_preferences.py    # 偏好设置（3 endpoints）
│   │   └── user_feedback.py       # 用户反馈（1 endpoint）
│   ├── workspace/                 # 工作区子路由
│   │   ├── workspace_agents.py    # 工作区智能体（7 endpoints）
│   │   ├── workspace_models.py    # 工作区模型（5 endpoints）
│   │   ├── workspace_skills.py    # 工作区技能（6 endpoints）
│   │   ├── workspace_backups.py   # 工作区备份（6 endpoints）
│   │   ├── workspace_security.py  # 工作区安全（6 endpoints）
│   │   ├── workspace_audit.py     # 工作区审计（3 endpoints）
│   │   └── workspace_voice.py     # 工作区语音（8 endpoints）
│   ├── channels/                  # 频道系统
│   │   ├── registry.py            # 频道注册中心
│   │   ├── wecom/                 # 企业微信
│   │   ├── dingtalk/              # 钉钉
│   │   ├── feishu/                # 飞书
│   │   └── console/               # 控制台频道
│   └── permissions/               # 权限系统
│       ├── manager.py             # PermissionManager（CRUD 矩阵）
│       ├── decorators.py          # @require_permission 装饰器
│       └── __init__.py            # 导出 require_permission
│
├── agent/                         # 智能体引擎
│   ├── core.py                    # 核心 Agent 逻辑
│   ├── react_agent.py             # ReAct Agent 实现
│   ├── workspace.py               # Workspace 管理
│   ├── skills_manager.py          # 技能管理器
│   ├── model_factory.py           # 模型工厂
│   └── prompt.py                  # Prompt 构建
│
├── config/
│   ├── config.py                  # Pydantic 配置模型
│   └── utils.py                   # load_config / save_config
│
├── providers/
│   └── provider_manager.py        # Provider 管理（API 调用、模型路由）
│
├── user_system/                   # 用户系统
│   ├── database.py                # UserSystemDB（JSON/SQLite 双模式）
│   ├── models.py                  # Pydantic 数据模型
│   ├── service.py                 # 用户业务逻辑
│   ├── middleware.py               # 用户上下文/隔离中间件
│   └── routers/                   # 用户系统路由（users_router, points_router, tokens_router）
│
├── crons/
│   └── api.py                     # 定时任务 API
│
├── constant.py                    # 全局常量（路径、端口、CORS 等）
└── __version__.py                 # 版本号
```

---

## 2. 路由地图

### 2.1 路由注册机制

**文件**：`server/coapis/app/routers/__init__.py`

所有路由通过 `APIRouter()` 统一注册，然后在 `_app.py` 中挂载到 `/api` 前缀：

```python
# routers/__init__.py
router = APIRouter()
router.include_router(agents_router)
router.include_router(auth_router)
# ... 所有路由 ...

# _app.py
app.include_router(api_router, prefix="/api")
```

### 2.2 权限装饰器规则

**文件**：`server/coapis/app/permissions/decorators.py`

```python
# ✅ 正确：@router.* 在外，@require_* 在内
@router.post("/skills/install")
@require_permission("skills:write")
async def install_skill(request: Request):
    ...

# ❌ 错误：FastAPI 注册的是原始函数，装饰器不执行
@require_permission("skills:write")
@router.post("/skills/install")
async def install_skill(request: Request):
    ...
```

**被保护路由必须有 `request: Request` 参数**，装饰器从中提取用户信息。

### 2.3 核心路由表

| 路由文件 | Prefix | 端点数 | 权限要求 | 主要功能 |
|---------|--------|--------|---------|---------|
| `auth.py` | `/auth` | 12 | 部分公开 | 登录/注册/验证/token 管理 |
| `agents.py` | (无) | 8 | `models:read` | 智能体 CRUD、排序、启停 |
| `skills.py` | `/skills` | 73 | `skills:read/write` | 技能安装/卸载/配置/搜索 |
| `providers.py` | `/models` | 16 | `models:read` | Provider 列表/配置/激活模型 |
| `admin_providers.py` | (无) | 7 | `admin:admin` | 全局 Provider 管理、可用模型池 |
| `config.py` | `/config` | 33 | `config:read/write` | 配置读写 |
| `config_router.py` | (无) | 17 | 混合 | 扩展配置 |
| `chats.py` | (无) | 7 | `chat:read` | 聊天会话 CRUD |
| `console.py` | (无) | 7 | `chat:send` | 对话执行 |
| `security.py` | (无) | 14 | `admin:admin` | 安全策略 |
| `permissions.py` | `/permissions` | 14 | `admin:admin` | 权限矩阵管理 |
| `tools.py` | (无) | 14 | `tools:read` | 工具管理 |
| `evolution.py` | (无) | 19 | 混合 | 智能体进化系统 |
| `multi_layer_evolution.py` | (无) | 14 | 混合 | 多层进化 |
| `local_models.py` | (无) | 11 | 混合 | 本地模型管理 |
| `mcp.py` | (无) | 7 | `tools:read` | MCP 客户端 |
| `cron.py` | (无) | 9 | 混合 | 定时任务 |
| `backup.py` | `/backups` | 7 | 混合 | 备份管理 |
| `token_usage.py` | (无) | 4 | `models:read` | Token 用量统计 |
| `approval.py` | `/approval` | 3 | 混合 | 操作审批 |
| `voice.py` | (无) | ... | 混合 | 语音转写 |
| `websocket.py` | (无) | ... | 无 | WebSocket 连接 |
| `settings.py` | (无) | 3 | 混合 | 系统设置 |
| `plan.py` | (无) | 4 | 混合 | 计划管理 |
| `health.py` | (无) | 3 | 公开 | 健康检查 |
| `root.py` | (无) | 2 | 公开 | 根路由 |
| `growth.py` | (无) | 4 | 混合 | 成长系统 |
| `foundation.py` | (无) | 5 | 混合 | 基础设施 |
| `plugins.py` | `/plugins` | 2 | 混合 | 插件管理 |
| `audit.py` | (无) | 4 | `admin:admin` | 审计日志 |
| `commands.py` | (无) | 3 | 混合 | 命令系统 |
| `user_model_prefs.py` | (无) | 7 | `models:read` | 用户模型偏好 |
| `envs.py` | (无) | 3 | 混合 | 环境变量 |

### 2.4 管理员子路由

| 路由文件 | Prefix | 端点数 | 权限 |
|---------|--------|--------|------|
| `admin/admin_users.py` | `/admin` | 6 | `admin:admin` |
| `admin/admin_global_agents.py` | `/admin` | 12 | `admin:admin` |
| `admin/admin_config.py` | `/admin` | 2 | `admin:admin` |
| `admin/admin_system.py` | `/admin` | 3 | `admin:admin` |
| `admin/admin_audit.py` | `/admin` | 4 | `admin:admin` |
| `admin/admin_templates.py` | `/admin` | 4 | `admin:admin` |
| `admin/admin_tools.py` | `/admin` | 5 | `admin:admin` |

### 2.5 用户/工作区子路由

| 路由文件 | Prefix | 端点数 | 权限 |
|---------|--------|--------|------|
| `user/user_me.py` | (无) | 1 | 登录用户 |
| `user/user_preferences.py` | (无) | 3 | 登录用户 |
| `user/user_feedback.py` | (无) | 1 | 登录用户 |
| `workspace/workspace_agents.py` | (无) | 7 | 混合 |
| `workspace/workspace_models.py` | (无) | 5 | 混合 |
| `workspace/workspace_skills.py` | (无) | 6 | 混合 |
| `workspace/workspace_backups.py` | (无) | 6 | 混合 |
| `workspace/workspace_security.py` | (无) | 6 | 混合 |
| `workspace/workspace_audit.py` | (无) | 3 | 混合 |
| `workspace/workspace_voice.py` | (无) | 8 | 混合 |

---

## 3. 核心数据流

### 3.1 请求处理链路

```
客户端请求
  ↓
FastAPI App (_app.py)
  ↓
中间件链（按安装顺序）：
  1. CORSMiddleware          ← 跨域
  2. AgentContextMiddleware   ← 解析 X-Agent-Id → request.state.agent_id
  3. install_user_context_middleware    ← 用户上下文注入
  4. install_user_isolation_middleware  ← 用户数据隔离
  5. install_quota_check_middleware     ← 配额检查
  6. install_rate_limit_middleware      ← 限流
  7. install_auth_middleware            ← JWT 认证（SSE 兼容）
  ↓
路由匹配（routers/__init__.py → api_router → /api/*）
  ↓
权限装饰器 @require_permission("module:action")
  → PermissionManager.has_permission(username, "module:action")
  → 检查 roles → modules → CRUD 矩阵
  → 检查 user_overrides 覆盖
  ↓
路由处理函数
  ↓
Service 层 / 业务逻辑
  ↓
响应返回
```

### 3.2 认证流程

**文件**：`server/coapis/app/auth.py` + `server/coapis/app/routers/auth.py`

```
POST /api/auth/login
  ↓
auth.py::authenticate(username, password)
  → user_store.py::authenticate_user()
    → 读取 SYSTEM_DIR/auth/users.json
    → bcrypt 校验密码（兼容旧 SHA-256）
  ↓
生成 JWT token（HMAC-SHA256）
  → 存入 SYSTEM_DIR/auth/auth.json
  ↓
返回 { token, username }
```

### 3.3 权限系统数据流

**文件**：`server/coapis/system/defaults.py` + `server/coapis/app/permissions/manager.py`

```
启动时:
defaults.py::DEFAULT_PERMISSIONS
  → 定义权限配置（modules: 模块定义, roles: 角色配置, user_overrides: 用户覆盖）
  ↓
PermissionManager.initialize(SYSTEM_DIR / "permissions.json")
  → 读取 permissions.json（覆盖默认值）
  → 检查 version 字段，必要时迁移 v1 → v2
  ↓
GET /api/permissions/config
  → 返回 { config: pm.get_config() }
  → config.modules 包含模块定义（name, icon, description）
  → config.roles 包含角色配置（modules CRUD 矩阵）
```

**关键字段名**：
- `config.modules`：模块定义（聊天、技能、模型等）
- `config.roles[name].modules`：角色权限矩阵（CRUD 操作）
- ⚠️ **必须使用 `modules`**，不是 `module_definitions`（前后端统一字段名）

### 3.4 模型可用性判断

**后端**：`server/coapis/app/routers/admin_providers.py`

```python
# _get_available_models_for_users() 函数
for pid, pconfig in providers.items():
    if not pconfig.get("enabled", True): continue
    models = pconfig.get("models", [])
    visible = pconfig.get("visible_to_users", True)
    if visible:
        available.extend(models)
    else:
        available.extend(pconfig.get("visible_models", []))
```

**前端**：`client/src/pages/Settings/Models/components/cards/RemoteProviderCard.tsx`

```typescript
// 可用性判断逻辑（必须与后端一致）
let isConfigured = false;
if (provider.is_custom && provider.base_url) {
    isConfigured = true;
} else if (provider.require_api_key === false) {
    isConfigured = true;
} else if (provider.require_api_key && provider.api_key) {
    isConfigured = true;
}
const hasModels = (provider.models.length + provider.extra_models.length) > 0;
const isAvailable = isConfigured && hasModels;
```

### 3.4 多智能体路由

**文件**：`server/coapis/app/_app.py` → `DynamicMultiAgentRunner`

```
请求 → DynamicMultiAgentRunner._get_workspace(request)
  → get_current_agent_id(request)  # 从 X-Agent-Id header 或 context
  → MultiAgentManager.get_workspace(agent_id)
  → 返回对应 Workspace 实例
  → workspace.runner.query_handler(request)
```

---

## 4. 关键修复点（按问题类型分类）

### 4.1 LLM 模型选择不显示

| 层级 | 文件 | 函数/位置 | 说明 |
|------|------|----------|------|
| 后端 | `routers/admin_providers.py` | `_get_available_models_for_users()` (L130-150) | 构建可用模型池 |
| 后端 | `routers/admin_providers.py` | `get_available_models()` (L230-260) | `/admin/providers/models` 端点 |
| 后端 | `routers/user_model_prefs.py` | `get_available_models()` | `/models/available` 端点（用户视角） |
| 前端 | `pages/Settings/Models/.../RemoteProviderCard.tsx` | `isConfigured` 判断逻辑 (L45-58) | Provider 可用状态 |
| 前端 | `pages/Chat/ModelSelector/index.tsx` | `fetchAvailableModels()` (L55-85) | 聊天模型选择器 |

**关键逻辑**：`is_configured = (is_custom && base_url) || (!require_key) || (require_key && has_key); is_available = is_configured && hasModels`

**必须同时读取** `pi.models` 和 `pi.extra_models`。

### 4.2 用户管理 500 报错

| 层级 | 文件 | 函数 | 说明 |
|------|------|------|------|
| 后端 | `routers/admin/admin_users.py` | `list_all_users()` (L120-145) | ⚠️ 必须用 `db.list_users_page()` |
| 后端 | `routers/admin/admin_users.py` | `create_user_admin()` (L150-210) | 双写：SQLite + JSON user_store |
| 后端 | `routers/admin/admin_users.py` | `_ensure_admin_in_db()` (L85-115) | admin 用户同步 |
| 后端 | `user_system/database.py` | `list_users_page()` (L540-560) | 分页查询 |
| 后端 | `user_system/database.py` | `get_user_by_id()` | 按 ID 查询 |
| 后端 | `user_system/database.py` | `update_user_by_id()` | 按 ID 更新 |
| 后端 | `user_system/database.py` | `delete_user_by_id()` | 按 ID 删除 |

**⚠️ 铁律**：开源版固定 JSON 模式，**不能用 SQL 查询**，必须用 `UserSystemDB` 的高级方法。

### 4.3 Admin 用户登录报错

| 层级 | 文件 | 函数 | 说明 |
|------|------|------|------|
| 后端 | `user_system/database.py` | `_load_json()` | 必须支持 `{"users": {...}}` 字典格式 |
| 后端 | `user_system/database.py` | `_save_json()` | 保持 `{"users": {...}}` 格式 |
| 后端 | `app/user_store.py` | `get_user()` / `create_user()` | JSON 认证存储 |

**兼容性**：`_save_json` 对 `users.json` 自动将 list 转为 `{"users": {"username": {...}}}` 格式，兼容 `user_store.py`。

### 4.4 智能体名称显示不一致

| 层级 | 文件 | 函数 | 说明 |
|------|------|------|------|
| 前端 | `utils/agentDisplayName.ts` | `getAgentDisplayName()` | **统一入口** |
| 前端 | `pages/Chat/` | 侧边栏下拉菜单 | 应使用 `getAgentDisplayName` |
| 前端 | `pages/Admin/` 或 `Settings/Agents/` | 智能体管理列表 | 应使用 `getAgentDisplayName` |

**规则**：`default` agent 用 i18n 翻译，其他用 `agent.name || agent.id`。

### 4.5 权限系统

| 层级 | 文件 | 函数 | 说明 |
|------|------|------|------|
| 后端 | `permissions/manager.py` | `PermissionManager.has_permission()` | 核心判断 |
| 后端 | `permissions/manager.py` | `_load_config()` | 从 `config/permissions.json` 加载 |
| 后端 | `permissions/decorators.py` | `require_permission()` | 路由装饰器 |
| 后端 | `permissions/manager.py` | `_ACTION_TO_CRUD` | action → CRUD 映射 |

**CRUD 映射**：`send/create/write` → `[create, update]`，`read` → `[read]`，`delete` → `[delete]`，`execute` → `[create, update, delete]`

### 4.6 数据库模式

| 层级 | 文件 | 函数 | 说明 |
|------|------|------|------|
| 后端 | `user_system/database.py` | `_is_database_enabled()` | 开源版固定返回 `False`（JSON 模式） |
| 后端 | `user_system/database.py` | `UserSystemDB` | 单例，线程安全 |
| 后端 | `user_system/database.py` | `_load_json()` | JSON 文件读取 |
| 后端 | `user_system/database.py` | `_save_json()` | JSON 文件写入（原子替换） |

**JSON 文件位置**：`SYSTEM_DIR/` 下的 `users.json`, `audit_logs.json`, `user_settings.json` 等。

---

## 5. 文件速查表：常见报错 → 对应文件 → 修复方向

| 报错/问题 | 对应文件 | 修复方向 |
|----------|---------|---------|
| `500 Internal Server Error` 用户管理 | `routers/admin/admin_users.py` | 检查是否用了 SQL 直接查询，改用 `UserSystemDB` 方法 |
| `403 Forbidden` 管理员操作 | `permissions/decorators.py` + `permissions/manager.py` | 检查 `config/permissions.json` 角色配置 |
| `401 Unauthorized` 所有请求 | `app/auth.py` → `auth_middleware.py` | 检查 JWT token 是否过期/撤销 |
| 登录失败 `Invalid credentials` | `app/user_store.py` → `app/auth.py` | 检查密码哈希格式（bcrypt vs SHA-256） |
| `admin` 用户登录报错 | `user_system/database.py` → `_load_json()` | 检查 `users.json` 格式是否为 `{"users": {...}}` |
| 模型不显示在下拉框 | `routers/admin_providers.py` → `_get_available_models_for_users()` | 检查 Provider `enabled` 和 `visible_to_users` 设置 |
| 模型可用状态错误 | `RemoteProviderCard.tsx` L45-58 | 检查 `is_configured` 和 `hasModels` 判断逻辑 |
| WebSocket 连接失败 | `routers/websocket.py` + `_app.py` lifespan | 检查 WebSocket 路由注册和认证中间件 |
| 智能体名称显示 `id` 而非 `name` | `utils/agentDisplayName.ts` | 统一使用 `getAgentDisplayName()` |
| 502 Bad Gateway | Docker 环境 | **重建后端后必须重启 nginx** |
| `agent_id` 找不到 | `app/agent_context.py` → `get_current_agent_id()` | 检查 `X-Agent-Id` header |
| 技能安装失败 | `routers/skills.py` → `skills_manager.py` | 检查技能目录权限和依赖 |
| 配置读写失败 | `config/utils.py` → `load_config()` / `save_config()` | 检查 `config/` 目录权限 |
| Token 用量统计不准 | `routers/token_usage.py` → `user_system/routers/tokens_router` | 检查 token 记录是否正确写入 |
| 备份/恢复失败 | `routers/backup.py` + `routers/backups.py` | 检查 `WORKSPACES_DIR` 路径权限 |
| 频道消息收不到 | `app/channels/registry.py` → 对应频道目录 | 检查频道配置和注册 |
| `provider_manager` 报错 | `providers/provider_manager.py` | 检查 Provider 配置和 API Key |
| 环境变量不生效 | `app/envs.py` → `load_envs_into_environ()` | 检查 `envs.json` 文件 |
| 权限矩阵显示英文模块名 | `system/defaults.py` + `client/src/pages/Admin/index.tsx` | 确保 `defaults.py` 使用 `modules` 字段名（不是 `module_definitions`），前端兼容两种字段名 |
| 技能页面加载失败 (500) | `agents/skills_manager.py` + `docker/.env.dev` | 1. 确保 `COAPIS_WORKING_DIR` 与 docker-compose 挂载路径一致；2. `skills_manager.py` 中 `_mutate_json` 需处理 `skills` 为列表的旧格式 |

---

### 4.7 权限系统字段名规范（重要！）

**问题**：后端 `system/defaults.py` 定义 `DEFAULT_PERMISSIONS` 时使用了 `module_definitions` 作为字段名，但前端读取 `cfg.config?.modules`，导致权限矩阵显示英文模块名（chat、skills 等）而非中文名称（聊天、技能等）。

**根因**：
- 后端 `defaults.py` 使用 `module_definitions` 字段名
- 前端 `Admin/index.tsx` 读取 `modules` 字段名
- 两者不一致导致前端 fallback 到英文 key

**修复**：
1. **后端**：`system/defaults.py` 中 `module_definitions` → `modules`（统一字段名）
2. **前端**：`Admin/index.tsx` 兼容两种字段名 `cfg.config?.modules || cfg.config?.module_definitions || {}`
3. **数据文件**：确保 `system/permissions.json` 使用 `modules` 字段名

**验证方法**：
```bash
# 检查后端返回的字段名
curl -X POST http://localhost:4300/api/auth/login -H "Content-Type: application/json" -d '{"username":"admin","password":"admin123"}' | jq -r '.token' > /tmp/token.txt
curl -s http://localhost:4300/api/permissions/config -H "Authorization: Bearer $(cat /tmp/token.txt)" | jq '.config | keys'
# 应该返回 ["modules", "roles", "version", ...]，不是 ["module_definitions", ...]
```

**相关文件**：
| 文件 | 字段名 | 说明 |
|------|--------|------|
| `server/coapis/system/defaults.py` | `modules` | 默认权限配置 |
| `server/coapis/app/permissions/manager.py` | `modules` | 权限管理器 |
| `client/src/pages/Admin/index.tsx` | `modules` 或 `module_definitions` | 前端兼容读取 |
| `system/permissions.json` | `modules` | 实际数据文件 |

---

## 6. Docker 部署

### 6.1 文件位置

| 环境 | Compose 文件 | 端口 | 镜像 |
|------|-------------|------|------|
| 开发 | `docker/docker-compose.dev.yaml` | 4300 (nginx) / 4308 (server) | `coapis-server:dev` |
| 生产 | `docker/docker-compose.yml` | 4200 (nginx) / 4208 (server) | `coapis-server:latest` |

### 6.2 生产镜像构建

```bash
docker build -f server/deploy/Dockerfile -t coapis-server:latest .
```

### 6.3 ⚠️ 重建后端后必须重启 nginx

```bash
# 正确序列
docker compose -f docker-compose.dev.yaml up -d --force-recreate server
sleep 10
docker restart coapis-nginx-dev  # 必须！
```

**原因**：后端容器重建后 IP 变化，nginx upstream 连接池失效，所有 API 返回 502。

---

## 7. 关键常量

**文件**：`server/coapis/constant.py`

| 常量 | 说明 |
|------|------|
| `WORKING_DIR` | 工作目录（配置、数据） |
| `SYSTEM_DIR` | 系统目录（用户数据、认证） |
| `WORKSPACES_DIR` | 工作区目录 |
| `DATA_DIR` | 数据目录 |
| `AUTH_FILE` | 认证文件路径 |
| `TOKEN_EXPIRY_SECONDS` | Token 过期时间 |
| `PUBLIC_PATHS` | 公开路径（无需认证） |
| `PUBLIC_PREFIXES` | 公开前缀 |
| `CORS_ORIGINS` | CORS 允许来源 |

---

## 8. 系统初始化流程

**文件**：`server/coapis/app/_app.py` → `lifespan()` + `server/coapis/system/initializer.py`

```
lifespan() 启动
  ↓ Phase 1（同步，<100ms）
  auto_register_from_env()           ← 自动注册环境变量中的用户
  telemetry（可选）
  ↓ Phase 2（后台）
  migrate_legacy_workspace_to_default_agent()  ← 旧 workspace 迁移
  migrate_legacy_skills_to_skill_pool()        ← 旧技能迁移
  ensure_default_agent_exists()                ← 确保 default agent 存在
  ensure_qa_agent_exists()                     ← 确保 QA agent 存在
  ensure_global_templates_exist()              ← 确保全局模板存在
  ensure_global_agent_roles()                  ← 确保全局智能体角色
  ensure_layered_templates()                   ← 确保分层模板
  PermissionManager.initialize()               ← 初始化权限系统
  ProviderManager.initialize()                 ← 初始化 Provider 管理器
  LocalModelManager.initialize()               ← 初始化本地模型管理器
  MultiAgentManager.initialize()               ← 初始化多智能体管理器
  ↓
  app.state.startup_ready.set()               ← 标记启动完成
```
