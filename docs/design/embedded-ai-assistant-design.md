# 嵌入式 AI 助手设计方案

## 🎯 核心理念

### 两种集成方向对比

#### 方向1：CoApis 整合其他系统（已设计）
```
CoApis 工作台（主）
├─ 📊 ERP 数据卡片
├─ 📈 CRM 图表卡片
└─ 📉 BI 报表卡片
```
**适用场景**：新建系统、CoApis 为主平台

#### 方向2：CoApis 嵌入其他系统（本次设计）⭐
```
企业 OA 系统（主）
├─ 📋 流程审批
├─ 📄 文档管理
└─ 🤖 CoApis AI 助手（嵌入式）
     ├─ 💬 智能对话
     ├─ 📝 文档生成
     └─ 📊 数据分析
```
**适用场景**：已有成熟系统、需要 AI 增强

---

## 💡 设计目标

### 核心价值

**为企业现有系统快速赋能 AI 能力**

**典型场景**：
1. **OA 系统** → AI 审批助手、智能填报
2. **ERP 系统** → AI 数据分析、智能查询
3. **CRM 系统** → AI 客户洞察、销售助手
4. **企业门户** → AI 搜索、智能导航
5. **业务系统** → AI 辅助决策、自动化处理

### 用户痛点

**企业现有系统的困境**：
- ❌ 系统复杂，操作困难
- ❌ 数据孤岛，难以获取洞察
- ❌ 流程繁琐，效率低下
- ❌ 缺乏智能化，依赖人工

**CoApis 嵌入方案的价值**：
- ✅ 快速增加 AI 能力，无需重构
- ✅ 统一 AI 入口，简化操作
- ✅ 数据智能分析，辅助决策
- ✅ 自动化流程，提升效率

---

## 🎨 嵌入方式设计

### 方式1：浮动按钮（推荐 ⭐）

#### 界面设计

```
┌────────────────────────────────────────────┐
│  企业 OA 系统                               │
│  ┌──────────────────────────────────────┐  │
│  │                                      │  │
│  │     业务功能区域                      │  │
│  │                                      │  │
│  │                                      │  │
│  └──────────────────────────────────────┘  │
│                                    ┌─────┐ │
│                                    │ 🤖  │ │ ← 浮动按钮
│                                    └─────┘ │
└────────────────────────────────────────────┘
```

**点击后展开**：
```
┌────────────────────────────────────────────┐
│  企业 OA 系统                               │
│  ┌────────────────────┬─────────────────┐  │
│  │                    │  🤖 AI 助手     │  │
│  │   业务功能区域      │  ────────────   │  │
│  │                    │  💬 对话        │  │
│  │                    │  📝 帮我起草...  │  │
│  │                    │  📊 分析数据     │  │
│  │                    │  ────────────   │  │
│  │                    │  [输入框]       │  │
│  └────────────────────┴─────────────────┘  │
└────────────────────────────────────────────┘
```

#### 技术实现

```typescript
// 嵌入式 SDK
<script src="https://cdn.coapis.com/embed/v1/coapis-embed.js"></script>

<script>
  CoApisEmbed.init({
    // 配置
    agentId: 'oa-assistant',
    position: 'bottom-right',  // 位置
    theme: 'light',            // 主题
    trigger: 'button',         // 触发方式
    
    // 上下文（可选）
    context: {
      system: 'OA',
      userId: 'current-user-id',
      currentPage: '/approval/pending',
    },
    
    // 回调（可选）
    callbacks: {
      onMessage: (msg) => console.log('AI 回复:', msg),
      onAction: (action) => handleAIAction(action),
    },
  });
</script>
```

#### 功能特性

**基础功能**：
- ✅ 智能对话（上下文感知）
- ✅ 快捷指令（一键操作）
- ✅ 文件处理（上传、分析）
- ✅ 数据查询（自然语言）

**深度集成**：
```typescript
// AI 助手可以调用主系统功能
用户: "帮我审批所有请假申请"
AI: 识别意图 → 调用 OA 审批 API
系统: 自动完成批量审批

用户: "查询本月销售数据"
AI: 解析需求 → 调用 ERP 查询接口
系统: 返回数据并可视化展示
```

---

### 方式2：侧边栏嵌入

#### 界面设计

```
┌──────────┬─────────────────────────────────┐
│ 企业 OA  │  业务内容区                      │
│ 导航栏   │  ┌────────────────────────────┐ │
│          │  │                            │ │
│ 🏠 首页  │  │   当前页面内容              │ │
│ 📋 流程  │  │                            │ │
│ 📄 文档  │  │                            │ │
│ 📊 报表  │  │                            │ │
│          │  └────────────────────────────┘ │
│          │  ┌────────────────────────────┐ │
│          │  │ 🤖 AI 助手                  │ │
│          │  │ 当前页面：流程审批          │ │
│          │  │ ─────────────             │ │
│          │  │ 💡 发现 5 条待审批          │ │
│          │  │ 📝 帮我起草审批意见         │ │
│          │  │ [输入框]                   │ │
│          │  └────────────────────────────┘ │
└──────────┴─────────────────────────────────┘
```

#### 技术实现

```typescript
CoApisEmbed.init({
  agentId: 'smart-assistant',
  mode: 'sidebar',           // 侧边栏模式
  position: 'bottom',        // 底部侧边栏
  height: '300px',           // 固定高度
  
  // 页面上下文自动识别
  contextProvider: () => ({
    currentPage: window.location.pathname,
    pageTitle: document.title,
    visibleData: extractPageData(),  // 提取页面数据
  }),
  
  // 智能建议
  suggestions: [
    {
      trigger: '/approval/pending',
      message: '发现 {count} 条待审批，需要我帮忙吗？',
    },
    {
      trigger: '/report/monthly',
      message: '我可以帮您分析本月数据趋势',
    },
  ],
});
```

---

### 方式3：嵌入式面板

#### 界面设计

```
┌────────────────────────────────────────────┐
│  企业 OA 系统 - 审批详情页                   │
│  ┌────────────────────┬─────────────────┐  │
│  │  审批表单           │  🤖 AI 助手     │  │
│  │                    │  ────────────   │  │
│  │  申请人: 张三       │  📋 审批建议    │  │
│  │  请假类型: 年假     │  ────────────   │  │
│  │  请假天数: 3天      │  ✅ 符合规定    │  │
│  │                    │  ✅ 年假充足    │  │
│  │  [审批通过] [驳回]  │  ⚠️  注意事项   │  │
│  │                    │  ────────────   │  │
│  │                    │  [生成审批意见]  │  │
│  └────────────────────┴─────────────────┘  │
└────────────────────────────────────────────┘
```

#### 技术实现

```typescript
// 在特定页面位置嵌入
<div id="coapis-assistant"></div>

<script>
CoApisEmbed.render('#coapis-assistant', {
  agentId: 'approval-assistant',
  mode: 'panel',
  
  // 自动读取页面表单数据
  dataBinding: {
    applicant: '#applicant-name',
    leaveType: '#leave-type',
    days: '#leave-days',
  },
  
  // AI 能力
  capabilities: [
    'analyze-approval',    // 审批分析
    'generate-opinion',    // 生成意见
    'check-compliance',    // 合规检查
    'suggest-action',      // 建议操作
  ],
  
  // 自动分析
  autoAnalyze: true,
});
</script>
```

---

### 方式4：API 集成（无界面）

#### 应用场景

**场景1：后端服务调用**
```typescript
// ERP 系统后端调用 CoApis API
const response = await fetch('https://api.coapis.com/v1/chat', {
  method: 'POST',
  headers: {
    'Authorization': 'Bearer YOUR_API_KEY',
    'Content-Type': 'application/json',
  },
  body: JSON.stringify({
    agent_id: 'data-analyst',
    message: '分析本月销售数据，找出异常',
    context: {
      system: 'ERP',
      data: salesData,  // 传递业务数据
    },
  }),
});

const aiInsight = await response.json();
// AI 返回洞察和建议
```

**场景2：定时任务**
```typescript
// 每日自动生成分析报告
cron.schedule('0 9 * * *', async () => {
  // 获取昨日数据
  const yesterdayData = await fetchYesterdayData();
  
  // 调用 CoApis AI 分析
  const report = await CoApisAPI.analyze({
    agent_id: 'report-generator',
    data: yesterdayData,
    template: 'daily-summary',
  });
  
  // 发送报告
  await sendEmail(report);
});
```

**场景3：Webhook 集成**
```typescript
// 业务事件触发 AI 处理
app.post('/webhook/order-created', async (req, res) => {
  const order = req.body;
  
  // 调用 CoApis AI 分析
  const analysis = await CoApisAPI.analyze({
    agent_id: 'order-assistant',
    event: 'order_created',
    data: order,
  });
  
  // AI 返回风险提示、建议等
  if (analysis.riskLevel === 'high') {
    await notifyManager(analysis.alert);
  }
  
  res.json({ success: true });
});
```

---

## 🔗 深度集成方案

### 1. 上下文感知

#### 自动识别当前页面

```typescript
class ContextAwareness {
  // 页面路由识别
  detectCurrentPage() {
    const route = window.location.pathname;
    return {
      module: this.parseModule(route),
      action: this.parseAction(route),
      entity: this.parseEntity(route),
    };
  }
  
  // 页面数据提取
  extractPageData() {
    return {
      formData: this.extractFormData(),
      tableData: this.extractTableData(),
      visibleElements: this.extractVisibleElements(),
    };
  }
  
  // 用户意图推断
  inferUserIntent(context) {
    // 根据页面上下文推断用户可能需要什么帮助
    if (context.module === 'approval' && context.action === 'pending') {
      return {
        suggestions: [
          '批量审批',
          '审批建议',
          '生成审批意见',
        ],
        autoActions: [
          {
            trigger: 'page_load',
            action: 'analyze_pending_approvals',
          },
        ],
      };
    }
  }
}
```

#### 智能提示示例

```typescript
// 场景1：审批页面
用户进入: /approval/pending
AI 自动: "发现 15 条待审批，其中 3 条已超时，需要我帮忙吗？"

// 场景2：报表页面
用户进入: /report/monthly
AI 自动: "我可以帮您分析本月数据，或生成月报"

// 场景3：客户详情页
用户进入: /customer/detail/123
AI 自动: "该客户最近 30 天未跟进，建议安排回访"

// 场景4：订单页面
用户进入: /order/create
AI 自动: "检测到客户偏好，可以智能推荐产品"
```

---

### 2. 双向数据交互

#### 主系统 → CoApis

```typescript
// 主系统传递数据给 AI
CoApisEmbed.sendContext({
  // 当前用户信息
  user: {
    id: 'user-123',
    name: '张三',
    role: 'manager',
    permissions: ['approve_leave', 'view_report'],
  },
  
  // 当前页面数据
  page: {
    module: 'approval',
    data: {
      pendingCount: 15,
      overdueCount: 3,
    },
  },
  
  // 业务数据
  business: {
    selectedRecords: [1, 2, 3],  // 用户选中的记录
    formData: { ... },           // 表单数据
  },
});
```

#### CoApis → 主系统

```typescript
// AI 触发主系统操作
CoApisEmbed.onAction((action) => {
  switch (action.type) {
    case 'batch_approve':
      // 批量审批
      return batchApprove(action.recordIds);
      
    case 'fill_form':
      // 自动填表
      return fillForm(action.formData);
      
    case 'navigate':
      // 页面跳转
      return navigateTo(action.url);
      
    case 'api_call':
      // 调用主系统 API
      return callMainSystemAPI(action.endpoint, action.params);
  }
});

// 示例对话
用户: "帮我审批所有请假申请"
AI: 识别意图 → 返回 action
系统: 执行批量审批
AI: "已完成审批，共处理 12 条申请"
```

---

### 3. 权限控制

#### 权限映射

```typescript
// 主系统权限 → CoApis 权限
const permissionMapping = {
  // OA 权限
  'oa:approve_leave': 'coapis:approve',
  'oa:view_report': 'coapis:analyze',
  'oa:edit_doc': 'coapis:edit',
  
  // ERP 权限
  'erp:view_finance': 'coapis:finance_view',
  'erp:edit_order': 'coapis:order_edit',
};

// 权限验证
CoApisEmbed.init({
  // 传入用户权限
  permissions: currentUser.permissions.map(
    p => permissionMapping[p]
  ),
  
  // 无权限时的提示
  onPermissionDenied: (action) => {
    showToast(`您没有权限执行此操作: ${action}`);
  },
});
```

---

## 🛠️ SDK 设计

### 核心 API

```typescript
interface CoApisEmbedSDK {
  // 初始化
  init(config: EmbedConfig): void;
  
  // 渲染到指定容器
  render(selector: string, config: PanelConfig): void;
  
  // 发送消息
  sendMessage(message: string, context?: any): Promise<Response>;
  
  // 发送上下文
  sendContext(context: any): void;
  
  // 注册回调
  onAction(callback: (action: Action) => void): void;
  onMessage(callback: (message: Message) => void): void;
  
  // 控制显示
  show(): void;
  hide(): void;
  toggle(): void;
  
  // 销毁
  destroy(): void;
}
```

### 配置项

```typescript
interface EmbedConfig {
  // 基础配置
  agentId: string;              // 智能体 ID
  apiEndpoint?: string;         // API 地址
  token?: string;               // 认证 token
  
  // 显示配置
  mode: 'button' | 'sidebar' | 'panel';
  position?: 'bottom-right' | 'bottom-left' | 'top-right' | 'top-left';
  theme?: 'light' | 'dark' | 'auto';
  
  // 尺寸配置
  width?: string;
  height?: string;
  
  // 上下文配置
  context?: any;
  contextProvider?: () => any;
  
  // 功能配置
  capabilities?: string[];      // AI 能力
  suggestions?: Suggestion[];   // 智能建议
  
  // 回调配置
  callbacks?: {
    onMessage?: (message: Message) => void;
    onAction?: (action: Action) => void;
    onError?: (error: Error) => void;
    onReady?: () => void;
  };
}
```

### 使用示例

#### 完整示例

```html
<!DOCTYPE html>
<html>
<head>
  <title>企业 OA 系统</title>
</head>
<body>
  <!-- OA 系统内容 -->
  <div id="app">
    <!-- 业务功能 -->
  </div>
  
  <!-- 嵌入 CoApis AI 助手 -->
  <script src="https://cdn.coapis.com/embed/v1/coapis-embed.js"></script>
  <script>
    // 初始化
    const assistant = CoApisEmbed.init({
      agentId: 'oa-assistant',
      mode: 'button',
      position: 'bottom-right',
      theme: 'light',
      
      // 上下文
      context: {
        system: 'OA',
        version: '3.0',
        userId: '<%= currentUserId %>',
      },
      
      // 智能建议
      suggestions: [
        {
          trigger: '/approval/pending',
          message: '发现 {pendingCount} 条待审批',
          actions: ['批量审批', '查看详情'],
        },
      ],
      
      // 回调
      callbacks: {
        onAction: (action) => {
          if (action.type === 'batch_approve') {
            // 调用 OA 审批接口
            OA.approval.batchApprove(action.ids);
          }
        },
      },
    });
    
    // 页面数据变化时更新上下文
    setInterval(() => {
      assistant.sendContext({
        pendingCount: getPendingCount(),
        currentPage: window.location.pathname,
      });
    }, 5000);
  </script>
</body>
</html>
```

---

## 📊 应用场景示例

### 场景1：OA 审批助手

```
企业 OA 系统
├─ 📋 流程审批
│  └─ 🤖 CoApis AI 助手
│     ├─ 💬 "帮我起草审批意见"
│     ├─ 📊 "分析审批风险"
│     ├─ ✅ "批量审批"
│     └─ 📝 "生成审批报告"
```

**典型对话**：
```
用户: "这个请假申请合理吗？"
AI: 
  ✅ 符合公司请假制度
  ✅ 年假余额充足（剩余 8 天）
  ⚠️  注意：该员工上月请假较多
  
  建议：批准，但需关注出勤情况
  
  [一键批准] [生成审批意见]
```

---

### 场景2：ERP 数据助手

```
企业 ERP 系统
├─ 📊 数据报表
│  └─ 🤖 CoApis AI 助手
│     ├─ 💬 "本月销售情况如何？"
│     ├─ 📈 "分析销售趋势"
│     ├─ 🔍 "查询异常订单"
│     └─ 📝 "生成分析报告"
```

**典型对话**：
```
用户: "分析本月销售数据，找出异常"
AI: 
  📊 数据分析结果：
  - 总销售额：¥1,234,567（↑12%）
  - 异常订单：3 笔
    - 订单 #12345：金额异常高
    - 订单 #12346：客户信用不足
    - 订单 #12347：重复下单
  
  💡 建议：
  - 订单 #12345 需人工审核
  - 订单 #12346 建议预付定金
  
  [查看详情] [生成报告]
```

---

### 场景3：CRM 客户助手

```
企业 CRM 系统
├─ 👥 客户管理
│  └─ 🤖 CoApis AI 助手
│     ├─ 💬 "这个客户的价值如何？"
│     ├─ 📊 "客户流失风险分析"
│     ├─ 📝 "生成跟进计划"
│     └─ 🔔 "智能提醒"
```

**典型对话**：
```
用户: "这个客户最近怎么样？"
AI:
  👤 客户：阿里巴巴
  📊 最近动态：
  - 30 天未跟进
  - 上次购买：60 天前
  - 流失风险：⚠️ 中等
  
  💡 建议行动：
  - 立即安排回访
  - 推荐新产品：智能客服系统
  - 提供优惠：老客户专享 9 折
  
  [立即跟进] [生成方案]
```

---

## 🏗️ 技术架构

### 整体架构

```
企业主系统（OA/ERP/CRM）
├── 主系统 UI
│   ├── 业务功能模块
│   └── 嵌入位置
│       ├── 浮动按钮
│       ├── 侧边栏
│       └── 嵌入面板
│
├── CoApis Embed SDK
│   ├── UI Renderer（UI 渲染）
│   ├── Context Manager（上下文管理）
│   ├── API Client（API 客户端）
│   └── Event Bus（事件总线）
│
└── CoApis Cloud Services
    ├── Agent Runtime（智能体运行时）
    ├── AI Engine（AI 引擎）
    ├── Knowledge Base（知识库）
    └── Integration Hub（集成中心）
```

### 数据流

```
┌─────────────────┐
│  主系统 UI       │
│  (用户操作)      │
└────────┬────────┘
         │ 用户输入
         ↓
┌─────────────────┐
│  Embed SDK      │
│  - 采集上下文    │
│  - 发送请求      │
└────────┬────────┘
         │ API 请求
         ↓
┌─────────────────┐
│  CoApis Cloud   │
│  - AI 处理      │
│  - 调用工具      │
│  - 访问知识库    │
└────────┬────────┘
         │ AI 响应
         ↓
┌─────────────────┐
│  Embed SDK      │
│  - 渲染 UI      │
│  - 触发回调      │
└────────┬────────┘
         │ 执行动作
         ↓
┌─────────────────┐
│  主系统 API      │
│  - 业务操作      │
│  - 数据更新      │
└─────────────────┘
```

---

## 📈 实施方案

### 阶段一：SDK 开发（2-3周）

**核心功能**：
- ✅ 浮动按钮模式
- ✅ 基础对话功能
- ✅ 上下文传递
- ✅ 事件回调

**技术选型**：
- 原生 JavaScript（不依赖框架）
- WebSocket 实时通信
- LocalStorage 状态持久化

### 阶段二：深度集成（3-4周）

**核心功能**：
- ✅ 页面上下文自动识别
- ✅ 双向数据交互
- ✅ 智能建议
- ✅ 权限控制

**集成适配**：
- ✅ OA 系统适配器
- ✅ ERP 系统适配器
- ✅ CRM 系统适配器

### 阶段三：高级功能（2-3周）

**核心功能**：
- ✅ 多种嵌入模式
- ✅ 自定义主题
- ✅ 多语言支持
- ✅ 移动端适配

### 阶段四：生态建设（持续）

**核心功能**：
- ✅ 开发者文档
- ✅ 示例代码
- ✅ 模板市场
- ✅ 第三方插件

---

## 💰 成本与收益

### 开发成本

| 阶段 | 工作量 | 时间 |
|------|--------|------|
| 阶段一：SDK 开发 | 2-3人月 | 2-3周 |
| 阶段二：深度集成 | 3-4人月 | 3-4周 |
| 阶段三：高级功能 | 2-3人月 | 2-3周 |
| 阶段四：生态建设 | 3-4人月 | 持续 |
| **总计** | **10-14人月** | **7-10周** |

### 收益预期

**对企业**：
- ✅ 快速为现有系统增加 AI 能力
- ✅ 无需重构系统，成本低
- ✅ 统一 AI 入口，体验好
- ✅ 提升办公效率 30-50%

**对 CoApis**：
- ✅ 快速拓展市场
- ✅ 降低客户使用门槛
- ✅ 建立生态壁垒
- ✅ 收益模式：按调用量计费

---

## ✅ 总结

### 核心优势

1. **快速赋能**：
   - ✅ 几行代码即可嵌入
   - ✅ 无需重构现有系统
   - ✅ 快速上线验证

2. **深度集成**：
   - ✅ 上下文感知
   - ✅ 双向数据交互
   - ✅ 权限控制

3. **灵活适配**：
   - ✅ 多种嵌入方式
   - ✅ 支持各种系统
   - ✅ 自定义配置

4. **价值明确**：
   - ✅ 为企业现有系统增加 AI 能力
   - ✅ 提升办公效率
   - ✅ 降低学习成本

### 与方案1的对比

| 维度 | 方案1：整合其他系统 | 方案2：嵌入其他系统 |
|------|-------------------|-------------------|
| **定位** | CoApis 为主平台 | 其他系统为主平台 |
| **适用场景** | 新建系统 | 已有成熟系统 |
| **实施成本** | 较高 | 较低 |
| **用户体验** | 统一工作台 | 无缝融入现有系统 |
| **市场拓展** | 替代现有系统 | 赋能现有系统 |

### 推荐策略

**双管齐下**：
1. **方案1**：针对新建系统、数字化转型企业
2. **方案2**：针对已有成熟系统、需要 AI 增强的企业

**优先级建议**：
- **短期（0-6个月）**：优先方案2（嵌入式）
  - 原因：市场拓展快，客户接受度高
  
- **中期（6-12个月）**：方案1 + 方案2 并行
  - 原因：满足不同客户需求
  
- **长期（12个月+）**：根据市场反馈调整
  - 原因：数据驱动决策

---

**两个方案互补，共同构建 CoApis 的企业级生态！**
