# 聊天界面工具栏优化方案 - 侧边抽屉式设计

## 💡 核心想法

**在聊天框添加一个展开按钮，点击后展开侧边工具栏**

**解决的关键问题**：
1. ✅ 手机适配 - 折叠式设计，不占空间
2. ✅ 按钮集中 - 历史、模型、设置、搜索等都放进去
3. ✅ 文件/知识库选择 - 需要更大的交互空间
4. ✅ 输入框简洁 - 不在输入框内堆砌按钮

---

## 📐 界面设计

### 方案1：左上角展开按钮（推荐）

#### 默认状态（简洁）

```
┌────────────────────────────────────────────────────┐
│                                                    │
│  [≡]  对话标题                                     │  ← 左上角展开按钮
│                                                    │
├────────────────────────────────────────────────────┤
│                                                    │
│                                                    │
│              聊天消息区域                          │
│                                                    │
│                                                    │
├────────────────────────────────────────────────────┤
│  输入框...                          [📎] [发送]   │  ← 输入框简洁
└────────────────────────────────────────────────────┘
```

#### 展开状态（侧边栏）

```
┌────────────┬───────────────────────────────────────┐
│ 工具栏     │                                       │
├────────────┤                                       │
│            │                                       │
│ [📋历史]   │                                       │
│            │         聊天消息区域                  │
│ [🎯模型▼]  │                                       │
│            │                                       │
│ [🎨设置]   │                                       │
│            │                                       │
│ [🔍搜索]   │                                       │
│            ├───────────────────────────────────────┤
│ ────────── │  输入框...            [📎] [发送]   │
│ 文件引用   │                                       │
│ ────────── │                                       │
│ 📁我的文件 │                                       │
│  ├─ 文档/  │                                       │
│  ├─ 图片/  │                                       │
│  └─ 项目/  │                                       │
│            │                                       │
│ ────────── │                                       │
│ 知识库引用 │                                       │
│ ────────── │                                       │
│ 📚产品文档 │                                       │
│ 📚技术文档 │                                       │
│            │                                       │
│ [收起 ×]   │                                       │
└────────────┴───────────────────────────────────────┘
```

---

### 方案2：右上角展开按钮

#### 默认状态

```
┌────────────────────────────────────────────────────┐
│                                    [≡]  模型选择▼  │  ← 右上角
│  对话标题                                         │
├────────────────────────────────────────────────────┤
│                                                    │
│              聊天消息区域                          │
│                                                    │
├────────────────────────────────────────────────────┤
│  输入框...                          [📎] [发送]   │
└────────────────────────────────────────────────────┘
```

#### 展开状态

```
┌───────────────────────────────────────┬────────────┐
│                                       │ 工具栏     │
│                                       ├────────────┤
│                                       │            │
│                                       │ [📋历史]   │
│         聊天消息区域                  │            │
│                                       │ [🎨设置]   │
│                                       │            │
│                                       │ [🔍搜索]   │
│                                       │            │
├───────────────────────────────────────┤ ────────── │
│  输入框...            [📎] [发送]   │ 文件引用   │
│                                       │ ────────── │
│                                       │ 📁文档/    │
│                                       │ 📁图片/    │
│                                       │ 📁项目/    │
│                                       │            │
│                                       │ ────────── │
│                                       │ 知识库引用 │
│                                       │ ────────── │
│                                       │ 📚产品文档 │
│                                       │ 📚技术文档 │
│                                       │            │
│                                       │ [收起 ×]   │
└───────────────────────────────────────┴────────────┘
```

---

## 🎯 推荐方案：方案1 - 左上角展开

### 核心优势

1. ✅ **符合阅读习惯** - 从左到右，工具栏在左侧
2. ✅ **不遮挡内容** - 侧边栏展开，主内容区收缩
3. ✅ **移动端友好** - 可以全屏展示工具栏
4. ✅ **扩展性强** - 工具栏可以容纳更多内容

---

## 📱 移动端适配

### 默认状态

```
┌──────────────────────┐
│ [≡]  对话标题       │
├──────────────────────┤
│                      │
│   聊天消息区域       │
│                      │
├──────────────────────┤
│ 输入框...  [📎] [➤] │
└──────────────────────┘
```

### 展开状态（全屏抽屉）

```
┌──────────────────────┐
│ 工具栏          [×] │
├──────────────────────┤
│ [📋历史]             │
│ [🎯模型选择▼]        │
│ [🎨设置]             │
│ [🔍搜索]             │
│                      │
│ ─────────────────── │
│ 文件引用            │
│ ─────────────────── │
│ 📁 文档/            │
│   ├─ 需求文档.docx  │
│   └─ 设计文档.pdf   │
│ 📁 图片/            │
│   └─ logo.png       │
│ 📁 项目/            │
│   └─ project.zip    │
│                      │
│ ─────────────────── │
│ 知识库引用          │
│ ─────────────────── │
│ 📚 产品文档         │
│ 📚 技术文档         │
│                      │
│ [确认选择]           │
└──────────────────────┘
```

---

## 🔧 工具栏内容设计

### 第一区：全局操作

```
┌──────────────────────┐
│ 全局操作             │
├──────────────────────┤
│ [📋历史]  查看历史会话│
│ [🎯模型]  切换模型    │
│ [🎨设置]  显示设置    │
│ [🔍搜索]  搜索消息    │
└──────────────────────┘
```

---

### 第二区：文件引用（树形结构）

```
┌──────────────────────┐
│ 文件引用             │
├──────────────────────┤
│ 📁 文档/             │
│   ├─ ☑ 需求文档.docx │  ← 可勾选
│   ├─ ☐ 设计文档.pdf  │
│   └─ ☐ 用户手册.md   │
│                      │
│ 📁 图片/             │
│   ├─ ☑ logo.png      │
│   └─ ☐ banner.jpg    │
│                      │
│ 📁 项目/             │
│   └─ ☐ project.zip   │
│                      │
│ 已选：2个文件        │
│ [清空选择]           │
└──────────────────────┘
```

**交互方式**：
- ✅ 树形结构，支持展开/折叠目录
- ✅ 复选框，支持多选
- ✅ 显示文件大小、类型图标
- ✅ 支持搜索文件
- ✅ 显示已选数量

---

### 第三区：知识库引用

```
┌──────────────────────┐
│ 知识库引用           │
├──────────────────────┤
│ ☑ 📚 产品文档        │  ← 可勾选
│   产品需求、功能说明  │
│                      │
│ ☐ 📚 技术文档        │
│   API文档、开发指南   │
│                      │
│ ☐ 📚 运维文档        │
│   部署、配置、监控    │
│                      │
│ 已选：1个知识库      │
│ [清空选择]           │
└──────────────────────┘
```

**交互方式**：
- ✅ 列表展示知识库
- ✅ 显示知识库描述
- ✅ 复选框，支持多选
- ✅ 显示已选数量

---

### 第四区：引用提示（底部）

```
┌──────────────────────┐
│ 当前引用 (2)         │
├──────────────────────┤
│ 📄 需求文档.docx [×] │
│ 📚 产品文档 [×]      │
│                      │
│ [清空所有引用]       │
└──────────────────────┘
```

---

## 🎨 引用提示在输入框的展示

### 桌面端

```
输入框上方（折叠状态）：
┌────────────────────────────────────────────────┐
│ 📄 需求文档.docx [×]  📚 产品文档 [×]  [清空] │
└────────────────────────────────────────────────┘

输入框：
┌────────────────────────────────────────────────┐
│ 输入框...                        [📎] [发送]   │
└────────────────────────────────────────────────┘
```

### 移动端

```
输入框上方：
┌──────────────────────┐
│ 📄 需求文档 [×]      │
│ 📚 产品文档 [×]      │
│ [清空]               │
└──────────────────────┘

输入框：
┌──────────────────────┐
│ 输入框...  [📎] [➤] │
└──────────────────────┘
```

---

## 🔧 技术实现

### 1. 工具栏组件

```typescript
// components/Chat/ChatToolbarDrawer.tsx

interface ChatToolbarDrawerProps {
  visible: boolean;
  onClose: () => void;
  onFileSelect: (files: FileInfo[]) => void;
  onKnowledgeSelect: (items: KnowledgeInfo[]) => void;
}

export function ChatToolbarDrawer({
  visible,
  onClose,
  onFileSelect,
  onKnowledgeSelect,
}: ChatToolbarDrawerProps) {
  const [activeTab, setActiveTab] = useState<'tools' | 'files' | 'knowledge'>('tools');
  const [selectedFiles, setSelectedFiles] = useState<FileInfo[]>([]);
  const [selectedKnowledge, setSelectedKnowledge] = useState<KnowledgeInfo[]>([]);

  return (
    <Drawer
      placement="left"
      open={visible}
      onClose={onClose}
      width={320}
      title="工具栏"
      className="chat-toolbar-drawer"
    >
      {/* 标签页 */}
      <Tabs activeKey={activeTab} onChange={setActiveTab}>
        <TabPane tab="工具" key="tools">
          <ToolList />
        </TabPane>
        <TabPane tab="文件" key="files">
          <FileTree
            selected={selectedFiles}
            onSelect={setSelectedFiles}
          />
        </TabPane>
        <TabPane tab="知识库" key="knowledge">
          <KnowledgeList
            selected={selectedKnowledge}
            onSelect={setSelectedKnowledge}
          />
        </TabPane>
      </Tabs>

      {/* 底部操作 */}
      <div className="toolbar-footer">
        <Button onClick={onClose}>取消</Button>
        <Button
          type="primary"
          onClick={() => {
            onFileSelect(selectedFiles);
            onKnowledgeSelect(selectedKnowledge);
            onClose();
          }}
        >
          确认选择
        </Button>
      </div>
    </Drawer>
  );
}
```

---

### 2. 文件树组件

```typescript
// components/Chat/FileTree.tsx

interface FileTreeProps {
  selected: FileInfo[];
  onSelect: (files: FileInfo[]) => void;
}

export function FileTree({ selected, onSelect }: FileTreeProps) {
  const [searchText, setSearchText] = useState('');
  const [expandedKeys, setExpandedKeys] = useState<string[]>([]);
  const [fileTree, setFileTree] = useState<FileNode[]>([]);

  // 加载文件树
  useEffect(() => {
    loadFileTree().then(setFileTree);
  }, []);

  // 过滤文件
  const filteredTree = useMemo(() => {
    if (!searchText) return fileTree;
    return filterTree(fileTree, searchText);
  }, [fileTree, searchText]);

  return (
    <div className="file-tree">
      {/* 搜索框 */}
      <Input
        placeholder="搜索文件..."
        prefix={<SearchOutlined />}
        value={searchText}
        onChange={e => setSearchText(e.target.value)}
      />

      {/* 文件树 */}
      <Tree
        checkable
        checkedKeys={selected.map(f => f.id)}
        expandedKeys={expandedKeys}
        onExpand={setExpandedKeys}
        onCheck={(checkedKeys) => {
          const files = findFilesByIds(fileTree, checkedKeys as string[]);
          onSelect(files);
        }}
        treeData={convertToTreeData(filteredTree)}
      />

      {/* 已选文件 */}
      {selected.length > 0 && (
        <div className="selected-files">
          <div className="selected-count">
            已选择 {selected.length} 个文件
          </div>
          <Button
            type="link"
            onClick={() => onSelect([])}
          >
            清空选择
          </Button>
        </div>
      )}
    </div>
  );
}
```

---

### 3. 集成到聊天页面

```typescript
// pages/Chat/index.tsx

export function ChatPage() {
  const [toolbarOpen, setToolbarOpen] = useState(false);
  const [references, setReferences] = useState<Reference[]>([]);

  return (
    <div className="chat-page">
      {/* 顶部栏 - 简洁版 */}
      <div className="chat-header">
        <IconButton
          icon={<MenuOutlined />}
          onClick={() => setToolbarOpen(true)}
        />
        <span className="chat-title">对话标题</span>
      </div>

      {/* 聊天内容 */}
      <div className="chat-content">
        <AgentScopeRuntimeWebUI {...options} />
      </div>

      {/* 引用提示 */}
      {references.length > 0 && (
        <div className="reference-hint">
          {references.map(ref => (
            <Tag
              key={ref.id}
              closable
              onClose={() => removeReference(ref.id)}
            >
              {ref.icon} {ref.name}
            </Tag>
          ))}
          <Button
            type="link"
            size="small"
            onClick={() => setReferences([])}
          >
            清空
          </Button>
        </div>
      )}

      {/* 工具栏抽屉 */}
      <ChatToolbarDrawer
        visible={toolbarOpen}
        onClose={() => setToolbarOpen(false)}
        onFileSelect={(files) => {
          setReferences([...references, ...files]);
        }}
        onKnowledgeSelect={(items) => {
          setReferences([...references, ...items]);
        }}
      />
    </div>
  );
}
```

---

## 📊 方案对比

| 方案 | 优点 | 缺点 | 推荐度 |
|------|------|------|--------|
| **输入框内工具栏** | 就近操作 | 空间有限，文件选择不便 | ⭐⭐ |
| **顶部栏按钮** | 传统方式 | 按钮过多，移动端不友好 | ⭐ |
| **左上角侧边栏** | 空间充足，移动端友好 | 需要点击展开 | ⭐⭐⭐⭐⭐ |

---

## ✅ 最终推荐

**方案：左上角展开按钮 + 侧边栏工具栏**

### 核心优势

1. ✅ **输入框简洁** - 只有附件和发送按钮
2. ✅ **空间充足** - 文件/知识库选择器有足够空间
3. ✅ **移动端友好** - 抽屉式设计，全屏展示
4. ✅ **功能集中** - 所有工具和功能统一管理
5. ✅ **扩展性强** - 可以添加更多工具

### 顶部栏变化

```
现有：[🎨设置] [🔍搜索] [📋历史] [➕新对话]  [📋计划]  [模型▼]

调整：[≡]  对话标题
      ↑
   展开按钮（所有功能都在里面）
```

### 输入框变化

```
现有：输入框  [📎] [发送]

保持：输入框  [📎] [发送]
       ↑ 简洁不变
```

---

## 💬 需要确认

**这个方案你觉得如何？**

关键点：
1. ✅ 左上角展开按钮
2. ✅ 侧边栏包含所有工具（历史、模型、设置、搜索、文件、知识库）
3. ✅ 文件选择器用树形结构，支持目录展开、多选
4. ✅ 输入框保持简洁
5. ✅ 移动端适配（全屏抽屉）

**如果同意，我可以整理一个完整的实施方案！** 🚀
