# 嵌入式 AI 助手设计（正确版）

## 🎯 核心理解

### 界面 vs 能力

#### ❌ 错误理解
```
界面简化 = 能力也简化
结果：AI 助手变成玩具，无法赋能业务
```

#### ✅ 正确理解
```
界面简化 = 只展示对话，隐藏管理功能
能力完整 = AI 具备完整的业务赋能能力
```

---

## 🎨 界面设计（简洁）

### 唯一模式：浮动对话窗口

```
收起状态：              展开状态：
┌─────────────┐        ┌──────────────────┐
│             │        │ 🤖 AI 助手  [─][×]│
│   主系统    │        │ ──────────────── │
│             │        │                  │
│       ┌──┐ │        │ 💬 对话区域       │
│       │🤖│ │        │   (简洁UI)        │
│       └──┘ │        │                  │
└─────────────┘        │ ──────────────── │
                       │ 🔍 输入框  [发送]│
                       └──────────────────┘
```

**界面极简**：
- ✅ 只有对话窗口
- ✅ 无管理界面
- ✅ 无配置选项
- ✅ 无复杂操作

---

## 🧠 AI 能力（完整）

### 完整的业务赋能能力

虽然界面简洁，但 AI 助手具备完整的能力：

#### 1. 上下文感知（自动识别）

```typescript
// AI 自动感知当前页面和业务数据
用户进入: /approval/pending
AI 自动分析:
  - 读取页面数据：15条待审批
  - 识别业务场景：审批流程
  - 智能提示："发现15条待审批，需要帮忙吗？"
  - 可执行操作：批量审批、生成意见、风险分析
```

#### 2. 业务数据读取（深度集成）

```typescript
// AI 可以读取主系统数据
用户: "分析本月销售数据"
AI:
  1. 自动调用主系统API（ERP）
  2. 获取销售数据
  3. AI分析洞察
  4. 返回分析结果

用户: "这个客户的信用如何？"
AI:
  1. 自动识别当前客户ID（从页面URL/表单）
  2. 调用CRM系统API
  3. 获取客户信息、历史记录
  4. 返回信用评估和建议
```

#### 3. 业务操作执行（双向交互）

```typescript
// AI 可以执行业务操作
用户: "帮我审批所有请假申请"
AI:
  1. 读取待审批列表（从主系统）
  2. 分析每条申请的合规性
  3. 调用主系统审批API
  4. 返回执行结果

用户: "把这个客户标记为高价值客户"
AI:
  1. 调用CRM系统API
  2. 更新客户标签
  3. 返回操作结果
```

#### 4. 智能分析（AI 增强）

```typescript
// AI 自动分析业务数据
用户进入审批页面
AI 自动:
  1. 分析当前审批项
  2. 检查合规性
  3. 风险评估
  4. 给出建议

AI: "检测到3条审批：
  - 张三请假：✅ 符合规定，建议批准
  - 李四请假：⚠️ 上月请假较多，需关注
  - 王五请假：❌ 年假余额不足，建议驳回

需要我帮忙批量处理吗？"
```

#### 5. 知识库查询（业务知识）

```typescript
// AI 可以查询企业知识库
用户: "公司的差旅报销标准是什么？"
AI:
  1. 查询知识库
  2. 返回准确答案
  3. 提供操作指引

用户: "这个流程怎么走？"
AI:
  1. 识别流程类型
  2. 查询知识库流程文档
  3. 提供步骤指引
```

---

## 🔧 深度集成方案

### 1. 自动上下文感知

```typescript
// SDK 自动采集上下文
class ContextAwareness {
  constructor() {
    // 监听页面变化
    this.watchRouteChange();
    
    // 监听页面数据
    this.watchPageData();
    
    // 监听用户操作
    this.watchUserActions();
  }
  
  // 自动发送上下文给 AI
  sendContext() {
    const context = {
      // 页面信息
      page: {
        route: window.location.pathname,
        title: document.title,
      },
      
      // 业务数据（自动提取）
      business: this.extractBusinessData(),
      
      // 用户信息
      user: this.getCurrentUser(),
    };
    
    CoApisAPI.sendContext(context);
  }
  
  // 提取业务数据
  extractBusinessData() {
    // 自动识别页面类型
    if (isApprovalPage()) {
      return {
        type: 'approval',
        pendingItems: extractPendingItems(),
        selectedItems: extractSelectedItems(),
      };
    }
    
    if (isCustomerPage()) {
      return {
        type: 'customer',
        customerId: extractCustomerId(),
        customerData: extractCustomerData(),
      };
    }
    
    // ... 其他页面类型
  }
}
```

### 2. 业务 API 调用

```typescript
// 主系统注册 API 给 AI 调用
CoApis.init({
  token: 'your-token',
  agent: 'oa-assistant',
  
  // 注册业务 API
  apis: {
    // 审批相关
    'approval.getPending': () => fetchPendingApprovals(),
    'approval.approve': (ids) => batchApprove(ids),
    'approval.reject': (ids, reason) => batchReject(ids, reason),
    
    // 客户相关
    'customer.getInfo': (id) => getCustomerInfo(id),
    'customer.updateTag': (id, tag) => updateCustomerTag(id, tag),
    
    // 订单相关
    'order.getList': (filters) => getOrders(filters),
    'order.analyze': (id) => analyzeOrder(id),
  },
});

// AI 可以直接调用这些 API
用户: "帮我审批所有请假"
AI: 调用 approval.getPending() → 获取列表
    调用 approval.approve(ids) → 执行审批
    返回结果："已完成12条审批"
```

### 3. 数据双向同步

```typescript
// 主系统 → AI（推送数据）
CoApis.sendData({
  type: 'approval_new',
  data: {
    id: '12345',
    applicant: '张三',
    type: '请假',
  },
});

// AI → 主系统（触发操作）
CoApis.onAction((action) => {
  switch (action.type) {
    case 'approve':
      return approveRequest(action.data);
    case 'navigate':
      return navigateTo(action.url);
    case 'fillForm':
      return fillFormData(action.data);
  }
});
```

---

## 💡 典型应用场景

### 场景1：OA 审批助手

```
┌──────────────────────────────────────┐
│  OA 系统 - 待审批列表                 │
│  ┌────────────────┬─────────────────┐│
│  │ 申请人: 张三    │ 🤖 AI 助手      ││
│  │ 类型: 请假      │                 ││
│  │ 天数: 3天       │ 💬 检测到3条    ││
│  │                │    待审批        ││
│  │ [详情] [审批]   │                 ││
│  ├────────────────┤ ✅ 张三：符合    ││
│  │ 申请人: 李四    │    规定，建议    ││
│  │ 类型: 出差      │    批准         ││
│  │ 天数: 5天      │                 ││
│  │                │ ⚠️ 李四：上月   ││
│  │ [详情] [审批]   │    请假较多     ││
│  └────────────────┴─────────────────┘│
└──────────────────────────────────────┘

用户: "帮我批量审批"
AI: "好的，我来帮您分析..."
   1. 调用 OA API 获取详情
   2. 分析每条申请
   3. 执行审批操作
   4. "已完成审批：
      ✅ 张三：已批准
      ⚠️ 李四：已标记需关注
      ❌ 王五：年假不足，已驳回"
```

### 场景2：ERP 数据助手

```
用户进入销售报表页面

AI 自动分析（后台）:
  1. 读取页面销售数据
  2. AI 分析趋势
  3. 识别异常

AI 主动提示:
  "📊 发现数据异常：
   - 订单 #12345 金额异常高（¥500,000）
   - 客户信用额度不足
   - 建议：人工审核

   需要我生成分析报告吗？"

用户: "生成报告"
AI: 调用 ERP API → 获取数据 → AI分析 → 生成报告
   "✅ 报告已生成：
   - 本月销售额：¥1,234,567（↑12%）
   - 异常订单：3笔
   - 风险提示：5项
   
   [下载报告] [查看详情]"
```

### 场景3：CRM 客户助手

```
用户查看客户详情页

AI 自动:
  1. 识别客户ID
  2. 查询客户信息
  3. 分析客户价值
  4. 查询跟进记录

AI 提示:
  "👤 客户分析：
   - 客户类型：大客户
   - 生命周期价值：¥500,000+
   - 最近跟进：30天前 ⚠️
   - 流失风险：中等

   💡 建议行动：
   1. 立即安排回访
   2. 推荐新产品：智能客服系统
   3. 提供老客户优惠

   [立即跟进] [生成方案]"

用户: "生成跟进方案"
AI: 调用 CRM API → 查询历史 → AI分析 → 生成方案
   "📋 跟进方案已生成：
   1. 回访时间：本周五下午
   2. 推荐产品：智能客服（匹配度高）
   3. 优惠方案：9折 + 免费试用
   
   [创建跟进任务] [发送邮件]"
```

---

## 🛠️ 集成代码示例

### 完整集成（简洁但功能完整）

```html
<!DOCTYPE html>
<html>
<head>
  <title>企业 OA 系统</title>
</head>
<body>
  <!-- OA 系统内容 -->
  
  <!-- 嵌入 CoApis AI 助手 -->
  <script src="https://cdn.coapis.com/embed/v1/coapis.min.js"></script>
  <script>
    CoApis.init({
      // 基础配置
      token: '<%= userToken %>',
      agent: 'oa-assistant',
      
      // 业务 API 注册（关键！）
      apis: {
        // 审批
        'approval.getPending': async () => {
          const res = await fetch('/api/approval/pending');
          return res.json();
        },
        'approval.approve': async (ids) => {
          const res = await fetch('/api/approval/approve', {
            method: 'POST',
            body: JSON.stringify({ ids }),
          });
          return res.json();
        },
        
        // 客户
        'customer.getInfo': async (id) => {
          const res = await fetch(`/api/customer/${id}`);
          return res.json();
        },
        
        // 订单
        'order.getList': async (filters) => {
          const res = await fetch('/api/orders', {
            method: 'POST',
            body: JSON.stringify(filters),
          });
          return res.json();
        },
      },
      
      // 上下文提供（关键！）
      contextProvider: () => ({
        currentPage: window.location.pathname,
        pageTitle: document.title,
        userData: getCurrentUser(),
        // 自动提取页面数据
        pageData: extractPageData(),
      }),
      
      // 主题适配
      theme: 'auto',
    });
    
    // 辅助函数：提取页面数据
    function extractPageData() {
      // 根据页面类型提取不同数据
      const route = window.location.pathname;
      
      if (route.includes('/approval')) {
        return {
          type: 'approval',
          pendingItems: document.querySelectorAll('.pending-item').length,
        };
      }
      
      if (route.includes('/customer')) {
        const customerId = route.match(/\/customer\/(\d+)/)?.[1];
        return {
          type: 'customer',
          customerId,
        };
      }
      
      return { type: 'unknown' };
    }
  </script>
</body>
</html>
```

### 代码说明

**核心配置**：

1. **apis**：注册业务 API 给 AI 调用
   - AI 可以直接调用这些 API
   - 实现深度业务集成

2. **contextProvider**：提供上下文
   - 自动采集页面信息
   - 提取业务数据
   - AI 自动感知

---

## 📊 能力对比

### 界面 vs 能力

| 维度 | 界面 | 能力 |
|------|------|------|
| **对话** | ✅ 简洁 | ✅ 完整（支持流式、Markdown） |
| **上下文** | ❌ 无UI | ✅ 完整（自动感知、智能分析） |
| **业务集成** | ❌ 无UI | ✅ 完整（API调用、双向交互） |
| **知识库** | ❌ 无UI | ✅ 完整（查询、检索） |
| **智能分析** | ❌ 无UI | ✅ 完整（风险分析、洞察） |
| **管理功能** | ❌ 无UI | ❌ 隐藏（跳转主站） |

---

## ✅ 总结

### 核心设计理念

**"界面极简，能力完整"**

- ✅ **界面**：只有对话窗口，无管理UI
- ✅ **能力**：完整业务赋能，深度集成

### 关键特性

1. **自动上下文感知**
   - 自动识别页面
   - 自动提取数据
   - 智能提示

2. **深度业务集成**
   - 注册业务 API
   - AI 直接调用
   - 双向数据交互

3. **智能分析**
   - 自动分析业务数据
   - 风险评估
   - 洞察建议

4. **界面极简**
   - 只有对话窗口
   - 无管理界面
   - 管理功能跳转主站

### 适用场景

- ✅ 需要深度业务集成
- ✅ 需要AI赋能业务
- ✅ 需要自动化操作
- ✅ 需要智能分析
- ✅ 界面保持简洁

---

**这才是正确的理解：界面简洁，但能力完整！** 🎉
