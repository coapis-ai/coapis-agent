# CoApis 技术总览

> **版本**: v0.8.29 | **更新**: 2026-06-23
> **用途**: 全局架构、部署配置、前后端交互接口

---

## 一、项目架构

```
coapis-agent/
├── server/                    # 后端 (Python FastAPI)
│   └── coapis/
│       ├── agent/             # 智能体引擎
│       ├── app/               # 应用层
│       └── system/            # 系统初始化
├── client/                    # 前端 (React + TypeScript)
│   └── src/
├── docker/                    # Docker 部署
└── tech_docs/                 # 技术文档
```

---

## 二、部署架构

### 2.1 Docker 容器

| 容器 | 用途 | 生产端口 | 开发端口 |
|------|------|----------|----------|
| `coapis-server` | 后端 API | 4208 | 4308 |
| `coapis-nginx` | 前端 + 反代 | 4200 | 4300 |
| `coapis-playwright` | 浏览器服务 | 4201 | 4201 |

### 2.2 环境配置

| 项目 | 开发环境 | 生产环境 |
|------|----------|----------|
| 配置文件 | `docker-compose.dev.yaml` | `docker-compose.yml` |
| 环境变量 | `.env.dev` | `.env` |
| 数据目录 | `/apps/ai/coapis-dev` | `/apps/ai/coapis` |
| 镜像 | `coapis-server:dev` | `coapis-server:latest` |

### 2.3 网络配置

| 网络 | 类型 | 用途 |
|------|------|------|
| `coapis-prod_frontend` | bridge | 前端 + 外网访问 |
| `coapis-prod_internal` | internal | 内部服务通信 |

**⚠️ 重要**：`internal` 网络无法访问外网！LLM API 需要外网访问，server 必须连接 `frontend` 网络。

```yaml
# docker-compose.yml 中 server 的网络配置
networks:
  - frontend    # 外网访问（LLM API）
  - internal    # 内部通信
```

### 2.4 部署命令

```bash
# 开发环境
cd docker && docker compose -f docker-compose.dev.yaml up -d

# 生产环境
cd docker && docker compose -f docker-compose.yml up -d

# ⚠️ 铁律：重建后端后必须重启 nginx！
docker compose up -d --force-recreate server
sleep 10
docker restart coapis-nginx  # 或 coapis-nginx-dev
```

---

## 三、API 接口规范

### 3.1 基础路径

```
/api/                  # 公开接口
/api/console/          # 控制台接口 (需认证)
/api/admin/            # 管理员接口
```

### 3.2 认证方式

```http
Authorization: Bearer <jwt_token>
```

### 3.3 核心接口

| 模块 | 路径 | 方法 | 说明 |
|------|------|------|------|
| 认证 | `/api/auth/login` | POST | 登录 |
| 认证 | `/api/auth/status` | GET | 认证状态 |
| 智能体 | `/api/agents` | GET | 获取智能体列表 |
| 聊天 | `/api/console/chat` | POST | 发送消息 |
| 模型 | `/api/models/available` | GET | 可用模型 |
| 模型 | `/api/models/active` | PUT | 设置默认模型 |
| 技能 | `/api/plugins` | GET | 获取技能列表 |
| 频道 | `/api/channels` | GET | 获取频道列表 |
| 配置 | `/api/settings` | GET/PUT | 系统设置 |

### 3.4 流式响应

```http
GET /api/console/chat/stream
Content-Type: text/event-stream

# 事件格式
event: message
data: {"type":"message","content":"...","status":"completed"}

event: reasoning
data: {"type":"reasoning","content":"...","status":"in_progress"}

event: plugin_call
data: {"type":"plugin_call","content":"...","status":"completed"}
```

---

## 四、前后端交互

### 4.1 数据格式

**请求体**:
```json
{
  "message": "用户消息",
  "agent_id": "global_default",
  "session_id": "xxx"
}
```

**响应体**:
```json
{
  "success": true,
  "data": {
    "session_id": "xxx",
    "response": "AI回复"
  }
}
```

### 4.2 事件类型

| 类型 | 说明 | 前端处理 |
|------|------|----------|
| `message` | 正文回复 | 显示在聊天框 |
| `reasoning` | 思考过程 | 折叠显示 |
| `plugin_call` | 工具调用 | 工具卡片 |
| `status` | 状态更新 | 进度指示 |

### 4.3 错误处理

```json
{
  "success": false,
  "error": {
    "code": "UNAUTHORIZED",
    "message": "未授权"
  }
}
```

---

## 五、技术栈

### 5.1 后端
- Python 3.11
- FastAPI
- SQLite (部分功能)
- JSON 文件 (主要存储)

### 5.2 前端
- React 18
- TypeScript
- Vite
- @agentscope-ai/chat
- Zustand (状态管理)

### 5.3 基础设施
- Docker / Docker Compose
- Nginx (反向代理)
- Playwright (浏览器自动化)

---

## 六、文档索引

| 文档 | 内容 |
|------|------|
| `TECHNICAL_OVERVIEW.md` | 本文档 - 全局架构 |
| `TECHNICAL_BACKEND.md` | 后端技术详情 |
| `TECHNICAL_FRONTEND.md` | 前端技术详情 |
| `INITIALIZATION.md` | 系统初始化 |
| `DYNAMIC_RECOMMENDATION_PLAN.md` | 推荐方案 |

---

**重要**: 开发、修复、优化工作请先参考对应技术文档定位模块。
