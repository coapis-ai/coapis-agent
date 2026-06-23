# CoApis 系统初始化与部署指南

> 版本：v1.0 | 更新时间：2026-06-23

本文档详细说明 CoApis 系统的初始化逻辑、目录结构、环境变量配置，以及三种部署方式（Docker、源码、一键安装）的具体操作。

---

## 目录

- [一、初始化逻辑](#一初始化逻辑)
  - [1.1 触发时机](#11-触发时机)
  - [1.2 初始化流程](#12-初始化流程)
  - [1.3 初始化内容](#13-初始化内容)
- [二、目录结构](#二目录结构)
  - [2.1 工作目录总览](#21-工作目录总览)
  - [2.2 关键目录说明](#22-关键目录说明)
- [三、默认配置文件](#三默认配置文件)
  - [3.1 config.json](#31-configjson)
  - [3.2 permissions.json](#32-permissionsjson)
  - [3.3 users.json](#33-usersjson)
- [四、环境变量配置](#四环境变量配置)
  - [4.1 核心环境变量](#41-核心环境变量)
  - [4.2 可选环境变量](#42-可选环境变量)
  - [4.3 变量加载优先级](#43-变量加载优先级)
- [五、部署方式](#五部署方式)
  - [5.1 Docker 部署](#51-docker-部署)
  - [5.2 源码部署](#52-源码部署)
  - [5.3 一键安装部署](#53-一键安装部署)
- [六、生产环境初始化](#六生产环境初始化)
- [七、关键文件清单](#七关键文件清单)
- [八、常见问题](#八常见问题)

---

## 一、初始化逻辑

### 1.1 触发时机

系统初始化在以下情况下自动触发：

- 容器首次启动（`entrypoint.sh` 检测缺少核心配置文件）
- 手动执行 `coapis init --defaults --accept-security`
- 调用 Python API `initialize_system()`

**自动检测条件**（满足任一即触发）：
```bash
[ ! -f "${SYSTEM_DIR}/config.json" ]
[ ! -f "${SYSTEM_DIR}/permissions.json" ]
[ ! -f "${SYSTEM_DIR}/users.json" ]
```

### 1.2 初始化流程

```
entrypoint.sh
  │
  ├─ 检测是否需要初始化
  │
  └─ init_workspace.sh
       │
       └─ Python initializer (coapis.system.initialize_system)
            │
            ├─ 1. 创建目录结构
            │     └─ 基于 DEFAULT_DIRECTORIES 创建所有必要目录
            │
            ├─ 2. 初始化配置文件
            │     └─ 生成 config.json（包含随机 secret_key）
            │
            ├─ 3. 初始化权限系统
            │     └─ 生成 permissions.json（v2.0 CRUD矩阵格式）
            │
            ├─ 4. 初始化用户系统
            │     ├─ 生成 users.json
            │     └─ 创建默认 admin 用户（bcrypt密码哈希）
            │
            ├─ 5. 初始化Token统计
            │     ├─ token_usage.json
            │     └─ token_usage_details.json
            │
            ├─ 6. 初始化审计日志
            │     └─ audit_logs.json
            │
            └─ 7. 版本迁移检查
                  └─ 比较并更新 config.json 中的版本号
```

### 1.3 初始化内容

#### 目录创建
基于 `DEFAULT_DIRECTORIES` 列表创建以下目录：
- `system/` - 系统配置
- `system/.secret/` - 敏感数据
- `system/templates/` - 全局模板
- `system/evolution/` - 全局进化机制
- `system/reviews/` - 全局审查记录
- `workspaces/` - 用户工作区（按用户隔离）
- `agents/` - 全局智能体数据
- `skills/` - 已安装技能
- `skill_pool/` - 技能池
- `logs/` - 日志
- `media/` - 全局媒体文件
- `local_models/` - 本地模型
- `memory/` - 全局记忆数据
- `.backups/` - 备份
- `custom_channels/` - 自定义频道
- `plugins/` - 插件
- `models/` - 模型配置
- `audit_log/` - 审计日志

#### 用户工作区创建（init_user_workspace）
新用户注册时，为其创建完整的工作区：
- `workspaces/{username}/` - 用户根目录
- `workspaces/{username}/agents/` - 子智能体配置
- `workspaces/{username}/skills/` - 用户技能
- `workspaces/{username}/chat/` - 聊天数据
- `workspaces/{username}/files/` - 用户文件
- `workspaces/{username}/files/media/` - 媒体文件
- `workspaces/{username}/memory/` - 每日记忆笔记
- `workspaces/{username}/sessions/` - 会话数据
- `workspaces/{username}/workflows/` - 工作流
- `workspaces/{username}/crons/` - 定时任务
- `workspaces/{username}/backups/` - 备份数据
- `workspaces/{username}/evolution/` - 用户级进化
- `workspaces/{username}/knowledge_flow/` - 知识流
- `workspaces/{username}/agent.json` - 智能体配置
- `workspaces/{username}/jobs.json` - 定时任务配置
- `workspaces/{username}/skill.json` - 技能清单
- `workspaces/{username}/chats.json` - 聊天列表

#### 模板文件
`system/templates/` 下的模板文件在用户/智能体初始化时复制到对应工作区：
- `SOUL.md` - 灵魂设定模板
- `AGENTS.md` - 行为准则模板
- `PROFILE.md` - 身份档案模板
- `MEMORY.md` - 记忆模板
- `BOOTSTRAP.md` - 引导模板
- `HEARTBEAT.md` - 心跳配置模板

#### 配置文件生成
- **config.json**：生成随机 `secret_key`（`secrets.token_hex(32)`）
- **permissions.json**：使用 `DEFAULT_PERMISSIONS` 模板
- **users.json**：使用 `DEFAULT_ADMIN_USER` 创建管理员账户

---

## 二、目录结构

### 2.1 工作目录总览

默认工作目录：`/apps/ai/coapis`（可通过 `COAPIS_WORKING_DIR` 自定义）

```
/apps/ai/coapis/
│
├── system/                          # 系统配置目录
│   ├── config.json                 # 主配置文件
│   ├── permissions.json            # 权限矩阵（v2.0）
│   ├── users.json                  # 用户数据
│   ├── token_usage.json            # Token统计汇总
│   ├── token_usage_details.json    # Token使用明细
│   ├── audit_logs.json             # 审计日志
│   │
│   ├── .secret/                    # 敏感数据（权限600）
│   │   ├── .master_key             # 主密钥
│   │   └── providers/              # 模型供应商配置
│   │       ├── builtin/            # 内置供应商
│   │       ├── custom/             # 自定义供应商
│   │       ├── plugin/             # 插件供应商
│   │       └── active_model.json   # 当前激活模型
│   │
│   ├── templates/                  # 全局模板（新用户/新智能体初始化时复制）
│   │   ├── SOUL.md                 # 灵魂模板
│   │   ├── AGENTS.md               # 行为准则模板
│   │   ├── PROFILE.md              # 身份档案模板
│   │   ├── MEMORY.md               # 记忆模板
│   │   ├── BOOTSTRAP.md            # 引导模板
│   │   └── HEARTBEAT.md            # 心跳模板
│   │
│   ├── evolution/                  # 全局进化机制数据
│   └── reviews/                    # 全局审查记录
│
├── workspaces/                     # 用户工作区（按用户隔离）
│   │
│   ├── admin/                      # admin 用户工作区（由 init_user_workspace 创建）
│   │   ├── agent.json             # 智能体配置（id=user:admin, owner=admin）
│   │   ├── AGENTS.md              # 行为准则
│   │   ├── SOUL.md                # 灵魂设定
│   │   ├── PROFILE.md             # 身份档案
│   │   ├── MEMORY.md              # 长期记忆
│   │   ├── HEARTBEAT.md           # 心跳配置
│   │   ├── BOOTSTRAP.md           # 引导文件
│   │   ├── chats.json             # 聊天列表（根级旧格式）
│   │   ├── jobs.json              # 定时任务配置
│   │   ├── skill.json             # 技能清单
│   │   │
│   │   ├── agents/                # 子智能体配置目录
│   │   ├── skills/                # 用户已安装技能
│   │   ├── chat/                  # 聊天数据
│   │   │   └── chats.json         # 聊天记录索引
│   │   ├── chats/                 # 聊天存储（运行时生成）
│   │   ├── files/                 # 用户文件
│   │   │   └── media/             # 媒体文件
│   │   ├── memory/                # 每日记忆笔记
│   │   ├── sessions/              # 会话数据
│   │   ├── workflows/             # 工作流
│   │   ├── crons/                 # 定时任务数据
│   │   ├── backups/               # 备份数据
│   │   ├── evolution/             # 用户级进化数据
│   │   └── knowledge_flow/        # 知识流数据
│   │
│   └── {username}/                 # 其他用户（结构同 admin）
│       ├── agent.json
│       ├── agents/
│       ├── skills/
│       ├── chat/
│       ├── files/
│       ├── memory/
│       ├── sessions/
│       ├── workflows/
│       ├── crons/
│       └── backups/
│
│   ⚠️ 注意：workspaces/ 下只有用户目录，不应有 global_default 或 default 目录。
│      全局智能体数据在 agents/ 目录，不在 workspaces/ 下。
│
├── agents/                         # 全局智能体数据
│   ├── global_default/             # 全局默认智能体（非用户级）
│   │   ├── data/                   # 运行时数据
│   │   └── skills/                 # 技能
│   └── global_qa_agent/            # 内置 QA 智能体
│       ├── agent.json
│       ├── skills/
│       └── ...
│
├── skills/                         # 已安装技能（全局）
├── skill_pool/                     # 技能池（可安装技能库）
├── logs/                           # 应用日志
│   └── coapis.log
├── audit_log/                      # 审计日志（不可变哈希链）
├── media/                          # 全局媒体文件
├── local_models/                   # 本地模型文件
├── memory/                         # 全局记忆数据
├── models/                         # 模型配置
├── plugins/                        # 已安装插件
├── custom_channels/                # 自定义频道模块
├── .backups/                       # 备份文件
└── tmp/                            # 临时数据（可随时清理）
    ├── evolution/                  # 临时进化数据
    │   ├── trajectories/
    │   └── experiences/
    ├── cache/                      # 临时缓存
    └── sessions/                   # 临时会话数据
```

### 2.2 关键目录说明

| 目录 | 用途 | 持久化 | 说明 |
|------|------|--------|------|
| `system/` | 系统配置 | ✅ 必须 | config.json, users.json, permissions.json 等 |
| `system/.secret/` | 敏感数据 | ✅ 必须 | 密钥、供应商配置（权限600） |
| `system/templates/` | 全局模板 | ✅ 必须 | 新用户/智能体初始化时复制的模板文件 |
| `workspaces/` | 用户工作区 | ✅ 必须 | 按用户隔离，包含智能体配置和用户数据 |
| `workspaces/{username}/` | 用户个人空间 | ✅ 必须 | 包含 agent.json、技能、聊天、文件、记忆等 |
| `agents/` | 全局智能体 | ✅ 建议 | global_default、global_qa_agent 等全局智能体 |
| `skills/` | 已安装技能 | ✅ 建议 | 全局已安装的技能 |
| `skill_pool/` | 技能池 | ⚠️ 可选 | 可安装的技能库（从远程拉取） |
| `logs/` | 应用日志 | ⚠️ 可选 | coapis.log 等运行日志 |
| `audit_log/` | 审计日志 | ✅ 建议 | 不可变哈希链，记录所有关键操作 |
| `media/` | 全局媒体 | ⚠️ 可选 | 频道共享的媒体文件 |
| `local_models/` | 本地模型 | ✅ 建议 | 本地模型文件（如 GGUF） |
| `memory/` | 全局记忆 | ✅ 建议 | 全局记忆数据 |
| `models/` | 模型配置 | ✅ 必须 | 模型相关配置 |
| `plugins/` | 插件 | ⚠️ 可选 | 通过 `coapis plugin install` 安装 |
| `custom_channels/` | 自定义频道 | ⚠️ 可选 | 通过 `coapis channels install` 安装 |
| `.backups/` | 备份文件 | ⚠️ 可选 | 自动备份和手动备份 |
| `tmp/` | 临时数据 | ❌ 可清理 | 运行时临时数据，可随时清理 |

---

## 三、默认配置文件

### 3.1 config.json

```json
{
  "version": "0.8.12",
  "channels": {
    "discord": { "enabled": false, ... },
    "dingtalk": { "enabled": false, ... },
    "feishu": { "enabled": false, ... }
  },
  "heartbeat": {
    "enabled": true,
    "every": 60,
    "query": "What should I work on next?"
  },
  "active_hours": {},
  "auth": {
    "enabled": true,
    "secret_key": "<随机生成的 hex 字符串>"
  },
  "agents": {
    "active_agent": "user:admin",
    "agent_order": [],
    "profiles": {
      "user:admin": {
        "id": "user:admin",
        "workspace_dir": "/apps/ai/coapis/workspaces/admin",
        "enabled": true,
        "username": "admin",
        "role": "admin"
      },
      "global_qa_agent": {
        "id": "global_qa_agent",
        "workspace_dir": "/apps/ai/coapis/agents/global_qa_agent",
        "enabled": true,
        "role": "service"
      }
    },
    "defaults": null,
    "running": { "max_iters": 100, ... }
  },
  "providers": {},
  "mcp_servers": {},
  "mcp": { "agents": {} },
  "show_tool_details": true,
  "user_timezone": "Etc/UTC"
}
```

**关键字段说明**：
- `auth.secret_key`：JWT签名密钥，初始化时自动生成随机值
- `auth.enabled`：是否启用认证（生产环境应设为 `true`）
- `agents.active_agent`：当前激活的智能体 ID（用户登录后自动切换为 `user:{username}`）
- `agents.profiles`：已注册的智能体配置表，包含用户智能体和全局智能体
- `providers`：模型供应商配置（可通过API或手动编辑）

### 3.2 permissions.json

```json
{
  "version": "2.0",
  "description": "CoApis permission system — CRUD matrix format.",
  "roles": {
    "user": {
      "name": "用户",
      "description": "标准用户，可通过权限矩阵配置",
      "level": 0,
      "is_default": true,
      "modules": {
        "chat": {"read": true, "create": true, "update": true, "delete": false},
        "skills": {"read": true, "create": true, "update": true, "delete": false},
        "models": {"read": true, "create": true, "update": true, "delete": true},
        "agents": {"read": true, "create": true, "update": false, "delete": false},
        "admin": {"read": false, "create": false, "update": false, "delete": false},
        "system": {"read": false, "create": false, "update": false, "delete": false},
        "audit": {"read": true, "create": false, "update": false, "delete": false},
        "sessions": {"read": true, "create": true, "update": true, "delete": true},
        "files": {"read": true, "create": true, "update": true, "delete": true}
      }
    },
    "advanced": {
      "name": "高级用户",
      "level": 1,
      "modules": {
        "models": {"read": true, "create": true, "update": true, "delete": false},
        "agents": {"read": true, "create": true, "update": true, "delete": true}
      }
    },
    "admin": {
      "name": "管理员",
      "level": 2,
      "modules": "*"
    }
  },
  "user_overrides": {},
  "module_definitions": {
    "chat": {"name": "聊天", "description": "AI 对话功能"},
    "models": {"name": "模型", "description": "模型配置"},
    "agents": {"name": "智能体", "description": "智能体管理"}
  }
}
```

**权限说明**：
- `user`：基础用户，可聊天、管理自己的智能体和模型
- `advanced`：高级用户，可管理更多资源
- `admin`：管理员，拥有所有权限（`"modules": "*"`）
- 支持 `user_overrides` 为特定用户设置独立权限

### 3.4 auth.json

```json
{
  "secret_key": "<JWT签名密钥，初始化时自动生成>",
  "algorithm": "HS256",
  "token_expiry_seconds": 604800
}
```

**说明**：
- `secret_key`：用于签名 JWT Token，初始化时自动生成
- 位于 `system/.secret/` 下，权限 600

### 3.3 users.json

```json
{
  "users": {
    "admin": {
      "username": "admin",
      "display_name": "管理员",
      "password_hash": "$2b$12$...",
      "salt": "$2b$",
      "role": "admin",
      "is_active": true,
      "created_at": 1782191793.3368676,
      "last_login": 1782192917.8385067
    }
  },
  "next_id": 2
}
```

**默认管理员**：
- 用户名：`admin`
- 密码：`admin123`（首次登录后应修改）
- 角色：`admin`
- `next_id`：自增用户ID计数器

---

## 四、环境变量配置

### 4.1 核心环境变量

| 变量名 | 默认值 | 说明 |
|--------|--------|------|
| `COAPIS_WORKING_DIR` | `/apps/ai/coapis` | 工作目录，所有数据存储位置 |
| `COAPIS_VERSION` | `0.8.28` | 版本号（用于显示和迁移） |

> **说明**：开源版多用户系统始终启用，认证始终开启，本地模型始终免费。无需配置开关变量。

### 4.2 可选环境变量

#### 网络配置
| 变量名 | 默认值 | 说明 |
|--------|--------|------|
| `COAPIS_WEB_PORT` | `4200` | Web端口（nginx） |
| `COAPIS_SERVER_PORT` | `4208` | API端口 |
| `COAPIS_PLAYWRIGHT_PORT` | `4201` | Playwright端口 |

#### 存储配置
| 变量名 | 默认值 | 说明 |
|--------|--------|------|
| `COAPIS_WORKSPACES_DIR` | `{WORKING_DIR}/workspaces` | 用户工作区目录（可分离到NFS） |
| `COAPIS_UPLOAD_MAX_FILES` | `10` | 单次最大上传文件数 |
| `COAPIS_UPLOAD_MAX_FILE_SIZE_MB` | `20` | 单文件最大体积(MB) |

#### 搜索配置
| 变量名 | 默认值 | 说明 |
|--------|--------|------|
| `COAPIS_WEB_SEARCH_DEFAULT_BACKEND` | `auto` | 默认搜索后端 |
| `COAPIS_WEB_SEARCH_BACKEND_ORDER` | `browser,tavily,bocha,ddgs,baidu,sogou` | fallback顺序 |
| `COAPIS_WEB_SEARCH_CACHE_TTL` | `600` | 搜索结果缓存时间(秒) |
| `COAPIS_WEB_SEARCH_TIMEOUT` | `15` | 单次搜索超时(秒) |

#### 浏览器配置
| 变量名 | 默认值 | 说明 |
|--------|--------|------|
| `BROWSER_CDP_URL` | - | CDP连接地址（如 `http://playwright:3000`） |
| `COAPIS_INSTALL_BROWSER` | `0` | 是否安装浏览器自动化 |
| `PLAYWRIGHT_CHROMIUM_EXECUTABLE_PATH` | - | 自定义Chromium路径 |

#### 其他配置
| 变量名 | 默认值 | 说明 |
|--------|--------|------|
| `COAPIS_LOG_LEVEL` | `INFO` | 日志级别 |
| `COAPIS_OPENAPI_DOCS` | `False` | 启用API文档（/docs） |
| `COAPIS_RUNNING_IN_CONTAINER` | `False` | 容器内运行标识 |
| `COAPIS_MODEL_PROVIDER_CHECK_TIMEOUT` | `5.0` | 供应商连接超时(秒) |

### 4.3 变量加载优先级

```
1. 系统环境变量（export）     ← 最高优先级
2. .env 文件                 ← 次优先级
3. 默认值                    ← 最低优先级
```

**加载逻辑**（`constant.py`）：
```python
# 1. 尝试从项目根目录加载 .env
_env_path = Path(__file__).resolve().parent.parent.parent / ".env"
if _env_path.exists():
    load_dotenv(_env_path)

# 2. 读取环境变量（带 COAPIS_ 前缀自动检查 legacy 版本）
def _get_env(key: str, default: str = "") -> str:
    if key in os.environ:
        return os.environ[key]
    if key.startswith("COAPIS_"):
        legacy_key = "COAPIS_" + key[len("COAPIS_"):]
        if legacy_key in os.environ:
            return os.environ[legacy_key]
    return default
```

---

## 五、部署方式

### 5.1 Docker 部署

#### 配置文件位置
- 开发环境：`docker/.env`
- 生产环境：`docker/.env.prod`

#### 步骤

**1. 编辑环境变量**
```bash
cd docker
vim .env.prod
```

**.env.prod 示例**：
```bash
# ── 基础配置 ──
COAPIS_VERSION=0.8.28
COAPIS_WORKING_DIR=/apps/ai/coapis

# ── 可选配置 ──
# COAPIS_WORKSPACES_DIR=${COAPIS_WORKING_DIR}/workspaces
# COAPIS_WEB_SEARCH_DEFAULT_BACKEND=auto
```

> **注意**：开源版无需配置 `COAPIS_AUTH_ENABLED`、`COAPIS_USER_SYSTEM_ENABLED`、`COAPIS_USER_LOCAL_MODEL_FREE_TOKENS`，这些功能已内置固定。

**2. 启动服务**
```bash
# 开发环境
docker compose -f docker-compose.dev.yaml up -d

# 生产环境
docker compose -f docker-compose.prod.yaml up -d
```

**3. 验证初始化**
```bash
# 查看初始化日志
docker logs coapis-server-prod | grep -i "init"

# 检查核心文件
docker exec coapis-server-prod ls -la /apps/ai/coapis/system/
```

**4. 重启后端后必须重启nginx**
```bash
# 铁律：每次重建后端后必须执行
docker restart coapis-nginx-dev  # 或 coapis-nginx-prod
```

#### Docker Compose 文件说明

| 文件 | 用途 | 端口映射 |
|------|------|----------|
| `docker-compose.dev.yaml` | 开发环境 | nginx:4300, server:4308, playwright:4301 |
| `docker-compose.prod.yaml` | 生产环境 | nginx:4200, server:4208, playwright:4201 |
| `docker-compose.build.yml` | 镜像构建 | - |

### 5.2 源码部署

#### 环境变量配置方式

**方式1：创建 .env 文件**（推荐）
```bash
# 在项目根目录创建
cat > .env << EOF
COAPIS_WORKING_DIR=/apps/ai/coapis
COAPIS_VERSION=0.8.29-dev
EOF
```

**方式2：导出环境变量**
```bash
export COAPIS_WORKING_DIR=/apps/ai/coapis
export COAPIS_VERSION=0.8.29-dev
```

#### 步骤

**1. 安装依赖**
```bash
cd server
pip install -e .
```

**2. 配置环境变量**
```bash
# 方式A：创建.env文件
echo "COAPIS_WORKING_DIR=/apps/ai/coapis" > .env

# 方式B：导出环境变量
export COAPIS_WORKING_DIR=/apps/ai/coapis
```

**3. 运行初始化**
```bash
python3 -c "
from coapis.system import initialize_system
import json
result = initialize_system()
print(json.dumps(result, indent=2, ensure_ascii=False))
"
```

**4. 启动服务**
```bash
# 方式A：使用CLI
coapis serve --host 0.0.0.0 --port 8000

# 方式B：使用Python模块
python3 -m coapis.server
```

#### 注意事项
- `.env` 文件会自动从项目根目录加载
- 环境变量优先级：`export` > `.env` 文件 > 默认值
- 源码部署时，`COAPIS_VERSION` 建议设置为开发版本号（如 `0.8.29-dev`）

### 5.3 一键安装部署

#### 命令行参数

```bash
# 标准安装（预构建镜像）
bash install.sh

# 源码构建模式（需要 Git + Node.js）
bash install.sh --source

# 包含 Playwright 浏览器服务
bash install.sh --with-playwright

# 仅更新到最新版本
bash install.sh --update

# 卸载
bash install.sh --uninstall
```

#### 环境变量配置

```bash
# 自定义安装目录
export COAPIS_INSTALL_DIR=/opt/coapis

# 自定义端口
export COAPIS_WEB_PORT=8080
export COAPIS_SERVER_PORT=8081

# 运行安装
bash install.sh
```

#### install.sh 内部逻辑

1. 检测系统环境（Docker 是否安装）
2. 下载 `docker-compose.yml` 和 `.env.example`
3. 根据参数生成最终的配置文件
4. 拉取镜像并启动服务
5. 等待服务健康检查通过
6. 输出访问地址和默认凭据

---

## 六、生产环境初始化验证

### 6.1 完整性检查脚本

```bash
#!/bin/bash
# 生产环境初始化完整性检查
echo "========== CoApis 初始化完整性检查 =========="

# 1. 系统目录
echo "--- system/ ---"
for f in config.json permissions.json users.json token_usage.json audit_logs.json; do
  [ -f "/apps/ai/coapis/system/$f" ] && echo "  ✅ $f" || echo "  ❌ $f 缺失"
done

# 2. 敏感数据
echo "--- .secret/ ---"
[ -f "/apps/ai/coapis/system/.secret/.master_key" ] && echo "  ✅ .master_key" || echo "  ❌ .master_key 缺失"
[ -d "/apps/ai/coapis/system/.secret/providers" ] && echo "  ✅ providers/" || echo "  ❌ providers/ 缺失"

# 3. 模板
echo "--- templates/ ---"
for f in SOUL.md AGENTS.md PROFILE.md MEMORY.md BOOTSTRAP.md HEARTBEAT.md; do
  [ -f "/apps/ai/coapis/system/templates/$f" ] && echo "  ✅ $f" || echo "  ❌ $f 缺失"
done

# 4. 用户工作区
echo "--- workspaces/ ---"
[ -d "/apps/ai/coapis/workspaces/admin" ] && echo "  ✅ admin/" || echo "  ❌ admin/ 缺失"
for d in agents skills chat files crons backups memory sessions workflows evolution knowledge_flow; do
  [ -d "/apps/ai/coapis/workspaces/admin/$d" ] && echo "  ✅ admin/$d/" || echo "  ❌ admin/$d/ 缺失"
done
for f in agent.json AGENTS.md SOUL.md PROFILE.md MEMORY.md HEARTBEAT.md BOOTSTRAP.md jobs.json skill.json; do
  [ -f "/apps/ai/coapis/workspaces/admin/$f" ] && echo "  ✅ admin/$f" || echo "  ❌ admin/$f 缺失"
done

# 5. config.json 关键字段
echo "--- config.json ---"
python3 -c "
import json
d = json.load(open('/apps/ai/coapis/system/config.json'))
aa = d['agents']['active_agent']
profiles = list(d['agents']['profiles'].keys())
print(f'  active_agent: {aa}')
print(f'  profiles: {profiles}')
ok = aa == 'user:admin' and 'user:admin' in profiles
print(f'  {\"✅\" if ok else \"❌\"} active_agent 和 profiles 配置')
"

# 6. users.json
echo "--- users.json ---"
python3 -c "
import json
d = json.load(open('/apps/ai/coapis/system/users.json'))
users = list(d.get('users', {}).keys())
print(f'  users: {users}')
print(f'  {\"✅\" if \"admin\" in users else \"❌\"} admin 用户存在')
"

echo "=============================================="
```

### 6.2 手动检查

```bash
# 1. 检查目录结构
ls -la /apps/ai/coapis/
ls -la /apps/ai/coapis/system/
ls -la /apps/ai/coapis/workspaces/
ls -la /apps/ai/coapis/workspaces/admin/

# 2. 检查用户
cat /apps/ai/coapis/system/users.json

# 3. 检查智能体配置
cat /apps/ai/coapis/workspaces/admin/agent.json | python3 -m json.tool

# 4. 检查服务状态
docker ps | grep coapis
curl http://localhost:4208/api/health
```

---

## 七、关键文件清单

| 文件 | 作用 | 路径 |
|------|------|------|
| `constant.py` | 环境变量加载、路径常量定义 | `server/coapis/constant.py` |
| `defaults.py` | 默认配置定义（目录、权限、用户） | `server/coapis/system/defaults.py` |
| `initializer.py` | 系统初始化逻辑 | `server/coapis/system/initializer.py` |
| `entrypoint.sh` | Docker容器入口脚本 | `server/deploy/entrypoint.sh` |
| `init_workspace.sh` | 工作区初始化脚本 | `server/deploy/init_workspace.sh` |
| `install.sh` | 一键安装脚本 | `install.sh` |
| `docker/.env` | 开发环境变量 | `docker/.env` |
| `docker/.env.prod` | 生产环境变量 | `docker/.env.prod` |
| `docker-compose.dev.yaml` | 开发环境编排 | `docker/docker-compose.dev.yaml` |
| `docker-compose.prod.yaml` | 生产环境编排 | `docker/docker-compose.prod.yaml` |

---

## 八、常见问题

### Q1: 初始化后权限不正确

**现象**：普通用户无法选择模型，API返回403

**原因**：`permissions.json` 中 `user` 角色的 `models` 权限为 `false`

**解决**：
```bash
# 检查当前权限
docker exec coapis-server-prod cat /apps/ai/coapis/system/permissions.json | \
  python3 -c "import sys,json; print(json.load(sys.stdin)['roles']['user']['modules']['models'])"

# 修复：重新初始化或手动更新
docker cp server/system/permissions.json coapis-server-prod:/apps/ai/coapis/system/permissions.json
curl -X POST "http://localhost:4200/api/permissions/reload" -H "Authorization: Bearer $TOKEN"
```

### Q2: 重建后端后API返回502

**现象**：所有API请求返回502 Bad Gateway

**原因**：nginx upstream 连接池失效

**解决**：铁律 - 每次重建后端后必须重启nginx
```bash
docker restart coapis-nginx-dev  # 或 coapis-nginx-prod
```

### Q3: 环境变量不生效

**现象**：修改环境变量后配置未更新

**原因**：环境变量只在容器启动时加载

**解决**：
```bash
# 方式1：重启容器
docker restart coapis-server-prod

# 方式2：重新创建容器（使用新环境变量）
docker compose -f docker-compose.prod.yaml up -d --force-recreate server
```

### Q4: 用户工作区数据丢失

**现象**：用户登录后看不到之前的对话

**原因**：`workspaces/` 目录未持久化

**解决**：
```yaml
# docker-compose.prod.yaml 中确保 volumes 配置正确
volumes:
  - coapis-data:/apps/ai/coapis  # 使用 named volume
```

### Q5: 版本号不一致

**现象**：界面显示版本与实际部署版本不符

**原因**：`COAPIS_VERSION` 环境变量未更新

**解决**：
```bash
# 更新 .env.prod 中的版本号
vim docker/.env.prod
# COAPIS_VERSION=0.8.29

# 重新创建容器
docker compose -f docker-compose.prod.yaml up -d --force-recreate server
```

### Q6: 用户工作区初始化不完整

**现象**：admin 用户左上角没有"智能体选择下拉"，"我的智能体"中没有默认智能体

**原因**：`workspaces/admin/` 目录缺少子目录（agents/、skills/、chat/ 等），或 `config.json` 中 `active_agent` 指向了不存在的智能体

**检查清单**：
```bash
# 1. 检查 workspaces 下是否有不该存在的目录
ls -la /apps/ai/coapis/workspaces/
# ⚠️ 只应有用户目录（如 admin/），不应有 global_default/ 或 default/

# 2. 检查 admin workspace 完整性
for d in agents skills chat files crons backups memory sessions workflows; do
  [ -d "/apps/ai/coapis/workspaces/admin/$d" ] && echo "✅ $d" || echo "❌ $d 缺失"
done

# 3. 检查 config.json
python3 -c "import json; d=json.load(open('/apps/ai/coapis/system/config.json')); print('active_agent:', d['agents']['active_agent'])"
# ⚠️ 应为 user:admin，不应为 global_default
```

**修复方案**：
```bash
# 1. 创建缺失目录
mkdir -p /apps/ai/coapis/workspaces/admin/{agents,skills,chat,files/media,crons,backups,memory,sessions,workflows,evolution,knowledge_flow,chats}

# 2. 修复 config.json
python3 -c "
import json
with open('/apps/ai/coapis/system/config.json') as f:
    cfg = json.load(f)
cfg['agents']['active_agent'] = 'user:admin'
if 'global_default' in cfg['agents']['profiles']:
    del cfg['agents']['profiles']['global_default']
with open('/apps/ai/coapis/system/config.json', 'w') as f:
    json.dump(cfg, f, indent=2, ensure_ascii=False)
"

# 3. 移除 workspaces 下的多余目录（先备份）
mv /apps/ai/coapis/workspaces/default /apps/ai/coapis/.backups/ 2>/dev/null
mv /apps/ai/coapis/workspaces/global_default /apps/ai/coapis/.backups/ 2>/dev/null

# 4. 重启服务
docker restart coapis-server && sleep 10 && docker restart coapis-nginx
```

### Q7: 重建后端后前端无法登录

**现象**：点击登录按钮无网络请求，页面无响应

**原因**：后端容器重建后 IP 变化，nginx upstream 连接池失效

**解决**：铁律 - 每次重建后端后必须重启 nginx
```bash
docker restart coapis-server && sleep 10 && docker restart coapis-nginx
```

---

## 附录：环境变量速查表

```bash
# ═══════════════════════════════════════════════════════════════════
# CoApis 环境变量速查表
# ═══════════════════════════════════════════════════════════════════

# ── 核心配置 ──
COAPIS_WORKING_DIR=/apps/ai/coapis      # 工作目录
COAPIS_VERSION=0.8.28                    # 版本号

# ── 网络端口 ──
COAPIS_WEB_PORT=4200                     # Web端口
COAPIS_SERVER_PORT=4208                  # API端口
COAPIS_PLAYWRIGHT_PORT=4201              # Playwright端口

# ── 存储配置 ──
COAPIS_WORKSPACES_DIR=/apps/ai/coapis/workspaces  # 用户空间
COAPIS_UPLOAD_MAX_FILES=10               # 最大上传文件数
COAPIS_UPLOAD_MAX_FILE_SIZE_MB=20        # 单文件最大体积

# ── 搜索配置 ──
COAPIS_WEB_SEARCH_DEFAULT_BACKEND=auto   # 默认搜索后端
BROWSER_CDP_URL=http://playwright:3000   # CDP连接地址

# ── 调试配置 ──
COAPIS_LOG_LEVEL=INFO                    # 日志级别
COAPIS_OPENAPI_DOCS=False                # 启用API文档

# ── 内置固定（无需配置） ──
# 多用户系统：始终启用
# 认证系统：始终开启
# 本地模型：始终免费
```
