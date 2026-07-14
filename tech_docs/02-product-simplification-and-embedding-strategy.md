# CoApis 产品简化与嵌入策略

> 日期：2026-07-05
> 状态：分析阶段
> 作者：蜜总裁

---

## 一、背景与目标

### 问题

当前 CoApis 是一个全功能平台，用户要使用需要理解：

```
注册用户 → 创建智能体 → 配置模型 → 配置工具 → 配置技能 → 配置频道 → 开始聊天
```

- **普通用户**：概念太多，路径太长
- **企业 OA 集成**：太重——OA 已有用户体系、权限、UI，只需要 AI 能力

### 目标

1. **简化**：普通用户零配置，开箱即用
2. **嵌入**：企业系统（OA、CRM 等）通过最轻量方式获得 AI 能力

---

## 二、核心价值分层

```
┌─────────────────────────────────────────────────┐
│  第三层：平台壳（Platform Shell）                  │
│  - 前端 UI（设置页、管理页、聊天页）                │
│  - 用户体系（注册/登录/权限）                      │
│  - 频道接入（企微/钉钉/飞书/Telegram）             │
│  - Admin 管理后台                                 │
│  价值：完整产品体验，适合独立部署                   │
├─────────────────────────────────────────────────┤
│  第二层：AI 引擎（AI Engine）                      │
│  - 智能体运行时（推理 + 工具调用 + 记忆）           │
│  - 多模型路由（自动降级、负载均衡）                 │
│  - 工具/技能执行框架                               │
│  - 记忆体系（短期/长期/跨智能体）                   │
│  - 会话管理                                       │
│  价值：核心 AI 能力，可被任何系统调用               │
├─────────────────────────────────────────────────┤
│  第一层：基础设施（Infrastructure）                 │
│  - LLM API 网关                                   │
│  - 向量存储                                       │
│  - 安全/加密                                      │
│  价值：底层支撑                                    │
└─────────────────────────────────────────────────┘
```

---

## 三、简化策略：为普通用户

**目标：零配置，开箱即用**

### 3.1 预置默认配置

| 当前 | 简化后 |
|------|--------|
| 用户自己创建智能体 | 首次部署自动生成 1-2 个默认智能体 |
| 用户自己配置模型 | 系统默认模型，用户可选切换 |
| 用户自己配置工具/技能 | 预置常用工具，按需启用 |
| 用户自己配置频道 | 部署时预配，用户无感 |

### 3.2 角色分级 UI

| 角色 | 可见功能 |
|------|---------|
| **普通用户** | 聊天 + 历史记录 |
| **管理员** | 完整设置页（智能体、模型、安全、Token 消耗等） |

### 3.3 实现方式

1. 启动时检测是否有默认智能体，没有则自动创建
2. 默认智能体绑定系统默认模型 + 预置工具集
3. 前端根据用户角色动态渲染菜单
4. 普通用户登录后直接进入聊天页

---

## 四、嵌入策略：为企业系统赋能

**目标：OA 等系统通过最轻量方式获得 AI 能力**

### 方案 A：API Only（最轻）

```
OA 系统 ──HTTP API──→ CoApis Engine ──→ AI 响应
```

- OA 通过 REST API 发送消息、获取回复
- CoApis 只暴露核心接口：
  - `POST /api/process` — 发送消息，获取 AI 回复
  - `GET /api/sessions` — 会话列表
  - `POST /api/sessions` — 创建会话
  - `GET /api/sessions/{id}/messages` — 历史消息
- 不需要 CoApis 的 UI、用户体系、频道
- **适合：已有成熟 UI 的系统**

**关键能力：**
- 支持 `X-User-Id` header 透传（OA 用户 → CoApis 会话隔离）
- 支持流式响应（SSE）用于打字机效果
- 支持自定义系统提示词（per-request）

### 方案 B：Embed Widget（中等）

```
OA 系统 ──<iframe/JS>──→ CoApis 聊天组件 ──→ AI 响应
```

- CoApis 提供可嵌入的聊天组件（JS SDK 或 iframe）
- OA 系统在页面中插入一行代码即可集成
- 认证通过 token 透传（OA 用户 → CoApis API token）
- **适合：想快速集成聊天能力的系统**

**集成示例：**
```html
<!-- 方式一：iframe -->
<iframe src="https://coapis.example.com/embed?token=xxx&agent=default"
        width="400" height="600" frameborder="0"></iframe>

<!-- 方式二：JS SDK -->
<script src="https://coapis.example.com/sdk/coapis-chat.js"></script>
<script>
  CoApisChat.init({
    apiUrl: 'https://coapis.example.com',
    token: 'xxx',
    agent: 'default',
    theme: 'light',
    position: 'bottom-right'
  });
</script>
```

### 方案 C：Channel 模式（最自然）

```
OA 系统 ──Webhook/消息推送──→ CoApis 频道 ──→ AI 响应 ──→ 回调 OA
```

- 利用现有频道机制，OA 作为"自定义频道"接入
- CoApis 负责 AI 推理，OA 负责 UI 和消息分发
- **适合：OA 有消息中心的系统**

**接口约定：**
```python
class OAClient:
    """OA 系统接入 CoApis 的标准接口"""
    
    def on_message(self, message: str, user_id: str) -> str:
        """接收用户消息，返回 AI 回复"""
        response = requests.post(
            f"{COAPIS_URL}/api/process",
            json={"message": message, "agent_id": "default"},
            headers={"X-User-Id": user_id}
        )
        return response.json()["reply"]
```

---

## 五、架构调整方向

### 5.1 当前架构

```
前端 UI + 后端 API + AI 引擎 + 频道 → 一个整体
```

### 5.2 目标架构

```
┌──────────────┐     ┌──────────────┐
│  Embed SDK   │     │  前端 UI     │
│  (iframe/JS) │     │  (管理后台)   │
└──────┬───────┘     └──────┬───────┘
       │                    │
       └────────┬───────────┘
                │
        ┌───────┴────────┐
        │  API Gateway   │ ← 认证 + 路由 + 限流 + 用户透传
        └───────┬────────┘
                │
        ┌───────┴────────┐     ┌──────────────┐
        │   AI Engine    │────→│ LLM Providers │
        │  (独立服务)     │     └──────────────┘
        └───────┬────────┘
                │
        ┌───────┴────────┐
        │   Data Layer   │ ← 记忆 + 会话 + 工具 + 技能
        └────────────────┘
                │
        ┌───────┴────────┐
        │   Channels     │ ← 企微/钉钉/飞书/自定义
        └────────────────┘
```

### 5.3 分层职责

| 层 | 职责 | 变化频率 |
|---|------|---------|
| **API Gateway** | 认证、路由、限流、用户透传 | 低 |
| **AI Engine** | 推理、工具调用、记忆管理 | 中 |
| **Data Layer** | 持久化、会话、向量存储 | 低 |
| **Channels** | 消息收发、格式转换 | 高（新渠道） |
| **前端 UI** | 管理界面、聊天界面 | 高 |

---

## 六、最小可行路径（MVP）

### 第一步：精简 API（最小改动，最大收益）

**目标：任何系统都能通过 HTTP 调用 CoApis 的 AI 能力**

1. 提供 `/api/process` 的精简 API 文档
2. 支持 `X-User-Id` header 透传（OA 用户 → CoApis 会话隔离）
3. 支持 `X-Agent-Id` header 指定智能体
4. 支持流式响应（SSE）
5. 提供 OpenAI 兼容端点（`/v1/chat/completions`）

**工作量：** 1-2 周（主要是文档 + OpenAI 兼容层）

### 第二步：Embed SDK（中等改动）

**目标：一行代码集成聊天能力**

1. 开发 Embed JS SDK（`coapis-chat.js`）
2. 支持 token 认证透传
3. 聊天组件可配置主题/尺寸/位置
4. 支持 iframe 嵌入模式
5. 提供集成文档和示例

**工作量：** 2-3 周

### 第三步：AI Engine 独立（较大改动）

**目标：前后端分离，AI Engine 可独立部署**

1. AI Engine 独立为微服务
2. 支持多租户 API Key
3. 提供 OpenAI 兼容 API
4. 支持水平扩展

**工作量：** 1-2 月

---

## 七、技术实现要点

### 7.1 用户透传机制

```python
# API Gateway 层
@app.middleware("http")
async def user_passthrough(request: Request, call_next):
    # 优先使用 header 中的用户 ID（嵌入场景）
    x_user_id = request.headers.get("X-User-Id")
    if x_user_id:
        request.state.user_id = x_user_id
        request.state.auth_method = "passthrough"
    else:
        # 使用 JWT token 中的用户 ID（独立部署场景）
        token = request.headers.get("Authorization", "").replace("Bearer ", "")
        request.state.user_id = verify_token(token)
        request.state.auth_method = "jwt"
    
    return await call_next(request)
```

### 7.2 会话隔离

```python
# 会话 ID 格式：{user_id}:{agent_id}:{session_id}
# 确保不同用户的会话完全隔离
session_id = f"{user_id}:{agent_id}:{uuid4()}"
```

### 7.3 OpenAI 兼容层

```python
@app.post("/v1/chat/completions")
async def openai_compatible(request: Request):
    """OpenAI 兼容端点，让其他系统用标准方式调用"""
    body = await request.json()
    
    # 转换为 CoApis 内部格式
    agent_id = body.get("model", "default")
    message = body["messages"][-1]["content"]
    
    # 调用 AI Engine
    response = await process_message(
        agent_id=agent_id,
        message=message,
        user_id=request.state.user_id,
        stream=body.get("stream", False)
    )
    
    # 转换为 OpenAI 格式
    return {
        "id": f"chatcmpl-{uuid4()}",
        "object": "chat.completion",
        "model": agent_id,
        "choices": [{
            "index": 0,
            "message": {"role": "assistant", "content": response},
            "finish_reason": "stop"
        }]
    }
```

---

## 八、风险与权衡

| 风险 | 影响 | 缓解措施 |
|------|------|---------|
| API 开放后安全性 | 未授权访问 | API Key + 速率限制 + IP 白名单 |
| 多租户资源竞争 | 性能下降 | 资源配额 + 队列管理 |
| 嵌入场景的认证复杂度 | 集成困难 | 提供 SDK 封装，隐藏认证细节 |
| 前后端分离的工程成本 | 开发周期长 | 渐进式分离，先 API 后 SDK |

---

## 九、总结

**核心思路：分层解耦**

- **普通用户** → 用完整平台（但预配置好，零门槛）
- **企业系统** → 用 API/SDK 嵌入 AI 引擎能力
- **最小改动** → 先开放精简 API + 支持用户透传
- **长期目标** → AI Engine 独立，支持多租户和水平扩展

**一句话：让 CoApis 既可以是完整产品，也可以是其他系统的 AI 能力底座。**
