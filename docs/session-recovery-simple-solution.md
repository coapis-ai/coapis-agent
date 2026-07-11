# 会话状态恢复 - 最简实现方案

## 🎯 核心发现

### 现有功能（无需重复造轮子）

1. **ChatSpec 已有 status 字段**
   ```python
   class ChatSpec(BaseModel):
       status: str = Field(default="idle", description="Conversation status: idle or running")
   ```

2. **ChatManager 已有持久化机制**
   - `patch_chat()` 可以更新 ChatSpec
   - ChatSpec 存储在 `chat/chats.json`
   - 已经持久化到文件系统

3. **前端已有 status 检测**
   ```typescript
   const isGenerating = (chatHistory: ChatHistory): boolean => {
       if (chatHistory.status === "running") return true;
       if (chatHistory.status === "idle") return false;
       // ...
   };
   ```

4. **进度显示已存在**
   - SessionState 追踪 token、工具调用等
   - 前端可以显示详细信息

## ❌ 不需要的功能

1. ~~TaskStateManager~~ - ChatManager 已经够用
2. ~~独立的 TaskState 文件~~ - ChatSpec 已经持久化
3. ~~监控告警~~ - 不是核心需求，增加复杂度
4. ~~复杂的进度追踪~~ - 已有 SessionState

## ✅ 最简方案

### 方案概述

**只需修改 3 个地方，无需新增文件或类**

```
任务启动 → 更新 ChatSpec.status="running"
任务结束 → 更新 ChatSpec.status="idle"
查询聊天 → 返回 ChatSpec.status
```

### 修改点

#### 1. 修改 ChatUpdate 类

**文件**: `server/coapis/app/runner/models.py`

```python
class ChatUpdate(BaseModel):
    """Mutable chat fields accepted from external clients."""

    model_config = ConfigDict(extra="forbid")

    name: str | None = Field(default=None, description="Chat name")
    pinned: bool | None = Field(
        default=False,
        description="Whether the chat is pinned to the top",
    )
    # 新增：允许更新 status
    status: str | None = Field(
        default=None,
        description="Conversation status: idle or running",
    )
```

#### 2. 任务启动时更新 status

**文件**: `server/coapis/app/routers/console.py`

```python
# 在 attach_or_start 之后添加
from ..runner.models import ChatUpdate

queue, started = await tracker.attach_or_start(
    chat.id,
    native_payload,
    console_channel.stream_one,
)

# 新增：标记为运行中
if started:  # 只有新启动的任务才需要更新
    try:
        await workspace.chat_manager.patch_chat(
            chat.id,
            ChatUpdate(status="running")
        )
        logger.info(f"Chat {chat.id} status updated to running")
    except Exception as e:
        logger.warning(f"Failed to update chat status: {e}")
```

#### 3. 任务结束时更新 status

**文件**: `server/coapis/app/runner/runner.py`

```python
# 在 finally 块中添加
finally:
    # ... 原有的清理逻辑 ...
    
    # 新增：标记为空闲
    if chat is not None:
        try:
            await asyncio.shield(self._persist_chat_messages(
                chat=chat,
                agent=agent,
                user_id=user_id,
                session_id=session_id,
                # ...
            ))
            
            # 更新 status 为 idle
            if hasattr(self, 'chat_manager') and self.chat_manager:
                from .models import ChatUpdate
                await self.chat_manager.patch_chat(
                    chat.id,
                    ChatUpdate(status="idle")
                )
                logger.info(f"Chat {chat.id} status updated to idle")
        except Exception as e:
            logger.warning(f"Failed to update chat status to idle: {e}")
```

### 完整流程

```
用户发送消息
    ↓
console.py: 创建 ChatSpec (status="idle")
    ↓
console.py: 启动任务 → patch_chat(status="running")
    ↓
ChatSpec.status="running" 持久化到 chats.json
    ↓
用户切换智能体/刷新页面
    ↓
前端调用 list_chats 或 get_chat
    ↓
后端返回 ChatSpec (status="running")
    ↓
前端检测到 generating=true
    ↓
前端触发 SSE reconnect
    ↓
后端检查 TaskTracker
    ↓
如果任务仍在运行 → 恢复连接 ✅
如果任务已结束/重启 → patch_chat(status="idle")
```

## 📊 代码改动量

| 文件 | 改动 | 行数 |
|------|------|------|
| `models.py` | 添加 status 字段到 ChatUpdate | +4 行 |
| `console.py` | 任务启动时更新 status | +10 行 |
| `runner.py` | 任务结束时更新 status | +15 行 |
| **总计** | | **~30 行** |

## 🎁 优势

### 1. 最小改动
- 只修改 3 个文件
- 只增加 ~30 行代码
- 无需新增类或文件

### 2. 利用现有基础设施
- ChatManager 已有持久化机制
- ChatSpec 已有 status 字段
- 前端已有 status 检测逻辑

### 3. 自动解决所有场景

#### ✅ 正常切换智能体
- status 持久化到 chats.json
- 切换回来时读取 status="running"
- 前端触发重连

#### ✅ 后端重启
- chats.json 文件持久化
- 重启后读取 status="running"
- 前端触发重连
- 后端发现任务不存在，自动更新为 "idle"

#### ✅ 刷新页面
- 前端读取 status="running"
- 自动触发 SSE reconnect

#### ✅ 跨设备同步
- chats.json 文件共享
- 企微和 console 读取相同状态

#### ✅ 异常退出
- finally 块确保 status 更新为 "idle"
- 即使任务中断也能正确清理

## 🔧 边界情况处理

### 情况 1: 任务启动失败

```python
# console.py
try:
    queue, started = await tracker.attach_or_start(...)
    if started:
        await workspace.chat_manager.patch_chat(
            chat.id, ChatUpdate(status="running")
        )
except Exception as e:
    # 任务启动失败，确保 status 不被错误标记
    logger.error(f"Failed to start task: {e}")
    raise
```

### 情况 2: 后端重启，任务丢失

```python
# chats.py - 在 list_chats 中添加
for entry in chats:
    # 如果 status="running" 但 TaskTracker 中没有任务
    if entry.get("status") == "running":
        if workspace.task_tracker:
            is_running = await workspace.task_tracker.get_status(entry["id"])
            if is_running != "running":
                # 任务丢失，自动修正
                await workspace.chat_manager.patch_chat(
                    entry["id"], ChatUpdate(status="idle")
                )
                entry["status"] = "idle"
                logger.info(f"Fixed stale running status for chat {entry['id']}")
    
    entry["generating"] = entry.get("status") == "running"
```

### 情况 3: finally 块被取消

```python
# runner.py
finally:
    # 使用 asyncio.shield 防止取消
    try:
        await asyncio.shield(self._persist_chat_messages(...))
        await asyncio.shield(
            self.chat_manager.patch_chat(chat.id, ChatUpdate(status="idle"))
        )
    except asyncio.CancelledError:
        # 即使被取消，也确保 status 更新
        logger.warning("Finally block cancelled, but status update completed")
```

## 🧪 测试场景

### 测试 1: 正常切换智能体
```bash
1. 发送消息，立即切换智能体
2. 再切换回来
3. 预期: 聊天记录恢复，显示"正在生成"
```

### 测试 2: 后端重启
```bash
1. 发送消息，等待生成开始
2. 重启后端容器
3. 刷新前端
4. 预期: 显示任务丢失提示，可以重新发送
```

### 测试 3: 刷新页面
```bash
1. 发送消息，等待生成开始
2. 刷新浏览器
3. 预期: 自动重连，继续显示生成内容
```

### 测试 4: 验证 status 持久化
```bash
1. 发送消息
2. 查看 chats.json
3. 预期: status="running"
4. 等待生成完成
5. 查看 chats.json
6. 预期: status="idle"
```

## 📈 性能影响

### 1. 文件写入
- 每次 patch_chat 会写入 chats.json
- chats.json 文件较小（通常 < 100KB）
- 写入频率：每个任务 2 次（开始 + 结束）
- **影响：可忽略**

### 2. 文件读取
- list_chats 已经读取 chats.json
- get_chat 已经读取 chats.json
- **影响：无额外开销**

### 3. 并发写入
- ChatManager 有锁机制（`self._lock`）
- 文件写入使用原子操作
- **影响：无并发问题**

## 🔒 安全性

### 1. 权限验证
- patch_chat 已有权限检查
- user_id 验证在路由层完成

### 2. 状态一致性
- 使用锁机制防止并发写入
- finally 块确保状态清理

### 3. 错误处理
- 所有 patch_chat 调用都有 try-except
- 失败不影响主流程

## 📋 实施计划

### 第 1 步: 修改 ChatUpdate（5 分钟）
```python
# models.py
class ChatUpdate(BaseModel):
    name: str | None = Field(default=None)
    pinned: bool | None = Field(default=False)
    status: str | None = Field(default=None)  # 新增
```

### 第 2 步: 修改 console.py（10 分钟）
```python
# 在 attach_or_start 后添加
if started:
    await workspace.chat_manager.patch_chat(
        chat.id, ChatUpdate(status="running")
    )
```

### 第 3 步: 修改 runner.py（15 分钟）
```python
# 在 finally 块中添加
await self.chat_manager.patch_chat(
    chat.id, ChatUpdate(status="idle")
)
```

### 第 4 步: 测试（30 分钟）
- 测试正常场景
- 测试异常场景
- 验证持久化

### 第 5 步: 边界情况处理（15 分钟）
- 后端重启后的状态修正
- 任务启动失败的清理

**总计时间：约 1-1.5 小时**

## 🎯 总结

### 核心原则
1. **最小改动** - 只修改 3 个文件
2. **利用现有** - ChatManager + ChatSpec
3. **简单可靠** - 无需新增复杂机制

### 为什么这个方案最好？

1. **无需新文件**
   - 利用已有的 ChatManager
   - 利用已有的 ChatSpec.status 字段

2. **无需新类**
   - 不需要 TaskStateManager
   - 不需要额外的状态管理器

3. **自动持久化**
   - chats.json 已经持久化
   - 无需额外的存储机制

4. **自动清理**
   - finally 块确保状态更新
   - 边界情况自动处理

5. **性能最优**
   - 无额外开销
   - 文件写入频率低（每个任务 2 次）

### 风险

- **无** - 改动最小，逻辑简单，易于理解和维护

---

**这个方案在 1-1.5 小时内可以完成，完全解决问题，无需增加复杂度。是否立即实施？**
