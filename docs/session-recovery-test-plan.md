# 会话状态恢复 - 测试计划

## 已完成的修改

### 1. models.py
- ✅ 在 `ChatUpdate` 中添加 `status` 字段
- 允许更新聊天状态（idle/running）

### 2. console.py
- ✅ 任务启动时调用 `patch_chat(status="running")`
- 确保 ChatSpec.status 持久化

### 3. runner.py
- ✅ 任务结束时调用 `patch_chat(status="idle")`
- 在 finally 块中确保状态清理

### 4. chats.py
- ✅ 导入 `ChatUpdate`
- ✅ 多重检测逻辑（TaskTracker + ChatSpec.status）
- ✅ 自动修正丢失的任务状态

## 测试场景

### 测试 1: 正常流程验证
```bash
# 步骤
1. 打开开发环境 http://localhost:4300
2. 发送一条消息
3. 立即切换到另一个智能体
4. 再切换回来

# 预期结果
- 聊天记录恢复
- 如果生成未完成，显示"正在生成"状态
- SSE 自动重连，继续显示生成内容
```

### 测试 2: 后端重启验证
```bash
# 步骤
1. 发送一条消息，等待生成开始
2. 重启后端容器：docker compose restart backend
3. 刷新前端页面

# 预期结果
- 聊天记录恢复
- status 自动修正为 "idle"（因为任务已丢失）
- 用户可以重新发送消息
```

### 测试 3: 刷新页面验证
```bash
# 步骤
1. 发送一条消息，等待生成开始
2. 刷新浏览器（F5）

# 预期结果
- 自动重连到正在运行的任务
- 继续显示生成内容
```

### 测试 4: 跨设备同步验证
```bash
# 步骤
1. 在企微发送消息
2. 在 console 打开同一会话

# 预期结果
- 两边都能看到相同的聊天记录
- 如果正在生成，两边都显示"正在生成"
```

### 测试 5: status 持久化验证
```bash
# 步骤
1. 发送消息
2. 查看 chats.json 文件：
   cat /apps/ai/coapis-dev/workspaces/{username}/chat/chats.json
3. 检查对应 chat 的 status 字段

# 预期结果
- 任务启动时：status="running"
- 任务结束时：status="idle"
```

### 测试 6: 异常中断验证
```bash
# 步骤
1. 发送一条消息
2. 点击"停止"按钮（如果有的话）
3. 检查聊天状态

# 预期结果
- status 仍然被正确更新为 "idle"
- finally 块确保状态清理
```

## 手动测试命令

### 1. 查看 chats.json
```bash
# 开发环境
cat /apps/ai/coapis-dev/workspaces/test712/chat/chats.json | jq .

# 生产环境
cat /apps/ai/coapis/workspaces/test712/chat/chats.json | jq .
```

### 2. 查看后端日志
```bash
# 开发环境
docker logs -f coapis-dev-backend | grep -E "status updated|Fixed stale"

# 生产环境
docker logs -f coapis-backend | grep -E "status updated|Fixed stale"
```

### 3. 重启后端
```bash
# 开发环境
cd /apps/ai/coapis-dev/docker && docker compose restart backend

# 生产环境
cd /apps/ai/coapis/docker && docker compose restart backend
```

## 成功标准

1. ✅ 所有测试场景通过
2. ✅ chats.json 中 status 字段正确更新
3. ✅ 后端日志显示状态更新信息
4. ✅ 前端正确显示 generating 状态
5. ✅ 切换智能体后聊天记录恢复
6. ✅ 后端重启后状态自动修正

## 已知限制

1. **延迟更新**：status 更新依赖 patch_chat 的文件写入（异步）
2. **并发控制**：ChatManager 有锁机制，不会出现并发写入问题
3. **文件大小**：chats.json 通常较小（< 100KB），写入开销可忽略

## 下一步

1. 部署到开发环境测试
2. 如果测试通过，部署到生产环境
3. 监控日志，确认功能正常
