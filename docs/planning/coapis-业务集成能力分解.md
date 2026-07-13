# CoApis 业务集成能力分解

**制定日期**：2026-07-13  
**目的**：明确业务系统集成所需的平台能力和业务层工作

---

## 一、CoApis平台需增加的能力

### 1. 可集成的UI前端

**目标**：业务系统可通过iframe等方式嵌入AI助手

#### 1.1 嵌入式对话界面

**功能清单**：
| 功能 | 说明 | 优先级 |
|------|------|--------|
| iframe嵌入模式 | 提供独立的对话页面，业务系统通过iframe嵌入 | P0 |
| 响应式布局 | 适配不同尺寸的嵌入容器 | P0 |
| 主题定制 | 支持业务系统自定义主题色、Logo | P1 |
| 样式隔离 | CSS作用域隔离，避免与业务系统样式冲突 | P0 |
| 消息通知 | 支持与父窗口通信（postMessage） | P1 |

**技术实现**：
```
业务系统页面
└── iframe (CoApis对话界面)
    ├── 顶部导航栏（可隐藏）
    ├── 对话消息区
    ├── 输入框
    └── 工具栏（文件上传、技能等）
```

**集成示例**：
```html
<!-- 业务系统页面 -->
<iframe 
  src="https://ai.company.com/embed/chat?token=xxx&theme=blue"
  width="100%" 
  height="600px"
  frameborder="0">
</iframe>
```

#### 1.2 独立对话窗口

**功能清单**：
| 功能 | 说明 | 优先级 |
|------|------|--------|
| 弹窗模式 | 以独立窗口形式打开对话 | P1 |
| 右下角悬浮按钮 | 类似客服按钮，点击打开对话 | P1 |
| 拖拽功能 | 对话窗口可拖拽移动 | P2 |

---

### 2. 业务基础数据层集成

**目标**：实现组织机构、用户、权限的集成，使用token/key认证

#### 2.1 认证与授权

**认证机制**：
| 方式 | 说明 | 适用场景 | 优先级 |
|------|------|----------|--------|
| API Key | 业务系统级别的认证 | 服务端调用 | P0 |
| JWT Token | 用户级别的认证 | 前端调用 | P0 |
| SSO集成 | 单点登录（OIDC/SAML） | 企业统一认证 | P1 |
| OAuth2 | 授权码模式 | 第三方应用 | P2 |

**Token生成流程**：
```
1. 业务系统后端调用CoApis API生成Token
   POST /api/auth/token
   {
     "api_key": "xxx",
     "user_id": "user123",
     "org_id": "org001",
     "permissions": ["read", "write"],
     "expire": 3600
   }

2. CoApis返回JWT Token
   {
     "token": "eyJhbGciOiJIUzI1NiIs...",
     "expire": 3600
   }

3. 业务系统前端使用Token访问CoApis
   iframe.src = "https://ai.company.com/embed/chat?token=xxx"
```

#### 2.2 组织机构集成

**集成方式**：
| 方式 | 说明 | 优先级 |
|------|------|--------|
| API同步 | 业务系统通过API同步组织架构到CoApis | P0 |
| 实时查询 | CoApis实时调用业务系统API查询组织架构 | P1 |
| 定时同步 | 定时从业务系统同步组织架构 | P2 |

**数据模型**：
```json
{
  "org_id": "org001",
  "org_name": "技术部",
  "parent_id": "org000",
  "level": 2,
  "path": "/公司/技术部",
  "users": [
    {
      "user_id": "user001",
      "username": "zhangsan",
      "display_name": "张三",
      "email": "zhangsan@company.com",
      "roles": ["developer", "admin"],
      "permissions": ["read", "write", "approve"]
    }
  ]
}
```

**API设计**：
```
# 同步组织架构
POST /api/org/sync
{
  "orgs": [...],
  "users": [...]
}

# 查询用户信息
GET /api/users/{user_id}

# 查询组织架构
GET /api/orgs/{org_id}/tree
```

#### 2.3 权限集成

**权限模型**：
- **数据权限**：用户只能访问自己部门的数据
- **功能权限**：用户只能使用被授权的功能
- **操作权限**：用户只能执行被授权的操作

**实现方式**：
```
业务系统 → CoApis权限映射
├── 角色同步：业务系统角色 → CoApis角色
├── 权限同步：业务系统权限 → CoApis权限
└── 动态权限：实时查询业务系统权限
```

**权限检查流程**：
```
1. 用户发送消息
2. CoApis解析Token，获取user_id和permissions
3. 检查用户是否有权限执行该操作
4. 如果涉及数据访问，检查数据权限（部门隔离）
5. 执行操作或返回权限错误
```

---

### 3. 业务系统模块与API的MCP包装

**目标**：将业务系统的模块和API包装成MCP（Model Context Protocol）工具，供AI调用

#### 3.1 MCP工具注册

**功能清单**：
| 功能 | 说明 | 优先级 |
|------|------|--------|
| API注册 | 注册业务系统API为MCP工具 | P0 |
| 参数定义 | 定义API的输入输出参数 | P0 |
| 权限控制 | 控制哪些用户/角色可以调用该工具 | P0 |
| 调用统计 | 统计工具调用次数、成功率等 | P1 |
| 错误处理 | 统一的错误处理和重试机制 | P0 |

**MCP工具定义示例**：
```json
{
  "tool_name": "create_leave_request",
  "display_name": "创建请假申请",
  "description": "在OA系统中创建请假申请单",
  "category": "oa",
  "api_endpoint": "https://oa.company.com/api/leave/create",
  "method": "POST",
  "auth_required": true,
  "input_schema": {
    "type": "object",
    "properties": {
      "leave_type": {
        "type": "string",
        "enum": ["年假", "事假", "病假"],
        "description": "请假类型"
      },
      "start_date": {
        "type": "string",
        "format": "date",
        "description": "开始日期"
      },
      "end_date": {
        "type": "string",
        "format": "date",
        "description": "结束日期"
      },
      "reason": {
        "type": "string",
        "description": "请假原因"
      }
    },
    "required": ["leave_type", "start_date", "end_date", "reason"]
  },
  "output_schema": {
    "type": "object",
    "properties": {
      "request_id": {"type": "string"},
      "status": {"type": "string"},
      "message": {"type": "string"}
    }
  },
  "permissions": ["oa:leave:create"],
  "rate_limit": {
    "max_calls": 100,
    "period": "hour"
  }
}
```

#### 3.2 MCP工具管理

**管理界面**：
| 功能 | 说明 | 优先级 |
|------|------|--------|
| 工具列表 | 查看所有已注册的工具 | P0 |
| 工具注册 | 注册新的MCP工具 | P0 |
| 工具测试 | 测试工具是否可用 | P0 |
| 权限配置 | 配置工具的访问权限 | P0 |
| 调用日志 | 查看工具调用日志 | P1 |

**工具注册流程**：
```
1. 业务系统管理员登录CoApis管理后台
2. 进入"MCP工具管理"页面
3. 点击"注册工具"
4. 填写工具信息（名称、API地址、参数等）
5. 测试工具是否可用
6. 配置权限（哪些角色可以调用）
7. 保存并启用
```

#### 3.3 AI调用MCP工具

**调用流程**：
```
1. 用户："帮我请3天年假，下周一到下周三"
2. AI分析意图：请假申请
3. AI调用MCP工具：create_leave_request
4. CoApis执行：
   a. 检查用户权限
   b. 调用业务系统API
   c. 返回结果
5. AI回复："已为您提交请假申请，申请单号：LEA-2026-001"
```

**安全机制**：
- 参数校验：校验输入参数的格式和范围
- 权限检查：检查用户是否有权限调用该工具
- 频率限制：限制调用频率，防止滥用
- 审计日志：记录所有调用日志

---

## 二、业务层工作

### 1. 基础数据梳理

**目标**：让AI知道业务系统有什么数据、什么功能

#### 1.1 组织架构梳理

**梳理内容**：
| 数据类型 | 说明 | 示例 |
|----------|------|------|
| 组织结构 | 公司的组织架构树 | 集团 → 分公司 → 部门 → 小组 |
| 用户信息 | 用户基本信息和角色 | 用户名、邮箱、部门、角色 |
| 权限配置 | 各角色的权限 | 管理员：全部权限；普通用户：只读 |
| 数据关系 | 用户与组织的关系 | 张三属于技术部，角色是开发工程师 |

**梳理方式**：
```
方式1：导出业务系统的组织架构数据
方式2：提供API接口，CoApis实时查询
方式3：手动配置（适合小型企业）
```

**输出物**：
- 组织架构树（JSON格式）
- 用户权限映射表
- 数据权限规则

#### 1.2 业务模块梳理

**梳理内容**：
| 模块类型 | OA示例 | 项目管理示例 |
|----------|--------|--------------|
| 审批流程 | 请假、报销、出差 | 项目立项、变更审批 |
| 信息管理 | 公告、制度、知识库 | 项目文档、需求文档 |
| 任务管理 | 待办事项、日程 | 项目任务、缺陷跟踪 |
| 报表统计 | 审批统计、考勤统计 | 项目进度、团队效能 |

**梳理模板**：
```markdown
## 模块：请假申请

### 功能说明
员工提交请假申请，审批人审批

### 数据字段
- 请假类型：年假/事假/病假
- 开始日期：date
- 结束日期：date
- 请假天数：number
- 请假原因：string
- 审批人：user
- 审批状态：pending/approved/rejected

### 用户角色
- 申请人：员工
- 审批人：部门经理
- 查看权限：申请人、审批人、HR

### API接口
- POST /api/leave/create - 创建申请
- GET /api/leave/{id} - 查询申请详情
- POST /api/leave/{id}/approve - 审批通过
- POST /api/leave/{id}/reject - 审批拒绝
```

#### 1.3 数据权限梳理

**数据权限规则**：
| 规则类型 | 说明 | 示例 |
|----------|------|------|
| 部门隔离 | 只能查看本部门数据 | 张三只能查看技术部的请假记录 |
| 角色权限 | 不同角色有不同权限 | HR可以查看所有人的请假记录 |
| 数据所有者 | 只能操作自己的数据 | 只能修改自己提交的申请 |
| 审批权限 | 审批人可以查看待审批数据 | 经理可以查看待审批的请假申请 |

---

### 2. API梳理

**目标**：梳理业务系统API，包装成MCP工具

#### 2.1 API清单

**OA系统API示例**：
| API | 方法 | 说明 | MCP工具名 |
|-----|------|------|-----------|
| /api/leave/create | POST | 创建请假申请 | create_leave_request |
| /api/leave/{id} | GET | 查询请假申请 | query_leave_request |
| /api/leave/{id}/approve | POST | 审批通过 | approve_leave_request |
| /api/leave/my | GET | 我的请假记录 | list_my_leaves |
| /api/announcement/list | GET | 公告列表 | list_announcements |
| /api/announcement/{id} | GET | 公告详情 | get_announcement |
| /api/policy/search | GET | 制度检索 | search_policies |

**项目管理API示例**：
| API | 方法 | 说明 | MCP工具名 |
|-----|------|------|-----------|
| /api/project/create | POST | 创建项目 | create_project |
| /api/task/create | POST | 创建任务 | create_task |
| /api/task/{id} | GET | 查询任务 | query_task |
| /api/task/{id}/update | PUT | 更新任务 | update_task |
| /api/project/{id}/tasks | GET | 项目任务列表 | list_project_tasks |
| /api/report/weekly | GET | 周报生成 | generate_weekly_report |

#### 2.2 API参数梳理

**梳理模板**：
```json
{
  "api": "/api/leave/create",
  "method": "POST",
  "description": "创建请假申请",
  "auth_required": true,
  "input_params": [
    {
      "name": "leave_type",
      "type": "string",
      "required": true,
      "enum": ["年假", "事假", "病假"],
      "description": "请假类型"
    },
    {
      "name": "start_date",
      "type": "date",
      "required": true,
      "description": "开始日期，格式：YYYY-MM-DD"
    },
    {
      "name": "end_date",
      "type": "date",
      "required": true,
      "description": "结束日期，格式：YYYY-MM-DD"
    },
    {
      "name": "reason",
      "type": "string",
      "required": true,
      "description": "请假原因，最多200字"
    }
  ],
  "output_params": {
    "request_id": "申请单号",
    "status": "状态",
    "message": "提示信息"
  },
  "error_codes": {
    "400": "参数错误",
    "401": "未授权",
    "403": "无权限",
    "500": "服务器错误"
  }
}
```

#### 2.3 API文档生成

**生成内容**：
- API接口文档（Swagger/OpenAPI格式）
- 调用示例（curl、Python、Java）
- 错误码说明
- 权限说明

---

### 3. 嵌入模式与交互设计

**目标**：设计iframe嵌入模式和业务系统交互方式

#### 3.1 嵌入模式

**模式1：侧边栏模式**
```
┌──────────────────────────────────┐
│  业务系统页面                      │
│  ┌────────────┬─────────────────┐│
│  │            │                 ││
│  │ 业务内容   │  AI助手         ││
│  │            │  (iframe)       ││
│  │            │  宽度: 400px    ││
│  │            │                 ││
│  └────────────┴─────────────────┘│
└──────────────────────────────────┘
```

**模式2：独立窗口模式**
```
┌──────────────────┐
│  业务系统页面     │
│                  │
│                  │  ┌─────────┐
│                  │  │ AI助手  │
│                  │  │ (弹窗)  │
│                  │  └─────────┘
└──────────────────┘
```

**模式3：右下角悬浮按钮**
```
┌──────────────────┐
│  业务系统页面     │
│                  │
│                  │
│                  │      ┌───┐
│                  │      │💬│ ← 点击打开对话
└──────────────────┘      └───┘
```

#### 3.2 与业务系统交互

**交互场景**：

| 场景 | 用户操作 | AI响应 | 业务系统交互 |
|------|----------|--------|--------------|
| 创建请假申请 | "帮我请3天年假" | AI调用MCP工具 | OA系统创建申请单，返回单号 |
| 查询审批进度 | "我的请假审批到哪了" | AI查询状态 | OA系统返回审批进度 |
| 智能填单 | "我要报销差旅费" | AI引导填写 | OA系统打开报销表单，自动填充 |
| 打开业务页面 | "打开项目A的详情页" | AI发送指令 | 业务系统打开对应页面 |

**交互方式**：

**方式1：postMessage通信**
```javascript
// 业务系统监听AI消息
window.addEventListener('message', (event) => {
  if (event.data.type === 'open_page') {
    // AI请求打开业务页面
    window.location.href = event.data.url;
  }
  
  if (event.data.type === 'fill_form') {
    // AI请求填充表单
    document.getElementById('form').elements['leave_type'].value = event.data.value;
  }
});

// AI向业务系统发送消息
window.parent.postMessage({
  type: 'open_page',
  url: '/oa/leave/detail?id=123'
}, '*');
```

**方式2：回调URL**
```javascript
// AI执行操作后，跳转到业务系统页面
https://oa.company.com/leave/detail?id=123&from=ai
```

**方式3：WebSocket实时通信**
```javascript
// 业务系统和AI建立WebSocket连接
const ws = new WebSocket('wss://ai.company.com/ws');
ws.onmessage = (event) => {
  const data = JSON.parse(event.data);
  // 处理AI指令
};
```

#### 3.3 交互协议定义

**协议格式**：
```json
{
  "action": "open_page",
  "data": {
    "url": "/oa/leave/detail?id=123",
    "title": "请假详情",
    "params": {
      "highlight": "status"
    }
  },
  "timestamp": "2026-07-13T10:00:00Z",
  "request_id": "req-001"
}
```

**支持的action类型**：
| action | 说明 | 示例 |
|--------|------|------|
| open_page | 打开业务页面 | 打开请假详情页 |
| fill_form | 填充表单 | 自动填充请假单 |
| refresh_data | 刷新数据 | 刷新审批列表 |
| show_notification | 显示通知 | 显示"操作成功"通知 |
| download_file | 下载文件 | 下载生成的周报 |

---

## 三、实施计划

### 阶段1：平台能力开发（7月）

#### 第1周（7.1-7.7）
- [ ] 嵌入式UI开发（iframe模式）
- [ ] Token认证机制开发
- [ ] API Key管理

#### 第2周（7.8-7.14）
- [ ] 组织架构同步API开发
- [ ] 权限集成API开发
- [ ] MCP工具注册功能开发

#### 第3周（7.15-7.21）
- [ ] MCP工具管理界面开发
- [ ] 工具测试功能开发
- [ ] 调用统计功能开发

#### 第4周（7.22-7.31）
- [ ] PostgreSQL基础支持
- [ ] Weaviate基础支持
- [ ] 集成测试

---

### 阶段2：业务层梳理（8月）

#### 第1周（8.1-8.7）
- [ ] OA系统基础数据梳理
- [ ] OA系统API梳理
- [ ] 项目管理系统基础数据梳理

#### 第2周（8.8-8.14）
- [ ] 项目管理系统API梳理
- [ ] MCP工具定义
- [ ] 权限规则梳理

#### 第3周（8.15-8.21）
- [ ] 嵌入模式设计
- [ ] 交互协议设计
- [ ] 测试验证

#### 第4周（8.22-8.31）
- [ ] MVP版本发布
- [ ] 集成文档编写
- [ ] 部署文档编写

---

### 阶段3：集成与部署（9-11月）

#### 9月：OA集成+企业A部署
- [ ] OA系统MCP工具注册
- [ ] OA嵌入模式实现
- [ ] 企业A部署上线

#### 10月：项目管理集成+企业B部署
- [ ] 项目管理MCP工具注册
- [ ] 项目管理嵌入模式实现
- [ ] 企业B部署上线

#### 11月：场景深化+企业C部署
- [ ] 业务场景深化
- [ ] 交互优化
- [ ] 企业C部署上线

---

## 四、交付物

### 技术交付物

**平台能力**：
- 嵌入式UI（iframe模式）
- Token认证机制
- 组织架构同步API
- 权限集成API
- MCP工具注册与管理

**文档**：
- 集成开发文档
- API接口文档
- MCP工具开发指南
- 嵌入模式开发指南

### 业务交付物

**内部验证（9月）**：
- 我们的OA系统集成完成（15个MCP工具）
- 我们的项目管理系统集成完成（15个MCP工具）
- 核心场景验证通过
- 集成文档和最佳实践

**客户落地（10-11月）**：
- 客户A部署完成（集成客户A的业务系统）
- 客户B部署完成（集成客户B的业务系统）
- 客户C部署完成（集成客户C的业务系统）
- 标准化适配流程文档
- 集成模板库（支持5+种系统类型）

**知识库（12月）**：
- 核心业务文档导入知识库（300+文档）
- AI回答准确率>85%
- 用户满意度>80%

---

## 五、客户系统适配模式

### 支持的系统类型

| 系统类型 | 常见产品 | 适配方式 |
|----------|----------|----------|
| **OA系统** | 致远、泛微、蓝凌、自研系统 | 通过API集成，注册MCP工具 |
| **项目管理** | Jira、Teambition、飞书项目、自研系统 | 通过API集成，注册MCP工具 |
| **CRM系统** | Salesforce、纷享销客、自研系统 | 通过API集成，注册MCP工具 |
| **ERP系统** | SAP、用友、金蝶、自研系统 | 通过API集成，注册MCP工具 |
| **HR系统** | 北森、薪人薪事、自研系统 | 通过API集成，注册MCP工具 |

### 标准化适配流程

**1. 系统调研（1-2天）**
```
调研内容：
- 客户使用的系统类型和版本
- 系统架构和部署方式
- API接口文档
- 认证方式（API Key、OAuth等）
- 数据模型和业务流程

输出物：
- 系统调研报告
- API接口清单
- 集成可行性评估
```

**2. 数据梳理（2-3天）**
```
梳理内容：
- 组织架构同步方案
- 用户权限映射规则
- API参数定义
- 数据权限规则

输出物：
- 组织架构数据
- 用户权限映射表
- API参数定义文档
```

**3. MCP工具定制（3-5天）**
```
定制内容：
- 根据客户系统API定制MCP工具
- 定义输入输出参数
- 配置权限和频率限制
- 工具测试验证

输出物：
- MCP工具定义文件
- 工具测试报告
```

**4. 部署集成（5-7天）**
```
集成内容：
- 系统部署（Docker/Kubernetes）
- 业务系统集成配置
- 功能验证测试

输出物：
- 部署文档
- 功能验证报告
```

**5. 培训上线（2-3天）**
```
培训内容：
- 关键用户培训（30人）
- 试运行和问题修复
- 用户反馈收集

输出物：
- 培训材料
- 用户反馈报告
```

### 集成模板库

**目标**：降低后续客户集成成本，提高效率

**模板内容**：
```
集成模板库/
├── OA系统/
│   ├── 致远OA集成模板.md
│   ├── 泛微OA集成模板.md
│   ├── 蓝凌OA集成模板.md
│   └── 自研OA集成指南.md
├── 项目管理/
│   ├── Jira集成模板.md
│   ├── Teambition集成模板.md
│   ├── 飞书项目集成模板.md
│   └── 自研项目系统集成指南.md
├── CRM系统/
│   ├── Salesforce集成模板.md
│   ├── 纷享销客集成模板.md
│   └── 自研CRM集成指南.md
└── 通用模板/
    ├── MCP工具定义模板.json
    ├── API参数梳理模板.md
    └── 权限配置模板.md
```

**模板价值**：
- 新客户集成时间缩短50%
- 减少重复工作
- 保证集成质量
- 便于知识传承

---

**文档维护**：根据实际进展每月更新  
**下次更新**：2026-08-01
