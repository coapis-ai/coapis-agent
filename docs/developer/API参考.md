# CoApis API 参考

> CoApis RESTful API 和 SSE 流式接口文档。

---

## 基础信息

- **Base URL**: `http://<host>:4200/api/`
- **认证**: JWT Token（Bearer）
- **Content-Type**: `application/json`

### 获取 Token
```
POST /api/auth/login
{
  "username": "admin",
  "password": "admin123"
}
```
响应：
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

---

## 认证 API

| 方法 | 端点 | 说明 |
|------|------|------|
| POST | `/api/auth/login` | 登录 |
| POST | `/api/auth/register` | 注册 |
| POST | `/api/auth/refresh` | 刷新 Token |
| GET | `/api/auth/me` | 获取当前用户信息 |

---

## 聊天 API

| 方法 | 端点 | 说明 |
|------|------|------|
| POST | `/api/chat` | 发送消息（SSE 流式响应） |
| GET | `/api/chat/sessions` | 获取会话列表 |
| GET | `/api/chat/sessions/{id}` | 获取会话详情 |
| DELETE | `/api/chat/sessions/{id}` | 删除会话 |
| GET | `/api/chat/sessions/{id}/messages` | 获取消息历史 |

### 发送消息
```
POST /api/chat
Content-Type: application/json
Authorization: Bearer <token>

{
  "session_id": "xxx",
  "message": "帮我分析一下这份数据",
  "agent_id": "default",
  "files": ["file_id_1", "file_id_2"]
}
```
响应：SSE 流式输出

---

## Agent API

| 方法 | 端点 | 说明 |
|------|------|------|
| GET | `/api/agents` | 获取 Agent 列表 |
| POST | `/api/agents` | 创建 Agent |
| GET | `/api/agents/{id}` | 获取 Agent 详情 |
| PUT | `/api/agents/{id}` | 更新 Agent |
| DELETE | `/api/agents/{id}` | 删除 Agent |

---

## 文件 API

| 方法 | 端点 | 说明 |
|------|------|------|
| POST | `/api/files/upload` | 上传文件 |
| GET | `/api/files` | 获取文件列表 |
| GET | `/api/files/{id}` | 下载文件 |
| DELETE | `/api/files/{id}` | 删除文件 |
| PUT | `/api/files/{id}/rename` | 重命名文件 |

---

## 技能 API

| 方法 | 端点 | 说明 |
|------|------|------|
| GET | `/api/skills` | 获取技能列表 |
| POST | `/api/skills/install` | 安装技能 |
| DELETE | `/api/skills/{id}` | 卸载技能 |
| PUT | `/api/skills/{id}/enable` | 启用技能 |
| PUT | `/api/skills/{id}/disable` | 禁用技能 |

---

## 频道 API

| 方法 | 端点 | 说明 |
|------|------|------|
| GET | `/api/channels` | 获取频道列表 |
| POST | `/api/channels` | 创建频道 |
| PUT | `/api/channels/{id}` | 更新频道 |
| DELETE | `/api/channels/{id}` | 删除频道 |
| POST | `/api/channels/{id}/test` | 测试频道连接 |

---

## 定时任务 API

| 方法 | 端点 | 说明 |
|------|------|------|
| GET | `/api/cron` | 获取任务列表 |
| POST | `/api/cron` | 创建任务 |
| PUT | `/api/cron/{id}` | 更新任务 |
| DELETE | `/api/cron/{id}` | 删除任务 |
| POST | `/api/cron/{id}/run` | 手动执行任务 |
| POST | `/api/cron/{id}/pause` | 暂停任务 |
| POST | `/api/cron/{id}/resume` | 恢复任务 |

---

## 管理 API

| 方法 | 端点 | 说明 |
|------|------|------|
| GET | `/api/admin/users` | 获取用户列表 |
| POST | `/api/admin/users` | 创建用户 |
| PUT | `/api/admin/users/{id}` | 更新用户 |
| DELETE | `/api/admin/users/{id}` | 删除用户 |
| POST | `/api/admin/users/reset-password` | 重置密码 |
| GET | `/api/admin/stats` | 系统统计 |
| GET | `/api/audit/logs` | 审计日志 |

---

## 健康检查

```
GET /api/health

Response:
{
  "status": "healthy",
  "timestamp": "2026-06-20T15:00:00",
  "version": "1.0.0"
}
```

---

## SSE 流式响应

聊天接口使用 Server-Sent Events 流式返回：

```
POST /api/chat

Response:
event: message
data: {"content": "你", "type": "token"}

event: message
data: {"content": "好", "type": "token"}

event: done
data: {"session_id": "xxx", "total_tokens": 150}
```

---

## 错误响应

```json
{
  "detail": "错误描述",
  "code": "ERROR_CODE"
}
```

常见错误码：
| 状态码 | 说明 |
|--------|------|
| 400 | 请求参数错误 |
| 401 | 未认证 |
| 403 | 无权限 |
| 404 | 资源不存在 |
| 429 | 请求过于频繁 |
| 500 | 服务器内部错误 |
