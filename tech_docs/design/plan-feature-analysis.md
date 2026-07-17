# 计划功能分析

## 📋 功能说明

**"📋计划"按钮**是一个任务计划面板，用于展示AI正在执行的任务计划及其子任务。

---

## 🎯 功能定位

**作用**：
- 展示AI正在执行的任务计划
- 实时更新任务进度
- 显示子任务列表和状态

**适用场景**：
- AI执行复杂任务时，用户可以查看执行计划
- 了解任务进度和完成情况
- 查看任务分解和执行步骤

---

## 📊 数据结构

### PlanStateResponse

```typescript
interface PlanStateResponse {
  id: string;                    // 计划ID
  name: string;                  // 计划名称
  description: string;           // 计划描述
  expected_outcome: string;      // 预期结果
  state: 'todo' | 'in_progress' | 'done' | 'abandoned';  // 状态
  subtasks: SubTaskResponse[];   // 子任务列表
  created_at: string;            // 创建时间
  finished_at: string;           // 完成时间
  outcome: string;               // 实际结果
}
```

### SubTaskResponse

```typescript
interface SubTaskResponse {
  name: string;                  // 子任务名称
  description: string;           // 子任务描述
  expected_outcome: string;      // 预期结果
  outcome: string;               // 实际结果
  state: 'todo' | 'in_progress' | 'done' | 'abandoned';  // 状态
  created_at: string;
  finished_at: string;
}
```

---

## 🎨 UI展示

### 状态图标

```
⬜ todo        - 待执行
🔄 in_progress - 执行中
✅ done        - 已完成
⛔ abandoned   - 已放弃
```

### 展示内容

```
┌──────────────────────────────────┐
│  任务计划面板                     │
├──────────────────────────────────┤
│  📋 计划名称                      │
│  描述：XXXX                       │
│                                  │
│  进度：███████░░░ 70%            │
│                                  │
│  子任务列表：                     │
│  ✅ 子任务1 - 已完成              │
│  🔄 子任务2 - 执行中              │
│  ⬜ 子任务3 - 待执行              │
│  ⬜ 子任务4 - 待执行              │
└──────────────────────────────────┘
```

---

## 🔧 技术实现

### API端点

```
GET  /plan/config   - 获取计划配置（是否启用）
PUT  /plan/config   - 更新计划配置
GET  /plan/current  - 获取当前计划
GET  /plan/stream   - SSE实时推送计划更新
```

### 配置

```json
{
  "plan": {
    "enabled": true
  }
}
```

---

## 🤔 使用场景分析

### 场景1：复杂任务执行

**用户**："帮我部署一个Web应用"

**AI执行计划**：
```
📋 部署Web应用
├─ ✅ 分析项目结构
├─ ✅ 安装依赖
├─ 🔄 构建生产版本
├─ ⬜ 配置服务器
└─ ⬜ 启动应用
```

**用户体验**：
- 实时查看AI在做什么
- 了解任务进度
- 知道还需要多久完成

---

### 场景2：多步骤任务

**用户**："帮我整理文档并生成报告"

**AI执行计划**：
```
📋 整理文档并生成报告
├─ ✅ 扫描文档目录
├─ ✅ 提取关键信息
├─ 🔄 生成报告大纲
├─ ⬜ 填充报告内容
└─ ⬜ 格式化输出
```

---

## 💡 功能价值

### 对用户

1. **透明度**：了解AI正在做什么
2. **信任感**：看到AI有计划地执行任务
3. **耐心等待**：知道任务进度和预计时间
4. **干预能力**：看到异常可以及时停止

### 对AI

1. **结构化执行**：按照计划逐步执行
2. **进度跟踪**：记录每一步的完成情况
3. **错误恢复**：从失败的任务继续执行
4. **自我管理**：管理复杂任务的执行流程

---

## 🚀 使用频率分析

### 高频使用场景
- 执行复杂任务（部署、迁移、重构）
- 长时间运行的任务
- 需要多步骤完成的任务

### 低频使用场景
- 简单对话
- 快速问答
- 单步操作

### 当前问题
- ⚠️ 按钮常驻显示，占用顶部空间
- ⚠️ 用户可能不知道这个功能的作用
- ⚠️ 只在特定场景下有用，但一直显示

---

## 💡 改进建议

### 建议1：按需显示

```typescript
// 只在有计划时显示按钮
{planEnabled && currentPlan && (
  <Tooltip title="查看任务计划">
    <IconButton icon={<PlanIcon />} onClick={() => setPlanOpen(true)} />
  </Tooltip>
)}
```

**优点**：
- ✅ 不占用常驻空间
- ✅ 更符合使用场景
- ✅ 用户不会被困惑

---

### 建议2：状态提示

```typescript
// 显示任务进度
{planEnabled && currentPlan && (
  <Badge count={currentPlan.subtasks.filter(s => s.state === 'done').length}>
    <IconButton icon={<PlanIcon />} />
  </Badge>
)}
```

**优点**：
- ✅ 显示进度提示
- ✅ 吸引用户注意
- ✅ 更好的交互

---

### 建议3：移动到工具栏

```typescript
// 将计划功能移到输入区域工具栏
const tools = [
  { key: 'plan', icon: <PlanIcon />, label: '任务计划', show: () => currentPlan !== null },
];
```

**优点**：
- ✅ 不占用顶部空间
- ✅ 与其他工具统一管理
- ✅ 可配置显示/隐藏

---

## 📊 对比总结

| 方案 | 优点 | 缺点 | 推荐度 |
|------|------|------|--------|
| **常驻显示** | 随时可访问 | 占用空间，可能不常用 | ⭐⭐ |
| **按需显示** | 不占空间，符合场景 | 需要判断逻辑 | ⭐⭐⭐⭐ |
| **状态提示** | 显示进度，更直观 | 实现稍复杂 | ⭐⭐⭐⭐⭐ |
| **移到工具栏** | 统一管理，可配置 | 改动较大 | ⭐⭐⭐ |

---

## ✅ 最终建议

**推荐方案**：**按需显示 + 状态提示**

```typescript
// 只在有计划时显示，并显示进度
{planEnabled && currentPlan && (
  <Tooltip title={`任务进度：${completedCount}/${totalCount}`}>
    <Badge count={completedCount} size="small">
      <IconButton
        icon={<PlanIcon />}
        onClick={() => setPlanOpen(true)}
      />
    </Badge>
  </Tooltip>
)}
```

**核心优势**：
- ✅ 不占用常驻空间
- ✅ 有计划时才显示
- ✅ 显示进度提示
- ✅ 用户一目了然

---

## 💬 需要确认

**问题**：你觉得"计划"功能应该：

1. **保持现状**：常驻显示在顶部栏
2. **按需显示**：只有执行计划时才显示
3. **移到工具栏**：作为工具栏的一个工具
4. **移除**：这个功能不需要

**你倾向哪个？** 🤔
