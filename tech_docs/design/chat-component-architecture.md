# 聊天界面组件化架构设计

## 🎯 设计目标

**将聊天界面组件化，支持多种场景复用**：
- ✅ 独立聊天页面（当前方案3）
- ✅ 嵌入式聊天（方案1）
- ✅ 卡片式聊天（方案2）
- ✅ 移动端聊天
- ✅ 其他自定义场景

---

## 📐 组件架构

### 架构总览

```
┌─────────────────────────────────────────────────────────┐
│  聊天组件体系                                            │
├─────────────────────────────────────────────────────────┤
│                                                         │
│  基础组件层（可独立使用）                                │
│  ├─ ChatMessage (消息组件)                              │
│  ├─ ChatInput (输入框组件)                              │
│  ├─ ChatToolbar (工具栏组件)                            │
│  ├─ FilePicker (文件选择器)                             │
│  ├─ KnowledgePicker (知识库选择器)                      │
│  └─ ReferenceHint (引用提示)                            │
│                                                         │
│  组合组件层（基础组件组合）                              │
│  ├─ ChatCore (核心聊天：消息列表+输入框)                │
│  ├─ ChatWithToolbar (带工具栏的聊天)                    │
│  ├─ ChatEmbedded (嵌入式聊天)                           │
│  └─ ChatCard (卡片式聊天)                               │
│                                                         │
│  场景组件层（完整场景）                                  │
│  ├─ ChatPage (独立聊天页面)                             │
│  ├─ ChatWidget (浮动聊天窗口)                           │
│  └─ ChatDrawer (抽屉式聊天)                             │
│                                                         │
└─────────────────────────────────────────────────────────┘
```

---

## 🧩 基础组件设计

### 1. ChatMessage（消息组件）

```typescript
// 单条消息的展示组件
interface ChatMessageProps {
  message: Message;
  showAvatar?: boolean;
  showTimestamp?: boolean;
  enableMarkdown?: boolean;
  enableCodeHighlight?: boolean;
  onReferenceClick?: (ref: Reference) => void;
}

// 使用示例
<ChatMessage
  message={msg}
  showAvatar={true}
  enableMarkdown={true}
  onReferenceClick={handleReferenceClick}
/>
```

**特性**：
- 支持Markdown渲染
- 支持代码高亮
- 支持引用追踪
- 支持头像显示
- 支持时间戳

---

### 2. ChatInput（输入框组件）

```typescript
// 输入框组件
interface ChatInputProps {
  placeholder?: string;
  maxLength?: number;
  enableVoice?: boolean;
  enableAttachment?: boolean;
  onSend: (message: string, attachments?: File[]) => void;
  onTyping?: () => void;
}

// 使用示例
<ChatInput
  placeholder="请输入消息..."
  enableAttachment={true}
  onSend={handleSend}
/>
```

**特性**：
- 支持多行输入
- 支持快捷键发送
- 支持语音输入
- 支持文件拖拽
- 支持粘贴图片

---

### 3. ChatToolbar（工具栏组件）

```typescript
// 工具栏组件
interface ChatToolbarProps {
  buttons?: ToolbarButton[];
  references?: Reference[];
  onFilePicker?: () => void;
  onKnowledgePicker?: () => void;
  onRemoveReference?: (id: string) => void;
}

interface ToolbarButton {
  key: string;
  icon: React.ReactNode;
  label?: string;
  onClick: () => void;
  disabled?: boolean;
}

// 使用示例
<ChatToolbar
  references={currentReferences}
  onFilePicker={openFilePicker}
  onKnowledgePicker={openKnowledgePicker}
  onRemoveReference={removeReference}
/>
```

**特性**：
- 可配置按钮
- 显示当前引用
- 支持自定义工具
- 响应式布局

---

### 4. FilePicker（文件选择器）

```typescript
// 文件选择器
interface FilePickerProps {
  visible: boolean;
  mode?: 'modal' | 'drawer' | 'dropdown';
  recentFiles?: File[];
  onSearch?: (keyword: string) => Promise<File[]>;
  onSelect: (files: File[]) => void;
  onClose: () => void;
}

// 使用示例
<FilePicker
  visible={filePickerOpen}
  mode="drawer"
  recentFiles={recentFiles}
  onSearch={searchFiles}
  onSelect={handleFileSelect}
  onClose={closeFilePicker}
/>
```

**特性**：
- 支持多种展示模式
- 支持搜索
- 支持最近使用
- 支持多选
- 支持预览

---

### 5. ReferenceHint（引用提示）

```typescript
// 引用提示组件
interface ReferenceHintProps {
  references: Reference[];
  onRemove: (id: string) => void;
  onPreview?: (ref: Reference) => void;
}

// 使用示例
<ReferenceHint
  references={selectedReferences}
  onRemove={removeReference}
  onPreview={previewFile}
/>
```

**特性**：
- 显示已引用文件
- 一键移除
- 支持预览
- 标签式展示

---

## 🔧 组合组件设计

### 1. ChatCore（核心聊天组件）

```typescript
// 核心聊天组件：消息列表 + 输入框
interface ChatCoreProps {
  messages: Message[];
  onSend: (message: string) => void;
  loading?: boolean;
  showAvatar?: boolean;
  inputPlaceholder?: string;
}

// 使用示例
<ChatCore
  messages={chatMessages}
  onSend={handleSend}
  loading={isLoading}
  showAvatar={true}
/>
```

**适用场景**：
- 简单聊天场景
- 不需要文件引用的场景
- 移动端聊天

---

### 2. ChatWithToolbar（带工具栏的聊天）

```typescript
// 带工具栏的聊天组件（混合方案）
interface ChatWithToolbarProps {
  messages: Message[];
  onSend: (message: string, fileIds?: string[], knowledgeIds?: string[]) => void;
  enableFilePicker?: boolean;
  enableKnowledgePicker?: boolean;
  enableSmartSuggestion?: boolean;
}

// 使用示例
<ChatWithToolbar
  messages={chatMessages}
  onSend={handleSend}
  enableFilePicker={true}
  enableKnowledgePicker={true}
  enableSmartSuggestion={true}
/>
```

**适用场景**：
- 独立聊天页面
- 需要文件引用的场景
- 需要知识库查询的场景

**实现**：

```typescript
export function ChatWithToolbar(props: ChatWithToolbarProps) {
  const [filePickerOpen, setFilePickerOpen] = useState(false);
  const [knowledgePickerOpen, setKnowledgePickerOpen] = useState(false);
  const [references, setReferences] = useState<Reference[]>([]);

  const handleSend = (message: string) => {
    const fileIds = references.filter(r => r.type === 'file').map(r => r.id);
    const knowledgeIds = references.filter(r => r.type === 'knowledge').map(r => r.id);
    props.onSend(message, fileIds, knowledgeIds);
    setReferences([]); // 清空引用
  };

  return (
    <div className="chat-with-toolbar">
      {/* 消息列表 */}
      <ChatMessageList messages={props.messages} />

      {/* 引用提示 */}
      {references.length > 0 && (
        <ReferenceHint
          references={references}
          onRemove={(id) => setReferences(refs => refs.filter(r => r.id !== id))}
        />
      )}

      {/* 输入框 + 工具栏 */}
      <div className="chat-input-area">
        <ChatInput
          placeholder="请输入消息..."
          onSend={handleSend}
        />
        <ChatToolbar
          references={references}
          onFilePicker={() => setFilePickerOpen(true)}
          onKnowledgePicker={() => setKnowledgePickerOpen(true)}
          onRemoveReference={(id) => setReferences(refs => refs.filter(r => r.id !== id))}
        />
      </div>

      {/* 文件选择器 */}
      {props.enableFilePicker && (
        <FilePicker
          visible={filePickerOpen}
          mode="drawer"
          onSelect={(files) => {
            setReferences([...references, ...files.map(f => ({
              id: f.id,
              type: 'file' as const,
              name: f.name,
            }))]);
            setFilePickerOpen(false);
          }}
          onClose={() => setFilePickerOpen(false)}
        />
      )}

      {/* 知识库选择器 */}
      {props.enableKnowledgePicker && (
        <KnowledgePicker
          visible={knowledgePickerOpen}
          mode="drawer"
          onSelect={(items) => {
            setReferences([...references, ...items.map(k => ({
              id: k.id,
              type: 'knowledge' as const,
              name: k.name,
            }))]);
            setKnowledgePickerOpen(false);
          }}
          onClose={() => setKnowledgePickerOpen(false)}
        />
      )}
    </div>
  );
}
```

---

### 3. ChatEmbedded（嵌入式聊天）

```typescript
// 嵌入式聊天组件
interface ChatEmbeddedProps {
  token: string;
  agentId: string;
  contextProvider?: () => any;
  apis?: Record<string, Function>;
  theme?: 'light' | 'dark';
  position?: 'bottom-right' | 'bottom-left' | 'custom';
}

// 使用示例
<ChatEmbedded
  token="user-token"
  agentId="oa-assistant"
  contextProvider={() => ({
    currentPage: window.location.pathname,
    pageData: extractPageData(),
  })}
  apis={{
    'approval.getPending': async () => { /* ... */ },
    'approval.approve': async (ids) => { /* ... */ },
  }}
  theme="light"
  position="bottom-right"
/>
```

**适用场景**：
- 嵌入到第三方系统（OA/ERP/CRM）
- 浮动窗口
- 小窗口聊天

**实现**：

```typescript
export function ChatEmbedded(props: ChatEmbeddedProps) {
  const [isOpen, setIsOpen] = useState(false);
  const [messages, setMessages] = useState<Message[]>([]);

  // 自动上下文注入
  useEffect(() => {
    if (props.contextProvider && isOpen) {
      const context = props.contextProvider();
      // 注入到AI上下文
      injectContext(context);
    }
  }, [isOpen, props.contextProvider]);

  return (
    <>
      {/* 浮动按钮 */}
      <FloatButton
        icon={<RobotOutlined />}
        onClick={() => setIsOpen(!isOpen)}
        style={{ position: 'fixed', [props.position]: '20px' }}
      />

      {/* 聊天窗口 */}
      {isOpen && (
        <div className="chat-embedded-window">
          <ChatCore
            messages={messages}
            onSend={handleSend}
            showAvatar={false}
          />
        </div>
      )}
    </>
  );
}
```

---

### 4. ChatCard（卡片式聊天）

```typescript
// 卡片式聊天组件
interface ChatCardProps {
  agentId: string;
  title?: string;
  collapsed?: boolean;
  onCollapse?: (collapsed: boolean) => void;
}

// 使用示例
<ChatCard
  agentId="sales-assistant"
  title="销售助手"
  collapsed={isCollapsed}
  onCollapse={setIsCollapsed}
/>
```

**适用场景**：
- 工作台卡片
- 侧边栏聊天
- 小尺寸聊天

**实现**：

```typescript
export function ChatCard(props: ChatCardProps) {
  const [messages, setMessages] = useState<Message[]>([]);
  const [collapsed, setCollapsed] = useState(props.collapsed || false);

  return (
    <Card
      title={props.title || 'AI助手'}
      extra={
        <Button
          type="text"
          icon={collapsed ? <DownOutlined /> : <UpOutlined />}
          onClick={() => setCollapsed(!collapsed)}
        />
      }
      className="chat-card"
    >
      {!collapsed && (
        <ChatCore
          messages={messages}
          onSend={handleSend}
          showAvatar={false}
          inputPlaceholder="问问AI..."
        />
      )}
    </Card>
  );
}
```

---

## 🎨 场景组件设计

### 1. ChatPage（独立聊天页面）

```typescript
// 独立聊天页面
export function ChatPage() {
  const { agentId } = useParams();
  const [messages, setMessages] = useState<Message[]>([]);

  return (
    <div className="chat-page">
      <PageHeader title="智能助手" />
      <ChatWithToolbar
        messages={messages}
        onSend={handleSend}
        enableFilePicker={true}
        enableKnowledgePicker={true}
        enableSmartSuggestion={true}
      />
    </div>
  );
}
```

---

### 2. ChatWidget（浮动聊天窗口）

```typescript
// 浮动聊天窗口（SDK）
export function ChatWidget(props: ChatWidgetProps) {
  return (
    <ChatEmbedded
      {...props}
      position="bottom-right"
    />
  );
}

// SDK使用
CoApis.init({
  token: 'user-token',
  agent: 'assistant',
});
```

---

### 3. ChatDrawer（抽屉式聊天）

```typescript
// 抽屉式聊天
export function ChatDrawer(props: ChatDrawerProps) {
  const [visible, setVisible] = useState(false);

  return (
    <>
      <Button onClick={() => setVisible(true)}>打开AI助手</Button>
      <Drawer
        title="AI助手"
        placement="right"
        open={visible}
        onClose={() => setVisible(false)}
        width={400}
      >
        <ChatCore
          messages={messages}
          onSend={handleSend}
        />
      </Drawer>
    </>
  );
}
```

---

## 📊 组件依赖关系

```
ChatPage (独立页面)
└─ ChatWithToolbar (带工具栏)
   ├─ ChatMessageList (消息列表)
   │  └─ ChatMessage (消息组件)
   ├─ ChatInput (输入框)
   ├─ ChatToolbar (工具栏)
   ├─ ReferenceHint (引用提示)
   ├─ FilePicker (文件选择器)
   └─ KnowledgePicker (知识库选择器)

ChatEmbedded (嵌入式)
└─ FloatButton + ChatCore
   ├─ ChatMessageList
   └─ ChatInput

ChatCard (卡片式)
└─ Card + ChatCore
   ├─ ChatMessageList (简化版)
   └─ ChatInput (简化版)
```

---

## 🚀 实施计划

### 阶段1：基础组件（5天）

**Day 1-2**：
- [ ] ChatMessage 组件
- [ ] ChatInput 组件
- [ ] ChatMessageList 组件

**Day 3-4**：
- [ ] ChatToolbar 组件
- [ ] ReferenceHint 组件

**Day 5**：
- [ ] FilePicker 组件
- [ ] KnowledgePicker 组件

---

### 阶段2：组合组件（7天）

**Day 6-7**：
- [ ] ChatCore 组件
- [ ] 状态管理（chatStore）

**Day 8-10**：
- [ ] ChatWithToolbar 组件
- [ ] 文件引用功能
- [ ] 知识库引用功能

**Day 11-12**：
- [ ] ChatEmbedded 组件
- [ ] 浮动窗口
- [ ] 上下文注入

**Day 13**：
- [ ] ChatCard 组件

---

### 阶段3：场景组件（5天）

**Day 14-15**：
- [ ] ChatPage 组件
- [ ] 页面布局

**Day 16-17**：
- [ ] ChatWidget SDK
- [ ] 集成文档

**Day 18**：
- [ ] ChatDrawer 组件

---

### 阶段4：优化与测试（3天）

**Day 19**：
- [ ] 性能优化
- [ ] 移动端适配

**Day 20**：
- [ ] 测试与修复
- [ ] 文档完善

---

## 📁 目录结构

```
client/src/components/Chat/
├── base/                    # 基础组件
│   ├── ChatMessage/
│   │   ├── index.tsx
│   │   ├── MessageContent.tsx
│   │   └── index.module.less
│   ├── ChatInput/
│   │   ├── index.tsx
│   │   └── index.module.less
│   ├── ChatToolbar/
│   │   ├── index.tsx
│   │   └── index.module.less
│   ├── ChatMessageList/
│   ├── FilePicker/
│   ├── KnowledgePicker/
│   └── ReferenceHint/
│
├── composite/               # 组合组件
│   ├── ChatCore/
│   ├── ChatWithToolbar/
│   ├── ChatEmbedded/
│   └── ChatCard/
│
├── scenes/                  # 场景组件
│   ├── ChatPage/
│   ├── ChatWidget/
│   └── ChatDrawer/
│
├── stores/                  # 状态管理
│   ├── chatStore.ts
│   └── referenceStore.ts
│
├── hooks/                   # 自定义Hooks
│   ├── useChat.ts
│   ├── useReferences.ts
│   └── useFilePicker.ts
│
└── types/                   # 类型定义
    ├── message.ts
    ├── reference.ts
    └── chat.ts
```

---

## ✅ 核心优势

### 1. 高度复用

- ✅ 所有基础组件可独立使用
- ✅ 组合组件复用基础组件
- ✅ 场景组件复用组合组件

### 2. 灵活配置

- ✅ 通过 props 控制功能
- ✅ 支持主题定制
- ✅ 支持国际化

### 3. 易于扩展

- ✅ 新增场景只需组合现有组件
- ✅ 新增功能只需扩展基础组件
- ✅ 不影响已有功能

### 4. 维护性强

- ✅ 单一职责原则
- ✅ 组件独立测试
- ✅ 问题隔离

---

## 💬 总结

**组件化架构 + 混合方案 = 最优解**

**优势**：
1. ✅ 聊天界面可复用于多种场景
2. ✅ 默认简洁（混合方案）
3. ✅ 按需展开
4. ✅ 易于维护和扩展
5. ✅ 支持独立使用和组合使用

**实施优先级**：
1. 先实现基础组件
2. 再实现组合组件（ChatWithToolbar）
3. 最后实现场景组件

**是否同意这个架构设计？** 🚀
