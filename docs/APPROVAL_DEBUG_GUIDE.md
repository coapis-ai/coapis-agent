# 审批功能问题调试指南

## 问题描述

用户报告：
1. AI 提示"等待审批"，但页面没有弹出审批框
2. 输入框无法发送（按钮处于暂停状态）

## 已添加的调试日志

已在 `server/coapis/app/routers/console.py` 中添加详细日志：

```python
# 查看 /console/push-messages API 的日志输出
[PUSH MESSAGES] Total pending approvals: X
[PUSH MESSAGES] list_pending_by_session(session_id) returned Y results
[PUSH MESSAGES] get_pending_by_root_session(session_id) returned Z results
```

## 调试步骤

### 1. 检查后端日志

执行命令后，查看后端日志：

```bash
docker logs coapis-server 2>&1 | grep "PUSH MESSAGES\|Tool.*requires approval"
```

**期望输出**：
```
Tool 'execute_bash' requires approval... Creating pending approval...
[PUSH MESSAGES] Total pending approvals: 1
[PUSH MESSAGES] list_pending_by_session(550e8400...) returned 0 results
[PUSH MESSAGES] get_pending_by_root_session(550e8400...) returned 1 results
```

### 2. 检查前端轮询

打开浏览器控制台，查看：

```javascript
// 检查 window.currentSessionId
console.log("window.currentSessionId:", window.currentSessionId);

// 检查 approvals 状态
console.log("approvals:", approvals);
```

### 3. 手动测试 API

```bash
# 替换 SESSION_ID 为实际的 session ID
curl "http://localhost:4208/api/console/push-messages?session_id=SESSION_ID"
```

## 可能的问题原因

### 原因 1：Session ID 不匹配

**症状**：
```
[PUSH MESSAGES] list_pending_by_session(console:admin) returned 0 results
[PUSH MESSAGES] get_pending_by_root_session(console:admin) returned 0 results
```

**原因**：前端传递的 session_id 与后端创建审批时使用的 ID 不一致。

**解决方案**：检查 `window.currentSessionId` 是否正确设置。

### 原因 2：审批创建失败

**症状**：
```
Tool 'execute_bash' requires approval...
# 但没有后续日志
```

**原因**：ApprovalService 未正确初始化或创建审批失败。

### 原因 3：前端未正确轮询

**症状**：后端日志显示有 pending approvals，但前端没有显示。

**原因**：`ConsolePollService` 未启动或轮询间隔过长。

## 临时解决方案

### 方案 1：降低工具审批级别

修改 `system/tool_guard.json`：

```json
{
  "execution_level": "guard",  // 从 "approve" 改为 "guard"
  "rules": {
    "shell": {
      "severity": "medium",  // 从 "high" 改为 "medium"
      "patterns": []
    }
  }
}
```

### 方案 2：禁用工具审批（仅测试）

修改 `system/tool_guard.json`：

```json
{
  "execution_level": "off"  // 完全禁用审批
}
```

### 方案 3：手动批准命令

在聊天中输入：

```
/approve
```

## 技能命令优化建议

### 问题：技能命令也需要审批

当前所有命令都需要审批，包括来自技能的预定义命令。

### 建议方案：

**1. 添加技能命令白名单**

在 `server/coapis/agents/tool_guard_mixin.py` 中：

```python
# 检查是否来自可信技能
tool_input = tool_call.get("input", {})
command = tool_input.get("command", "")

# 技能安装依赖的命令可以自动批准
SKILL_WHITELIST_COMMANDS = [
    "pip install",
    "pip3 install",
    "npm install",
    "yarn add",
]

if any(cmd in command for cmd in SKILL_WHITELIST_COMMANDS):
    # 自动批准
    return None
```

**2. 添加技能标记**

在技能调用工具时添加元数据：

```python
tool_input = {
    "command": "pip install python-docx",
    "_skill_source": "document_writer",  # 技能来源
    "_trusted": True,  # 标记为可信
}
```

## 下一步

1. **收集日志**：重现问题，查看后端日志输出
2. **验证 Session ID**：检查前端和后端的 session_id 是否一致
3. **测试 API**：手动调用 API 验证返回数据
4. **提交 Issue**：附上完整日志提交 Issue

---

**创建日期**：2026-07-13
**相关文件**：
- `server/coapis/app/routers/console.py`
- `server/coapis/agents/tool_guard_mixin.py`
- `client/src/components/ApprovalCard/ApprovalCard.tsx`
