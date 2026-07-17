# 计划功能界面设计优化方案

## 🤔 问题分析

### 当前设计的问题

```
┌────────────────────────────────────────┐
│  [📋历史] [➕新对话]  [📋计划]  [模型▼] │  ← 计划按钮在顶部栏
├────────────────────────────────────────┤
│                                        │
│         聊天消息区域                    │
│                                        │
└────────────────────────────────────────┘
```

**问题**：
- ❌ 计划是**聊天过程中**产生的，不应该在顶部栏
- ❌ 顶部栏是**全局操作**（历史、新对话、模型选择）
- ❌ 计划和聊天内容割裂，体验不连贯
- ❌ 用户需要点击按钮才能看到，增加操作成本

---

## 💡 正确的设计思路

### 计划的本质

**计划** = 聊天对话的一部分

- ✅ AI执行任务时生成计划
- ✅ 计划和当前对话关联
- ✅ 应该在聊天区域展示
- ✅ 和消息流自然融合

---

## 🎯 优化方案对比

### 方案1：集成到聊天消息中（推荐）

```
用户：帮我部署一个Web应用

AI：好的，我来帮你部署。我会按照以下步骤执行：
    ┌────────────────────────────────┐
    │ 📋 执行计划                     │
    ├────────────────────────────────┤
    │ ✅ 1. 分析项目结构              │
    │ ✅ 2. 安装依赖                  │
    │ 🔄 3. 构建生产版本              │
    │ ⬜ 4. 配置服务器                │
    │ ⬜ 5. 启动应用                  │
    │                                │
    │ 进度：40% ████████░░░░░░░░     │
    └────────────────────────────────┘

    我正在执行第3步：构建生产版本...
```

**优点**：
- ✅ 计划和聊天内容自然融合
- ✅ 用户无需额外操作
- ✅ 实时更新进度
- ✅ 和对话上下文关联

**实现**：
- 计划作为特殊的消息卡片
- 类似 ToolCallCard，但有进度展示
- 实时更新状态（通过SSE）

---

### 方案2：浮动在聊天区域内

```
┌────────────────────────────────────────┐
│  聊天消息区域                          │
│                                        │
│  用户：帮我部署应用                    │
│  AI：好的，开始部署...                 │
│                                        │
│  ┌────────────────────────────────┐   │
│  │ 📋 执行计划            [收起]  │   │  ← 浮动卡片
│  │ ✅ 分析项目结构                │   │
│  │ 🔄 构建中...                   │   │
│  │ 进度：40%                      │   │
│  └────────────────────────────────┘   │
│                                        │
└────────────────────────────────────────┘
```

**优点**：
- ✅ 不干扰消息流
- ✅ 可收起/展开
- ✅ 固定位置，易于查看

**缺点**：
- ⚠️ 可能遮挡消息
- ⚠️ 移动端空间有限

---

### 方案3：侧边栏抽屉

```
┌──────────────────────────┬─────────────┐
│  聊天消息区域            │ 📋 执行计划 │
│                          │             │
│  用户：帮我部署应用      │ ✅ 分析项目 │
│  AI：好的，开始部署...   │ ✅ 安装依赖 │
│                          │ 🔄 构建中   │
│                          │ ⬜ 配置服务 │
│                          │ ⬜ 启动应用 │
│                          │             │
│                          │ 进度：40%   │
└──────────────────────────┴─────────────┘
```

**优点**：
- ✅ 不干扰聊天
- ✅ 空间足够
- ✅ 可随时查看

**缺点**：
- ⚠️ 需要额外空间
- ⚠️ 移动端不友好
- ⚠️ 和聊天内容分离

---

## ✅ 推荐方案：方案1 - 集成到聊天消息中

### 设计细节

#### 1. PlanMessageCard 组件

```typescript
// components/Chat/messages/PlanMessageCard.tsx

interface PlanMessageCardProps {
  plan: PlanStateResponse;
  onTaskClick?: (taskId: string) => void;
}

export function PlanMessageCard({ plan, onTaskClick }: PlanMessageCardProps) {
  const completedCount = plan.subtasks.filter(s => s.state === 'done').length;
  const totalCount = plan.subtasks.length;
  const progress = totalCount > 0 ? (completedCount / totalCount) * 100 : 0;

  return (
    <div className="plan-message-card">
      {/* 计划标题 */}
      <div className="plan-header">
        <span className="plan-icon">📋</span>
        <span className="plan-name">{plan.name}</span>
      </div>

      {/* 子任务列表 */}
      <div className="plan-subtasks">
        {plan.subtasks.map((task, index) => (
          <div
            key={task.name}
            className={`subtask-item ${task.state}`}
            onClick={() => onTaskClick?.(task.name)}
          >
            <span className="subtask-icon">
              {STATE_ICONS[task.state]}
            </span>
            <span className="subtask-name">
              {index + 1}. {task.name}
            </span>
          </div>
        ))}
      </div>

      {/* 进度条 */}
      <div className="plan-progress">
        <Progress percent={progress} size="small" />
        <span className="progress-text">
          {completedCount}/{totalCount} 已完成
        </span>
      </div>
    </div>
  );
}
```

---

#### 2. 消息类型扩展

```typescript
// 扩展消息类型，支持计划消息
interface Message {
  id: string;
  role: 'user' | 'assistant' | 'system';
  content: string;
  // 新增：计划数据
  plan?: PlanStateResponse;
}
```

---

#### 3. 消息渲染

```typescript
// 在消息列表中渲染计划卡片
function MessageList({ messages }: { messages: Message[] }) {
  return (
    <div className="message-list">
      {messages.map(msg => (
        <div key={msg.id} className="message-item">
          {msg.role === 'assistant' && msg.plan ? (
            <PlanMessageCard plan={msg.plan} />
          ) : (
            <MessageContent content={msg.content} />
          )}
        </div>
      ))}
    </div>
  );
}
```

---

#### 4. 实时更新

```typescript
// 通过SSE实时更新计划状态
useEffect(() => {
  const unsubscribe = subscribePlanUpdates((plan) => {
    if (plan) {
      // 更新当前消息的计划数据
      updateMessage(currentMessageId, { plan });
    }
  });

  return unsubscribe;
}, [currentMessageId]);
```

---

### 移动端适配

```
用户：帮我部署应用

AI：好的，开始部署...

┌──────────────────────┐
│ 📋 执行计划          │
├──────────────────────┤
│ ✅ 分析项目          │
│ ✅ 安装依赖          │
│ 🔄 构建中...         │
│ ⬜ 配置服务          │
│ ⬜ 启动应用          │
├──────────────────────┤
│ ████████░░ 40%       │
└──────────────────────┘
```

---

## 📊 方案对比总结

| 方案 | 优点 | 缺点 | 推荐度 |
|------|------|------|--------|
| **顶部栏按钮** | 随时可访问 | 和聊天割裂，体验差 | ⭐ |
| **集成到消息** | 自然融合，实时更新 | 需要修改消息组件 | ⭐⭐⭐⭐⭐ |
| **浮动卡片** | 不干扰消息流 | 可能遮挡内容 | ⭐⭐⭐ |
| **侧边栏** | 空间充足 | 移动端不友好 | ⭐⭐ |

---

## ✅ 最终推荐

**方案：集成到聊天消息中**

**核心优势**：
1. ✅ 计划和聊天内容自然融合
2. ✅ 用户无需额外操作
3. ✅ 实时更新进度
4. ✅ 和对话上下文关联
5. ✅ 移动端友好

**实施步骤**：
1. 创建 PlanMessageCard 组件
2. 扩展消息类型，支持计划数据
3. 修改消息渲染逻辑
4. 集成SSE实时更新

---

## 💬 需要确认

**问题**：是否同意移除顶部栏的"计划"按钮，改为集成到聊天消息中？

**如果同意，我们可以：**
- 移除顶部栏的计划按钮
- 创建 PlanMessageCard 组件
- 将计划作为消息卡片展示

**你觉得这样设计合理吗？** 🚀
