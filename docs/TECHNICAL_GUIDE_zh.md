# CoApis 技术开发指南

> **面向对象**：前端/后端开发人员、运维优化人员  
> **版本**：v0.1.0 · 2026-06-05  
> **文档目的**：便于二次开发及人工核验

---

## 目录

1. [项目概览](#1-项目概览)
2. [目录结构](#2-目录结构)
3. [后端架构](#3-后端架构)
4. [前端架构](#4-前端架构)
5. [部署与运维](#5-部署与运维)
6. [配置参考](#6-配置参考)
7. [核心流程](#7-核心流程)

---

## 1. 项目概览

### 1.1 产品定位

CoApis（蜜蜂）是一个**多智能体对话平台**，支持：
- 多用户隔离对话（Console Chat）
- 多智能体管理（全局/用户级）
- 多渠道接入（Console、钉钉、Discord、飞书、Matrix、MQTT、Telegram 等）
- 技能系统（Skill Pool + 安装管理）
- 定时任务（Cron Jobs）
- 访问控制（白名单/黑名单/审批流）
- 上下文压缩与记忆管理

### 1.2 技术栈

| 层级 | 技术 |
|------|------|
| **前端** | React 18 + TypeScript + Vite + Ant Design 5 + Zustand |
| **后端** | Python 3.12 + FastAPI + Uvicorn |
| **部署** | Docker Compose + Nginx 反向代理 |
| **数据存储** | JSON 文件（agent.json、chat.json）+ SQLite（可选） |
| **LLM Provider** | OpenAI / Anthropic / Gemini / Ollama / LMStudio / OpenRouter |

---

## 2. 目录结构

### 2.1 项目根目录

```
coapis-agent/
├── client/                    # 前端 React 应用
├── server/                    # 后端 Python 应用
├── docker/                    # Docker 部署配置
├── enterprise/                # 企业版插件（可选）
├── docs/                      # 项目文档
├── install.sh                 # 一键安装脚本
├── README.md
├── CHANGELOG.md
├── CONTRIBUTING.md
├── SECURITY.md
└── LICENSE                    # Apache 2.0
```

### 2.2 后端目录结构 (`server/coapis/`)

```
server/coapis/
├── __main__.py                # 启动入口
├── constant.py                # 全局常量（路径、环境变量）
├── cleanup.py                 # 清理引擎（文件/对话清理）
├── run.py                     # 运行脚本
│
├── agent/                     # 🧠 Agent 核心模块
│   ├── workspace.py           # Agent 工作空间管理（943行）⭐
│   ├── core.py                # Agent 核心逻辑
│   ├── prompt_builder.py      # Prompt 构建器（132行）
│   ├── memory_manager.py      # 记忆管理器（161行）
│   ├── context_compressor.py  # 上下文压缩器（797行）⭐
│   ├── agent_config_watcher.py# Agent 配置热重载
│   ├── command_handler.py     # 命令处理器
│   ├── growth.py              # Agent 成长/演化
│   ├── context/               # 上下文管理
│   │   ├── agent_context.py
│   │   ├── base_context_manager.py
│   │   ├── light_context_manager.py
│   │   └── compactor_prompts.py
│   ├── memory/                # 记忆系统
│   │   ├── base_memory_manager.py
│   │   ├── agent_md_manager.py
│   │   ├── prompts.py
│   │   ├── reme_light_memory_manager.py
│   │   └── proactive/         # 主动记忆
│   ├── hooks/                 # 生命周期钩子
│   │   └── bootstrap.py
│   └── acp/                   # Agent Communication Protocol
│       ├── client.py
│       ├── core.py
│       ├── server.py
│       └── service.py
│
├── app/                       # 🌐 Web 应用层
│   ├── _app.py                # FastAPI 应用入口（890行）⭐
│   ├── auth.py                # JWT 认证
│   ├── auth_middleware.py      # 认证中间件
│   ├── multi_agent_manager.py # 多 Agent 管理器（674行）⭐
│   ├── access_control.py      # 访问控制核心
│   ├── access_control_api.py  # 访问控制 REST API
│   ├── agent_config_watcher.py# 配置热重载
│   ├── cleanup.py             # 清理 API
│   ├── cleanup_api.py         # 清理 REST API
│   │
│   ├── routers/               # 📡 API 路由
│   │   ├── __init__.py        # 统一路由注册 ⭐
│   │   ├── console.py         # Console Chat 路由（553行）⭐
│   │   ├── agents.py          # Agent 管理路由
│   │   ├── agent.py           # 单 Agent 操作路由
│   │   ├── auth.py            # 认证路由
│   │   ├── channels.py        # 渠道路由
│   │   ├── chat.py            # 聊天记录路由
│   │   ├── cronjob.py         # 定时任务路由
│   │   ├── permissions.py     # 权限路由
│   │   ├── settings.py        # 设置路由
│   │   ├── skills.py          # 技能路由
│   │   ├── tools.py           # 工具路由
│   │   ├── backup.py          # 备份路由
│   │   ├── token_usage.py     # Token 用量路由
│   │   ├── config_router.py   # 配置路由
│   │   ├── path_compat.py     # 前端路径兼容层
│   │   ├── admin_providers.py # 管理员 Provider 路由
│   │   ├── audit.py           # 审计路由
│   │   ├── user/              # 用户相关路由
│   │   └── workspace/         # 工作空间路由
│   │
│   ├── channels/              # 💬 渠道适配层
│   │   ├── base.py            # 渠道基类
│   │   ├── manager.py         # 渠道管理器（266行）
│   │   ├── console/           # Console 渠道
│   │   ├── dingtalk/          # 钉钉渠道
│   │   ├── discord_/          # Discord 渠道
│   │   ├── feishu/            # 飞书渠道
│   │   ├── matrix/            # Matrix 渠道
│   │   ├── mqtt/              # MQTT 渠道
│   │   ├── telegram/          # Telegram 渠道
│   │   └── ...
│   │
│   ├── crons/                 # ⏰ 定时任务
│   │   └── manager.py         # Cron 管理器
│   │
│   ├── permissions/           # 🔐 权限系统
│   │   └── decorators.py      # @require_permission 装饰器
│   │
│   ├── runner/                # 🏃 对话运行器
│   │   └── runner.py
│   │
│   └── skill_market/          # 🏪 技能市场
│       └── router.py
│
├── config/                    # ⚙️ 配置模块
│   ├── settings.py            # 应用设置
│   ├── session_context.py     # 会话上下文
│   └── config.py              # Agent 配置加载
│
├── providers/                 # 🤖 LLM Provider 管理
│   ├── provider_manager.py    # Provider 管理器 ⭐
│   ├── openai_provider.py     # OpenAI
│   ├── anthropic_provider.py  # Anthropic
│   ├── gemini_provider.py     # Google Gemini
│   ├── ollama_provider.py     # Ollama（本地）
│   ├── lmstudio_provider.py   # LMStudio（本地）
│   ├── openrouter_provider.py # OpenRouter
│   ├── rate_limiter.py        # 速率限制
│   └── retry_chat_model.py    # 重试包装器
│
├── user_system/               # 👤 多用户系统
│   ├── middleware.py           # 用户隔离中间件（387行）⭐
│   └── ...
│
├── plan/                      # 📋 计划系统
│   ├── broadcast.py
│   ├── hints.py
│   └── schemas.py
│
├── plugins/                   # 🔌 插件系统
│   ├── loader.py
│   ├── registry.py
│   └── runtime.py
│
├── security/                  # 🔒 安全模块
│   ├── secret_store.py
│   └── skill_scanner/         # 技能安全扫描
│
├── skills/                    # 🛠️ 技能实现
│   ├── __init__.py
│   └── ...
│
├── local_models/              # 🏠 本地模型
│   └── tag_parser.py
│
└── scripts/                   # 📜 工具脚本
    ├── check_prompt_size.py
    ├── sync_qa_user.py
    └── ...
```

### 2.3 前端目录结构 (`client/src/`)

```
client/src/
├── App.tsx                    # 应用根组件（233行）
├── routes.tsx                 # 路由配置
├── main.tsx                   # 入口文件
│
├── api/                       # 📡 API 请求层
│   ├── index.ts               # API 统一导出
│   ├── request.ts             # 请求封装（axios/fetch）
│   ├── config.ts              # API 配置
│   ├── authHeaders.ts         # 认证头处理
│   └── modules/               # 按模块拆分的 API
│       ├── chat.ts            # 聊天 API
│       ├── agents.ts          # Agent API
│       ├── auth.ts            # 认证 API
│       ├── channel.ts         # 渠道 API
│       ├── cronjob.ts         # 定时任务 API
│       ├── skill.ts           # 技能 API
│       ├── cleanup.ts         # 清理 API
│       ├── console.ts         # Console Chat API
│       ├── permissions.ts     # 权限 API
│       └── ...
│   └── types/                 # API 类型定义
│       ├── chat.ts
│       ├── agents.ts
│       └── ...
│
├── pages/                     # 📄 页面组件
│   ├── Chat/                  # 💬 聊天页面 ⭐
│   │   ├── index.tsx          # 主聊天页面（1506行）⭐⭐
│   │   └── components/
│   │       ├── ChatSessionDropdown/
│   │       ├── ChatSessionInitializer/
│   │       └── ...
│   │
│   ├── Agent/                 # 🤖 Agent 管理
│   │   ├── Config/            # Agent 配置
│   │   ├── Skills/            # Agent 技能
│   │   ├── MCP/               # MCP 协议
│   │   └── ACP/               # ACP 协议
│   │
│   ├── Admin/                 # 🔧 管理员页面
│   │   ├── GlobalAgentsTab.tsx
│   │   ├── GlobalAgentDetail.tsx
│   │   └── ...
│   │
│   ├── Control/               # ⚙️ 控制面板
│   │   ├── Channels/          # 渠道管理
│   │   ├── CronJobs/          # 定时任务
│   │   └── ...
│   │
│   ├── Cleanup/               # 🧹 清理管理
│   ├── Evolution/             # 📈 演化监控
│   ├── Security/              # 🔒 安全设置
│   ├── Backup/                # 💾 备份管理
│   └── ...
│
├── components/                # 🧩 公共组件
│   └── ...
│
├── layouts/                   # 📐 布局组件
│   └── MainLayout/
│       ├── index.tsx          # 主布局（路由管理）⭐
│       ├── Header.tsx         # 顶部导航
│       ├── Sidebar.tsx        # 侧边栏
│       └── constants.ts       # 布局常量
│
├── contexts/                  # 🌐 React Context
│   ├── UserContext.tsx         # 用户上下文
│   ├── ThemeContext.tsx        # 主题上下文
│   └── ApprovalContext.tsx     # 审批上下文
│
├── hooks/                     # 🪝 自定义 Hooks
│   └── ...
│
├── stores/                    # 🗄️ Zustand 状态管理
│   └── ...
│
└── i18n.ts                    # 🌍 国际化配置
```

---

## 3. 后端架构

### 3.1 应用入口 (`_app.py`)

**职责**：创建 FastAPI 应用实例，注册中间件和路由

**核心流程**：
```python
app = FastAPI(title="CoApis")

# 中间件链（按顺序）
app.add_middleware(ErrorHandlerMiddleware)    # 错误处理
app.add_middleware(UserIsolationMiddleware)   # 用户隔离
app.add_middleware(RateLimitMiddleware)       # 速率限制

# 路由注册
app.include_router(api_router, prefix="/api")           # 主 API
app.include_router(agent_app.router, prefix="/api/agent")  # Agent 子应用
```

**关键方法**：
| 方法 | 职责 |
|------|------|
| `create_app()` | 创建并配置 FastAPI 实例 |
| `_load_enterprise_routes()` | 动态加载企业版路由 |
| `register_custom_channel_routes()` | 注册自定义渠道路由 |

### 3.2 路由注册 (`routers/__init__.py`)

**职责**：统一导入并注册所有 API 路由

**注册的路由模块**（30+）：
```python
# 核心路由
router.include_router(agents_router)      # /api/agents
router.include_router(console_router)     # /api/console
router.include_router(auth_router)        # /api/auth
router.include_router(chat_router)        # /api/chats

# 功能路由
router.include_router(channels_router)    # /api/channels
router.include_router(cronjob_router)     # /api/cron
router.include_router(skills_router)      # /api/skills
router.include_router(tools_router)       # /api/tools
router.include_router(backup_router)      # /api/backup

# 管理路由
router.include_router(permissions_router) # /api/permissions
router.include_router(audit_router)       # /api/audit
router.include_router(security_router)    # /api/security
```

### 3.3 Agent 工作空间 (`agent/workspace.py`)

**职责**：管理 Agent 的文件系统、配置、技能、记忆

**核心类**：`Workspace`

**关键属性**：
| 属性 | 类型 | 说明 |
|------|------|------|
| `agent_id` | `str` | Agent 唯一标识 |
| `workspace_dir` | `Path` | 工作空间根目录 |
| `data_dir` | `Path` | 数据目录 |
| `skills_dir` | `Path` | 技能目录 |
| `status` | `str` | 运行状态 |
| `config` | `Dict` | Agent 配置 |

**关键方法**：
| 方法 | 职责 |
|------|------|
| `__init__(agent_id, username, is_global)` | 初始化工作空间，确定目录结构 |
| `start()` | 启动工作空间，加载配置、技能、记忆 |
| `stop()` | 停止工作空间 |
| `_ensure_identity_files()` | 确保身份文件存在 |
| `load_config()` | 加载 agent.json 配置 |

**目录隔离逻辑**：
```python
if username and not is_global:
    # 用户级：workspaces/{username}/agents/{agent_id}/
    workspace_dir = _get_user_agents_dir(username) / agent_id
else:
    # 全局级：data/agents/{agent_id}/
    workspace_dir = DATA_DIR / agent_id
```

### 3.4 多 Agent 管理器 (`app/multi_agent_manager.py`)

**职责**：管理多个 Agent 实例的生命周期

**核心类**：`MultiAgentManager`

**关键方法**：
| 方法 | 职责 |
|------|------|
| `create_agent(agent_id, config)` | 创建新 Agent 实例 |
| `start_agent(agent_id)` | 启动指定 Agent |
| `stop_agent(agent_id)` | 停止指定 Agent |
| `get_agent(agent_id)` | 获取 Agent 实例 |
| `list_agents(user_id)` | 列出用户的所有 Agent |

### 3.5 上下文压缩器 (`agent/context_compressor.py`)

**职责**：在对话过长时压缩上下文，保留关键信息

**压缩策略**：
| 策略 | 说明 |
|------|------|
| **规则压缩** (`_compress_rule_based`) | 基于规则的快速压缩（去重、截断工具输出） |
| **LLM 压缩** (`_compress_llm`) | 调用 LLM 生成摘要 |
| **工具输出裁剪** (`_prune_tool_outputs`) | 裁剪过长的工具返回结果 |

**关键方法**：
| 方法 | 职责 |
|------|------|
| `compress(messages, model)` | 主入口，自动选择压缩策略 |
| `_estimate_tokens(messages)` | 估算 token 数 |
| `_get_context_limit(model)` | 获取模型上下文限制 |
| `_summarize(messages)` | 生成对话摘要 |

### 3.6 渠道管理器 (`app/channels/manager.py`)

**职责**：统一管理多渠道的消息收发

**支持的渠道**：
| 渠道 | 模块 | 说明 |
|------|------|------|
| Console | `channels/console/` | Web 控制台 |
| 钉钉 | `channels/dingtalk/` | 钉钉机器人 |
| Discord | `channels/discord_/` | Discord Bot |
| 飞书 | `channels/feishu/` | 飞书机器人 |
| Matrix | `channels/matrix/` | Matrix 协议 |
| MQTT | `channels/mqtt/` | MQTT 消息 |
| Telegram | `channels/telegram/` | Telegram Bot |

**核心方法**：
| 方法 | 职责 |
|------|------|
| `register_channel(channel_type, config)` | 注册渠道实例 |
| `send_message(channel_type, target, content)` | 发送消息 |
| `broadcast_message(content, channels)` | 广播消息 |

### 3.7 访问控制 (`app/access_control.py`)

**职责**：管理用户对频道的访问权限

**权限模型**：
| 概念 | 说明 |
|------|------|
| **白名单** (whitelist) | 允许访问的用户列表 |
| **黑名单** (blacklist) | 禁止访问的用户列表 |
| **待审批** (pending) | 等待审批的用户请求 |

**核心方法**：
| 方法 | 职责 |
|------|------|
| `get_access_control_store()` | 获取访问控制存储实例 |
| `check_access(user_id, channel)` | 检查用户是否有权限 |
| `add_to_whitelist(user_id, channel)` | 添加白名单 |
| `add_to_blacklist(user_id, channel)` | 添加黑名单 |
| `approve_user(user_id, channel)` | 批准用户访问 |

### 3.8 Cron 管理器 (`app/crons/manager.py`)

**职责**：管理定时任务的创建、执行、暂停、恢复

**核心方法**：
| 方法 | 职责 |
|------|------|
| `start()` | 启动 Cron 调度器 |
| `stop()` | 停止调度器 |
| `create_or_replace_job(spec)` | 创建或替换任务 |
| `delete_job(job_id)` | 删除任务 |
| `pause_job(job_id)` | 暂停任务 |
| `resume_job(job_id)` | 恢复任务 |
| `run_job_once(job_id)` | 立即执行一次 |
| `reschedule_heartbeat()` | 重新调度心跳任务 |

### 3.9 用户隔离中间件 (`user_system/middleware.py`)

**职责**：确保多用户环境下的数据隔离

**关键方法**：
| 方法 | 职责 |
|------|------|
| `user_isolation_dispatch()` | 用户隔离中间件入口 |
| `rate_limit_dispatch()` | 速率限制中间件入口 |
| `set_current_user(user_id)` | 设置当前用户上下文 |
| `get_current_user()` | 获取当前用户 |

### 3.10 LLM Provider 管理 (`providers/provider_manager.py`)

**职责**：统一管理多种 LLM Provider 的配置和调用

**支持的 Provider**：
| Provider | 模块 | 特点 |
|----------|------|------|
| OpenAI | `openai_provider.py` | GPT-4o/4-turbo/3.5 |
| Anthropic | `anthropic_provider.py` | Claude 3.5/3 Opus |
| Gemini | `gemini_provider.py` | Google Gemini |
| Ollama | `ollama_provider.py` | 本地部署 |
| LMStudio | `lmstudio_provider.py` | 本地部署 |
| OpenRouter | `openrouter_provider.py` | 聚合路由 |

**核心方法**：
| 方法 | 职责 |
|------|------|
| `get_provider(provider_name)` | 获取 Provider 实例 |
| `list_providers()` | 列出所有可用 Provider |
| `configure_provider(name, config)` | 配置 Provider |

---

## 4. 前端架构

### 4.1 技术选型

| 技术 | 版本 | 用途 |
|------|------|------|
| React | 18 | UI 框架 |
| TypeScript | 5.x | 类型安全 |
| Vite | 5.x | 构建工具 |
| Ant Design | 5.x | UI 组件库 |
| Zustand | 4.x | 状态管理 |
| React Router | 6.x | 路由管理 |
| i18next | - | 国际化 |
| dayjs | - | 日期处理 |

### 4.2 路由结构

**路由管理**：`layouts/MainLayout/index.tsx`

**页面路由映射表**：
| 路径 | 页面组件 | 说明 |
|------|----------|------|
| `/` | `Navigate → /chat` | 重定向到聊天 |
| `/chat` | `ChatPage` | 💬 聊天页面（核心） |
| `/agents` | `AgentsPage` | 🤖 Agent 管理 |
| `/skills` | `SkillsPage` | 🛠️ 技能管理 |
| `/channels` | `ChannelsPage` | 📡 渠道管理 |
| `/cron-jobs` | `CronJobsPage` | ⏰ 定时任务 |
| `/agent-config` | `AgentConfigPage` | ⚙️ Agent 配置 |
| `/models` | `ModelsPage` | 🧠 模型管理 |
| `/cleanup` | `CleanupPage` | 🧹 清理管理 |
| `/access-control` | `AccessControlPage` | 🔐 访问控制 |
| `/evolution` | `EvolutionPage` | 📈 演化监控 |
| `/backups` | `BackupsPage` | 💾 备份管理 |
| `/security` | `SecurityPage` | 🔒 安全设置 |
| `/token-usage` | `TokenUsagePage` | 📊 Token 用量 |
| `/debug` | `DebugPage` | 🐛 调试工具 |
| `/workspace/myspace` | `MySpacePage` | 📁 工作空间 |
| `/user/profile` | `UserProfilePage` | 👤 个人资料 |
| `/admin` | `AdminPage` | 🔧 管理员面板 |

### 4.3 核心页面

#### 4.3.1 聊天页面 (`pages/Chat/index.tsx`)

**职责**：对话交互的主界面，1506 行，是前端最复杂的页面

**核心组件**：
| 组件 | 职责 |
|------|------|
| `ChatSessionDropdown` | 会话选择器 |
| `ChatSessionInitializer` | 新会话初始化 |
| `ChatInput` | 消息输入框 |
| `ChatMessageList` | 消息列表 |
| `ChatStreaming` | SSE 流式渲染 |

**关键功能**：
- SSE 流式接收 AI 回复
- 多会话管理（创建/切换/删除）
- Markdown 渲染
- 代码高亮
- 文件上传
- 工具调用展示

#### 4.3.2 Agent 配置页面 (`pages/Agent/Config/index.tsx`)

**职责**：配置 Agent 的各项参数

**配置卡片**：
| 卡片 | 职责 |
|------|------|
| `LightContextCard` | 轻量上下文配置 |
| `LlmRateLimiterCard` | LLM 速率限制 |
| `LlmRetryCard` | LLM 重试策略 |
| `ReactAgentCard` | 反应式 Agent 配置 |
| `ReMeLightMemoryCard` | 轻量记忆配置 |
| `ToolExecutionLevelCard` | 工具执行级别 |

### 4.4 API 请求层 (`api/`)

**统一请求封装**：`api/request.ts`
- 自动附加 Authorization 头
- 错误处理
- 请求/响应拦截

**按模块拆分**：`api/modules/`
- 每个模块对应一个后端路由组
- TypeScript 类型定义在 `api/types/`

### 4.5 状态管理 (`stores/`)

使用 Zustand 进行全局状态管理：
- 用户状态
- 主题状态
- Agent 状态
- 聊天状态

### 4.6 国际化 (`i18n.ts`)

支持语言：
- 中文 (zh-CN)
- 英文 (en-US)
- 日文 (ja-JP)
- 俄文 (ru-RU)

---

## 5. 部署与运维

### 5.1 Docker 架构

```
┌─────────────────────────────────────────┐
│              Nginx (4200)               │
│  - 静态资源服务                          │
│  - API 反向代理 → server:8000            │
│  - WebSocket 代理                       │
│  - SPA 回退                             │
└─────────────┬───────────────────────────┘
              │
┌─────────────▼───────────────────────────┐
│           FastAPI Server (8000)          │
│  - Uvicorn ASGI 服务器                  │
│  - 多用户隔离                           │
│  - Agent 生命周期管理                   │
│  - LLM Provider 调度                    │
└─────────────┬───────────────────────────┘
              │
┌─────────────▼───────────────────────────┐
│          持久化数据卷                    │
│  /apps/ai/coapis/                    │
│  - agent.json（Agent 配置）             │
│  - chat.json（对话记录）                │
│  - workspaces/（用户工作空间）          │
│  - system/（系统配置）                  │
└─────────────────────────────────────────┘
```

### 5.2 Docker Compose 配置

**文件**：`docker/docker-compose.dev.yaml`

**服务定义**：
```yaml
services:
  server:
    image: coapis-server:latest
    ports:
      - "4103:8000"
    volumes:
      - /apps/ai/coapis:/apps/ai/coapis          # 运行数据
      - ../server/coapis:/opt/coapis/coapis    # 源码热更新
      - ./volume/pageindex:/opt/coapis/volume/pageindex
    environment:
      - PYTHONPATH=/opt/coapis
      - COAPIS_HOME=/opt/coapis
    restart: unless-stopped

  nginx:
    image: nginx:alpine
    ports:
      - "4200:80"
    volumes:
      - ./nginx/conf:/etc/nginx/conf.d
    depends_on:
      - server
```

### 5.3 Nginx 配置

**文件**：`docker/nginx/conf/default.conf`

**核心配置**：
| 配置 | 说明 |
|------|------|
| `/api/*` | 反向代理到 `server:8000` |
| `/ws` | WebSocket 代理 |
| `/` | 静态资源 + SPA 回退 |
| `index.html` | 不缓存（no-cache） |
| `*.js/css` | 长期缓存（1年） |

### 5.4 一键安装

**脚本**：`install.sh`

**安装流程**：
1. 检查 Docker 环境
2. 构建镜像
3. 生成 `.env` 配置
4. 启动服务
5. 输出访问地址

---

## 6. 配置参考

### 6.1 环境变量

**文件**：`docker/.env`

| 变量 | 默认值 | 说明 |
|------|--------|------|
| `COAPIS_PORT` | `4103` | API 服务端口 |
| `COAPIS_FRONTEND_PORT` | `4200` | 前端端口 |
| `COAPIS_DATA_DIR` | `/apps/ai/coapis` | 数据目录 |
| `COAPIS_HOME` | `/opt/coapis` | 应用根目录 |
| `COAPIS_EDITION` | `community` | 版本（community/enterprise） |
| `COAPIS_LICENSE_KEY` | - | 企业版密钥 |
| `PYTHONPATH` | `/opt/coapis` | Python 路径 |

### 6.2 Agent 配置 (`agent.json`)

**路径**：`workspaces/{username}/agents/{agent_id}/agent.json`

**核心字段**：
```json
{
  "id": "default",
  "name": "Default Agent",
  "description": "系统默认智能体",
  "provider": "openai",
  "model": "gpt-4o",
  "temperature": 0.7,
  "max_tokens": 4096,
  "system_prompt": "你是一个智能助手...",
  "tools": ["file_manager", "shell", "browser", "search"],
  "skills": ["skill-1", "skill-2"],
  "config": {
    "light_context": true,
    "rate_limit": 60,
    "retry_count": 3
  }
}
```

### 6.3 权限配置 (`permissions.json`)

**路径**：`system/permissions.json`

**角色定义**：
| 角色 | 模块权限 |
|------|----------|
| `visitor` | chat |
| `user` | chat, myspace, skills, channels, cron-jobs, heartbeat, sessions, tools, mcp, acp, agent-config, agent-stats, models, voice-transcription |
| `advanced` | user + agents |
| `admin` | 所有模块 |

### 6.4 渠道配置

**路径**：`system/channels.json`

**配置示例**：
```json
{
  "dingtalk": {
    "enabled": true,
    "app_key": "xxx",
    "app_secret": "xxx",
    "bot_name": "CoApis Bot"
  },
  "telegram": {
    "enabled": true,
    "bot_token": "xxx",
    "webhook_url": "https://xxx"
  }
}
```

---

## 7. 核心流程

### 7.1 Console Chat 流程

```
用户发送消息
    ↓
POST /api/console/chat
    ↓
console.py: console_chat()
    ↓
_extract_native_payload()  # 提取原生载荷
    ↓
console_channel.resolve_session_id()  # 解析会话 ID
    ↓
set_current_session_id()  # 设置会话上下文
    ↓
user_cm.get_or_create_chat()  # 获取或创建对话
    ↓
runner.run()  # 执行对话
    ↓
SSE 流式返回结果
```

### 7.2 Agent 启动流程

```
MultiAgentManager.start_agent(agent_id)
    ↓
Workspace(agent_id, username)
    ↓
workspace.start()
    ↓
_ensure_identity_files()  # 确保身份文件
    ↓
load_config()  # 加载 agent.json
    ↓
加载技能 (skills_dir)
    ↓
加载记忆 (memory_manager)
    ↓
初始化 Provider (provider_manager)
    ↓
Agent 就绪
```

### 7.3 中间件链

```
请求进入
    ↓
ErrorHandlerMiddleware  # 错误捕获
    ↓
UserIsolationMiddleware  # 用户隔离
    ↓
RateLimitMiddleware  # 速率限制
    ↓
require_permission  # 权限检查
    ↓
路由处理函数
    ↓
响应返回
```

---

## 附录 A：关键文件索引

| 文件 | 行数 | 职责 |
|------|------|------|
| `agent/workspace.py` | 943 | Agent 工作空间管理 |
| `app/_app.py` | 890 | FastAPI 应用入口 |
| `agent/context_compressor.py` | 797 | 上下文压缩 |
| `app/multi_agent_manager.py` | 674 | 多 Agent 管理 |
| `app/routers/console.py` | 553 | Console Chat 路由 |
| `user_system/middleware.py` | 387 | 用户隔离中间件 |
| `app/channels/manager.py` | 266 | 渠道管理器 |
| `agent/prompt_builder.py` | 132 | Prompt 构建器 |
| `agent/memory_manager.py` | 161 | 记忆管理器 |

---

## 附录 B：API 端点索引

### 核心端点
| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/api/health` | 健康检查 |
| GET | `/api/user/me` | 当前用户信息 |
| GET | `/api/auth/users` | 用户列表 |
| POST | `/api/auth/login` | 登录 |
| POST | `/api/auth/register` | 注册 |

### Agent 管理
| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/api/agents` | Agent 列表 |
| POST | `/api/agents` | 创建 Agent |
| GET | `/api/agents/{id}` | Agent 详情 |
| PUT | `/api/agents/{id}` | 更新 Agent |
| DELETE | `/api/agents/{id}` | 删除 Agent |

### Console Chat
| 方法 | 路径 | 说明 |
|------|------|------|
| POST | `/api/console/chat` | 发送消息（SSE） |
| POST | `/api/console/chat/stop` | 停止生成 |

### 聊天管理
| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/api/chats` | 对话列表 |
| POST | `/api/chats` | 创建对话 |
| GET | `/api/chats/{id}` | 对话详情 |
| DELETE | `/api/chats/{id}` | 删除对话 |

### 渠道管理
| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/api/channels` | 渠道列表 |
| POST | `/api/channels` | 添加渠道 |
| PUT | `/api/channels/{id}` | 更新渠道 |
| DELETE | `/api/channels/{id}` | 删除渠道 |

### 定时任务
| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/api/cron/jobs` | 任务列表 |
| POST | `/api/cron/jobs` | 创建任务 |
| PUT | `/api/cron/jobs/{id}` | 更新任务 |
| DELETE | `/api/cron/jobs/{id}` | 删除任务 |

### 技能管理
| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/api/skills` | 技能列表 |
| POST | `/api/skills/install` | 安装技能 |
| DELETE | `/api/skills/{id}` | 卸载技能 |

### 访问控制
| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/api/access-control/summary` | ACL 摘要 |
| GET | `/api/access-control/{channel}` | 频道 ACL |
| POST | `/api/access-control/{channel}/whitelist` | 添加白名单 |
| DELETE | `/api/access-control/{channel}/whitelist/{user_id}` | 移除白名单 |
| GET | `/api/access-control/pending` | 待审批列表 |
| POST | `/api/access-control/{channel}/pending/{user_id}/approve` | 批准 |

### 清理管理
| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/api/cleanup/overview` | 清理概览 |
| GET | `/api/cleanup/rules` | 清理规则 |
| GET | `/api/cleanup/history` | 清理历史 |

### 权限管理
| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/api/permissions/config` | 权限配置 |
| GET | `/api/permissions/modules` | 模块列表 |
| GET | `/api/permissions/roles` | 角色列表 |

### 管理员
| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/api/admin/overview` | 管理概览 |
| GET | `/api/admin/audit` | 审计日志 |
| GET | `/api/backups` | 备份列表 |

---

## 附录 C：开发环境搭建

### 前端开发
```bash
cd client
npm install          # 安装依赖
npm run dev          # 启动开发服务器（端口 5173）
npm run build        # 生产构建
```

### 后端开发
```bash
cd server
pip install -r requirements.txt  # 安装依赖
python -m coapis              # 启动服务器
```

### Docker 开发
```bash
cd docker
docker compose -f docker-compose.dev.yaml up -d  # 启动
docker compose -f docker-compose.dev.yaml down    # 停止
docker compose -f docker-compose.dev.yaml logs -f # 查看日志
```

### 代码质量检查
```bash
# 前端
cd client && npm run lint

# 后端
cd server && python -m ruff check .
```

---

## 附录 C-2：安全架构与沙箱隔离

### 设计理念

CoApis 采用**分层防御**策略，不依赖单一安全机制，而是多层叠加：

```
┌─────────────────────────────────────────────────────┐
│  Layer 5: Hash Chain 审计日志（防篡改）               │
├─────────────────────────────────────────────────────┤
│  Layer 4: 工具调用监控（异常检测）                    │
├─────────────────────────────────────────────────────┤
│  Layer 3: 跨平台统一沙箱                             │
│  - ImportSandbox（模块级导入隔离）                    │
│  - ASTSandbox（代码级危险操作拦截）                   │
│  - ResourceLimiter（CPU/内存/文件限制）               │
│  - ProcessIsolator（独立进程+临时目录+环境过滤）       │
├─────────────────────────────────────────────────────┤
│  Layer 2: ToolSandbox（路径/命令校验）               │
├─────────────────────────────────────────────────────┤
│  Layer 1: 应用层隔离（contextvars + user_id）         │
└─────────────────────────────────────────────────────┘
```

### 安全模块清单

| 模块 | 文件 | 行数 | 功能 | 依赖 |
|------|------|------|------|------|
| `ToolSandbox` | `security/tool_sandbox.py` | 136 | 路径白名单+命令黑名单 | 纯 Python |
| `ImportSandbox` | `security/import_sandbox.py` | 160 | 拦截危险模块导入 | 纯 Python |
| `ASTSandbox` | `security/ast_sandbox.py` | 180 | AST 级危险操作检测 | 纯 Python |
| `ResourceLimiter` | `security/resource_limiter.py` | 271 | CPU/内存/文件/进程限制 | 标准库 |
| `ProcessIsolator` | `security/process_isolator.py` | 186 | 独立进程+临时目录+环境过滤 | 纯 Python |
| `SandboxedExecutor` | `security/sandboxed_executor.py` | 156 | 沙箱化工具执行器 | 纯 Python |
| `HashChainAuditLogger` | `security/audit_chain.py` | 193 | 防篡改审计日志 | 纯 Python |
| `ToolCallMonitor` | `security/tool_monitor.py` | 189 | 异常检测+告警 | 纯 Python |

**总计**：~1371 行安全代码，零外部依赖。

### 各沙箱组件详解

#### ToolSandbox — 路径/命令校验

```python
from coapis.security import ToolSandbox

sandbox = ToolSandbox("admin", "/opt/coapis/workspaces/admin")

# 路径检查
result = sandbox.check_path("/opt/coapis/workspaces/admin/files/test.txt")
# → allowed=True

result = sandbox.check_path("/etc/passwd")
# → allowed=False, reason="Blocked pattern: /etc/passwd"

# 命令检查
result = sandbox.check_command("ls -la /opt/coapis")
# → allowed=True

result = sandbox.check_command("rm -rf /")
# → allowed=False, reason="Dangerous command pattern: rm -rf /"
```

#### ImportSandbox — 模块级导入隔离

拦截 `__import__` 机制，阻止危险模块加载：

| 被拦截模块 | 风险 |
|-----------|------|
| `os` | 系统命令执行 |
| `subprocess` | 进程创建 |
| `socket` | 网络访问 |
| `ctypes` | 底层内存操作 |
| `importlib` | 动态导入 |
| `shutil` | 文件系统操作 |

| 放行模块 | 用途 |
|---------|------|
| `json` | 数据序列化 |
| `pathlib` | 路径操作 |
| `asyncio` | 异步执行 |
| `re` | 正则匹配 |
| `hashlib` | 哈希计算 |

#### ASTSandbox — 代码级危险操作拦截

解析 Python AST，检测以下危险模式：

```python
from coapis.security import ASTSandbox

sandbox = ASTSandbox()

# 检测 exec()
result = sandbox.check_code('exec("import os")')
# → safe=False, violations=['Dangerous function call: exec()']

# 检测 eval()
result = sandbox.check_code('result = eval(user_input)')
# → safe=False, violations=['Dangerous function call: eval()']

# 检测 __subclasses__()
result = sandbox.check_code('cls = []().__class__.__bases__[0].__subclasses__()')
# → safe=False, violations=['Dangerous attribute access: .__subclasses__', ...]

# 安全代码放行
result = sandbox.check_code('import json; data = json.loads("{}")')
# → safe=True
```

#### ResourceLimiter — 跨平台资源限制

| 平台 | 机制 | 强制级别 |
|------|------|---------|
| **Linux** | `resource` 模块 | 🟢 内核级 |
| **macOS** | `resource` 模块 | 🟢 内核级 |
| **Windows** | `CREATE_NEW_PROCESS_GROUP` | 🟡 进程级 |

默认限制：

```python
ResourceLimits(
    cpu_seconds=10,      # 最大 CPU 时间
    memory_mb=256,       # 最大内存
    file_size_mb=10,     # 最大单文件大小
    max_processes=50,    # 最大子进程数
    max_open_files=64,   # 最大打开文件数
    wall_time_seconds=30 # 最大执行时间
)
```

#### ProcessIsolator — 进程隔离

每次工具执行在独立进程中运行：

```python
from coapis.security import ProcessIsolator

isolator = ProcessIsolator("/opt/coapis/workspaces/admin", timeout=5)

# 执行后自动清理临时目录
result = await isolator.execute("ls -la")
# result.workpoint → /tmp/isolated_xxx（临时目录，执行后删除）
# result.stdout → 命令输出
# result.output_truncated → 是否被截断
```

环境变量过滤：仅保留 `PATH/HOME/USER/LANG/TERM` 等 10 个安全变量，阻止敏感信息泄露。

### 审计日志（Hash Chain）

防篡改审计日志，每条记录包含前一条的 SHA-256 哈希：

```python
from coapis.security import HashChainAuditLogger

logger = HashChainAuditLogger("/opt/coapis/system/logs/audit")

# 记录事件
logger.log_tool_call("admin", "read_file", '{"path": "/tmp/test"}', True, 50.0)
logger.log_auth_event("admin", "login_success", True)

# 验证链完整性
result = logger.verify_chain()
# → {"valid": True, "entries": 2, "message": "All 2 entries verified"}
```

### AgentCore 集成

沙箱在 `AgentCore.process()` 和 `stream_chat()` 中自动生效：

```python
# core.py 工具执行链路
if self._tool_sandbox:
    # 1. 路径检查（read_file/write_file/edit_file）
    if tool_name in ("read_file", "write_file", "edit_file"):
        result = self._tool_sandbox.check_path(path)
        if not result.allowed:
            raise PermissionError(f"Path: {result.reason}")

    # 2. 命令检查（execute_shell_command）
    if tool_name == "execute_shell_command":
        result = self._tool_sandbox.check_command(cmd)
        if not result.allowed:
            raise PermissionError(f"Command: {result.reason}")

# 被拦截时返回错误消息给用户
except PermissionError as e:
    tool_result = f"⛔ Security: {e}"
```

### 跨平台兼容性

| 平台 | ToolSandbox | ImportSandbox | ASTSandbox | ResourceLimiter | ProcessIsolator |
|------|:-----------:|:-------------:|:----------:|:---------------:|:---------------:|
| **Linux** | ✅ | ✅ | ✅ | ✅ 内核级 | ✅ |
| **macOS** | ✅ | ✅ | ✅ | ✅ 内核级 | ✅ |
| **Windows** | ✅ | ✅ | ✅ | 🟡 进程级 | ✅ |

### 安全收益评估

| 攻击向量 | 防护层 | 效果 |
|---------|--------|------|
| 路径遍历（`../../etc/passwd`） | ToolSandbox | ✅ 拦截 |
| 命令注入（`rm -rf /`） | ToolSandbox | ✅ 拦截 |
| 模块滥用（`import os`） | ImportSandbox | ✅ 拦截 |
| 代码注入（`exec("...")`） | ASTSandbox | ✅ 拦截 |
| 原型链污染（`__subclasses__`） | ASTSandbox | ✅ 拦截 |
| 资源耗尽（CPU/内存炸弹） | ResourceLimiter | ✅ 限制 |
| 环境变量泄露 | ProcessIsolator | ✅ 过滤 |
| 审计日志篡改 | HashChainAuditLogger | ✅ 防篡改 |
| 异常行为（高频调用） | ToolCallMonitor | ✅ 告警 |

### 后续演进方向

| 阶段 | 方案 | 状态 |
|------|------|------|
| **Phase 1** | Python 层沙箱（已实现） | ✅ 完成 |
| **Phase 2** | Linux Landlock + seccomp | 📋 规划中 |
| **Phase 3** | macOS sandbox-exec | 📋 规划中 |
| **Phase 4** | gVisor 生产部署 | 📋 规划中 |
| **Phase 5** | WASM 沙箱（长期） | 📋 研究中 |

---

## 附录 D：常见问题排查

### 1. Console Chat 返回 500
- **原因**：`.pyc` 缓存与源码不一致
- **解决**：删除 `__pycache__` 目录并重启容器

### 2. Docker 容器重启无效
- **原因**：`restart: unless-stopped` 策略导致容器自动重建
- **解决**：使用 `docker compose down --force-recreate` 强制重建

### 3. 前端页面空白
- **原因**：API 请求失败或路由配置错误
- **解决**：检查浏览器控制台错误，确认 Nginx 代理配置正确

### 4. Agent 无法启动
- **原因**：配置文件格式错误或 Provider 未配置
- **解决**：检查 `agent.json` 格式，确认 Provider 密钥已配置

---

**文档完成时间**：2026-06-05 00:05  
**维护者**：CoApis 团队  
**许可证**：Apache License 2.0