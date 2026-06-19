# CoApis 架构设计文档

## 📋 目录

- [整体架构](#整体架构)
- [目录结构](#目录结构)
- [数据流架构](#数据流架构)
- [多租户隔离架构](#多租户隔离架构)
- [分层记忆架构](#分层记忆架构)
- [认证与权限架构](#认证与权限架构)
- [技能系统架构](#技能系统架构)
- [进化系统架构](#进化系统架构)
- [部署架构](#部署架构)
- [技术栈](#技术栈)

---

## 整体架构

CoApis 采用**三层架构**设计：

```
┌─────────────────────────────────────────────────────────────────┐
│                      Presentation Layer                          │
│  ┌─────────────────┐  ┌─────────────────┐  ┌─────────────────┐ │
│  │   Web Console   │  │   API Gateway   │  │  Channel Proxy  │ │
│  │  (React + Vite) │  │   (Nginx)       │  │ (WeCom/DingTalk│ │
│  └─────────────────┘  └─────────────────┘  │  /Slack/Telegram)│ │
└─────────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────────┐
│                       Application Layer                          │
│  ┌─────────────────┐  ┌─────────────────┐  ┌─────────────────┐ │
│  │   FastAPI       │  │   Auth & RBAC   │  │   File Backend  │ │
│  │   (Backend)     │  │   (Middleware)  │  │  (Local/Remote) │ │
│  └─────────────────┘  └─────────────────┘  └─────────────────┘ │
│  ┌─────────────────┐  ┌─────────────────┐  ┌─────────────────┐ │
│  │   User System   │  │   Cron Manager  │  │   Evolution     │ │
│  │  (Multi-tenant) │  │  (Scheduled)    │  │   Engine        │ │
│  └─────────────────┘  └─────────────────┘  └─────────────────┘ │
└─────────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────────┐
│                        Core Layer                                │
│  ┌─────────────────┐  ┌─────────────────┐  ┌─────────────────┐ │
│  │   Agent Core    │  │   Memory System │  │   Skill System  │ │
│  │  (Orchestration)│  │  (Hierarchical) │  │  (Plugin-based) │ │
│  └─────────────────┘  └─────────────────┘  └─────────────────┘ │
│  ┌─────────────────┐  ┌─────────────────┐  ┌─────────────────┐ │
│  │  Context Mgr    │  │   Tool System   │  │   MCP/ACP       │ │
│  │ (Compressor)    │  │  (13+ built-in) │  │  (Protocols)    │ │
│  └─────────────────┘  └─────────────────┘  └─────────────────┘ │
└─────────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────────┐
│                     Infrastructure Layer                         │
│  ┌─────────────────┐  ┌─────────────────┐  ┌─────────────────┐ │
│  │   LLM Service   │  │   SQLite DB     │  │   File Storage  │ │
│  │ (OpenAI Compat) │  │  (User/Config)  │  │  (Workspaces)   │ │
│  └─────────────────┘  └─────────────────┘  └─────────────────┘ │
│  ┌─────────────────┐  ┌─────────────────┐  ┌─────────────────┐ │
│  │   ReMeLight     │  │   PageIndex     │  │   Browser       │ │
│  │  (Vector Search)│  │  (RAG Engine)   │  │  (Playwright)   │ │
│  └─────────────────┘  └─────────────────┘  └─────────────────┘ │
└─────────────────────────────────────────────────────────────────┘
```

---

## 目录结构

### 运行时目录结构

```
{WORKING_DIR}/                          # 默认: /apps/ai/coapis
├── system/                             # 系统级文件（全局共享）
│   ├── config.json                     # Agent 全局配置
│   ├── providers.json                  # LLM Provider 配置
│   ├── users.json                      # 用户数据（JSON 存储）
│   ├── auth.json                       # JWT 认证配置
│   ├── permissions.json                # RBAC 权限配置
│   ├── evolution_config.json           # 进化系统配置
│   ├── token_usage.json                # Token 消耗统计
│   ├── user_system.db                  # SQLite 用户数据库（可选）
│   └── .secret/                        # 密钥存储目录
│       └── providers/                  # Provider 密钥
│           ├── builtin/                # 内置 Provider
│           ├── custom/                 # 自定义 Provider
│           └── plugin/                 # 插件 Provider
│
├── workspaces/                         # 用户级数据（按用户隔离）
│   └── {username}/                     # 每个用户独立工作区
│       ├── agents/                     # 用户专属 Agent 配置
│       ├── skills/                     # 用户专属技能
│       ├── files/                      # 用户文件空间
│       ├── chats/                      # 聊天历史记录
│       ├── workflows/                  # 工作流配置
│       ├── crons/                      # 定时任务配置
│       ├── backups/                    # 用户数据备份
│       ├── SOUL.md                     # Agent 人格定义
│       ├── MEMORY.md                   # 长期记忆
│       ├── PROFILE.md                  # 用户/Agent 档案
│       └── agent.json                  # Agent 实例配置
│
├── agents/                             # 全局共享 Agent 模板（只读）
├── skills/                             # 全局共享技能模板（只读）
└── logs/                               # 运行日志
    └── audit.log                       # 审计日志（JSONL 格式）
```

### 代码目录结构

```
coapis-agent/
├── client/                             # 前端源码
│   ├── src/
│   │   ├── api/                        # API 封装层
│   │   ├── components/                 # 通用 UI 组件
│   │   ├── contexts/                   # React Context (Auth/User)
│   │   ├── layouts/                    # 布局组件
│   │   ├── pages/                      # 页面组件
│   │   │   ├── ChatPage.tsx            # 聊天页面
│   │   │   ├── MySpacePage.tsx         # 我的空间
│   │   │   ├── SkillsPage.tsx          # 技能管理
│   │   │   ├── AdminPage.tsx           # 管理后台
│   │   │   └── ...
│   │   ├── locales/                    # 国际化 (zh/en/ja/ru)
│   │   └── App.tsx                     # 应用入口
│   ├── Dockerfile
│   └── package.json
│
├── server/coapis/                   # 后端源码
│   ├── agent/                          # Agent 核心引擎
│   │   ├── core.py                     # Agent 主类
│   │   ├── context_compressor.py       # 上下文压缩器
│   │   └── ...
│   ├── app/                            # API 路由与中间件
│   │   ├── auth_middleware.py          # 认证中间件
│   │   ├── routers/                    # 路由模块
│   │   │   ├── auth.py                 # 认证路由
│   │   │   ├── users.py                # 用户路由
│   │   │   ├── agents.py               # Agent 路由
│   │   │   ├── files.py                # 文件路由
│   │   │   ├── evolution.py            # 进化路由
│   │   │   └── ...
│   │   └── main.py                     # FastAPI 应用入口
│   ├── evolution/                      # 进化引擎
│   ├── foundation/                     # 分层记忆管理
│   ├── skills/                         # 技能管理系统
│   ├── user_system/                    # 多租户用户体系
│   │   ├── models/                     # 数据模型
│   │   ├── routers/                    # 用户路由
│   │   └── services/                   # 用户服务
│   └── config/                         # 配置管理
│
├── docker/                             # Docker 部署配置
│   ├── docker-compose.yaml             # 服务编排
│   ├── .env.example                    # 环境变量模板
│   ├── Dockerfile.server               # 后端镜像
│   ├── init_workspace.sh               # 首次启动初始化
│   ├── nginx/                          # Nginx 配置
│   │   └── conf/                       # Nginx 配置文件
│   └── volume/                         # 数据卷
│       ├── pageindex/                  # PageIndex 缓存
│       └── playwright/                 # Playwright 浏览器缓存
│
├── docs/                               # 文档
│   ├── help/                           # 帮助文档
│   ├── deployment.md                   # 部署指南
│   ├── architecture.md                 # 架构文档（本文）
│   └── API-REFERENCE.md                # API 参考
│
├── CHANGELOG.md                        # 更新日志
├── CONTRIBUTING.md                     # 贡献指南
├── SECURITY.md                         # 安全说明
├── CODE_OF_CONDUCT.md                  # 行为准则
└── LICENSE                             # Apache 2.0 许可证
```

---

## 数据流架构

### 请求处理流程

```
用户请求 → Nginx → FastAPI → Auth Middleware → Router → Service → Response
            │           │           │              │         │
            │           │           │              │         └→ Database/File
            │           │           │              └→ Permission Check
            │           │           └→ JWT Validation
            │           └→ Rate Limiting
            └→ Static Files (SPA fallback)
```

### SSE 流式聊天流程

```
前端 → POST /api/console/chat → ConsoleChannel → TaskTracker → ChatManager
        │                         │                │             │
        │                         │                │             └→ Agent Core
        │                         │                │                    │
        │                         │                │                    └→ LLM
        │                         │                │                    │
        │                         │                │                    └→ Stream
        │                         │                │                    │
        └← SSE Events ←←←←←←←←←←←←←←←←←←←←←←←←←←←←←←←←←←←←←←←←←←←←←←←←←←←←←←
```

---

## 多租户隔离架构

### 数据隔离策略

```
┌─────────────────────────────────────────────────────────────┐
│                      System Level                           │
│  ┌─────────────┐  ┌─────────────┐  ┌─────────────────────┐ │
│  │ users.json  │  │auth.json    │  │ permissions.json    │ │
│  │ (Global)    │  │ (Global)    │  │ (Global)            │ │
│  └─────────────┘  └─────────────┘  └─────────────────────┘ │
└─────────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────────┐
│                     User Level (Isolated)                    │
│  ┌─────────────┐  ┌─────────────┐  ┌─────────────────────┐ │
│  │ workspaces/ │  │ workspaces/ │  │ workspaces/         │ │
│  │   admin/    │  │  testuser/  │  │   {username}/       │ │
│  │  (Isolated) │  │ (Isolated)  │  │   (Isolated)        │ │
│  └─────────────┘  └─────────────┘  └─────────────────────┘ │
└─────────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────────┐
│                   Shared Level (Read-only)                   │
│  ┌─────────────┐  ┌─────────────┐  ┌─────────────────────┐ │
│  │ agents/     │  │ skills/     │  │ workflows/          │ │
│  │ (Templates) │  │ (Templates) │  │ (Templates)         │ │
│  └─────────────┘  └─────────────┘  └─────────────────────┘ │
└─────────────────────────────────────────────────────────────┘
```

### 路径安全

- **路径遍历防护**: 所有文件操作经过路径安全检查
- **工作区边界检查**: 用户只能访问自己的工作区目录
- **系统文件保护**: 系统级文件对普通用户不可见

---

## 分层记忆架构

### 三层记忆模型

```
┌─────────────────────────────────────────────────────────────┐
│                    Instance Layer (Context)                  │
│  ┌─────────────┐  ┌─────────────┐  ┌─────────────────────┐ │
│  │ Current     │  │ Session     │  │ Short-term          │ │
│  │ Conversation│  │ History     │  │ Memory              │ │
│  └─────────────┘  └─────────────┘  └─────────────────────┘ │
│  • Per-session   • Auto-compression   • Context window     │
└─────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────┐
│                  Professional Layer (Domain)                 │
│  ┌─────────────┐  ┌─────────────┐  ┌─────────────────────┐ │
│  │ Domain      │  │ Skills      │  │ Workflows           │ │
│  │ Knowledge   │  │ Knowledge   │  │ Knowledge           │ │
│  └─────────────┘  └─────────────┘  └─────────────────────┘ │
│  • Per-user      • Learned from     • Reusable across      │
│  • Persistent    • experience       • sessions             │
└─────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────┐
│                   Foundation Layer (Long-term)              │
│  ┌─────────────┐  ┌─────────────┐  ┌─────────────────────┐ │
│  │ SOUL.md     │  │ MEMORY.md   │  │ PROFILE.md          │ │
│  │ (Identity)  │  │ (History)   │  │ (Preferences)       │ │
│  └─────────────┘  └─────────────┘  └─────────────────────┘ │
│  • Global        • Cross-session      • User preferences   │
│  • Core identity • Long-term facts    • Persistent         │
└─────────────────────────────────────────────────────────────┘
```

---

## 认证与权限架构

### JWT 认证流程

```
1. User Login → POST /api/auth/login
2. Server validates credentials → users.json / user_system.db
3. Server generates JWT token → auth.json (secret)
4. Client stores token → localStorage / cookie
5. Subsequent requests → Authorization: Bearer <token>
6. Auth Middleware validates token → extracts user_info
7. Permission Middleware checks role → permissions.json
8. Request proceeds or 403 Forbidden
```

### RBAC 权限模型

| Role | Modules Accessible | Description |
|------|-------------------|-------------|
| `admin` | All 18+ modules | Full system access |
| `user` | 9 basic modules | Chat, MySpace, Skills, Channels, Cron, Config, Voice |
| `visitor` | Chat only | Read-only access |

### 权限配置结构

```json
{
  "roles": {
    "admin": {
      "modules": ["all"],
      "shell_permissions": {
        "whitelist": ["*"],
        "blacklist": []
      }
    },
    "user": {
      "modules": ["chat", "myspace", "skills", "channels", "cron", "config", "voice"],
      "shell_permissions": {
        "whitelist": ["ls", "cat", "grep", "find"],
        "blacklist": ["rm -rf /", "sudo", "chmod 777"]
      }
    }
  }
}
```

---

## 技能系统架构

### 技能加载流程

```
1. User sends message → Agent Core
2. Agent extracts intent → Query matching
3. Skill Manager matches skills → match_skills_by_query()
4. Relevant skills loaded → System prompt
5. Agent generates response → Tool calls if needed
6. Response returned → User
```

### 技能类型

| Type | Description | Example |
|------|-------------|---------|
| Built-in | Core tools shipped with CoApis | `file_reader`, `web_search` |
| Custom | User-created skills | Data analysis, report writing |
| Plugin | External skills via MCP | Filesystem, GitHub |

---

## 进化系统架构

### 进化流程

```
1. Conversation ends → Trajectory captured
2. Evolution Engine analyzes → Experience extraction
3. Experience reviewed → AI review (pending)
4. Approved experience → Knowledge base
5. Knowledge promoted → Higher layer (Foundation/Professional)
6. Skill improvement → Auto-update skill definitions
```

### 跨 Agent 进化

```
Agent A (learns) → Knowledge Flow → Review → Agent B (receives)
                                        → Agent C (receives)
                                        → Global Pool (shared)
```

---

## 部署架构

### Docker Compose 架构

```
┌─────────────────────────────────────────────────────────────┐
│                     Host Machine                            │
│  ┌─────────────────┐  ┌─────────────────┐  ┌─────────────┐ │
│  │  coapis-     │  │  coapis-     │  │  LLM       │ │
│  │  nginx          │  │  server         │  │  Service   │ │
│  │  (Port 4200)    │  │  (Port 4103)    │  │ (External) │ │
│  └────────┬────────┘  └────────┬────────┘  └──────┬──────┘ │
│           │                    │                    │       │
│           └────────────────────┼────────────────────┘       │
│                    │         │                               │
│                    ▼         ▼                               │
│           ┌─────────────────┐  ┌─────────────────┐          │
│           │   Volumes       │  │   Volumes       │          │
│           │  - WORKING_DIR  │  │  - pageindex    │          │
│           │  - system/      │  │  - playwright   │          │
│           │  - workspaces/  │  │                 │          │
│           └─────────────────┘  └─────────────────┘          │
└─────────────────────────────────────────────────────────────┘
```

### 端口映射

| Service | Host Port | Container Port | Description |
|---------|-----------|----------------|-------------|
| Nginx | 4200 | 80 | Frontend SPA |
| Backend | 4103 | 8000 | FastAPI API |

---

## 技术栈

### 前端技术栈

| Component | Technology | Version |
|-----------|------------|---------|
| Framework | React | 18 |
| Language | TypeScript | 5.x |
| UI Library | Ant Design | 5.x |
| Build Tool | Vite | 5.x |
| State Management | React Context | - |
| HTTP Client | Axios | - |
| i18n | react-i18next | - |

### 后端技术栈

| Component | Technology | Version |
|-----------|------------|---------|
| Framework | FastAPI | Latest |
| Language | Python | 3.11+ |
| Validation | Pydantic | v2 |
| Database | SQLite | 3.x |
| Async | asyncio | - |
| SSE | sse-starlette | - |
| Auth | authlib | - |

### 基础设施

| Component | Technology | Purpose |
|-----------|------------|---------|
| Container | Docker | Isolation |
| Orchestration | Docker Compose | Service management |
| Reverse Proxy | Nginx | Static files + API routing |
| LLM | OpenAI-compatible API | AI inference |
| Vector Search | ReMeLight | Semantic search |
| RAG | PageIndex | Document retrieval |
| Browser | Playwright | Web automation |

---

**最后更新**: 2026-05-27
