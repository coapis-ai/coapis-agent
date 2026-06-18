# CoApis API 参考

## 概述

CoApis 提供 RESTful API 和 SSE (Server-Sent Events) 流式接口。所有 API 端点通过 Nginx 反向代理访问，统一入口为 `http://<host>:4200/api/`。

### 认证

启用认证后，需要在请求头中携带 JWT Token：
```
Authorization: Bearer <token>
```

Token 通过 `POST /api/auth/login` 获取。

---

## 认证 API

### 登录

```
POST /api/auth/login
Content-Type: application/json

{
  "username": "admin",
  "password": "admin123"
}
```

**响应:**
```json
{
  "token": "eyJhbGciOiJIUzI1NiIs...",
  "user": {
    "username": "admin",
    "level": 0,
    "points": 100
  }
}
```

### 注册

```
POST /api/auth/register
Content-Type: application/json

{
  "username": "newuser",
  "password": "password123",
  "email": "user@example.com"
}
```

**响应:**
```json
{
  "token": "eyJhbGciOiJIUzI1NiIs...",
  "user": {
    "username": "newuser",
    "level": 0,
    "points": 20
  }
}
```

### Token 验证

```
GET /api/auth/verify
Authorization: Bearer <token>
```

**响应:**
```json
{
  "valid": true,
  "user": {
    "username": "admin",
    "level": 0,
    "points": 100
  }
}
```

---

## 用户 API

### 获取当前用户信息

```
GET /api/user/me
Authorization: Bearer <token>
```

**响应:**
```json
{
  "username": "admin",
  "email": "admin@example.com",
  "level": 0,
  "points": 100,
  "preferences": {
    "chat_display": {
      "show_timestamps": false,
      "show_token_count": false,
      "show_model_name": true,
      "auto_scroll": true,
      "font_size": "normal",
      "code_theme": "dark"
    }
  }
}
```

### 更新用户偏好

```
PUT /api/user/preferences
Authorization: Bearer <token>
Content-Type: application/json

{
  "chat_display": {
    "show_timestamps": true,
    "font_size": "large"
  }
}
```

**响应:**
```json
{
  "success": true,
  "preferences": {
    "chat_display": {
      "show_timestamps": true,
      "show_token_count": false,
      "show_model_name": true,
      "auto_scroll": true,
      "font_size": "large",
      "code_theme": "dark"
    }
  }
}
```

---

## 聊天 API

### 流式聊天 (SSE)

```
POST /api/console/chat
Authorization: Bearer <token>
Content-Type: application/json

{
  "input": [
    {
      "role": "user",
      "type": "message",
      "content": [
        {"type": "text", "text": "你好"}
      ]
    }
  ],
  "session_id": "unique-session-id",
  "user_id": "username",
  "channel": "console",
  "stream": true,
  "biz_params": {
    "agent_id": "default"
  }
}
```

**SSE 响应流:**
```
data: {"object": "chunk", "id": "session-id", "created": 1234567890, "model": "qwen3.6-27b", "output": [{"role": "assistant", "content": "你"}]}

data: {"object": "chunk", "id": "session-id", "created": 1234567890, "model": "qwen3.6-27b", "output": [{"role": "assistant", "content": "好"}]}

data: {"object": "response", "id": "session-id", "status": "completed", "created": 1234567890, "model": "qwen3.6-27b", "output": [{"role": "assistant", "content": "你好！"}]}
```

---

## Agent API

### 获取 Agent 列表

```
GET /api/agents
Authorization: Bearer <token>
```

**响应:**
```json
{
  "agents": [
    {
      "agent_id": "default",
      "name": "Default Agent",
      "model": "qwen3.6-27b",
      "provider": "local_llm"
    }
  ]
}
```

### 获取 Agent 配置

```
GET /api/agents/{agent_id}/config
Authorization: Bearer <token>
```

### 更新 Agent 配置

```
PUT /api/agents/{agent_id}/config
Authorization: Bearer <token>
Content-Type: application/json

{
  "model": "qwen3.6-27b",
  "provider": "local_llm"
}
```

---

## 模型 API

### 获取活跃模型

```
GET /api/models/active?scope=effective&agent_id=default
Authorization: Bearer <token>
```

**响应:**
```json
{
  "active_llm": {
    "provider_id": "local_llm",
    "model": "qwen3.6-27b"
  }
}
```

### 设置活跃模型

```
PUT /api/models/active
Authorization: Bearer <token>
Content-Type: application/json

{
  "agent_id": "default",
  "provider_id": "local_llm",
  "model": "qwen3.6-27b"
}
```

---

## 文件管理 API (MySpace)

### 列出文件

```
GET /api/myfiles?path=/files
Authorization: Bearer <token>
```

**响应:**
```json
{
  "files": [
    {
      "name": "document.pdf",
      "type": "file",
      "size": 1024000,
      "modified": "2026-05-07T10:00:00"
    },
    {
      "name": "projects",
      "type": "directory",
      "modified": "2026-05-07T09:00:00"
    }
  ],
  "storage_used": 1024000,
  "storage_limit": 53687091200
}
```

### 上传文件

```
POST /api/myfiles/upload?path=/files/document.pdf
Authorization: Bearer <token>
Content-Type: multipart/form-data

[file: binary data]
```

### 下载文件

```
GET /api/myfiles/download?path=/files/document.pdf
Authorization: Bearer <token>
```

### 创建目录

```
POST /api/myfiles/mkdir
Authorization: Bearer <token>
Content-Type: application/json

{
  "path": "/files/new-folder"
}
```

### 重命名

```
POST /api/myfiles/rename
Authorization: Bearer <token>
Content-Type: application/json

{
  "old_path": "/files/old-name",
  "new_path": "/files/new-name"
}
```

### 删除

```
DELETE /api/myfiles/delete?path=/files/document.pdf
Authorization: Bearer <token>
```

---

## 进化系统 API

### 获取进化状态

```
GET /api/evolution/status
Authorization: Bearer <token>
```

**响应:**
```json
{
  "enabled": true,
  "trajectories_count": 10,
  "experiences_count": 5,
  "pending_reviews": 2
}
```

### 获取经验列表

```
GET /api/evolution/experiences
Authorization: Bearer <token>
```

### 知识流动状态

```
GET /api/evolution/knowledge-flow/status
Authorization: Bearer <token>
```

### 批准晋升

```
POST /api/evolution/knowledge-flow/approve
Authorization: Bearer <token>
Content-Type: application/json

{
  "id": "flow-123"
}
```

### 拒绝晋升

```
POST /api/evolution/knowledge-flow/reject
Authorization: Bearer <token>
Content-Type: application/json

{
  "id": "flow-123",
  "reason": "Not valuable enough"
}
```

---

## 基础层 API

### 获取基础层状态

```
GET /api/foundation/status
Authorization: Bearer <token>
```

**响应:**
```json
{
  "quota": {
    "foundation_limit": 100,
    "foundation_used": 10,
    "professional_limit": 500,
    "professional_used": 50
  }
}
```

### 获取记忆详情

```
GET /api/foundation/memory
Authorization: Bearer <token>
```

---

## 管理员 API

### 获取用户列表

```
GET /api/admin/users
Authorization: Bearer <admin-token>
```

### 获取系统统计

```
GET /api/admin/stats
Authorization: Bearer <admin-token>
```

---

## 定时任务 API

### 获取任务列表

```
GET /api/cron/jobs
Authorization: Bearer <token>
```

### 创建任务

```
POST /api/cron/jobs
Authorization: Bearer <token>
Content-Type: application/json

{
  "name": "daily-backup",
  "schedule": "0 2 * * *",
  "command": "backup"
}
```

---

## 健康检查

```
GET /api/health
```

**响应 (无需认证):**
```json
{
  "status": "healthy",
  "timestamp": "2026-05-07T14:00:00",
  "version": "0.1.0"
}
```

---

## 错误响应

### 400 Bad Request

```json
{
  "detail": "agent_id is required (in biz_params or session)"
}
```

### 401 Unauthorized

```json
{
  "detail": "Not authenticated"
}
```

### 403 Forbidden

```json
{
  "detail": "Insufficient permissions"
}
```

### 404 Not Found

```json
{
  "detail": "Resource not found"
}
```

### 429 Too Many Requests

```json
{
  "detail": "Rate limit exceeded. Try again later."
}
```

### 500 Internal Server Error

```json
{
  "detail": "Internal server error"
}
```
