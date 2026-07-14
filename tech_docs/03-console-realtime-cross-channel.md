# Console 实时显示跨频道对话 — 设计方案

## 1. 问题描述

用户在 Console（Web UI）中看不到企微频道正在进行的实时对话。只有等企微消息处理完毕、持久化后，刷新 Console 才能看到历史消息。

## 2. 根因分析

### 事件流架构（当前）

```
企微消息 → consume_one() → _consume_with_tracker() → TaskTracker.attach_or_start(chat_id)
                                                              ↓
                                                    _stream_with_tracker(payload)
                                                              ↓
                                                    self._process(request) → Event 流
                                                              ↓
                                                    yield f"data: {json}\n\n"  ← SSE 字符串
                                                              ↓
                                                    TaskTracker 广播到所有 queue
```

**关键发现**：
- `_stream_with_tracker` 已经把事件序列化为 `data: {json}\n\n` SSE 格式
- TaskTracker 的 `_producer` 已经把 SSE 字符串广播到所有订阅 queue
- `_consume_with_tracker` 用 `chat.id` 作为 TaskTracker 的 run_key

### Console 的 SSE 重连机制（已有）

```
前端 _emitReconnectEvent(sessionId)
    → CustomEvent("handleReconnect")
    → @agentscope-ai/chat 库监听
    → POST /console/chat { reconnect: true, chat_id: xxx }
    → tracker.attach(chat_id)  ← attach 到已有 run 的 queue
    → SSE 流推送 buffer replay + 新事件
```

### 前端的生成中轮询（已有）

```
_startGeneratingPoll(realId)
    → 每 3 秒 GET /chats/{chat_id}
    → 检查 isGenerating(chatHistory)
    → 完成则加载最终消息
    → 超时 3 分钟自动停止
```

### 断裂点

1. **企微频道确实注册到了 TaskTracker**（通过 `_consume_with_tracker`）
2. **TaskTracker 确实广播 SSE 事件到所有 queue**
3. **Console 的 reconnect 机制确实能 attach 到已有 queue**
4. **但前端没有触发 reconnect** — 因为它不知道有其他频道正在处理消息

## 3. 设计方案

### 核心思路：利用已有基础设施，最小改动

不需要新建 EventBus、SessionBroadcaster 等组件。TaskTracker + reconnect 机制已经就绪，只需要：

1. **后端**：在 `GET /chats` 响应中暴露 `generating` 状态
2. **前端**：session 列表检测 generating 状态，显示 "Live" 标记
3. **前端**：用户点击 generating 的 session 时，触发 reconnect

### 3.1 后端改动（最小）

#### 方案 A：扩展现有 `GET /chats` 响应

在 `chats.py` 的 `list_chats` 响应中，为每个 chat 添加 `generating` 字段：

```python
# chats.py - list_chats endpoint
for chat in chats:
    # 检查 TaskTracker 是否有该 chat 的活跃任务
    is_generating = False
    if manager:
        ws = manager.get_workspace(chat.agent_id or f"user:{username}", username=username)
        if ws and ws.task_tracker:
            is_generating = await ws.task_tracker.get_status(chat.id) == "running"
    
    sessions.append({
        "id": chat.id,
        "name": chat.name,
        "generating": is_generating,  # 新增
        ...
    })
```

#### 方案 B：新增 `/console/active-tasks` 端点（可选）

```python
@router.get("/console/active-tasks")
async def get_active_tasks(request: Request):
    """返回所有正在生成的 chat_id 列表"""
    manager = request.app.state.multi_agent_manager
    username = getattr(request.state, "username", "anonymous")
    
    active = []
    # 遍历所有 workspace，收集活跃任务
    for agent_id, ws in manager.get_all_workspaces(username=username).items():
        if ws.task_tracker:
            tasks = await ws.task_tracker.list_active_tasks()
            for chat_id in tasks:
                active.append({"chat_id": chat_id, "agent_id": agent_id})
    
    return {"active_tasks": active}
```

### 3.2 前端改动

#### 3.2.1 Session 列表显示 "Live" 标记

在 `getSessionList()` 中，利用 `generating` 字段：

```typescript
// sessionApi/index.ts - getSessionList()
const chats = await api.listChats(params);

const newList = chats.map(chat => ({
    id: chat.id,
    name: chat.name,
    generating: chat.generating ?? false,  // 新增
    ...
}));

// 为 generating 的 session 触发 reconnect
for (const session of newList) {
    if (session.generating && session.realId) {
        this._startGeneratingPoll(session.realId);
    }
}
```

#### 3.2.2 Session 列表项显示 "Live" 指示器

```tsx
// ChatSessionItem/index.tsx
{session.generating && (
    <span className={styles.liveIndicator}>
        <span className={styles.liveDot} /> Live
    </span>
)}
```

#### 3.2.3 点击 generating session 时触发 reconnect

在 `ChatSessionInitializer` 或 session 切换逻辑中：

```typescript
// 当用户切换到一个 generating 的 session
if (session.generating && session.realId) {
    this._emitReconnectEvent(session.realId);
}
```

### 3.3 数据流（改造后）

```
企微用户发消息
    → 企微频道 consume_one()
    → _consume_with_tracker(chat_id)
    → TaskTracker 注册 run (chat_id)
    → _stream_with_tracker 产出 SSE 事件
    → TaskTracker 广播到所有 queue

Console 用户查看 session 列表
    → GET /chats → 发现 generating=true 的 session
    → 显示 "Live" 标记

Console 用户点击该 session
    → _emitReconnectEvent(chat_id)
    → POST /console/chat { reconnect: true, chat_id }
    → tracker.attach(chat_id) → 获取 buffer replay + 新事件
    → SSE 流 → 前端实时渲染
```

## 4. 改动范围

| 文件 | 改动 | 难度 |
|------|------|------|
| `server/.../routers/chats.py` | `list_chats` 响应添加 `generating` 字段 | 低 |
| `client/.../sessionApi/index.ts` | `getSessionList` 读取 `generating` 字段，触发 poll | 低 |
| `client/.../ChatSessionItem/index.tsx` | 显示 "Live" 指示器 | 低 |
| `client/.../ChatSessionInitializer/index.tsx` | 切换到 generating session 时触发 reconnect | 低 |

**总计改动：约 4 个文件，~50 行代码。**

## 5. 验证方案

1. 在企微发一条消息（触发 agent 处理）
2. 立刻打开 Console 的 session 列表
3. 应该看到对应的 session 有 "Live" 标记
4. 点击该 session，应该实时看到 thinking、工具调用、文本回复
5. 企微消息处理完毕后，"Live" 标记消失，Console 显示完整历史

## 6. 风险与限制

- **首次加载延迟**：用户必须在 session 列表中看到 "Live" 标记并点击才能实时查看。不会自动跳转。
- **buffer 大小**：TaskTracker 的 buffer 是无限的（list append），长时间运行的任务可能占用较多内存。
- **SSE 格式兼容**：`_stream_with_tracker` 的 SSE 格式与 `ConsoleChannel.stream_one` 的格式一致（都是 `model_dump_json`），前端可以正确解析。
- **不需要改 runner/base.py**：已有的 `_consume_with_tracker` + TaskTracker 机制完全满足需求。

## 7. 后续优化（可选）

- **自动跳转**：当检测到新的 generating session 时，弹出通知让用户选择是否跳转
- **后台静默订阅**：即使用户不在该 session 页面，也在后台缓存事件，切换时即时显示
- **active-tasks 端点**：新增独立端点，避免每次 list_chats 都遍历 TaskTracker
