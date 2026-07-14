# 工具栏集成方案

## 🎯 集成策略

### 最小化影响原则

1. **不删除现有代码** - 保留ChatSessionHeader现有功能
2. **添加展开按钮** - 在左侧添加菜单按钮
3. **并行运行** - 工具栏和现有按钮可以同时使用
4. **渐进式迁移** - 用户可以逐步适应新界面

---

## 📐 界面变化

### 现有界面

```
顶部栏：
[🎨] [🔍] [📋] [➕]  对话标题  [📋计划]  [模型▼]
```

### 集成后界面

```
顶部栏：
[≡]  对话标题  [模型▼]
 ↑
菜单按钮（点击展开工具栏）
```

---

## 🔧 集成步骤

### 步骤1：添加菜单按钮

在ChatSessionHeader左侧添加菜单按钮：

```typescript
// pages/Chat/components/ChatSessionHeader/index.tsx

import { MenuOutlined } from '@ant-design/icons';

// 在最左侧添加菜单按钮
<IconButton
  bordered={false}
  icon={<MenuOutlined />}
  onClick={() => setToolbarOpen(true)}
/>
```

---

### 步骤2：添加工具栏抽屉

在Chat页面添加工具栏抽屉：

```typescript
// pages/Chat/index.tsx

import { ChatToolbarDrawer, useToolbarState } from '@/components/Chat';

export function ChatPage() {
  const {
    visible: toolbarOpen,
    openToolbar,
    closeToolbar,
    selectedFiles,
    selectedKnowledge,
    setSelectedFiles,
    setSelectedKnowledge,
    totalReferences,
    clearAllReferences,
  } = useToolbarState();

  return (
    <>
      {/* 现有聊天内容 */}
      <ChatSessionHeader onToolbarOpen={openToolbar} />
      
      {/* 引用提示 */}
      {totalReferences > 0 && (
        <ReferenceHint
          files={selectedFiles}
          knowledge={selectedKnowledge}
          onRemoveFile={(id) => ...}
          onRemoveKnowledge={(id) => ...}
          onClear={clearAllReferences}
        />
      )}

      {/* 工具栏抽屉 */}
      <ChatToolbarDrawer
        visible={toolbarOpen}
        onClose={closeToolbar}
        selectedFiles={selectedFiles}
        selectedKnowledge={selectedKnowledge}
        onFileSelect={setSelectedFiles}
        onKnowledgeSelect={setSelectedKnowledge}
      />
    </>
  );
}
```

---

### 步骤3：传递引用到消息发送

修改消息发送逻辑，包含文件和知识库引用：

```typescript
const handleSend = async (message: string) => {
  const fileIds = selectedFiles.map(f => f.id);
  const knowledgeIds = selectedKnowledge.map(k => k.id);

  // 发送消息时包含引用
  await chatApi.sendMessage(message, {
    file_ids: fileIds,
    knowledge_ids: knowledgeIds,
  });

  // 清空引用
  clearAllReferences();
};
```

---

## 📊 影响范围

### 修改文件

| 文件 | 修改内容 | 影响等级 |
|------|---------|---------|
| `pages/Chat/components/ChatSessionHeader/index.tsx` | 添加菜单按钮 | 🟢 小影响 |
| `pages/Chat/index.tsx` | 添加工具栏和引用提示 | 🟡 中等影响 |

### 不修改文件

- ✅ 不修改AgentScopeRuntimeWebUI
- ✅ 不修改消息渲染逻辑
- ✅ 不修改API接口
- ✅ 不修改样式系统

---

## 🧪 测试计划

### 功能测试

- [ ] 点击菜单按钮，工具栏正常展开
- [ ] 工具栏包含所有功能（历史、模型、文件、知识库）
- [ ] 选择文件后，引用提示正确显示
- [ ] 发送消息时，引用正确传递
- [ ] 固定功能正常工作
- [ ] 移动端适配正常

### 兼容性测试

- [ ] Chrome/Firefox/Safari
- [ ] iOS/Android移动端
- [ ] 暗色主题

---

## 🚀 实施顺序

1. **添加菜单按钮**（最小影响）
2. **添加工具栏抽屉**（独立组件）
3. **添加引用提示**（独立组件）
4. **修改消息发送逻辑**（需要测试）
5. **全面测试**（验证所有功能）

---

## 💬 备注

- 保持现有功能不变，用户可以继续使用
- 工具栏是新功能，不影响现有用户习惯
- 可以逐步迁移用户到新界面
- 支持回滚，风险可控
