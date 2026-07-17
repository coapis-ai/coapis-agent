# 工具栏功能改进方案

## 🎯 需求理解

### 问题

1. **模型选择没反应** - 应该直接显示下拉选择器
2. **聊天历史需要搜索** - 添加搜索框，可以快速查找历史聊天
3. **文件/知识库不应该硬性加到工具栏** - 应该作为可展开的子菜单
4. **知识库可选择性显示** - 如果没有知识库，应该可以设置不显示

---

## 💡 改进方案

### 方案一：工具栏统一为一个"工具"标签页

**结构设计**：

```
工具栏
├─ ⚡ 模型选择
│   └─ [GPT-4o ▼]  ← 直接显示下拉选择器
│
├─ 📜 聊天历史
│   └─ [搜索框]     ← 添加搜索功能
│   └─ [历史列表]
│
├─ 📁 我的空间 (可展开)
│   └─ [文件列表]
│
├─ 📚 知识库 (可展开，可选)
│   └─ [知识库列表]
│
├─ ⚙️ 显示设置
│
└─ 🔍 搜索消息
    └─ [搜索框]
```

---

### 方案二：具体实现

#### 1. 模型选择 - 直接显示下拉选择器

```tsx
// 在工具标签页中
<div className="tool-section">
  <div className="tool-label">⚡ 模型选择</div>
  <ModelSelector />  {/* 直接嵌入模型选择器组件 */}
</div>
```

**ModelSelector 组件**：
- 显示当前选择的模型
- 点击可下拉选择其他模型

---

#### 2. 聊天历史 - 添加搜索框

```tsx
<div className="tool-section">
  <div className="tool-label">📜 聊天历史</div>
  <Input.Search
    placeholder="搜索聊天历史..."
    onSearch={handleHistorySearch}
  />
  <ChatSessionDropdown 
    searchKeyword={historySearchKeyword}
  />
</div>
```

**ChatSessionDropdown 改进**：
- 接收 `searchKeyword` 参数
- 根据关键词过滤历史列表
- 支持实时搜索

---

#### 3. 我的空间 - 可展开子菜单

```tsx
<Collapse
  items={[
    {
      key: 'files',
      label: '📁 我的空间',
      children: <FileTreeSelector ... />,
    },
  ]}
/>
```

**特点**：
- 默认折叠
- 点击标题展开
- 显示文件列表

---

#### 4. 知识库 - 可选显示

```tsx
// 配置项
const [showKnowledge, setShowKnowledge] = useState(true);

// 显示逻辑
{showKnowledge && (
  <Collapse
    items={[
      {
        key: 'knowledge',
        label: '📚 知识库',
        children: <KnowledgeSelector ... />,
      },
    ]}
  />
)}
```

**显示条件**：
- 检测是否有知识库
- 如果没有，自动隐藏
- 可以在设置中手动开启/关闭

---

### 方案三：标签页简化

**简化前**：
```
[工具] [文件] [知识库] [已选引用]
```

**简化后**：
```
[工具] [已选引用]
```

**工具标签页包含**：
- ⚡ 模型选择（下拉选择器）
- 📜 聊天历史（带搜索）
- 📁 我的空间（可展开）
- 📚 知识库（可展开，可选）
- ⚙️ 显示设置
- 🔍 搜索消息

**已选引用标签页**：
- 显示已选择的文件和知识库
- 可以移除或清空

---

## 📋 具体修改内容

### 1. 修改 GlobalTools.tsx

**改进点**：
- 模型选择：嵌入 ModelSelector 组件
- 聊天历史：添加搜索框
- 我的空间：使用 Collapse 组件
- 知识库：使用 Collapse 组件，可选显示

```tsx
import { Collapse, Input, List, Button, Switch } from 'antd';
import { ThunderboltOutlined, HistoryOutlined, SettingOutlined, SearchOutlined, FolderOutlined, BookOutlined } from '@ant-design/icons';
import ModelSelector from '../../../pages/Chat/ModelSelector';
import ChatSessionDropdown from '../../ChatSessionDropdown';
import { FileTreeSelector } from './FileTreeSelector';
import { KnowledgeSelector } from './KnowledgeSelector';

interface GlobalToolsProps {
  onSettingsClick?: () => void;
  onSearchClick?: () => void;
  showKnowledge?: boolean;  // 是否显示知识库
  onToggleKnowledge?: (show: boolean) => void;
}

export function GlobalTools({ 
  onSettingsClick,
  onSearchClick,
  showKnowledge = true,
  onToggleKnowledge,
}: GlobalToolsProps) {
  const [historySearchKeyword, setHistorySearchKeyword] = useState('');
  
  return (
    <div className="global-tools-container">
      {/* 模型选择 */}
      <div className="tool-section">
        <div className="tool-label">
          <ThunderboltOutlined /> 模型选择
        </div>
        <ModelSelector />
      </div>
      
      {/* 聊天历史 */}
      <div className="tool-section">
        <div className="tool-label">
          <HistoryOutlined /> 聊天历史
        </div>
        <Input.Search
          placeholder="搜索聊天历史..."
          onSearch={setHistorySearchKeyword}
          style={{ marginBottom: 8 }}
        />
        <ChatSessionDropdown 
          searchKeyword={historySearchKeyword}
        />
      </div>
      
      {/* 我的空间 */}
      <Collapse
        items={[
          {
            key: 'files',
            label: (
              <span>
                <FolderOutlined /> 我的空间
              </span>
            ),
            children: <FileTreeSelector ... />,
          },
        ]}
      />
      
      {/* 知识库（可选） */}
      {showKnowledge && (
        <Collapse
          items={[
            {
              key: 'knowledge',
              label: (
                <span>
                  <BookOutlined /> 知识库
                </span>
              ),
              children: <KnowledgeSelector ... />,
            },
          ]}
        />
      )}
      
      {/* 显示设置 */}
      <Button 
        icon={<SettingOutlined />} 
        onClick={onSettingsClick}
        block
      >
        显示设置
      </Button>
      
      {/* 搜索消息 */}
      <Button 
        icon={<SearchOutlined />} 
        onClick={onSearchClick}
        block
      >
        搜索消息
      </Button>
    </div>
  );
}
```

---

### 2. 修改 ChatSessionDropdown.tsx

**添加搜索功能**：

```tsx
interface ChatSessionDropdownProps {
  open: boolean;
  onClose: () => void;
  searchKeyword?: string;  // 新增：搜索关键词
}

export function ChatSessionDropdown({ 
  open, 
  onClose,
  searchKeyword = '',
}: ChatSessionDropdownProps) {
  // 过滤历史列表
  const filteredSessions = useMemo(() => {
    if (!searchKeyword) return sortedSessions;
    return sortedSessions.filter(session => 
      session.name?.toLowerCase().includes(searchKeyword.toLowerCase())
    );
  }, [sortedSessions, searchKeyword]);
  
  // 使用 filteredSessions 渲染列表
}
```

---

### 3. 修改 ChatToolbarSidebar.tsx

**简化标签页**：

```tsx
const tabs = [
  {
    key: 'tools',
    label: '工具',
    children: (
      <GlobalTools
        onSettingsClick={onSettingsClick}
        onSearchClick={onSearchClick}
        showKnowledge={showKnowledge}
        onToggleKnowledge={setShowKnowledge}
      />
    ),
  },
  {
    key: 'references',
    label: `已选引用 (${totalReferences})`,
    children: <SelectedReferences ... />,
  },
];
```

---

### 4. 添加知识库显示配置

**在设置中添加开关**：

```tsx
// 显示设置面板
<Modal title="显示设置">
  <Form.Item label="显示知识库选项">
    <Switch 
      checked={showKnowledge}
      onChange={onToggleKnowledge}
    />
  </Form.Item>
</Modal>
```

---

## 🎨 UI 效果

### 工具标签页

```
┌─────────────────────────────┐
│ ⚡ 模型选择                 │
│   [GPT-4o ▼]               │
├─────────────────────────────┤
│ 📜 聊天历史                 │
│   [搜索框]                 │
│   • 今天                   │
│   • 昨天                   │
├─────────────────────────────┤
│ 📁 我的空间              ▶ │  ← 可展开
├─────────────────────────────┤
│ 📚 知识库                ▶ │  ← 可展开，可选
├─────────────────────────────┤
│ ⚙️ 显示设置                 │
├─────────────────────────────┤
│ 🔍 搜索消息                 │
└─────────────────────────────┘
```

### 展开我的空间后

```
┌─────────────────────────────┐
│ 📁 我的空间              ▼ │  ← 已展开
│   ┌───────────────────────┐ │
│   │ 📂 docs/              │ │
│   │ 📂 images/            │ │
│   │ 📄 readme.md          │ │
│   └───────────────────────┘ │
└─────────────────────────────┘
```

---

## ✅ 优点

1. **模型选择直观** - 直接显示下拉选择器
2. **历史可搜索** - 快速查找历史聊天
3. **结构清晰** - 所有工具在一个页面
4. **灵活配置** - 知识库可选择显示
5. **空间利用** - 可展开设计，节省空间

---

## 📌 注意事项

1. **搜索性能** - 聊天历史搜索要支持实时过滤
2. **展开状态** - 记住用户的展开/折叠状态
3. **空状态** - 没有文件或知识库时的提示
4. **响应式** - 移动端和PC端都要适配

---

## 🚀 实施步骤

### 第一步：修改 GlobalTools.tsx
- 嵌入 ModelSelector
- 添加历史搜索框
- 使用 Collapse 组件

### 第二步：修改 ChatSessionDropdown.tsx
- 添加 searchKeyword 参数
- 实现过滤逻辑

### 第三步：修改 ChatToolbarSidebar.tsx
- 简化标签页为：工具、已选引用
- 传递相关参数

### 第四步：添加知识库显示配置
- 在设置中添加开关
- 保存用户偏好

---

**确认这个方案后，我开始实施修改。**
