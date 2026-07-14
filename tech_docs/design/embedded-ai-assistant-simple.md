# 嵌入式 AI 助手设计（简化版）

## 🎯 设计原则

### 核心原则

1. **极简主义**
   - 只保留核心功能
   - UI 尽可能简洁
   - 配置零门槛

2. **用户级聚焦**
   - 面向普通用户，非管理员
   - 智能对话、快捷操作
   - 无需管理功能

3. **即插即用**
   - 几行代码即可嵌入
   - 自动适应主系统
   - 无需复杂配置

4. **非侵入式**
   - 不干扰主系统使用
   - 可随时收起/展开
   - 不占用主要空间

---

## 🎨 界面设计

### 唯一模式：浮动对话窗口

#### 收起状态（默认）

```
┌────────────────────────────────────────┐
│  主系统（OA/ERP/CRM）                   │
│                                        │
│                                        │
│                                        │
│                                 ┌────┐│
│                                 │ 🤖 ││ ← 浮动按钮
│                                 └────┘│
└────────────────────────────────────────┘
```

**按钮样式**：
- 尺寸：56x56px
- 位置：右下角（可配置）
- 样式：圆形 + 阴影
- 动画：hover 放大、呼吸效果
- 图标：🤖 或自定义

#### 展开状态（点击后）

```
┌────────────────────────────────────────┐
│  主系统（OA/ERP/CRM）                   │
│                           ┌────────────┐│
│                           │ 🤖 AI 助手  ││
│                           │ ────────── ││
│                           │            ││
│                           │ 💬 对话区  ││
│                           │            ││
│                           │ ────────── ││
│                           │ 🔍 输入框  ││
│                           └────────────┘│
└────────────────────────────────────────┘
```

**窗口样式**：
- 尺寸：380x520px（可拖拽调整）
- 位置：右下角（可拖拽）
- 样式：圆角、阴影、毛玻璃效果
- 主题：自动跟随主系统（亮/暗）

---

## 🔧 核心功能（极简）

### 1. 智能对话

```typescript
// 基础对话
用户: "帮我起草一份请假条"
AI: 生成请假条模板

用户: "这个流程怎么走？"
AI: 解答操作步骤
```

**特性**：
- ✅ 自然语言对话
- ✅ 上下文记忆
- ✅ 流式输出
- ✅ Markdown 渲染

### 2. 快捷指令

```typescript
// 预设快捷指令（可自定义）
/translate <text>      # 翻译
/summarize <text>      # 总结
/polish <text>         # 润色
/template <name>       # 模板
/help                  # 帮助
```

### 3. 智能建议（可选）

```typescript
// 根据当前页面自动提示
if (current_page === '/approval/pending') {
  show_suggestion("发现 15 条待审批，需要帮忙吗？");
}
```

**特性**：
- ✅ 页面上下文感知
- ✅ 智能提示
- ✅ 可关闭

---

## 🛠️ 集成方式

### 标准集成（推荐）

```html
<!-- 1. 引入 SDK -->
<script src="https://cdn.coapis.com/embed/v1/coapis.min.js"></script>

<!-- 2. 初始化 -->
<script>
CoApis.init({
  token: 'your-token',  // 认证token
  agent: 'default',     // 智能体ID
});
</script>
```

**就这么简单！** ✨

### 高级配置（可选）

```html
<script>
CoApis.init({
  // 基础配置
  token: 'your-token',
  agent: 'default',
  
  // 位置配置（可选）
  position: 'bottom-right',  // bottom-right | bottom-left | top-right | top-left
  
  // 主题配置（可选）
  theme: 'auto',  // auto | light | dark
  
  // 语言配置（可选）
  lang: 'auto',   // auto | zh-CN | en-US
  
  // 按钮自定义（可选）
  button: {
    icon: '🤖',       // 图标
    color: '#1890ff', // 颜色
  },
  
  // 欢迎消息（可选）
  welcome: '你好！我是 AI 助手，有什么可以帮你的吗？',
});
</script>
```

---

## 📱 响应式设计

### 移动端适配

```typescript
// 自动检测移动端
if (isMobile) {
  // 全屏模式
  window_size = '100vw x 100vh';
  position = 'center';
} else {
  // 浮动窗口模式
  window_size = '380px x 520px';
  position = 'bottom-right';
}
```

### 平板适配

```typescript
// 平板中等尺寸
if (isTablet) {
  window_size = '420px x 600px';
}
```

---

## 🎯 用户级功能聚焦

### 不包含的功能（由主 CoApis 管理）

❌ **管理功能**：
- 智能体配置
- 模型管理
- 用户管理
- 权限配置
- 系统设置

❌ **高级功能**：
- 知识库管理
- 技能编辑
- 工作空间文件管理
- 多智能体切换

### 只包含的功能

✅ **核心对话**：
- 智能对话
- 快捷指令
- 智能建议

✅ **便捷操作**：
- 复制内容
- 清空对话
- 最小化窗口

---

## 🔗 需要管理功能时

### 方案：跳转到 CoApis 主站

```typescript
// 点击"管理"按钮，打开新窗口
<button onClick={() => {
  window.open('https://your-coapis.com', '_blank');
}}>
  打开管理后台
</button>
```

**场景示例**：
```
用户: 在嵌入窗口中使用
需求: 需要配置智能体、上传文件、管理知识库
操作: 点击"打开完整版"按钮
结果: 新标签页打开 CoApis 主站
```

---

## 💡 设计细节

### 1. 窗口交互

#### 拖拽移动
```typescript
// 支持拖拽窗口位置
<Draggable>
  <ChatWindow />
</Draggable>
```

#### 调整大小
```typescript
// 支持调整窗口大小
<Resizable
  minWidth={320}
  minHeight={400}
  maxWidth={600}
  maxHeight={800}
>
  <ChatWindow />
</Resizable>
```

#### 最小化
```typescript
// 点击最小化按钮，收起到浮动按钮
<Button onClick={minimize}>─</Button>
```

### 2. 消息操作

#### 快捷操作按钮
```typescript
// 每条消息右侧显示快捷操作
<Message>
  <Content>{message.text}</Content>
  <Actions>
    <Button icon={<CopyOutlined />} onClick={copy} />
    <Button icon={<LikeOutlined />} onClick={like} />
    <Button icon={<DislikeOutlined />} onClick={dislike} />
  </Actions>
</Message>
```

#### 输入框增强
```typescript
// 输入框工具栏
<InputArea>
  <Toolbar>
    <Button icon={<AudioOutlined />} />      {/* 语音输入 */}
    <Button icon={<ClearOutlined />} />      {/* 清空对话 */}
  </Toolbar>
  <TextArea placeholder="输入消息..." />
  <Button type="primary" icon={<SendOutlined />}>发送</Button>
</InputArea>
```

### 3. 主题适配

#### 自动检测主系统主题
```typescript
// 检测主系统主题
const detectTheme = () => {
  // 方式1：检测 class
  if (document.body.classList.contains('dark')) {
    return 'dark';
  }
  
  // 方式2：检测 data 属性
  if (document.body.dataset.theme === 'dark') {
    return 'dark';
  }
  
  // 方式3：检测 CSS 变量
  const bgColor = getComputedStyle(document.body).backgroundColor;
  if (isDarkColor(bgColor)) {
    return 'dark';
  }
  
  return 'light';
};
```

#### 主题样式
```less
// 亮色主题
.coapis-chat-light {
  --bg-color: #ffffff;
  --text-color: #333333;
  --border-color: #e8e8e8;
}

// 暗色主题
.coapis-chat-dark {
  --bg-color: #1f1f1f;
  --text-color: #ffffff;
  --border-color: #333333;
}
```

---

## 🚀 性能优化

### 1. 懒加载

```typescript
// SDK 核心代码 < 10KB
// 对话界面按需加载
const ChatWindow = React.lazy(() => import('./ChatWindow'));

// 首次点击时才加载
const handleClick = async () => {
  if (!loaded) {
    await loadChatUI();
    loaded = true;
  }
  setVisible(true);
};
```

### 2. 资源压缩

```
coapis.min.js      8 KB   (核心SDK)
chat-ui.min.js    45 KB   (UI组件，按需加载)
chat-ui.min.css   12 KB   (样式，按需加载)
─────────────────────────
总计：65 KB (首次加载)
       8 KB (仅SDK)
```

### 3. 缓存策略

```typescript
// 使用 Service Worker 缓存
self.addEventListener('install', (event) => {
  event.waitUntil(
    caches.open('coapis-embed-v1').then((cache) => {
      return cache.addAll([
        '/embed/v1/coapis.min.js',
        '/embed/v1/chat-ui.min.js',
        '/embed/v1/chat-ui.min.css',
      ]);
    })
  );
});
```

---

## 🔒 安全设计

### 1. 认证方式

```typescript
// 方式1：Token 认证（推荐）
CoApis.init({
  token: 'eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9...',
});

// 方式2：OAuth 2.0（企业版）
CoApis.init({
  oauth: {
    clientId: 'your-client-id',
    redirectUri: 'https://your-site.com/callback',
  },
});
```

### 2. 权限隔离

```typescript
// 嵌入式窗口权限限制
permissions: [
  'chat',          // 对话
  'quick_actions', // 快捷操作
  // ❌ 无管理权限
]
```

### 3. 数据隔离

```typescript
// 嵌入式会话与主站隔离
session_id: 'embed:' + userId + ':' + timestamp;

// 对话历史仅在当前嵌入窗口可见
// 不会同步到主站
```

---

## 📊 配置项总结

### 必填配置

| 配置项 | 说明 | 示例 |
|--------|------|------|
| `token` | 认证 token | `'your-jwt-token'` |
| `agent` | 智能体 ID | `'default'` |

### 可选配置

| 配置项 | 说明 | 默认值 |
|--------|------|--------|
| `position` | 按钮位置 | `'bottom-right'` |
| `theme` | 主题 | `'auto'` |
| `lang` | 语言 | `'auto'` |
| `button.icon` | 按钮图标 | `'🤖'` |
| `button.color` | 按钮颜色 | `'#1890ff'` |
| `welcome` | 欢迎消息 | `'你好！我是 AI 助手...'` |

---

## 🎯 集成示例

### 场景1：OA 系统集成

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
      token: '<%= userToken %>',
      agent: 'oa-assistant',
      welcome: '你好！我是 OA 助手，可以帮你处理流程、起草文档等。',
    });
  </script>
</body>
</html>
```

### 场景2：ERP 系统集成

```html
<script>
CoApis.init({
  token: '<%= userToken %>',
  agent: 'erp-assistant',
  button: {
    icon: '📊',
    color: '#52c41a',
  },
  welcome: '你好！我是 ERP 助手，可以帮你查询数据、生成报表等。',
});
</script>
```

### 场景3：CRM 系统集成

```html
<script>
CoApis.init({
  token: '<%= userToken %>',
  agent: 'crm-assistant',
  button: {
    icon: '👥',
    color: '#722ed1',
  },
  welcome: '你好！我是 CRM 助手，可以帮你分析客户、生成报告等。',
});
</script>
```

---

## ✅ 简化对比

| 维度 | 原方案 | 简化方案 |
|------|--------|---------|
| **嵌入方式** | 4种（浮动、侧边栏、面板、API） | 1种（浮动窗口）⭐ |
| **配置项** | 20+ | 7个 |
| **核心功能** | 对话+管理+集成 | 对话+快捷操作 ⭐ |
| **集成代码** | 15行 | 3行 ⭐ |
| **SDK 大小** | 未知 | 8KB（核心）+ 57KB（UI）⭐ |
| **学习成本** | 中等 | 极低 ⭐ |
| **适用场景** | 企业级深度集成 | 用户级快速集成 ⭐ |

---

## 🎯 核心优势

### 1. 极简集成
```
只需 3 行代码，1 分钟完成集成
```

### 2. 零配置
```
开箱即用，无需复杂配置
```

### 3. 轻量化
```
SDK < 10KB，不影响主系统性能
```

### 4. 用户友好
```
简洁界面，无学习成本
```

### 5. 自动适配
```
自动跟随主系统主题、语言
```

---

## 📝 实施建议

### 开发阶段

**阶段一：核心功能**（1-2周）
- ✅ 浮动按钮 UI
- ✅ 对话窗口 UI
- ✅ 基础对话功能
- ✅ Token 认证

**阶段二：优化体验**（1周）
- ✅ 拖拽、调整大小
- ✅ 主题自动适配
- ✅ 移动端适配
- ✅ 快捷指令

**阶段三：性能优化**（1周）
- ✅ 懒加载
- ✅ 资源压缩
- ✅ 缓存优化

### 推广策略

**第一步**：提供 CDN 和文档
```
https://cdn.coapis.com/embed/v1/coapis.min.js
https://docs.coapis.com/embed
```

**第二步**：提供示例代码
```
GitHub: coapis-ai/embed-examples
包含：OA、ERP、CRM 集成示例
```

**第三步**：提供在线演示
```
https://demo.coapis.com/embed
用户可直接体验效果
```

---

## ✅ 总结

### 核心设计理念

**"够用就好，简单至上"**

- ✅ 只保留核心功能（对话）
- ✅ 配置极简（3行代码）
- ✅ UI 极简（浮动窗口）
- ✅ 零学习成本

### 适用场景

- ✅ 已有成熟系统，需要快速增加 AI 能力
- ✅ 普通用户使用，无需管理功能
- ✅ 快速验证 AI 价值
- ✅ 降低使用门槛

### 不适用场景

- ❌ 需要深度集成（如调用主系统 API）
- ❌ 需要管理功能（配置智能体、知识库）
- ❌ 需要自定义界面（侧边栏、嵌入式面板）

**这些场景请使用方案1（卡片化工作台）或主站**

---

**这是一个面向普通用户的、极简的、快速集成的嵌入式 AI 助手方案！** 🎉
