# 聊天组件可扩展工具栏设计

## 🤔 问题分析

**错误设计**：
```typescript
// ❌ 固定的工具栏
<ChatWithToolbar
  enableFilePicker={true}      // 固定功能
  enableKnowledgePicker={true} // 固定功能
/>
```

**问题**：
- ❌ 工具栏固定，无法扩展
- ❌ 添加新功能需要修改组件代码
- ❌ 不灵活

---

## ✅ 正确设计：可配置工具栏

### 设计理念

**工具栏 = 插槽（Slot）**

- 工具栏是一个容器
- 可以插入任意工具
- 每个工具是独立组件
- 支持动态配置

---

## 📐 架构设计

### 1. 工具定义

```typescript
// types/toolbar.ts

/**
 * 工具栏工具定义
 */
export interface ToolbarTool {
  key: string;                    // 唯一标识
  icon: React.ReactNode;          // 图标
  label?: string;                 // 标签（可选）
  component?: React.ComponentType<any>;  // 工具组件（如选择器）
  onClick?: () => void;           // 点击事件
  disabled?: boolean;             // 是否禁用
  visible?: boolean;              // 是否显示
  order?: number;                 // 排序
}

/**
 * 工具栏配置
 */
export interface ToolbarConfig {
  tools: ToolbarTool[];           // 工具列表
  position?: 'left' | 'right';    // 位置
  layout?: 'horizontal' | 'vertical';  // 布局
}
```

---

### 2. 核心组件

#### ChatCore（核心聊天组件）

```typescript
// components/Chat/core/ChatCore.tsx

import { AgentScopeRuntimeWebUI } from '@agentscope-ai/chat';

interface ChatCoreProps {
  // 透传所有现有props
  ...IAgentScopeRuntimeWebUIOptions;

  // 新增：工具栏插槽
  toolbarSlot?: React.ReactNode;  // 工具栏插槽

  // 新增：输入框扩展插槽
  inputSlot?: React.ReactNode;    // 输入框扩展插槽
}

/**
 * 核心聊天组件
 * 保持所有现有功能，提供插槽扩展
 */
export function ChatCore(props: ChatCoreProps) {
  const { toolbarSlot, inputSlot, ...restProps } = props;

  return (
    <div className="chat-core">
      {/* 工具栏区域 */}
      {toolbarSlot && (
        <div className="chat-toolbar-slot">
          {toolbarSlot}
        </div>
      )}

      {/* 聊天主体 */}
      <AgentScopeRuntimeWebUI
        {...restProps}
        // 输入框扩展
        inputExtra={inputSlot}
      />
    </div>
  );
}
```

**特点**：
- ✅ 保持所有现有功能
- ✅ 提供工具栏插槽
- ✅ 提供输入框扩展插槽
- ✅ 零破坏性修改

---

#### ChatToolbar（工具栏容器）

```typescript
// components/Chat/base/ChatToolbar.tsx

interface ChatToolbarProps {
  tools: ToolbarTool[];           // 工具列表
  position?: 'left' | 'right';    // 位置
  onToolClick?: (key: string) => void;  // 工具点击回调
}

/**
 * 工具栏容器
 * 支持动态配置工具
 */
export function ChatToolbar(props: ChatToolbarProps) {
  const { tools, position = 'right', onToolClick } = props;

  // 过滤可见的工具
  const visibleTools = tools.filter(tool => tool.visible !== false);

  // 排序
  const sortedTools = [...visibleTools].sort((a, b) => (a.order || 0) - (b.order || 0));

  return (
    <div className={`chat-toolbar chat-toolbar-${position}`}>
      {sortedTools.map(tool => (
        <Tooltip key={tool.key} title={tool.label}>
          <Button
            type="text"
            icon={tool.icon}
            disabled={tool.disabled}
            onClick={() => {
              tool.onClick?.();
              onToolClick?.(tool.key);
            }}
          />
        </Tooltip>
      ))}
    </div>
  );
}
```

**特点**：
- ✅ 支持动态配置
- ✅ 支持排序
- ✅ 支持显示/隐藏
- ✅ 支持禁用

---

### 3. 内置工具组件

#### FilePickerTool（文件选择工具）

```typescript
// components/Chat/tools/FilePickerTool.tsx

interface FilePickerToolProps {
  onFileSelect: (files: File[]) => void;
  visible?: boolean;
  disabled?: boolean;
}

/**
 * 文件选择工具
 */
export function FilePickerTool(props: FilePickerToolProps) {
  const [pickerOpen, setPickerOpen] = useState(false);

  return (
    <>
      {/* 工具按钮 */}
      <Tooltip title="选择文件">
        <Button
          type="text"
          icon={<PaperClipOutlined />}
          onClick={() => setPickerOpen(true)}
          disabled={props.disabled}
        />
      </Tooltip>

      {/* 文件选择器 */}
      <FilePicker
        visible={pickerOpen}
        onSelect={(files) => {
          props.onFileSelect(files);
          setPickerOpen(false);
        }}
        onClose={() => setPickerOpen(false)}
      />
    </>
  );
}

// 工具定义
export const filePickerTool: ToolbarTool = {
  key: 'file-picker',
  icon: <PaperClipOutlined />,
  label: '选择文件',
  order: 1,
};
```

---

#### KnowledgePickerTool（知识库选择工具）

```typescript
// components/Chat/tools/KnowledgePickerTool.tsx

/**
 * 知识库选择工具
 */
export function KnowledgePickerTool(props: KnowledgePickerToolProps) {
  // 类似 FilePickerTool
}

export const knowledgePickerTool: ToolbarTool = {
  key: 'knowledge-picker',
  icon: <BookOutlined />,
  label: '知识库',
  order: 2,
};
```

---

### 4. 组合使用

#### 方式1：使用默认配置

```typescript
// pages/Chat/index.tsx

import { ChatCore, ChatToolbar, filePickerTool, knowledgePickerTool } from '@/components/Chat';

// 默认工具栏配置
const defaultTools: ToolbarTool[] = [
  filePickerTool,
  knowledgePickerTool,
];

export function ChatPage() {
  const handleToolClick = (key: string) => {
    console.log('Tool clicked:', key);
  };

  return (
    <ChatCore
      toolbarSlot={
        <ChatToolbar
          tools={defaultTools}
          onToolClick={handleToolClick}
        />
      }
    />
  );
}
```

---

#### 方式2：自定义工具栏

```typescript
// 自定义工具
const customTools: ToolbarTool[] = [
  {
    key: 'voice',
    icon: <AudioOutlined />,
    label: '语音输入',
    onClick: () => startVoiceInput(),
    order: 1,
  },
  filePickerTool,
  knowledgePickerTool,
  {
    key: 'settings',
    icon: <SettingOutlined />,
    label: '设置',
    onClick: () => openSettings(),
    order: 99,  // 最后
  },
];

<ChatCore
  toolbarSlot={<ChatToolbar tools={customTools} />}
/>
```

---

#### 方式3：动态工具栏

```typescript
// 根据权限动态显示工具
function getAvailableTools(user: User): ToolbarTool[] {
  const tools: ToolbarTool[] = [];

  // 所有人都能用语音
  tools.push({
    key: 'voice',
    icon: <AudioOutlined />,
    label: '语音输入',
  });

  // 有文件权限的用户
  if (user.hasPermission('files:read')) {
    tools.push(filePickerTool);
  }

  // 有知识库权限的用户
  if (user.hasPermission('knowledge:read')) {
    tools.push(knowledgePickerTool);
  }

  // 管理员额外工具
  if (user.isAdmin) {
    tools.push({
      key: 'admin',
      icon: <SettingOutlined />,
      label: '管理',
      onClick: openAdminPanel,
    });
  }

  return tools;
}

<ChatCore
  toolbarSlot={<ChatToolbar tools={getAvailableTools(currentUser)} />}
/>
```

---

#### 方式4：插件化工具栏

```typescript
// 工具栏插件系统
interface ToolbarPlugin {
  id: string;
  name: string;
  tools: ToolbarTool[];
}

// 插件注册
const toolbarPlugins: Map<string, ToolbarPlugin> = new Map();

function registerToolbarPlugin(plugin: ToolbarPlugin) {
  toolbarPlugins.set(plugin.id, plugin);
}

function getToolsFromPlugins(): ToolbarTool[] {
  const tools: ToolbarTool[] = [];
  toolbarPlugins.forEach(plugin => {
    tools.push(...plugin.tools);
  });
  return tools;
}

// 使用插件
registerToolbarPlugin({
  id: 'file-picker',
  name: '文件选择器',
  tools: [filePickerTool],
});

registerToolbarPlugin({
  id: 'knowledge-picker',
  name: '知识库选择器',
  tools: [knowledgePickerTool],
});

<ChatCore
  toolbarSlot={<ChatToolbar tools={getToolsFromPlugins()} />}
/>
```

---

### 5. 高级用法

#### 带状态的工具

```typescript
// 工具可以有自己的状态
function FilePickerToolWithState() {
  const [selectedFiles, setSelectedFiles] = useState<File[]>([]);

  return (
    <>
      <Tooltip title={selectedFiles.length > 0 ? `已选${selectedFiles.length}个文件` : '选择文件'}>
        <Badge count={selectedFiles.length}>
          <Button
            type="text"
            icon={<PaperClipOutlined />}
            onClick={() => setPickerOpen(true)}
          />
        </Badge>
      </Tooltip>

      <FilePicker
        visible={pickerOpen}
        selectedFiles={selectedFiles}
        onSelect={setSelectedFiles}
        onClose={() => setPickerOpen(false)}
      />
    </>
  );
}
```

---

#### 工具栏分组

```typescript
// 工具栏分组
const tools: ToolbarTool[] = [
  // 输入工具组
  {
    key: 'voice',
    icon: <AudioOutlined />,
    label: '语音',
    group: 'input',
    order: 1,
  },
  {
    key: 'image',
    icon: <PictureOutlined />,
    label: '图片',
    group: 'input',
    order: 2,
  },

  // 引用工具组
  {
    key: 'file-picker',
    icon: <PaperClipOutlined />,
    label: '文件',
    group: 'reference',
    order: 1,
  },
  {
    key: 'knowledge-picker',
    icon: <BookOutlined />,
    label: '知识库',
    group: 'reference',
    order: 2,
  },

  // 其他工具组
  {
    key: 'settings',
    icon: <SettingOutlined />,
    label: '设置',
    group: 'other',
    order: 99,
  },
];

// 分组渲染
<ChatToolbar
  tools={tools}
  renderGroups={true}  // 显示分组分隔符
/>
```

---

## 📊 对比总结

| 方案 | 扩展性 | 灵活性 | 维护性 | 推荐度 |
|------|--------|--------|--------|--------|
| **固定工具栏** | ❌ 差 | ❌ 差 | ❌ 差 | ❌ 不推荐 |
| **可配置工具栏** | ✅ 好 | ✅ 好 | ✅ 好 | ✅ 推荐 |
| **插件化工具栏** | ✅✅ 很好 | ✅✅ 很好 | ✅✅ 很好 | ✅✅ 推荐 |

---

## 🚀 实施步骤

### 阶段1：核心组件（2天）

- [ ] ChatCore（提供插槽）
- [ ] ChatToolbar（工具栏容器）
- [ ] 工具类型定义

---

### 阶段2：内置工具（3天）

- [ ] FilePickerTool（文件选择工具）
- [ ] KnowledgePickerTool（知识库选择工具）
- [ ] ReferenceHint（引用提示）

---

### 阶段3：组合组件（3天）

- [ ] 默认工具栏配置
- [ ] 动态工具栏示例
- [ ] 插件化工具栏

---

### 阶段4：文档与测试（2天）

- [ ] 使用文档
- [ ] 单元测试
- [ ] 示例代码

---

## ✅ 最终方案

**可配置工具栏 + 插件化扩展**

**核心优势**：
1. ✅ 工具栏完全可配置
2. ✅ 支持动态添加/移除
3. ✅ 支持插件化扩展
4. ✅ 易于维护和扩展
5. ✅ 向后兼容

**是否同意这个设计？** 🚀
