# CoApis 技术框架文档

> **版本**: v0.8.29 | **更新**: 2026-06-23
> **用途**: 所有开发、修复、优化工作的技术参考基准

---

## 一、项目架构概览

```
coapis-agent/
├── server/                    # 后端服务 (Python FastAPI)
│   ├── coapis/                # 核心包
│   │   ├── agent/             # 智能体引擎
│   │   ├── app/               # 应用层 (路由、频道、权限等)
│   │   └── system/            # 系统初始化与配置
│   └── deploy/                # 部署配置
├── client/                    # 前端 (React + TypeScript)
│   └── src/
│       ├── api/               # API 调用层
│       ├── components/        # UI 组件
│       ├── pages/             # 页面路由
│       └── locales/           # 国际化
├── docker/                    # Docker 部署
│   ├── docker-compose.yml     # 生产环境
│   ├── docker-compose.dev.yaml # 开发环境
│   └── .env                   # 环境变量
└── docs/                      # 文档
```

---

## 二、核心模块技术说明

### 2.1 智能体引擎 (`server/coapis/agent/`)

| 文件 | 职责 | 关键点 |
|------|------|--------|
| `core.py` | 智能体核心逻辑 | 系统提示构建、工具注册 |
| `react_agent.py` | ReAct 推理引擎 | 思考-行动循环、流式输出 |
| `workspace.py` | 工作空间管理 | **事件分块、流式缓冲、阶段管理** |
| `skills_manager.py` | 技能管理 | 技能加载、执行、权限 |
| `model_factory.py` | 模型工厂 | LLM 适配、Provider 管理 |
| `prompt.py` | 提示构建 | 系统提示模板、上下文管理 |
| `context_compressor.py` | 上下文压缩 | 长对话历史压缩 |

**关键数据流**：
```
用户消息 → react_agent.py → workspace.py → 流式事件 → 频道/前端
```

### 2.2 应用层 (`server/coapis/app/`)

| 模块 | 职责 | 关键文件 |
|------|------|----------|
| **路由** | API 端点 | `routers/` 目录 (40+ 路由文件) |
| **频道** | 消息通道 | `channels/` (企业微信、钉钉、飞书等) |
| **权限** | 访问控制 | `permissions/`, `access_control.py` |
| **多智能体** | 智能体管理 | `multi_agent_manager.py` |
| **认证** | 用户认证 | `auth.py`, `auth_middleware.py` |
| **清理** | 数据清理 | `cleanup.py`, `cleanup_manager.py` |
| **定时任务** | Cron 任务 | `crons/` 目录 |
| **MCP** | 工具协议 | `mcp/` 目录 |

### 2.3 频道系统 (`channels/`)

| 频道 | 文件 | 状态 |
|------|------|------|
| 企业微信 | `wecom/` | ✅ 已实现 |
| 钉钉 | `dingtalk/` | ✅ 已实现 |
| 飞书 | `feishu/` | ✅ 已实现 |
| 控制台 | `console/` | ✅ Web UI |
| Telegram | `telegram/` | ✅ 已实现 |
| Discord | `discord_/` | ⚠️ 半成品 |
| 语音 | `voice/` | ✅ 已实现 |

**频道基类**: `base.py` - 所有频道继承此类，提供流式消息处理

### 2.4 前端 (`client/src/`)

| 模块 | 目录 | 职责 |
|------|------|------|
| API 层 | `api/` | 后端接口调用 |
| 组件库 | `components/` | 可复用 UI 组件 |
| 页面 | `pages/` | 17 个主要页面 |
| 状态管理 | `stores/` | Zustand 状态 |
| 路由 | `App.tsx` | React Router |
| 国际化 | `locales/` | 中英文支持 |

**关键页面**:
- `Chat/` - 聊天主界面
- `Agents/` - 智能体管理
- `Channels/` - 频道配置
- `Settings/` - 系统设置

---

## 三、数据流与事件系统

### 3.1 流式消息事件

```python
# 事件类型 (workspace.py)
class StreamEvent:
    MESSAGE = "message"           # 正文回复
    REASONING = "reasoning"       # 思考过程
    PLUGIN_CALL = "plugin_call"   # 工具调用
```

**事件格式**:
```json
{
  "type": "message|reasoning|plugin_call",
  "content": "...",
  "status": "in_progress|completed|error"
}
```

### 3.2 频道流式处理

```python
# base.py 核心方法
_dispatch_streaming_event()  # 分发流式事件
streaming_buffers = {}       # 流式缓冲区 (key: f"{stream_type}:{msg_id}")
```

**关键修复点**:
1. `streaming_buffers` 键策略: `f"{stream_type}:{msg_id}"`
2. 企业微信小方块: `on_streaming_start` 检查已有会话
3. `RunStatus` 使用 `Completed/Failed` (非 Error)

---

## 四、部署架构

### 4.1 Docker 容器

| 容器 | 用途 | 端口 |
|------|------|------|
| `coapis-server` | 后端 API | 4208 (prod) / 4308 (dev) |
| `coapis-nginx` | 前端 + 反向代理 | 4200 (prod) / 4300 (dev) |
| `coapis-playwright` | 浏览器服务 | 4201 |

### 4.2 环境变量

```bash
# 关键配置 (.env)
COAPIS_WORKING_DIR=/apps/ai/coapis    # 工作目录 (bind mount)
COAPIS_WEB_PORT=4200                   # Web 端口
COAPIS_SERVER_PORT=4208                # API 端口
COAPIS_VERSION=0.8.29                  # 版本号
```

### 4.3 数据目录

```
/apps/ai/coapis/
├── system/          # 系统配置
│   ├── config.json  # 主配置
│   ├── auth.json    # JWT 密钥
│   ├── users.json   # 用户列表
│   └── permissions.json  # 权限配置
├── workspaces/      # 智能体工作空间
│   ├── global_default/  # 全局默认智能体
│   └── default/         # 默认用户空间
├── plugins/         # 插件
├── skills/          # 技能
└── skill_pool/      # 技能池
```

---

## 五、关键修复点 (历史问题)

### 5.1 聊天崩溃修复
- **问题**: `TypeError: Cannot read properties of undefined (reading 'call_id')`
- **文件**: `workspace.py`, `GroupedResponseCard.tsx`
- **方案**: 事件分块管理、插件调用数据结构修正

### 5.2 Thinking 显示修复
- **问题**: 深度思考内容不流式输出
- **文件**: `workspace.py` (`_open_phase` 添加 `status=RunStatus.InProgress`)
- **前端**: `CoApisDeepThinking` 组件

### 5.3 企业微信流式显示
- **问题**: 小方块堆积、消息不显示
- **文件**: `channels/base.py`, `channels/wecom/channel.py`
- **方案**: `streaming_buffers` 键策略、加载指示器检查

### 5.4 工具调用显示
- **问题**: 工具名称不显示
- **文件**: `workspace.py` (`DataContent` 替代 `TextContent`)
- **格式**: `{"name": "tool_name", "arguments": {...}}`

### 5.5 登录失败修复
- **问题**: nginx upstream 连接池失效
- **方案**: 重建后端后必须重启 nginx

---

## 六、开发规范

### 6.1 修复流程
1. **定位**: 使用本文档找到相关模块
2. **分析**: 阅读对应文件理解上下文
3. **方案**: 先提供完整方案，用户确认后再执行
4. **验证**: 修复后验证无副作用

### 6.2 关键文件速查

| 问题类型 | 优先检查文件 |
|----------|--------------|
| 聊天显示 | `workspace.py`, `GroupedResponseCard.tsx` |
| 流式消息 | `channels/base.py`, 具体频道 `channel.py` |
| 工具调用 | `workspace.py` (事件分发), `react_agent.py` |
| 权限问题 | `permissions.json`, `access_control.py` |
| 认证问题 | `auth.py`, `auth_middleware.py` |
| 模型配置 | `model_factory.py`, `providers.py` |
| 智能体管理 | `multi_agent_manager.py` |
| 前端组件 | `client/src/components/` |

### 6.3 部署铁律

```bash
# 重建后端后必须重启 nginx！
docker compose -f docker-compose.dev.yaml up -d --force-recreate server
sleep 10
docker restart coapis-nginx-dev  # 或 coapis-nginx (prod)
```

---

## 七、环境区分

| 项目 | 开发环境 | 生产环境 |
|------|----------|----------|
| 配置文件 | `docker-compose.dev.yaml` | `docker-compose.yml` |
| 容器名后缀 | `-dev` | 无 |
| 镜像 | `coapis-server:dev` | `coapis-server:latest` |
| 数据目录 | `/apps/ai/coapis-dev` | `/apps/ai/coapis` |
| 端口 | 4300/4308 | 4200/4208 |
| 自动更新 | ✅ 代码改动后重建 | ❌ 手动部署 |

---

**重要**: 后续所有开发工作请首先参考本文档定位相关模块和文件。
