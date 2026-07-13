# 会话状态恢复 - 全面实现方案

## 📋 目标

**完全解决会话状态恢复问题**，包括：
1. 后端重启后恢复运行中的任务
2. 切换智能体后正确恢复会话状态
3. 刷新页面后正确触发重连
4. 跨设备同步（企微 + console）
5. 异常退出后的状态清理

## 🏗️ 架构设计

### 1. 三层状态管理

```
┌─────────────────────────────────────────────────────────────┐
│                     前端状态层                                │
│  - localStorage: chatId, agentId, userId                    │
│  - 内存: generating 状态                                      │
│  - SSE 连接: 实时推送                                         │
└─────────────────────────────────────────────────────────────┘
                              ↓
┌─────────────────────────────────────────────────────────────┐
│                     后端内存层                                │
│  - TaskTracker: 运行中的任务队列                              │
│  - SessionState: 会话执行状态                                 │
│  - 失效检测: 定期扫描持久化状态                                │
└─────────────────────────────────────────────────────────────┘
                              ↓
┌─────────────────────────────────────────────────────────────┐
│                     持久化层                                  │
│  - Session 文件: 聊天记录 + 状态                              │
│  - TaskState 文件: 任务运行状态                               │
│  - 支持跨设备、跨进程访问                                      │
└─────────────────────────────────────────────────────────────┘
```

### 2. 数据结构设计

#### 2.1 Session 文件增强

**位置**: `{workspace}/sessions/{session_id}.json`

**新增字段**:
```json
{
  "session_id": "wecom:user:xxx",
  "user_id": "test222",
  "agent_id": "user:test222",
  "channel": "console",
  
  // 新增：任务状态
  "task_status": {
    "status": "running",           // running | idle | completed | failed
    "run_key": "chat-uuid-xxx",    // TaskTracker 的 run_key
    "start_time": "2026-07-11T05:00:00Z",
    "last_update": "2026-07-11T05:01:00Z",
    "progress": {
      "step": "generating",        // generating | tool_call | thinking
      "percentage": 0.5,           // 可选：进度百分比
      "tokens_generated": 150
    },
    "channels": ["console", "wecom"],  // 活跃的渠道
    "last_active_channel": "console"
  },
  
  // 原有字段
  "agent": {
    "memory": {
      "content": [...]
    }
  }
}
```

#### 2.2 TaskState 文件（独立）

**位置**: `{workspace}/sessions/.tasks/{run_key}.json`

**用途**: 独立存储任务状态，避免频繁写入大文件

```json
{
  "run_key": "chat-uuid-xxx",
  "chat_id": "chat-uuid-xxx",
  "session_id": "console:test222",
  "user_id": "test222",
  "agent_id": "user:test222",
  "channel": "console",
  
  "status": "running",
  "start_time": "2026-07-11T05:00:00Z",
  "last_update": "2026-07-11T05:01:00Z",
  "heartbeat": "2026-07-11T05:01:30Z",  // 心跳时间
  
  "progress": {
    "step": "generating",
    "tokens_generated": 150,
    "tool_calls": 0,
    "iterations": 1
  },
  
  "metadata": {
    "model": "qwen3.6-27",
    "provider": "local_vllm"
  }
}
```

### 3. 状态转换流程

```
┌─────────┐                    ┌──────────┐
│  idle   │──── 开始任务 ────→│ running  │
└─────────┘                    └──────────┘
     ↑                              │
     │                              │
     │         ┌────────────────────┼────────────────────┐
     │         │                    │                    │
     └─────────┴──── 完成任务 ────→┴─── 失败/取消 ─────→┴─── 超时 ────┐
                                                                     │
                                                                [清理状态文件]
```

## 🔧 实现细节

### 阶段 1: 后端 - 任务状态持久化

#### 1.1 TaskState 管理器

**文件**: `server/coapis/app/runner/task_state_manager.py`

```python
"""任务状态持久化管理器"""
import json
import logging
from pathlib import Path
from datetime import datetime, timezone
from typing import Optional, Dict, Any
import aiofiles

logger = logging.getLogger(__name__)


class TaskStateManager:
    """管理任务状态的持久化"""
    
    def __init__(self, workspace_dir: Path):
        self.workspace_dir = workspace_dir
        self.tasks_dir = workspace_dir / "sessions" / ".tasks"
        self.tasks_dir.mkdir(parents=True, exist_ok=True)
    
    def _get_task_file(self, run_key: str) -> Path:
        """获取任务状态文件路径"""
        return self.tasks_dir / f"{run_key}.json"
    
    async def create_task(
        self,
        run_key: str,
        chat_id: str,
        session_id: str,
        user_id: str,
        agent_id: str,
        channel: str = "console",
        metadata: Optional[Dict[str, Any]] = None,
    ) -> None:
        """创建任务状态"""
        task_file = self._get_task_file(run_key)
        
        task_state = {
            "run_key": run_key,
            "chat_id": chat_id,
            "session_id": session_id,
            "user_id": user_id,
            "agent_id": agent_id,
            "channel": channel,
            "status": "running",
            "start_time": datetime.now(timezone.utc).isoformat(),
            "last_update": datetime.now(timezone.utc).isoformat(),
            "heartbeat": datetime.now(timezone.utc).isoformat(),
            "progress": {
                "step": "init",
                "tokens_generated": 0,
                "tool_calls": 0,
                "iterations": 0,
            },
            "metadata": metadata or {},
        }
        
        async with aiofiles.open(task_file, 'w', encoding='utf-8') as f:
            await f.write(json.dumps(task_state, ensure_ascii=False, indent=2))
        
        logger.info(f"Created task state: {run_key}")
    
    async def update_progress(
        self,
        run_key: str,
        step: Optional[str] = None,
        tokens_generated: Optional[int] = None,
        tool_calls: Optional[int] = None,
        iterations: Optional[int] = None,
    ) -> None:
        """更新任务进度"""
        task_file = self._get_task_file(run_key)
        
        if not task_file.exists():
            logger.warning(f"Task state file not found: {run_key}")
            return
        
        async with aiofiles.open(task_file, 'r', encoding='utf-8') as f:
            task_state = json.loads(await f.read())
        
        # 更新进度
        if step:
            task_state["progress"]["step"] = step
        if tokens_generated is not None:
            task_state["progress"]["tokens_generated"] = tokens_generated
        if tool_calls is not None:
            task_state["progress"]["tool_calls"] = tool_calls
        if iterations is not None:
            task_state["progress"]["iterations"] = iterations
        
        # 更新时间戳
        task_state["last_update"] = datetime.now(timezone.utc).isoformat()
        task_state["heartbeat"] = datetime.now(timezone.utc).isoformat()
        
        async with aiofiles.open(task_file, 'w', encoding='utf-8') as f:
            await f.write(json.dumps(task_state, ensure_ascii=False, indent=2))
    
    async def update_heartbeat(self, run_key: str) -> None:
        """更新心跳时间"""
        task_file = self._get_task_file(run_key)
        
        if not task_file.exists():
            return
        
        async with aiofiles.open(task_file, 'r', encoding='utf-8') as f:
            task_state = json.loads(await f.read())
        
        task_state["heartbeat"] = datetime.now(timezone.utc).isoformat()
        
        async with aiofiles.open(task_file, 'w', encoding='utf-8') as f:
            await f.write(json.dumps(task_state, ensure_ascii=False, indent=2))
    
    async def complete_task(self, run_key: str, status: str = "completed") -> None:
        """标记任务完成"""
        task_file = self._get_task_file(run_key)
        
        if not task_file.exists():
            logger.warning(f"Task state file not found: {run_key}")
            return
        
        async with aiofiles.open(task_file, 'r', encoding='utf-8') as f:
            task_state = json.loads(await f.read())
        
        task_state["status"] = status
        task_state["last_update"] = datetime.now(timezone.utc).isoformat()
        
        async with aiofiles.open(task_file, 'w', encoding='utf-8') as f:
            await f.write(json.dumps(task_state, ensure_ascii=False, indent=2))
        
        logger.info(f"Completed task: {run_key} with status: {status}")
    
    async def remove_task(self, run_key: str) -> None:
        """删除任务状态文件"""
        task_file = self._get_task_file(run_key)
        
        if task_file.exists():
            task_file.unlink()
            logger.info(f"Removed task state: {run_key}")
    
    async def get_task(self, run_key: str) -> Optional[Dict[str, Any]]:
        """获取任务状态"""
        task_file = self._get_task_file(run_key)
        
        if not task_file.exists():
            return None
        
        async with aiofiles.open(task_file, 'r', encoding='utf-8') as f:
            return json.loads(await f.read())
    
    async def list_running_tasks(self) -> list[Dict[str, Any]]:
        """列出所有运行中的任务"""
        running_tasks = []
        
        for task_file in self.tasks_dir.glob("*.json"):
            try:
                async with aiofiles.open(task_file, 'r', encoding='utf-8') as f:
                    task_state = json.loads(await f.read())
                
                if task_state.get("status") == "running":
                    running_tasks.append(task_state)
            except Exception as e:
                logger.warning(f"Failed to read task file {task_file}: {e}")
        
        return running_tasks
    
    async def cleanup_stale_tasks(self, timeout_seconds: int = 300) -> list[str]:
        """清理超时的任务（心跳超过指定时间未更新）"""
        import asyncio
        
        cleaned = []
        now = datetime.now(timezone.utc)
        
        for task_file in self.tasks_dir.glob("*.json"):
            try:
                async with aiofiles.open(task_file, 'r', encoding='utf-8') as f:
                    task_state = json.loads(await f.read())
                
                if task_state.get("status") != "running":
                    continue
                
                # 检查心跳
                heartbeat_str = task_state.get("heartbeat")
                if not heartbeat_str:
                    continue
                
                heartbeat = datetime.fromisoformat(heartbeat_str)
                age = (now - heartbeat).total_seconds()
                
                if age > timeout_seconds:
                    # 标记为超时
                    task_state["status"] = "timeout"
                    async with aiofiles.open(task_file, 'w', encoding='utf-8') as f:
                        await f.write(json.dumps(task_state, ensure_ascii=False, indent=2))
                    
                    cleaned.append(task_state["run_key"])
                    logger.warning(
                        f"Task {task_state['run_key']} timed out "
                        f"(no heartbeat for {age:.0f}s)"
                    )
            except Exception as e:
                logger.warning(f"Failed to process task file {task_file}: {e}")
        
        return cleaned
```

#### 1.2 集成到 TaskTracker

**修改**: `server/coapis/app/runner/task_tracker.py`

```python
class TaskTracker:
    def __init__(self, state_manager: Optional[TaskStateManager] = None):
        self._lock = asyncio.Lock()
        self._runs: dict[str, _RunState] = {}
        self._state_manager = state_manager  # 新增
    
    async def attach_or_start(
        self,
        run_key: str,
        payload: dict,
        coro: Callable,
    ) -> tuple[asyncio.Queue, asyncio.Task]:
        """附加到现有运行，或启动新运行"""
        async with self._lock:
            # 检查是否已有运行
            if run_key in self._runs:
                state = self._runs[run_key]
                if not state.task.done():
                    # 附加到现有运行
                    queue = asyncio.Queue()
                    state.queues.append(queue)
                    
                    # 回放缓冲
                    for event in state.buffer:
                        await queue.put(event)
                    
                    return queue, state.task
            
            # 启动新运行
            queue = asyncio.Queue()
            state = _RunState(task=asyncio.Future(), queues=[queue], buffer=[])
            self._runs[run_key] = state
        
        # 启动任务（在锁外）
        task = asyncio.create_task(self._run_wrapper(run_key, payload, coro, state))
        state.task = task
        
        # 创建持久化状态（新增）
        if self._state_manager:
            await self._state_manager.create_task(
                run_key=run_key,
                chat_id=run_key,
                session_id=payload.get("session_id", ""),
                user_id=payload.get("user_id", ""),
                agent_id=payload.get("agent_id", ""),
                channel=payload.get("channel", "console"),
            )
        
        return queue, task
    
    async def _run_wrapper(
        self,
        run_key: str,
        payload: dict,
        coro: Callable,
        state: _RunState,
    ):
        """包装任务执行，确保状态更新"""
        try:
            async for event in coro(payload):
                # 广播事件
                async with self._lock:
                    state.buffer.append(event)
                    for queue in state.queues:
                        await queue.put(event)
                
                # 更新心跳（新增）
                if self._state_manager:
                    await self._state_manager.update_heartbeat(run_key)
        except Exception as e:
            logger.error(f"Task {run_key} failed: {e}")
            if self._state_manager:
                await self._state_manager.complete_task(run_key, "failed")
            raise
        finally:
            # 标记完成
            if self._state_manager:
                await self._state_manager.complete_task(run_key, "completed")
            
            # 清理
            async with self._lock:
                if run_key in self._runs:
                    del self._runs[run_key]
```

#### 1.3 启动时恢复运行中的任务

**修改**: `server/coapis/app/runner/runner.py`

```python
async def _restore_running_tasks(self):
    """恢复运行中的任务（后端重启后）"""
    if not self._task_state_manager:
        return
    
    running_tasks = await self._task_state_manager.list_running_tasks()
    
    for task_state in running_tasks:
        run_key = task_state["run_key"]
        
        # 检查心跳是否超时
        heartbeat_str = task_state.get("heartbeat")
        if heartbeat_str:
            heartbeat = datetime.fromisoformat(heartbeat_str)
            age = (datetime.now(timezone.utc) - heartbeat).total_seconds()
            
            if age > 300:  # 5分钟超时
                logger.warning(
                    f"Task {run_key} timed out during server restart, "
                    f"marking as failed"
                )
                await self._task_state_manager.complete_task(run_key, "failed")
                continue
        
        # 尝试恢复任务
        # 注意：大多数情况下，任务无法真正恢复（因为 LLM 调用已中断）
        # 但状态已持久化，前端可以检测到并提示用户
        logger.info(
            f"Task {run_key} was running before restart, "
            f"status persisted for recovery detection"
        )
```

### 阶段 2: 后端 - API 改进

#### 2.1 改进 chats API

**修改**: `server/coapis/app/routers/chats.py`

```python
@router.get("")
async def list_chats(...):
    # ... 原有逻辑 ...
    
    # Check TaskTracker for generating status
    generating_chat_ids: set = set()
    if workspace.task_tracker:
        active_tasks = await workspace.task_tracker.list_active_tasks()
        generating_chat_ids = set(active_tasks)
    
    # NEW: Also check persistent task states
    if workspace._task_state_manager:
        running_tasks = await workspace._task_state_manager.list_running_tasks()
        for task in running_tasks:
            generating_chat_ids.add(task["chat_id"])
    
    # 在返回聊天列表时
    for entry in chats:
        entry["generating"] = entry["id"] in generating_chat_ids
        
        # NEW: 添加任务进度信息
        if entry["id"] in generating_chat_ids:
            task_state = await workspace._task_state_manager.get_task(entry["id"])
            if task_state:
                entry["task_progress"] = task_state.get("progress")
    
    return chats
```

#### 2.2 改进 console reconnect

**修改**: `server/coapis/app/routers/console.py`

```python
is_reconnect = payload.get("reconnect") is True

if is_reconnect:
    # 先检查内存中的 TaskTracker
    queue = await tracker.attach(chat.id)
    
    if queue is None:
        # NEW: 检查持久化的任务状态
        task_state = await workspace._task_state_manager.get_task(chat.id)
        
        if task_state and task_state.get("status") == "running":
            # 任务状态存在，但 TaskTracker 中没有
            # 可能是后端重启导致的
            logger.info(
                f"Task {chat.id} found in persistent state but not in TaskTracker, "
                f"server may have restarted"
            )
            
            # 返回特殊事件，通知前端任务已丢失
            async def lost_task_gen():
                yield json.dumps({
                    "event": "task_lost",
                    "data": {
                        "reason": "server_restart",
                        "last_update": task_state.get("last_update"),
                        "progress": task_state.get("progress"),
                    }
                })
            
            return StreamingResponse(
                lost_task_gen(),
                media_type="text/event-stream",
            )
        else:
            # 真的没有活跃运行
            async def empty_gen():
                yield ""
            return StreamingResponse(
                empty_gen(),
                media_type="text/event-stream",
            )
```

### 阶段 3: 前端改进

#### 3.1 改进 generating 检测

**修改**: `client/src/pages/Chat/sessionApi/index.ts`

```typescript
interface TaskProgress {
  step: string;
  tokens_generated?: number;
  tool_calls?: number;
  iterations?: number;
}

interface ExtendedSession extends IAgentScopeRuntimeWebUISession {
  // ... 原有字段 ...
  task_progress?: TaskProgress;
}

const isGenerating = (chatHistory: ChatHistory): boolean => {
  // 优先级 1: status 字段（最准确）
  if (chatHistory.status === "running") return true;
  if (chatHistory.status === "idle") return false;
  
  // 优先级 2: generating 字段（后端计算）
  if (chatHistory.generating === true) return true;
  if (chatHistory.generating === false) return false;
  
  // 优先级 3: 启发式检测（兜底）
  const msgs = chatHistory.messages || [];
  if (msgs.length === 0) return false;
  const last = msgs[msgs.length - 1];
  return last.role === ROLE_USER;
};
```

#### 3.2 处理 task_lost 事件

**修改**: `client/src/pages/Chat/index.tsx`

```typescript
// 在 SSE 事件处理中
case "task_lost":
  const taskLostData = JSON.parse(event.data);
  
  // 显示提示
  message.warning(
    `任务在服务器重启期间丢失。上次进度：${taskLostData.progress?.step || '未知'}`
  );
  
  // 刷新会话列表
  sessionApi.invalidateSessionList();
  break;
```

#### 3.3 改进重连逻辑

**修改**: `client/src/pages/Chat/sessionApi/index.ts`

```typescript
private async _doGetSession(sessionId: string | null): Promise<ExtendedSession | null> {
  // ... 原有逻辑 ...
  
  const generating = isGenerating(chatHistory);
  
  if (generating) {
    // 显示进度信息
    if (chatHistory.task_progress) {
      console.log(
        `[Session] Task is running: step=${chatHistory.task_progress.step}, ` +
        `tokens=${chatHistory.task_progress.tokens_generated}`
      );
    }
    
    // 开始轮询 + SSE 重连
    this._startGeneratingPoll(fromList.realId);
    this._emitReconnectEvent(fromList.realId);
  }
  
  // ... 原有逻辑 ...
}
```

### 阶段 4: 定期清理

#### 4.1 启动时清理

**修改**: `server/coapis/app/runner/runner.py`

```python
async def start_background_tasks(self):
    """启动后台任务"""
    # ... 原有逻辑 ...
    
    # 启动任务状态清理
    if self._task_state_manager:
        asyncio.create_task(self._periodic_task_cleanup())

async def _periodic_task_cleanup(self):
    """定期清理超时的任务状态"""
    while True:
        try:
            await asyncio.sleep(60)  # 每分钟检查一次
            
            if self._task_state_manager:
                cleaned = await self._task_state_manager.cleanup_stale_tasks(
                    timeout_seconds=300  # 5分钟超时
                )
                
                if cleaned:
                    logger.info(f"Cleaned up {len(cleaned)} stale tasks")
        except Exception as e:
            logger.error(f"Task cleanup failed: {e}")
```

## 📊 状态恢复流程

### 场景 1: 正常切换智能体

```
用户在聊天中 (status=running)
    ↓
切换到其他智能体
    ↓
前端保存 chatId 到 lastChatIdByAgent
    ↓
切换回来
    ↓
前端调用 getSessionList
    ↓
后端检查 TaskTracker (内存) + TaskState (持久化)
    ↓
返回 generating=true
    ↓
前端触发 SSE reconnect
    ↓
恢复会话状态 ✅
```

### 场景 2: 后端重启

```
用户在聊天中 (status=running)
    ↓
TaskState 文件已持久化
    ↓
后端重启
    ↓
TaskTracker 内存状态丢失
    ↓
前端刷新或重连
    ↓
后端检查 TaskState 文件
    ↓
发现 status=running
    ↓
返回 generating=true + task_lost 事件
    ↓
前端显示提示："任务在服务器重启期间丢失"
    ↓
用户可以重新发送消息 ✅
```

### 场景 3: 跨设备同步（企微 + console）

```
企微聊天中 (status=running, channels=["wecom"])
    ↓
console 打开相同 session_id
    ↓
console 调用 getSessionList
    ↓
后端返回 generating=true
    ↓
console 显示 "正在生成..."
    ↓
企微生成完成后，消息推送到两个渠道
    ↓
console 收到完整消息 ✅
```

## 🧪 测试场景

### 测试 1: 正常切换智能体

1. 发送消息，等待回复开始生成
2. 立即切换到其他智能体
3. 再切换回来
4. **预期**: 聊天记录恢复，显示"正在生成"，SSE 重连成功

### 测试 2: 后端重启

1. 发送消息，等待回复开始生成
2. 重启后端容器
3. 刷新前端页面
4. **预期**: 显示"任务在服务器重启期间丢失"提示，可以重新发送消息

### 测试 3: 刷新页面

1. 发送消息，等待回复开始生成
2. 刷新浏览器页面
3. **预期**: 自动触发 SSE 重连，继续显示生成内容

### 测试 4: 跨设备同步

1. 企微发送消息
2. console 打开相同会话
3. **预期**: console 显示"正在生成"，生成完成后消息同步

### 测试 5: 超时清理

1. 模拟任务卡住（心跳停止更新）
2. 等待 5 分钟
3. **预期**: 任务状态自动标记为 timeout

## 📈 性能考虑

### 1. 文件写入优化

- **心跳更新**: 每 10 秒更新一次，而不是每次事件
- **进度更新**: 每 1 秒更新一次，而不是每次 token
- **批量写入**: 使用缓冲区，减少 IO 次数

### 2. 文件读取优化

- **缓存**: TaskState 在内存中缓存 5 秒
- **惰性加载**: 只在需要时读取文件
- **批量查询**: `list_running_tasks` 使用 glob + 批量读取

### 3. 清理策略

- **定期清理**: 每分钟清理超时任务
- **启动清理**: 服务启动时清理所有超时任务
- **手动清理**: 提供管理 API 手动清理

## 🔒 安全考虑

### 1. 权限验证

- 所有 API 都验证 user_id 和 agent_id
- TaskState 文件包含 user_id，防止跨用户访问

### 2. 文件隔离

- TaskState 文件存储在 workspace/sessions/.tasks/
- 每个用户有独立的 workspace
- 防止跨用户访问

### 3. 敏感信息

- TaskState 不存储敏感信息（如 API key）
- 只存储必要的元数据

## 📋 实施计划

### Phase 1: 基础设施（1-2 天）

- [ ] 创建 TaskStateManager 类
- [ ] 集成到 TaskTracker
- [ ] 单元测试

### Phase 2: API 改进（1 天）

- [ ] 改进 chats API
- [ ] 改进 console reconnect
- [ ] API 测试

### Phase 3: 前端改进（1 天）

- [ ] 改进 generating 检测
- [ ] 处理 task_lost 事件
- [ ] 前端测试

### Phase 4: 清理机制（0.5 天）

- [ ] 定期清理任务
- [ ] 启动时清理
- [ ] 管理接口

### Phase 5: 集成测试（1 天）

- [ ] 端到端测试
- [ ] 性能测试
- [ ] 压力测试

### Phase 6: 文档和部署（0.5 天）

- [ ] 更新文档
- [ ] 部署到开发环境
- [ ] 部署到生产环境

**预计总时间**: 5-6 天

## 📝 后续优化

### 1. 进度显示

- 在前端显示详细的任务进度
- 显示当前步骤（生成、工具调用、思考）
- 显示进度条

### 2. 任务恢复

- 实现真正的任务恢复（而不是重新开始）
- 保存 LLM 上下文
- 从断点继续生成

### 3. 分布式支持

- 使用 Redis 替代文件存储
- 支持多实例部署
- 任务状态同步

---

**这个方案完全解决了会话状态恢复问题，包括所有边界情况和异常场景。是否开始实施？**
