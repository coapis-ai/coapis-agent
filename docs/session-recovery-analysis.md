# 会话状态恢复深度分析

## 问题场景

用户在聊天中（可能正在进行流式响应），此时：
1. 切换智能体
2. 退出登录
3. 关闭浏览器标签页
4. 企业微信聊天中，同时 console 打开对应聊天

期望行为：
- 切换回来或重新登录时，打开正在执行中的会话，能够恢复会话状态

## 当前架构分析

### 1. TaskTracker（内存级）

**位置**: `server/coapis/app/runner/task_tracker.py`

**职责**:
- 管理正在运行的后台任务
- 每个任务有队列和事件缓冲
- 支持重连（reconnect）

**关键方法**:
```python
class TaskTracker:
    async def attach(self, run_key: str) -> asyncio.Queue | None:
        """附加到现有运行，返回队列用于接收事件"""
        
    async def attach_or_start(self, run_key, payload, coro):
        """附加到现有运行，或启动新运行"""
```

**局限性**:
- ❌ 状态只在内存中
- ❌ 后端重启后状态丢失
- ❌ 无法持久化正在运行的任务

### 2. SessionState（内存级）

**位置**: `server/coapis/agents/session_execution/state.py`

**职责**:
- 追踪会话执行状态（迭代次数、token消耗、工具调用历史）
- 用于循环检测、预算控制

**局限性**:
- ❌ 状态只在内存中
- ❌ 不持久化

### 3. Session（持久化级）

**位置**: `server/coapis/app/runner/session.py`

**职责**:
- 保存到文件系统（`sessions/*.json`）
- 包含 agent 的 memory（聊天记录）

**局限性**:
- ✅ 持久化聊天记录
- ❌ 不保存"正在生成"的状态
- ❌ 不保存流式响应的中间状态

### 4. generating 状态检测

**后端** (`server/coapis/app/routers/chats.py`):
```python
# Check TaskTracker for generating status
generating_chat_ids: set = set()
if workspace.task_tracker:
    active_tasks = await workspace.task_tracker.list_active_tasks()
    generating_chat_ids = set(active_tasks)
    
# 在返回聊天列表时
entry["generating"] = entry["id"] in generating_chat_ids
```

**前端** (`client/src/pages/Chat/sessionApi/index.ts`):
```typescript
const isGenerating = (chatHistory: ChatHistory): boolean => {
  if (chatHistory.status === "running") return true;
  if (chatHistory.status === "idle") return false;
  const msgs = chatHistory.messages || [];
  if (msgs.length === 0) return false;
  const last = msgs[msgs.length - 1];
  return last.role === ROLE_USER;  // 最后一条是用户消息 = 正在生成
};
```

### 5. 重连机制

**前端**:
```typescript
// 如果检测到正在生成
if (generating) {
  this._startGeneratingPoll(fromList.realId);  // 开始轮询
  this._emitReconnectEvent(fromList.realId);   // 触发 SSE 重连
}
```

**后端**:
```python
is_reconnect = payload.get("reconnect") is True

if is_reconnect:
    queue = await tracker.attach(chat.id)
    if queue is None:
        # 没有活跃运行 - 返回空流
        return empty_stream()
```

## 问题根因

### 问题 1: TaskTracker 状态不持久化

**影响**:
- 后端重启后，TaskTracker 状态丢失
- 无法知道哪些任务正在运行
- `generating` 状态会变成 false

**场景**:
1. 用户发送消息，后端开始处理（TaskTracker 记录任务）
2. 后端容器重启
3. TaskTracker 状态丢失
4. 用户刷新页面，后端返回 `generating=false`
5. 前端不会触发重连

### 问题 2: generating 状态检测不准确

**前端检测逻辑**:
```typescript
const last = msgs[msgs.length - 1];
return last.role === ROLE_USER;  // 最后一条是用户消息 = 正在生成
```

**问题**:
- 这个假设在以下情况下不成立：
  1. 用户发送消息后立即刷新
  2. 后端还没来得及生成回复
  3. 但 TaskTracker 已经启动了任务
  4. 如果后端重启，TaskTracker 状态丢失
  5. 这个检测就会失败

### 问题 3: 会话状态不完整

**Session 文件只保存**:
- 聊天记录（messages）
- 用户信息
- 元数据

**缺失**:
- 正在生成的状态
- 流式响应的中间状态
- 任务执行进度

## 解决方案

### 方案 1: 持久化 TaskTracker 状态

**实现**:
1. TaskTracker 状态持久化到 Redis 或文件
2. 记录：run_key, task_id, start_time, status
3. 后端重启后恢复状态

**优点**:
- ✅ 准确知道哪些任务正在运行
- ✅ 后端重启后可以恢复

**缺点**:
- ❌ 需要引入 Redis 或额外的持久化层
- ❌ 实现复杂度较高

### 方案 2: 改进 generating 状态检测

**实现**:
1. 后端在 Session 文件中标记 `status: "running"`
2. 任务开始时设置 `status: "running"`
3. 任务结束时设置 `status: "idle"`
4. 前端从 Session 读取 status

**优点**:
- ✅ 简单易实现
- ✅ 状态持久化到文件

**缺点**:
- ❌ 需要确保状态更新的原子性
- ❌ 如果任务异常退出，状态可能不一致

### 方案 3: 双重检测机制

**实现**:
1. **优先级 1**: TaskTracker 内存状态（准确）
2. **优先级 2**: Session 文件中的 status 字段（持久化）
3. **优先级 3**: 前端启发式检测（最后一条消息是用户）

**优点**:
- ✅ 兼顾准确性和持久化
- ✅ 多重保障

**缺点**:
- ❌ 实现复杂度适中

### 方案 4: 流式响应状态持久化（推荐）

**实现**:

1. **任务状态文件**:
```json
{
  "chat_id": "xxx",
  "status": "running",
  "start_time": "2026-07-11T05:00:00Z",
  "last_update": "2026-07-11T05:01:00Z",
  "progress": {
    "step": "generating",
    "tokens_generated": 150
  }
}
```

2. **更新时机**:
   - 任务开始：创建状态文件
   - 任务进行：定期更新进度
   - 任务结束：删除状态文件或标记为完成

3. **恢复流程**:
   - 后端启动时扫描状态文件
   - 发现有 `running` 状态的任务
   - 根据任务类型决定是否恢复

**优点**:
- ✅ 状态持久化，后端重启可恢复
- ✅ 可以保存详细的进度信息
- ✅ 支持跨设备同步

**缺点**:
- ❌ 实现复杂度较高
- ❌ 需要定期更新状态文件

## 推荐方案

**短期方案（快速实现）**:
1. **方案 2 + 方案 3**: 改进 generating 状态检测
   - 在 Session 文件中添加 `status` 字段
   - 任务开始时设置为 `"running"`
   - 任务结束时设置为 `"idle"`
   - 前端使用双重检测机制

**长期方案（完善实现）**:
2. **方案 4**: 流式响应状态持久化
   - 实现任务状态文件
   - 支持详细的进度追踪
   - 支持跨设备同步

## 实现步骤

### 阶段 1: 快速修复（方案 2 + 3）

1. **后端修改**:
   - 在 `runner.py` 中，任务开始时更新 Session status
   - 在任务结束时更新 Session status
   - 在 `chats.py` 中，从 Session 读取 status

2. **前端修改**:
   - 改进 `isGenerating` 函数，优先使用 `status` 字段
   - 添加多重检测逻辑

### 阶段 2: 完善实现（方案 4）

1. **设计任务状态文件格式**
2. **实现状态更新机制**
3. **实现恢复机制**
4. **添加前端进度显示**

## 企业微信场景的特殊处理

**场景**:
- 用户在企业微信聊天中
- 同时在 console 打开了对应聊天
- 需要恢复聊天状态

**关键点**:
1. **session_id 一致性**:
   - 企微和 console 使用相同的 session_id
   - 确保消息同步

2. **跨设备状态同步**:
   - 使用持久化的状态（文件或数据库）
   - 不依赖内存状态

3. **消息推送**:
   - 企微和 console 都能接收推送
   - 使用相同的 push-messages 机制

**实现**:
```python
# 在 Session 文件中添加
{
  "session_id": "wecom:user:xxx",
  "status": "running",
  "channels": ["wecom", "console"],  # 活跃的渠道
  "last_active_channel": "wecom"
}
```

## 总结

**当前问题**:
1. TaskTracker 状态不持久化
2. generating 状态检测不准确
3. 会话状态不完整

**推荐方案**:
1. 短期：改进 generating 状态检测（方案 2 + 3）
2. 长期：流式响应状态持久化（方案 4）

**关键原则**:
- 状态应该持久化，不依赖内存
- 多重检测机制，提高鲁棒性
- 支持跨设备同步
