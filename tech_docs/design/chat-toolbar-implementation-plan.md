# 聊天界面工具栏优化 - 完整实施方案

## 📋 方案概述

**核心设计**：左上角展开按钮 + 侧边工具栏 + 固定显示功能

**解决问题**：
1. ✅ 文件选择器空间充足（树形结构，支持目录）
2. ✅ 输入框简洁（不堆砌按钮）
3. ✅ 移动端友好（全屏抽屉）
4. ✅ PC端高效（固定显示，不用频繁展开）

---

## 🎨 UI设计

### 1. 默认状态（未展开）

```
┌────────────────────────────────────────────────────┐
│ [≡]  对话标题                                     │  ← 左上角展开按钮
├────────────────────────────────────────────────────┤
│                                                    │
│                                                    │
│                 聊天消息区域                       │
│                                                    │
│                                                    │
├────────────────────────────────────────────────────┤
│  输入框...                          [📎] [发送]   │
└────────────────────────────────────────────────────┘
```

---

### 2. 展开状态（未固定）

```
┌────────────┬───────────────────────────────────────┐
│ 工具栏  [📌]│                                       │  ← 固定按钮
├────────────┤                                       │
│            │                                       │
│ [📋历史]   │                                       │
│            │         聊天消息区域                  │
│ [🎯模型▼]  │                                       │
│            │                                       │
│ [🎨设置]   │                                       │
│            │                                       │
│ [🔍搜索]   │                                       │
│            │                                       │
│ ────────── │                                       │
│ 文件引用   │                                       │
│ ────────── │                                       │
│ 📁 文档/   │                                       │
│   ├─ ☑ 需求│                                       │
│   └─ ☐ 设计│                                       │
│            │                                       │
│ ────────── │                                       │
│ 知识库引用 │                                       │
│ ────────── │                                       │
│ ☑ 📚 产品 │                                       │
│            │                                       │
│ [收起 ×]   │                                       │
└────────────┴───────────────────────────────────────┘

点击外部区域 → 工具栏收起
```

---

### 3. 固定状态（PC端推荐）

```
┌────────────┬───────────────────────────────────────┐
│ 工具栏  [📌]│                                       │  ← 固定按钮（激活状态）
├────────────┤                                       │
│            │                                       │
│ [📋历史]   │                                       │
│            │         聊天消息区域                  │
│ [🎯模型▼]  │         （宽度自适应收缩）            │
│            │                                       │
│ [🎨设置]   │                                       │
│            │                                       │
│ [🔍搜索]   │                                       │
│            │                                       │
│ ────────── │                                       │
│ 文件引用   │                                       │
│ ────────── │                                       │
│ 🔍 搜索... │                                       │
│            │                                       │
│ 📁 文档/   │                                       │
│   ├─ ☑ 需求│                                       │
│   └─ ☐ 设计│                                       │
│            │                                       │
│ 📁 图片/   │                                       │
│   └─ ☐ logo│                                       │
│            │                                       │
│ ────────── │                                       │
│ 知识库引用 │                                       │
│ ────────── │                                       │
│ ☑ 📚 产品 │                                       │
│ ☐ 📚 技术 │                                       │
│            │                                       │
│ 已选：2项  │                                       │
│            ├───────────────────────────────────────┤
│            │  输入框...            [📎] [发送]   │
└────────────┴───────────────────────────────────────┘

点击外部区域 → 工具栏不收起（保持固定）
点击 [📌] → 取消固定 → 工具栏收起
```

---

### 4. 移动端展开（全屏抽屉）

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
│ 🔍 搜索...          │
│                      │
│ 📁 文档/             │
│   ├─ ☑ 需求.docx    │
│   └─ ☐ 设计.pdf     │
│ 📁 图片/             │
│   └─ ☐ logo.png     │
│                      │
│ ─────────────────── │
│ 知识库引用          │
│ ─────────────────── │
│ ☑ 📚 产品文档        │
│ ☐ 📚 技术文档        │
│                      │
│ 已选：2项            │
│                      │
│ [确认选择]           │
└──────────────────────┘

移动端：不显示固定按钮（空间有限，不适合固定）
```

---

## 🔧 功能设计

### 1. 固定显示按钮

#### 位置
- 工具栏标题栏右侧
- 和标题在同一行

#### 状态
```
未固定：[📌] 灰色图标，提示"固定工具栏"
已固定：[📌] 高亮图标，提示"取消固定"
```

#### 行为
```
点击固定按钮：
- 未固定 → 固定：工具栏保持展开，不自动收起
- 已固定 → 取消固定：工具栏保持展开，但点击外部可收起

点击外部区域：
- 未固定：工具栏收起
- 已固定：工具栏不收起
```

#### 持久化
```typescript
// 保存用户偏好到 localStorage
const TOOLBAR_PINNED_KEY = 'chat-toolbar-pinned';

// 初始化时读取
const isPinned = localStorage.getItem(TOOLBAR_PINNED_KEY) === 'true';

// 切换时保存
const togglePinned = (pinned: boolean) => {
  localStorage.setItem(TOOLBAR_PINNED_KEY, String(pinned));
};
```

---

### 2. 工具栏内容

#### 第一区：全局操作

```typescript
const globalTools = [
  {
    key: 'history',
    icon: <HistoryOutlined />,
    label: '历史会话',
    component: HistoryDropdown,
  },
  {
    key: 'model',
    icon: <ThunderboltOutlined />,
    label: '模型选择',
    component: ModelSelector,
  },
  {
    key: 'settings',
    icon: <SettingOutlined />,
    label: '显示设置',
    component: DisplaySettings,
  },
  {
    key: 'search',
    icon: <SearchOutlined />,
    label: '搜索消息',
    component: SearchInput,
  },
];
```

#### 第二区：文件引用

```typescript
// 文件树组件
interface FileTreeProps {
  selected: FileInfo[];
  onSelect: (files: FileInfo[]) => void;
  maxSelect?: number;  // 最多选择数量
}

// 功能：
// - 树形结构展示
// - 支持展开/折叠目录
// - 支持搜索文件
// - 支持多选（复选框）
// - 显示文件大小、类型图标
// - 显示已选数量
```

#### 第三区：知识库引用

```typescript
// 知识库列表组件
interface KnowledgeListProps {
  selected: KnowledgeInfo[];
  onSelect: (items: KnowledgeInfo[]) => void;
}

// 功能：
// - 列表展示知识库
// - 显示知识库描述
// - 支持多选（复选框）
// - 显示已选数量
```

#### 第四区：引用提示（底部）

```typescript
// 已选引用列表
interface SelectedReferencesProps {
  files: FileInfo[];
  knowledge: KnowledgeInfo[];
  onRemove: (id: string) => void;
  onClear: () => void;
}

// 功能：
// - 显示已选文件和知识库
// - 支持单独移除
// - 支持清空所有
// - 显示总数量
```

---

### 3. 引用提示在输入框上方

```
已选引用时显示：
┌────────────────────────────────────────────────┐
│ 📄 需求文档.docx [×]  📚 产品文档 [×]  [清空] │
└────────────────────────────────────────────────┘

输入框：
┌────────────────────────────────────────────────┐
│ 输入框...                        [📎] [发送]   │
└────────────────────────────────────────────────┘
```

---

## 💻 技术实现

### 1. 组件结构

```
/client/src/components/Chat/
├── ChatToolbarDrawer/
│   ├── index.tsx                    # 主组件
│   ├── index.module.less            # 样式
│   ├── PinButton.tsx                # 固定按钮
│   ├── GlobalTools.tsx              # 全局工具
│   ├── FileTreeSelector.tsx         # 文件选择器
│   ├── KnowledgeSelector.tsx        # 知识库选择器
│   └── SelectedReferences.tsx       # 已选引用
├── hooks/
│   ├── useToolbarState.ts           # 工具栏状态管理
│   ├── useFileTree.ts               # 文件树数据
│   └── useKnowledgeList.ts          # 知识库数据
└── types.ts                         # 类型定义
```

---

### 2. 主组件实现

```typescript
// components/Chat/ChatToolbarDrawer/index.tsx

import { useState, useEffect } from 'react';
import { Drawer, Tabs, Button, Tooltip } from 'antd';
import { PushpinOutlined, PushpinFilled } from '@ant-design/icons';
import { PinButton } from './PinButton';
import { GlobalTools } from './GlobalTools';
import { FileTreeSelector } from './FileTreeSelector';
import { KnowledgeSelector } from './KnowledgeSelector';
import { SelectedReferences } from './SelectedReferences';
import useIsMobile from '@/hooks/useIsMobile';
import './index.module.less';

interface ChatToolbarDrawerProps {
  visible: boolean;
  onClose: () => void;
  onFileSelect: (files: FileInfo[]) => void;
  onKnowledgeSelect: (items: KnowledgeInfo[]) => void;
  selectedFiles?: FileInfo[];
  selectedKnowledge?: KnowledgeInfo[];
}

export function ChatToolbarDrawer({
  visible,
  onClose,
  onFileSelect,
  onKnowledgeSelect,
  selectedFiles = [],
  selectedKnowledge = [],
}: ChatToolbarDrawerProps) {
  const isMobile = useIsMobile();
  const [pinned, setPinned] = useState(() => {
    // 从 localStorage 读取固定状态
    return localStorage.getItem('chat-toolbar-pinned') === 'true';
  });

  const [activeTab, setActiveTab] = useState<'tools' | 'files' | 'knowledge'>('tools');

  // 保存固定状态
  useEffect(() => {
    localStorage.setItem('chat-toolbar-pinned', String(pinned));
  }, [pinned]);

  // 处理关闭
  const handleClose = () => {
    if (!pinned) {
      onClose();
    }
  };

  // 移动端不显示固定按钮
  const showPinButton = !isMobile;

  return (
    <Drawer
      placement="left"
      open={visible}
      onClose={handleClose}
      mask={!pinned}  // 固定时不显示遮罩
      maskClosable={!pinned}  // 固定时点击遮罩不关闭
      width={isMobile ? '100%' : 320}
      title={
        <div className="toolbar-header">
          <span>工具栏</span>
          {showPinButton && (
            <PinButton
              pinned={pinned}
              onToggle={() => setPinned(!pinned)}
            />
          )}
        </div>
      }
      className={`chat-toolbar-drawer ${pinned ? 'pinned' : ''}`}
      styles={{
        body: { padding: 0 },
      }}
    >
      {/* 标签页 */}
      <Tabs
        activeKey={activeTab}
        onChange={(key) => setActiveTab(key as any)}
        items={[
          {
            key: 'tools',
            label: '工具',
            children: <GlobalTools />,
          },
          {
            key: 'files',
            label: (
              <span>
                文件
                {selectedFiles.length > 0 && (
                  <span className="badge">{selectedFiles.length}</span>
                )}
              </span>
            ),
            children: (
              <FileTreeSelector
                selected={selectedFiles}
                onSelect={onFileSelect}
              />
            ),
          },
          {
            key: 'knowledge',
            label: (
              <span>
                知识库
                {selectedKnowledge.length > 0 && (
                  <span className="badge">{selectedKnowledge.length}</span>
                )}
              </span>
            ),
            children: (
              <KnowledgeSelector
                selected={selectedKnowledge}
                onSelect={onKnowledgeSelect}
              />
            ),
          },
        ]}
      />

      {/* 已选引用 */}
      {(selectedFiles.length > 0 || selectedKnowledge.length > 0) && (
        <SelectedReferences
          files={selectedFiles}
          knowledge={selectedKnowledge}
          onRemove={(id) => {
            // 移除引用
          }}
          onClear={() => {
            onFileSelect([]);
            onKnowledgeSelect([]);
          }}
        />
      )}
    </Drawer>
  );
}
```

---

### 3. 固定按钮组件

```typescript
// components/Chat/ChatToolbarDrawer/PinButton.tsx

import { Tooltip } from 'antd';
import { PushpinOutlined, PushpinFilled } from '@ant-design/icons';
import './index.module.less';

interface PinButtonProps {
  pinned: boolean;
  onToggle: () => void;
}

export function PinButton({ pinned, onToggle }: PinButtonProps) {
  return (
    <Tooltip title={pinned ? '取消固定' : '固定工具栏'}>
      <Button
        type="text"
        className={`pin-button ${pinned ? 'pinned' : ''}`}
        icon={pinned ? <PushpinFilled /> : <PushpinOutlined />}
        onClick={(e) => {
          e.stopPropagation();
          onToggle();
        }}
      />
    </Tooltip>
  );
}
```

---

### 4. 文件选择器组件

```typescript
// components/Chat/ChatToolbarDrawer/FileTreeSelector.tsx

import { useState, useEffect } from 'react';
import { Tree, Input, Empty, Spin } from 'antd';
import { SearchOutlined, FolderOutlined, FileOutlined } from '@ant-design/icons';
import { fileApi } from '@/api/modules/file';
import type { FileInfo, FileNode } from '../types';
import './index.module.less';

interface FileTreeSelectorProps {
  selected: FileInfo[];
  onSelect: (files: FileInfo[]) => void;
}

export function FileTreeSelector({ selected, onSelect }: FileTreeSelectorProps) {
  const [loading, setLoading] = useState(false);
  const [fileTree, setFileTree] = useState<FileNode[]>([]);
  const [searchText, setSearchText] = useState('');
  const [expandedKeys, setExpandedKeys] = useState<string[]>([]);

  // 加载文件树
  useEffect(() => {
    loadFileTree();
  }, []);

  const loadFileTree = async () => {
    setLoading(true);
    try {
      const tree = await fileApi.getFileTree();
      setFileTree(tree);
    } catch (error) {
      console.error('Failed to load file tree:', error);
    } finally {
      setLoading(false);
    }
  };

  // 过滤文件树
  const filteredTree = useMemo(() => {
    if (!searchText) return fileTree;
    return filterTree(fileTree, searchText.toLowerCase());
  }, [fileTree, searchText]);

  // 转换为 Tree 组件数据格式
  const treeData = useMemo(() => {
    return convertToTreeData(filteredTree);
  }, [filteredTree]);

  // 处理选择
  const handleCheck = (checkedKeys: any) => {
    const files = findFilesByIds(fileTree, checkedKeys as string[]);
    onSelect(files);
  };

  return (
    <div className="file-tree-selector">
      {/* 搜索框 */}
      <div className="search-box">
        <Input
          placeholder="搜索文件..."
          prefix={<SearchOutlined />}
          value={searchText}
          onChange={(e) => setSearchText(e.target.value)}
          allowClear
        />
      </div>

      {/* 文件树 */}
      <div className="file-tree-container">
        {loading ? (
          <Spin />
        ) : treeData.length > 0 ? (
          <Tree
            checkable
            checkedKeys={selected.map((f) => f.id)}
            expandedKeys={expandedKeys}
            onExpand={setExpandedKeys}
            onCheck={handleCheck}
            treeData={treeData}
            selectable={false}
            showIcon
          />
        ) : (
          <Empty description="暂无文件" />
        )}
      </div>

      {/* 已选数量 */}
      {selected.length > 0 && (
        <div className="selected-count">
          已选择 {selected.length} 个文件
          <Button type="link" onClick={() => onSelect([])}>
            清空
          </Button>
        </div>
      )}
    </div>
  );
}

// 辅助函数：转换文件树数据
function convertToTreeData(nodes: FileNode[]): any[] {
  return nodes.map((node) => ({
    key: node.id,
    title: node.name,
    icon: node.type === 'folder' ? <FolderOutlined /> : <FileOutlined />,
    children: node.children ? convertToTreeData(node.children) : undefined,
  }));
}

// 辅助函数：过滤文件树
function filterTree(nodes: FileNode[], searchText: string): FileNode[] {
  return nodes
    .map((node) => {
      if (node.children) {
        const filteredChildren = filterTree(node.children, searchText);
        if (filteredChildren.length > 0 || node.name.toLowerCase().includes(searchText)) {
          return { ...node, children: filteredChildren };
        }
        return null;
      }
      return node.name.toLowerCase().includes(searchText) ? node : null;
    })
    .filter(Boolean) as FileNode[];
}
```

---

### 5. 集成到聊天页面

```typescript
// pages/Chat/index.tsx

export function ChatPage() {
  const [toolbarOpen, setToolbarOpen] = useState(() => {
    // 如果用户之前固定了工具栏，初始化时打开
    return localStorage.getItem('chat-toolbar-pinned') === 'true';
  });
  const [selectedFiles, setSelectedFiles] = useState<FileInfo[]>([]);
  const [selectedKnowledge, setSelectedKnowledge] = useState<KnowledgeInfo[]>([]);

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

      {/* 聊天内容区 */}
      <div className="chat-content">
        <AgentScopeRuntimeWebUI {...options} />
      </div>

      {/* 引用提示 */}
      {(selectedFiles.length > 0 || selectedKnowledge.length > 0) && (
        <div className="reference-hint">
          {selectedFiles.map((file) => (
            <Tag
              key={file.id}
              closable
              onClose={() => {
                setSelectedFiles(selectedFiles.filter((f) => f.id !== file.id));
              }}
            >
              📄 {file.name}
            </Tag>
          ))}
          {selectedKnowledge.map((item) => (
            <Tag
              key={item.id}
              closable
              onClose={() => {
                setSelectedKnowledge(selectedKnowledge.filter((k) => k.id !== item.id));
              }}
            >
              📚 {item.name}
            </Tag>
          ))}
          <Button
            type="link"
            size="small"
            onClick={() => {
              setSelectedFiles([]);
              setSelectedKnowledge([]);
            }}
          >
            清空
          </Button>
        </div>
      )}

      {/* 输入框（AgentScopeRuntimeWebUI 内置） */}

      {/* 工具栏抽屉 */}
      <ChatToolbarDrawer
        visible={toolbarOpen}
        onClose={() => setToolbarOpen(false)}
        selectedFiles={selectedFiles}
        selectedKnowledge={selectedKnowledge}
        onFileSelect={setSelectedFiles}
        onKnowledgeSelect={setSelectedKnowledge}
      />
    </div>
  );
}
```

---

### 6. 样式实现

```less
// components/Chat/ChatToolbarDrawer/index.module.less

.chat-toolbar-drawer {
  &.pinned {
    // 固定状态下的样式
    .ant-drawer-content-wrapper {
      box-shadow: 2px 0 8px rgba(0, 0, 0, 0.1);
    }
  }

  .toolbar-header {
    display: flex;
    justify-content: space-between;
    align-items: center;
    width: 100%;

    .pin-button {
      padding: 4px;

      &.pinned {
        color: #1890ff;
      }
    }
  }

  .file-tree-selector {
    padding: 16px;
    height: 100%;
    display: flex;
    flex-direction: column;

    .search-box {
      margin-bottom: 12px;
    }

    .file-tree-container {
      flex: 1;
      overflow: auto;
    }

    .selected-count {
      padding-top: 12px;
      border-top: 1px solid #f0f0f0;
      margin-top: 12px;
    }
  }

  .badge {
    display: inline-block;
    margin-left: 4px;
    padding: 0 6px;
    font-size: 12px;
    line-height: 18px;
    border-radius: 9px;
    background: #1890ff;
    color: #fff;
  }
}
```

---

## 📊 功能清单

### 核心功能

| 功能 | 优先级 | 说明 |
|------|--------|------|
| 左上角展开按钮 | P0 | 点击展开工具栏 |
| 固定显示按钮 | P0 | 点击固定工具栏（PC端） |
| 全局工具 | P0 | 历史、模型、设置、搜索 |
| 文件引用 | P0 | 树形选择器，支持搜索、多选 |
| 知识库引用 | P0 | 列表选择器，支持多选 |
| 引用提示 | P0 | 输入框上方显示已选引用 |

### 扩展功能

| 功能 | 优先级 | 说明 |
|------|--------|------|
| 固定状态持久化 | P1 | 记住用户固定偏好 |
| 文件搜索 | P1 | 搜索文件名 |
| 文件预览 | P2 | 预览文件内容 |
| 最近使用 | P2 | 显示最近使用的文件/知识库 |

---

## 🚀 实施步骤

### 第1周：基础组件开发（5天）

#### Day 1-2：主组件框架
- [ ] ChatToolbarDrawer 主组件
- [ ] PinButton 固定按钮组件
- [ ] 工具栏状态管理（useToolbarState）
- [ ] 基础样式

#### Day 3-4：文件选择器
- [ ] FileTreeSelector 组件
- [ ] 文件树数据加载
- [ ] 搜索过滤功能
- [ ] 多选逻辑

#### Day 5：知识库选择器
- [ ] KnowledgeSelector 组件
- [ ] 知识库列表加载
- [ ] 多选逻辑

---

### 第2周：集成与优化（5天）

#### Day 6-7：集成到聊天页面
- [ ] 修改 ChatSessionHeader（移除现有按钮）
- [ ] 集成工具栏抽屉
- [ ] 引用提示组件
- [ ] 输入框适配

#### Day 8：固定功能
- [ ] 固定状态持久化
- [ ] 固定状态下的布局调整
- [ ] 响应式设计

#### Day 9：移动端适配
- [ ] 移动端全屏抽屉
- [ ] 移动端交互优化
- [ ] 隐藏固定按钮

#### Day 10：测试与优化
- [ ] 功能测试
- [ ] 性能优化
- [ ] 用户体验优化

---

## ✅ 验收标准

### 功能验收

- [ ] 点击展开按钮，工具栏正常展开
- [ ] 点击固定按钮，工具栏保持展开
- [ ] 点击外部区域，未固定时收起，已固定时不收起
- [ ] 文件选择器支持搜索、展开目录、多选
- [ ] 知识库选择器支持多选
- [ ] 引用提示正确显示已选内容
- [ ] 移动端全屏展示，交互正常

### 性能验收

- [ ] 工具栏展开速度 < 200ms
- [ ] 文件树加载速度 < 1s（1000个文件）
- [ ] 搜索响应速度 < 300ms

### 兼容性验收

- [ ] Chrome、Firefox、Safari 正常
- [ ] 移动端 iOS、Android 正常
- [ ] 响应式布局正常

---

## 📝 注意事项

### 1. 向后兼容

**保留现有功能**：
- AgentScopeRuntimeWebUI 组件不变
- 现有聊天逻辑不变
- 只移除顶部栏按钮，改为工具栏内

**影响范围**：
- ChatSessionHeader 组件（移除按钮）
- 聊天页面布局（添加工具栏）

---

### 2. 数据迁移

**无需数据迁移**：
- 文件、知识库数据已存在
- 只需前端调整

---

### 3. 用户引导

**首次使用提示**：
```
┌────────────────────────────────┐
│ 点击左上角 [≡] 按钮展开工具栏  │
│                                │
│ [我知道了]                     │
└────────────────────────────────┘
```

---

## 📊 预期效果

### 桌面端

```
固定后：
├─ 工具栏常驻左侧（320px宽）
├─ 聊天区域自适应收缩
├─ 用户可以边聊天边选文件
└─ 高效便捷
```

### 移动端

```
展开后：
├─ 工具栏全屏展示
├─ 用户选择后自动关闭
└─ 节省空间
```

---

## 💬 总结

### 核心优势

1. ✅ **输入框简洁** - 只有附件和发送按钮
2. ✅ **空间充足** - 文件/知识库选择器有足够空间
3. ✅ **移动端友好** - 全屏抽屉，交互自然
4. ✅ **PC端高效** - 固定显示，不用频繁展开
5. ✅ **扩展性强** - 可以添加更多工具

### 关键特性

- 📌 固定显示按钮（PC端）
- 📂 文件树形选择器
- 📚 知识库列表选择器
- 🔍 文件搜索
- 💾 固定状态持久化

---

**方案确定！准备开始实施！** 🚀
