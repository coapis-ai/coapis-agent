# 卡片化工作台设计方案

## 🎯 核心理念

### 从"聊天工具"到"业务工作台"

**传统思维**：
```
聊天界面 + 工作空间侧边栏
```

**新思维**：
```
工作台 = 多种功能卡片的自由组合
├─ 💬 聊天卡片（默认）
├─ 📁 文件管理卡片
├─ 📊 数据图表卡片
├─ 📚 知识库卡片
├─ 📝 笔记卡片
├─ 📈 项目看板卡片
└─ ... 可扩展
```

---

## 💡 设计灵感来源

### 1. 企业级应用特征

**领导视角**：
- ✅ 快速查看业务数据（图表、仪表盘）
- ✅ 审批流程（待办事项）
- ✅ 团队动态（消息、进度）
- ✅ 决策支持（AI 分析）

**员工视角**：
- ✅ 日常办公（聊天、文件）
- ✅ 任务协作（看板、日历）
- ✅ 知识查询（知识库、搜索）
- ✅ 工具使用（AI 助手）

**系统整合**：
- ✅ ERP 数据展示
- ✅ CRM 客户管理
- ✅ OA 审批流程
- ✅ BI 报表分析

### 2. 卡片化设计的优势

**灵活性**：
- 用户可以自由组合需要的卡片
- 不同角色有不同的默认布局
- 支持保存多个工作台模板

**可扩展性**：
- 新功能 = 新卡片类型
- 第三方系统 = 第三方卡片
- 插件化架构

**统一体验**：
- 所有卡片遵循统一设计规范
- 统一的交互模式
- 统一的数据流

---

## 🎨 界面设计

### 布局方案

#### 方案1：网格式布局（推荐 ⭐）

```
┌─────────────────────────────────────────────────────────┐
│  Header（用户信息、全局搜索、通知、设置）                    │
├──────────┬──────────────────────────────────────────────┤
│          │                                              │
│  侧边栏   │           工作区（卡片网格）                   │
│          │   ┌──────────────┬──────────────┐           │
│ 🏠 首页   │   │ 💬 聊天       │ 📊 数据图表   │           │
│ 📁 项目   │   │              │              │           │
│ 📚 知识   │   │              │              │           │
│ 🎯 任务   │   ├──────────────┼──────────────┤           │
│ ⚙️ 设置   │   │ 📁 文件管理   │ 📈 项目看板   │           │
│          │   │              │              │           │
│          │   │              │              │           │
│          │   └──────────────┴──────────────┘           │
├──────────┴──────────────────────────────────────────────┤
│  快捷操作栏（常用功能、最近使用）                            │
└─────────────────────────────────────────────────────────┘
```

**特点**：
- ✅ 卡片可自由拖拽排列
- ✅ 支持调整卡片大小
- ✅ 类似 Windows 10 磁贴、Notion 页面

#### 方案2：标签页式布局

```
┌─────────────────────────────────────────────────────────┐
│  Header                                                 │
├──────────┬──────────────────────────────────────────────┤
│          │  [聊天] [文件] [数据] [知识] [+添加标签]       │
│  侧边栏   ├──────────────────────────────────────────────┤
│          │                                              │
│          │           当前标签的内容                       │
│          │                                              │
│          │                                              │
├──────────┴──────────────────────────────────────────────┤
│  快捷操作栏                                              │
└─────────────────────────────────────────────────────────┘
```

**特点**：
- ✅ 每个标签是一个独立的工作区
- ✅ 支持保存多个工作区配置
- ✅ 类似浏览器标签页

#### 方案3：分屏式布局

```
┌─────────────────────────────────────────────────────────┐
│  Header                                                 │
├──────────┬──────────────────────────┬──────────────────┤
│          │                          │                  │
│  侧边栏   │      主工作区              │    辅助面板      │
│          │   （大卡片或卡片组）         │  （小卡片列表）   │
│          │                          │  ┌────────────┐ │
│          │                          │  │ 💬 快速聊天 │ │
│          │                          │  ├────────────┤ │
│          │                          │  │ 📊 数据概览 │ │
│          │                          │  ├────────────┤ │
│          │                          │  │ 📝 待办事项 │ │
│          │                          │  └────────────┘ │
├──────────┴──────────────────────────┴──────────────────┤
│  快捷操作栏                                              │
└─────────────────────────────────────────────────────────┘
```

**特点**：
- ✅ 主次分明
- ✅ 适合深度工作
- ✅ 类似 VS Code 布局

---

## 🔧 卡片类型设计

### 核心卡片类型

#### 1. 💬 聊天卡片

```typescript
interface ChatCardProps {
  agentId: string;
  conversationId?: string;
  compact?: boolean;  // 紧凑模式（小卡片）
  height?: 'auto' | 'fixed';
  
  // 卡片功能
  showInput?: boolean;      // 显示输入框
  showHistory?: boolean;    // 显示历史记录
  showFiles?: boolean;      // 显示文件附件
  
  // 卡片操作
  onMaximize?: () => void;  // 最大化
  onPopout?: () => void;    // 弹出窗口
  onShare?: () => void;     // 分享对话
}
```

**视图模式**：
- **完整模式**：完整的聊天界面
- **紧凑模式**：只显示最近几条消息
- **只读模式**：用于展示对话记录

**卡片操作**：
- 🔍 搜索对话
- 📤 分享对话
- 🔗 关联文件/知识
- ⬜ 最大化/全屏
- 🖼️ 弹出窗口

#### 2. 📊 数据图表卡片

```typescript
interface DataChartCardProps {
  dataSource: 'erp' | 'crm' | 'bi' | 'custom';
  chartType: 'line' | 'bar' | 'pie' | 'table';
  metrics: string[];
  filters?: FilterConfig;
  
  // 交互功能
  drillDown?: boolean;      // 支持下钻
  exportable?: boolean;     // 支持导出
  refreshable?: boolean;    // 支持刷新
  
  // AI 增强
  aiAnalysis?: boolean;     // AI 自动分析
  aiInsights?: boolean;     // AI 洞察建议
}
```

**数据源支持**：
- 📊 **BI 系统**：连接内部 BI 平台
- 📈 **业务系统**：ERP、CRM 数据
- 🤖 **AI 分析**：自然语言查询数据

**示例场景**：
```
领导打开工作台：
- 左上：销售数据图表（实时更新）
- 右上：客户分布地图
- 左下：AI 分析洞察（自动生成）
- 右下：待审批事项列表
```

#### 3. 📁 文件管理卡片

```typescript
interface FileManagerCardProps {
  path?: string;
  viewMode: 'list' | 'grid' | 'tree';
  selectedFiles?: string[];
  
  // 功能
  uploadable?: boolean;
  searchable?: boolean;
  previewable?: boolean;
  
  // 交互
  onFileSelect?: (file: File) => void;
  onFileDrop?: (files: File[]) => void;
}
```

**特点**：
- 支持拖拽文件到聊天卡片
- 文件预览
- 快速搜索

#### 4. 📚 知识库卡片

```typescript
interface KnowledgeBaseCardProps {
  category?: string;
  searchQuery?: string;
  viewMode: 'list' | 'card' | 'tree';
  
  // 功能
  searchable?: boolean;
  editable?: boolean;
  aiAssist?: boolean;  // AI 辅助编辑
}
```

**特点**：
- 快速搜索知识
- AI 辅助总结
- 关联聊天对话

#### 5. 🎯 任务看板卡片

```typescript
interface TaskBoardCardProps {
  projectId?: string;
  viewMode: 'kanban' | 'list' | 'calendar';
  filter?: TaskFilter;
  
  // 功能
  creatable?: boolean;
  assignable?: boolean;
  aiAssist?: boolean;  // AI 自动分解任务
}
```

**特点**：
- 任务可视化
- AI 自动分解任务
- 与聊天联动（从对话创建任务）

#### 6. 📝 笔记卡片

```typescript
interface NoteCardProps {
  noteId?: string;
  mode: 'edit' | 'preview';
  
  // 功能
  aiAssist?: boolean;  // AI 辅助写作
  template?: string;   // 笔记模板
}
```

**特点**：
- Markdown 编辑
- AI 辅助写作
- 关联聊天记录

---

## 🔗 卡片间联动

### 1. 拖拽交互

```typescript
// 拖拽文件到聊天卡片
用户: 在文件管理卡片中选择文件
用户: 拖拽文件到聊天卡片的输入框
系统: 文件自动附加到消息
系统: 智能体读取文件并回复

// 拖拽数据图表到聊天
用户: 在数据图表卡片中选择图表
用户: 拖拽到聊天卡片
系统: 图表截图 + 数据摘要附加到消息
系统: 智能体分析数据并给出洞察
```

### 2. 上下文传递

```typescript
// 全局上下文
interface GlobalContext {
  selectedProject?: Project;
  selectedFiles?: File[];
  selectedKnowledge?: KnowledgeItem[];
  activeTasks?: Task[];
  currentData?: DataSnapshot;
}

// 卡片间共享
用户: 在文件管理卡片选择"需求文档.docx"
系统: 全局上下文更新
用户: 切换到聊天卡片
系统: 输入框自动提示"是否分析需求文档？"
```

### 3. 智能推荐

```typescript
// AI 根据上下文推荐操作
用户: 在聊天卡片中讨论项目进度
系统: AI 检测到"进度"关键词
系统: 自动推荐打开"项目看板卡片"
系统: 自动推荐关联相关"任务卡片"

// 智能工作流
用户: 在聊天卡片中说"帮我写一份周报"
系统: AI 自动收集本周数据
  - 从数据图表卡片获取销售数据
  - 从任务看板卡片获取完成情况
  - 从笔记卡片获取会议记录
系统: 生成周报草稿，在笔记卡片中打开
```

---

## 👥 多角色工作台

### 领导工作台

```typescript
const leaderWorkbench = {
  name: '领导工作台',
  layout: 'grid',
  cards: [
    {
      type: 'data-chart',
      position: { x: 0, y: 0, w: 2, h: 2 },
      config: {
        dataSource: 'erp',
        chartType: 'line',
        metrics: ['sales', 'orders'],
        aiAnalysis: true,
      },
    },
    {
      type: 'task-board',
      position: { x: 2, y: 0, w: 1, h: 2 },
      config: {
        viewMode: 'list',
        filter: { status: 'pending', priority: 'high' },
      },
    },
    {
      type: 'chat',
      position: { x: 0, y: 2, w: 2, h: 2 },
      config: {
        agentId: 'executive-assistant',
        compact: false,
      },
    },
    {
      type: 'knowledge-base',
      position: { x: 2, y: 2, w: 1, h: 2 },
      config: {
        category: 'reports',
        viewMode: 'list',
      },
    },
  ],
};
```

**界面布局**：
```
┌──────────────────┬──────────┐
│ 📊 销售数据图表   │ 🎯 待办   │
│ （AI 分析）      │ （高优先）│
├──────────────────┼──────────┤
│ 💬 行政助理聊天   │ 📚 报告   │
│                  │          │
└──────────────────┴──────────┘
```

### 研发工作台

```typescript
const developerWorkbench = {
  name: '研发工作台',
  layout: 'grid',
  cards: [
    {
      type: 'chat',
      position: { x: 0, y: 0, w: 2, h: 3 },
      config: {
        agentId: 'code-assistant',
        showFiles: true,
      },
    },
    {
      type: 'file-manager',
      position: { x: 2, y: 0, w: 1, h: 2 },
      config: {
        path: '/projects/my-app',
        viewMode: 'tree',
      },
    },
    {
      type: 'task-board',
      position: { x: 2, y: 2, w: 1, h: 1 },
      config: {
        viewMode: 'kanban',
        filter: { assignee: 'me' },
      },
    },
  ],
};
```

**界面布局**：
```
┌──────────────────┬──────────┐
│ 💬 代码助手聊天   │ 📁 项目  │
│                  │ 文件树    │
│                  ├──────────┤
│                  │ 🎯 任务   │
│                  │ 看板      │
└──────────────────┴──────────┘
```

### 运营工作台

```typescript
const operatorWorkbench = {
  name: '运营工作台',
  layout: 'grid',
  cards: [
    {
      type: 'data-chart',
      position: { x: 0, y: 0, w: 2, h: 2 },
      config: {
        dataSource: 'crm',
        chartType: 'bar',
        metrics: ['users', 'conversion'],
      },
    },
    {
      type: 'chat',
      position: { x: 2, y: 0, w: 1, h: 2 },
      config: {
        agentId: 'data-analyst',
      },
    },
    {
      type: 'knowledge-base',
      position: { x: 0, y: 2, w: 3, h: 1 },
      config: {
        category: 'operations',
        viewMode: 'card',
      },
    },
  ],
};
```

**界面布局**：
```
┌──────────────────┬──────────┐
│ 📊 用户数据图表   │ 💬 数据  │
│                  │ 分析师   │
├──────────────────┴──────────┤
│ 📚 运营知识库               │
└─────────────────────────────┘
```

---

## 🏗️ 技术架构

### 整体架构

```
Workbench
├── Layout Engine          # 布局引擎
│   ├── GridLayout         # 网格布局
│   ├── TabLayout          # 标签页布局
│   └── SplitLayout        # 分屏布局
│
├── Card System            # 卡片系统
│   ├── CardRegistry       # 卡片注册表
│   ├── CardRenderer       # 卡片渲染器
│   ├── CardStateManager   # 卡片状态管理
│   └── CardInteraction    # 卡片交互
│
├── Context System         # 上下文系统
│   ├── GlobalContext      # 全局上下文
│   ├── CardContext        # 卡片上下文
│   └── ContextSync        # 上下文同步
│
├── Integration Layer      # 集成层
│   ├── ERPConnector       # ERP 连接器
│   ├── CRMConnector       # CRM 连接器
│   ├── BIConnector        # BI 连接器
│   └── CustomConnector    # 自定义连接器
│
└── AI Enhancement         # AI 增强
    ├── ContextAnalyzer    # 上下文分析
    ├── SmartRecommend     # 智能推荐
    └── AutoWorkflow       # 自动工作流
```

### 核心模块

#### 1. 卡片注册表

```typescript
// 卡片类型定义
interface CardType {
  id: string;
  name: string;
  icon: React.ReactNode;
  description: string;
  defaultProps: Partial<CardProps>;
  component: React.ComponentType<CardProps>;
  defaultSize: { w: number; h: number };
  minSize: { w: number; h: number };
  maxSize?: { w: number; h: number };
}

// 卡片注册
class CardRegistry {
  private cards: Map<string, CardType> = new Map();
  
  register(card: CardType) {
    this.cards.set(card.id, card);
  }
  
  get(id: string): CardType | undefined {
    return this.cards.get(id);
  }
  
  getAll(): CardType[] {
    return Array.from(this.cards.values());
  }
}

// 注册卡片
registry.register({
  id: 'chat',
  name: '聊天',
  icon: <MessageOutlined />,
  description: 'AI 智能对话',
  component: ChatCard,
  defaultSize: { w: 2, h: 3 },
  minSize: { w: 1, h: 2 },
});
```

#### 2. 布局引擎

```typescript
// 使用 react-grid-layout
import GridLayout from 'react-grid-layout';

const WorkbenchLayout: React.FC = () => {
  const [layout, setLayout] = useState<Layout[]>([]);
  const [cards, setCards] = useState<CardInstance[]>([]);
  
  const handleLayoutChange = (newLayout: Layout[]) => {
    setLayout(newLayout);
    saveLayout(newLayout);
  };
  
  return (
    <GridLayout
      layout={layout}
      cols={12}
      rowHeight={100}
      width={1200}
      onLayoutChange={handleLayoutChange}
      draggableHandle=".card-header"
    >
      {cards.map(card => (
        <div key={card.id}>
          <CardRenderer card={card} />
        </div>
      ))}
    </GridLayout>
  );
};
```

#### 3. 上下文系统

```typescript
// 全局上下文状态
interface GlobalContextState {
  selectedProject?: Project;
  selectedFiles: File[];
  selectedKnowledge: KnowledgeItem[];
  activeFilters: Record<string, any>;
  currentData: Record<string, any>;
}

// 上下文 Provider
const GlobalContextProvider: React.FC = ({ children }) => {
  const [context, setContext] = useState<GlobalContextState>({
    selectedFiles: [],
    selectedKnowledge: [],
    activeFilters: {},
    currentData: {},
  });
  
  const updateContext = useCallback((updates: Partial<GlobalContextState>) => {
    setContext(prev => ({ ...prev, ...updates }));
  }, []);
  
  return (
    <GlobalContext.Provider value={{ context, updateContext }}>
      {children}
    </GlobalContext.Provider>
  );
};

// 卡片使用上下文
const ChatCard: React.FC<CardProps> = () => {
  const { context } = useGlobalContext();
  
  // 根据上下文智能提示
  useEffect(() => {
    if (context.selectedFiles.length > 0) {
      showSuggestion(`是否分析选中的 ${context.selectedFiles.length} 个文件？`);
    }
  }, [context.selectedFiles]);
  
  return <ChatInterface />;
};
```

#### 4. 卡片间通信

```typescript
// 事件总线
class CardEventBus {
  private listeners: Map<string, Set<Function>> = new Map();
  
  on(event: string, callback: Function) {
    if (!this.listeners.has(event)) {
      this.listeners.set(event, new Set());
    }
    this.listeners.get(event)!.add(callback);
  }
  
  emit(event: string, data: any) {
    const callbacks = this.listeners.get(event);
    if (callbacks) {
      callbacks.forEach(cb => cb(data));
    }
  }
}

// 使用示例
const bus = new CardEventBus();

// 文件卡片发布事件
bus.emit('file:selected', { file: selectedFile });

// 聊天卡片订阅事件
bus.on('file:selected', ({ file }) => {
  showFileAttachmentSuggestion(file);
});
```

---

## 🔌 第三方集成

### ERP 系统集成

```typescript
interface ERPConnector {
  // 连接配置
  config: {
    endpoint: string;
    apiKey: string;
    syncInterval: number;
  };
  
  // 数据卡片
  cards: {
    salesChart: DataChartCard;
    inventoryTable: DataTableCard;
    orderList: ListCard;
  };
  
  // API
  fetchSalesData(): Promise<SalesData>;
  fetchInventory(): Promise<Inventory>;
  createOrder(order: Order): Promise<void>;
}

// 使用示例
<ERPConnector
  endpoint="https://erp.company.com/api"
  apiKey="xxx"
>
  <DataChartCard
    dataSource="erp:sales"
    metrics={['revenue', 'orders']}
    refreshInterval={300000}
  />
</ERPConnector>
```

### BI 系统集成

```typescript
interface BIConnector {
  // 嵌入 BI 报表
  embedDashboard(dashboardId: string): React.ReactNode;
  
  // 自然语言查询
  query(question: string): Promise<QueryResult>;
}

// 使用示例
<BICard
  connector="powerbi"
  dashboardId="sales-overview"
  aiQuery={true}
/>
```

### 自定义系统

```typescript
// 自定义卡片开发
class CustomCard implements CardType {
  id = 'custom-my-system';
  name = '我的系统';
  
  async render() {
    // 调用自定义 API
    const data = await fetch('https://my-system.com/api/data');
    
    return (
      <CustomUI data={data} />
    );
  }
}

// 注册自定义卡片
registry.register(new CustomCard());
```

---

## 🎯 实施路线图

### 阶段一：核心框架（2-3周）

**目标**：搭建卡片化工作台基础

**功能**：
- ✅ 布局引擎（网格布局）
- ✅ 卡片系统基础架构
- ✅ 卡片注册表
- ✅ 核心卡片：聊天、文件管理

**技术选型**：
- `react-grid-layout` - 布局引擎
- `dnd-kit` - 拖拽交互
- `zustand` - 状态管理

### 阶段二：核心卡片（3-4周）

**目标**：完善核心卡片功能

**功能**：
- ✅ 聊天卡片（增强版）
- ✅ 文件管理卡片
- ✅ 知识库卡片
- ✅ 任务看板卡片
- ✅ 笔记卡片

**联动功能**：
- ✅ 卡片间拖拽
- ✅ 全局上下文
- ✅ 智能推荐

### 阶段三：数据集成（2-3周）

**目标**：支持外部系统数据

**功能**：
- ✅ 数据图表卡片
- ✅ ERP 连接器
- ✅ CRM 连接器
- ✅ BI 系统集成

**AI 增强**：
- ✅ 自然语言查询数据
- ✅ AI 数据分析
- ✅ 智能洞察

### 阶段四：高级功能（持续）

**目标**：企业级功能完善

**功能**：
- ✅ 多角色工作台模板
- ✅ 权限管理
- ✅ 审计日志
- ✅ 插件系统

**优化**：
- ✅ 性能优化
- ✅ 移动端适配
- ✅ 用户反馈迭代

---

## 📊 成本与收益分析

### 开发成本

| 阶段 | 工作量 | 时间 |
|------|--------|------|
| 阶段一：核心框架 | 2-3人月 | 2-3周 |
| 阶段二：核心卡片 | 3-4人月 | 3-4周 |
| 阶段三：数据集成 | 2-3人月 | 2-3周 |
| 阶段四：高级功能 | 3-4人月 | 持续 |
| **总计** | **10-14人月** | **7-10周** |

### 收益预期

**用户体验**：
- ✅ 一站式工作台，减少系统切换
- ✅ 个性化定制，提升效率
- ✅ 智能联动，降低操作成本

**业务价值**：
- ✅ 整合企业系统，数据统一展示
- ✅ 多角色支持，满足不同需求
- ✅ AI 增强，提升决策效率

**技术价值**：
- ✅ 插件化架构，易于扩展
- ✅ 统一体验，降低维护成本
- ✅ 第三方集成，生态开放

---

## ✅ 总结

### 核心优势

1. **卡片化设计**：
   - ✅ 灵活组合，自由定制
   - ✅ 统一体验，易于学习
   - ✅ 插件化，易于扩展

2. **多角色支持**：
   - ✅ 领导：数据概览、决策支持
   - ✅ 员工：日常办公、协作工具
   - ✅ 开发：代码助手、项目管理

3. **系统集成**：
   - ✅ ERP、CRM、BI 等企业系统
   - ✅ 数据统一展示
   - ✅ AI 智能分析

4. **AI 增强**：
   - ✅ 智能推荐
   - ✅ 自动工作流
   - ✅ 自然语言交互

### 推荐方案

**推荐采用卡片化工作台方案**

**理由**：
1. ✅ 符合企业级应用需求
2. ✅ 支持多角色、多场景
3. ✅ 易于集成第三方系统
4. ✅ 扩展性强，可持续演进

### 实施建议

1. **分阶段实施**：先核心框架，再逐步完善
2. **用户参与**：早期引入用户反馈，快速迭代
3. **模板优先**：提供预设工作台模板，降低学习成本
4. **开放生态**：提供卡片开发 SDK，鼓励第三方开发

---

**这是一个面向未来的企业级工作台设计，能够满足当前需求，并为未来发展预留空间。**
