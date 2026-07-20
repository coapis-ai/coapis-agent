# CoApis 嵌入式聊天集成文档

## 概述

CoApis 支持外部系统通过 **iframe 嵌入** 或 **JavaScript SDK** 集成 AI 聊天功能。

### 功能特性

- ✅ 场景可选（有场景/无场景）
- ✅ Token 认证
- ✅ postMessage 双向通信
- ✅ 可拖拽、可缩放浮窗
- ✅ 事件回调

---

## 方式一：iframe 嵌入

最简单的集成方式，适合所有支持 iframe 的系统。

### 基本用法

```html
<!-- 无场景：默认 AI 助手 -->
<iframe 
  src="https://your-coapis.com/chat/embedded?token=YOUR_TOKEN" 
  width="800" 
  height="600"
  style="border: none; border-radius: 8px;"
/>

<!-- 有场景：场景智能体 -->
<iframe 
  src="https://your-coapis.com/chat/embedded?token=YOUR_TOKEN&scene_id=meeting-minutes&scene_name=会议纪要" 
  width="800" 
  height="600"
  style="border: none; border-radius: 8px;"
/>
```

### URL 参数

| 参数 | 必需 | 说明 |
|------|------|------|
| `token` | ✅ | 认证令牌 |
| `scene_id` | ❌ | 场景 ID（不传则使用默认智能体） |
| `scene_name` | ❌ | 场景名称（用于显示） |

### postMessage 通信

iframe 加载后，可通过 postMessage 与之通信。

#### 入站消息（外部系统 → CoApis）

```javascript
const iframe = document.querySelector('iframe');

// 发送消息
iframe.contentWindow.postMessage({
  type: 'COAPIS_SEND_MESSAGE',
  payload: { message: '你好' }
}, '*');

// 获取状态
iframe.contentWindow.postMessage({
  type: 'COAPIS_GET_STATE'
}, '*');
```

#### 出站事件（CoApis → 外部系统）

```javascript
window.addEventListener('message', (event) => {
  const { type, data } = event.data;
  
  switch (type) {
    case 'COAPIS_READY':
      console.log('聊天页面已就绪');
      break;
      
    case 'COAPIS_MESSAGE_RECEIVED':
      console.log('AI 回复:', data.message);
      break;
      
    case 'COAPIS_MESSAGE_SENT':
      console.log('用户消息已发送:', data.message);
      break;
      
    case 'COAPIS_ERROR':
      console.error('错误:', data.error);
      break;
      
    case 'COAPIS_STATE_CHANGE':
      console.log('状态变化:', data.state);
      break;
  }
});
```

---

## 方式二：JavaScript SDK

提供更友好的 API，封装了 iframe 创建和通信逻辑。

### 引入 SDK

```html
<script src="https://your-coapis.com/sdk/coapis-chat.js"></script>
```

### 使用示例

#### 1. 浮动窗口模式

```javascript
// 打开浮动聊天窗口
const chat = CoApisChat.open({
  baseUrl: 'https://your-coapis.com',
  token: 'YOUR_TOKEN',
  sceneId: 'meeting-minutes',  // 可选
  sceneName: '会议纪要',       // 可选
  width: 700,
  height: 500,
  onReady: () => console.log('聊天已就绪'),
  onMessage: (msg) => console.log('AI 回复:', msg),
  onError: (err) => console.error('错误:', err),
  onClose: () => console.log('窗口已关闭'),
});

// 发送消息
chat.sendMessage('你好');

// 关闭窗口
chat.close();

// 销毁实例
chat.destroy();
```

#### 2. 容器嵌入模式

```html
<div id="chat-container" style="width: 800px; height: 600px;"></div>

<script>
const chat = CoApisChat.init({
  baseUrl: 'https://your-coapis.com',
  token: 'YOUR_TOKEN',
  container: document.getElementById('chat-container'),
  sceneId: 'meeting-minutes',  // 可选
  onMessage: (msg) => console.log('AI 回复:', msg),
});
</script>
```

### API 参考

#### `CoApisChat.init(config)`

初始化聊天窗口。

| 参数 | 类型 | 必需 | 说明 |
|------|------|------|------|
| `baseUrl` | string | ✅ | CoApis 服务地址 |
| `token` | string | ✅ | 认证令牌 |
| `sceneId` | string | ❌ | 场景 ID |
| `sceneName` | string | ❌ | 场景名称 |
| `container` | HTMLElement | ❌ | 容器元素（不传则创建浮动窗口） |
| `width` | number/string | ❌ | 宽度（默认 700px） |
| `height` | number/string | ❌ | 高度（默认 500px） |
| `position` | { x, y } | ❌ | 浮动窗口位置 |
| `draggable` | boolean | ❌ | 是否可拖拽（默认 true） |
| `resizable` | boolean | ❌ | 是否可缩放（默认 true） |
| `theme` | 'light' \| 'dark' | ❌ | 主题（默认 light） |
| `onReady` | function | ❌ | 就绪回调 |
| `onMessage` | function | ❌ | 收到消息回调 |
| `onMessageSent` | function | ❌ | 消息已发送回调 |
| `onError` | function | ❌ | 错误回调 |
| `onClose` | function | ❌ | 关闭回调 |

#### `CoApisChat.open(options)`

快速打开浮动聊天窗口（简化版 API）。

#### 实例方法

| 方法 | 说明 |
|------|------|
| `sendMessage(message)` | 发送消息 |
| `getState()` | 获取状态 |
| `close()` | 关闭窗口 |
| `destroy()` | 销毁实例 |

---

## 获取 Token

### 方式 1：登录后获取

用户登录后，从浏览器开发者工具中获取 token：

1. 打开浏览器开发者工具（F12）
2. 切换到 Application 标签
3. 找到 Local Storage → your-coapis.com
4. 复制 `auth_token` 的值

### 方式 2：API 获取

```bash
curl -X POST https://your-coapis.com/api/auth/login \
  -H "Content-Type: application/json" \
  -d '{"username": "your-username", "password": "your-password"}'
```

返回：
```json
{
  "token": "eyJhbGciOiJIUzI1NiIs...",
  "user": { ... }
}
```

---

## 安全注意事项

1. **Token 保护**：Token 是敏感信息，不要在客户端代码中硬编码
2. **HTTPS**：生产环境必须使用 HTTPS
3. **Token 过期**：Token 有过期时间，需要处理过期重新获取
4. **跨域**：确保 CoApis 服务器配置了正确的 CORS

---

## 示例代码

### 完整示例：浮动聊天窗口

```html
<!DOCTYPE html>
<html>
<head>
  <title>CoApis 聊天演示</title>
</head>
<body>
  <h1>我的应用</h1>
  <button id="open-chat">打开聊天</button>

  <script src="https://your-coapis.com/sdk/coapis-chat.js"></script>
  <script>
    const openBtn = document.getElementById('open-chat');
    let chatInstance = null;

    openBtn.addEventListener('click', () => {
      if (!chatInstance) {
        chatInstance = CoApisChat.open({
          baseUrl: 'https://your-coapis.com',
          token: 'YOUR_TOKEN',
          sceneId: 'meeting-minutes',
          sceneName: '会议纪要助手',
          onReady: () => console.log('聊天已就绪'),
          onMessage: (msg) => console.log('AI:', msg),
        });
      } else {
        chatInstance.close();
        chatInstance.destroy();
        chatInstance = null;
      }
    });
  </script>
</body>
</html>
```

### 完整示例：iframe 嵌入

```html
<!DOCTYPE html>
<html>
<head>
  <title>CoApis 聊天演示</title>
  <style>
    #chat-container {
      width: 800px;
      height: 600px;
      border: 1px solid #ddd;
      border-radius: 8px;
      overflow: hidden;
    }
  </style>
</head>
<body>
  <h1>我的应用</h1>
  <div id="chat-container">
    <iframe 
      src="https://your-coapis.com/chat/embedded?token=YOUR_TOKEN&scene_id=meeting-minutes" 
      width="100%" 
      height="100%"
      style="border: none;"
    />
  </div>

  <script>
    // 监听消息
    window.addEventListener('message', (event) => {
      if (event.data.type === 'COAPIS_MESSAGE_RECEIVED') {
        console.log('AI 回复:', event.data.data.message);
      }
    });
  </script>
</body>
</html>
```

---

## 常见问题

### Q: Token 过期怎么办？

A: 监听 `COAPIS_ERROR` 事件，检测到 token 过期后重新获取。

```javascript
onError: (err) => {
  if (err.includes('过期')) {
    // 重新获取 token
    refreshToken().then(newToken => {
      // 重新初始化聊天
    });
  }
}
```

### Q: 如何自定义样式？

A: iframe 内的样式由 CoApis 控制，可通过主题参数切换明暗模式。如需深度定制，请联系我们。

### Q: 支持哪些浏览器？

A: 支持所有现代浏览器（Chrome、Firefox、Safari、Edge），不支持 IE。

---

## 联系我们

- 文档：https://your-coapis.com/docs
- 支持：support@your-coapis.com
