# 工作台嵌入式聊天方案设计

> **核心思路**：工作台保持独立，聊天界面以嵌入式方式呈现  
> **设计依据**：`embedded-ai-assistant-design.md`  
> **创建日期**：2026-07-17

---

## 一、问题回顾

### 1.1 传统方案的问题

**方案A-B-C-D的共同问题**：
- ❌ 菜单变化：工作台→聊天，菜单从"场景分类"变成"系统菜单"
- ❌ 导航混淆：用户不知道如何返回工作台
- ❌ 页面跳转：体验不连贯
- ❌ 心智负担：需要理解两个"系统"的关系

### 1.2 嵌入式方案的优势

**核心优势**：
- ✅ 工作台保持独立的菜单和布局
- ✅ 聊天界面以浮层/嵌入方式呈现
- ✅ 用户无需离开工作台
- ✅ 体验连贯，操作流畅

---

## 二、方案设计

### 方案1：浮动窗口（推荐 ⭐）

#### 界面设计

**初始状态（工作台）**：
```
┌─────────────────────────────────────────────────────────┐
│  CoApis 工作台                                          │
├────────────┬────────────────────────────────────────────┤
│            │                                            │
│  ┌──────┐  │  📁 办公                                   │
│  │ 办公 │✓ │  ──────────────────────────────────────   │
│  ├──────┤  │  ┌────────┐ ┌────────┐ ┌────────┐        │
│  │ 数据 │  │  │  📝    │ │  📊    │ │  ✉️    │        │
│  ├──────┤  │  │会议纪要│ │工作报告│ │邮件撰写│        │
│  │ 文档 │  │  └────────┘ └────────┘ └────────┘        │
│  ├──────┤  │                                            │
│  │ 沟通 │  │  📊 数据分析                               │
│  ├──────┤  │  ──────────────────────────────────────   │
│  │ 设置 │  │  ┌────────┐ ┌────────┐                   │
│  └──────┘  │  │ 数据统计│ │ 图表生成│                   │
│            │  └────────┘ └────────┘                   │
│            │                                            │
│            │                                    ┌─────┐ │
│            │                                    │ 💬  │ │ ← 浮动按钮
│            │                                    └─────┘ │
└────────────┴────────────────────────────────────────────┘
```

**点击场景卡片后**：
```
┌─────────────────────────────────────────────────────────┐
│  CoApis 工作台                                          │
├────────────┬────────────────────────────────────────────┤
│            │  ┌──────────────────────────────────┐     │
│  ┌──────┐  │  │ 🤖 会议纪要助手       [✕]       │     │
│  │ 办公 │✓ │  ├──────────────────────────────────┤     │
│  ├──────┤  │  │                                  │     │
│  │ 数据 │  │  │  🤖 您好！我是会议纪要助手...     │     │
│  ├──────┤  │  │                                  │     │
│  │ 文档 │  │  │  用户: ...                       │     │
│  ├──────┤  │  │                                  │     │
│  │ 沟通 │  │  │                                  │     │
│  ├──────┤  │  ├──────────────────────────────────┤     │
│  │ 设置 │  │  │ 📎 文件  📚 知识库               │     │
│  └──────┘  │  │ [输入框]              [发送]     │     │
│            │  └──────────────────────────────────┘     │
└────────────┴────────────────────────────────────────────┘
```

**特点**：
- ✅ 工作台菜单不变
- ✅ 聊天窗口浮动在工作台上方
- ✅ 用户可以拖动、调整大小
- ✅ 可以随时最小化或关闭

---

### 方案2：右侧面板嵌入

#### 界面设计

**初始状态**：
```
┌─────────────────────────────────────────────────────────┐
│  CoApis 工作台                                          │
├────────────┬────────────────────────────────────────────┤
│            │                                            │
│  ┌──────┐  │  📁 办公                                   │
│  │ 办公 │✓ │  ┌────────┐ ┌────────┐ ┌────────┐        │
│  ├──────┤  │  │  📝    │ │  📊    │ │  ✉️    │        │
│  │ 数据 │  │  │会议纪要│ │工作报告│ │邮件撰写│        │
│  ├──────┤  │  └────────┘ └────────┘ └────────┘        │
│  │ 文档 │  │                                            │
│  ├──────┤  │  📊 数据分析                               │
│  │ 沟通 │  │  ┌────────┐ ┌────────┐                   │
│  ├──────┤  │  │ 数据统计│ │ 图表生成│                   │
│  │ 设置 │  │  └────────┘ └────────┘                   │
│  └──────┘  │                                            │
└────────────┴────────────────────────────────────────────┘
```

**点击场景卡片后（右侧滑出面板）**：
```
┌─────────────────────────────────────────────────────────────┐
│  CoApis 工作台                                              │
├────────────┬────────────────────────────┬──────────────────┤
│            │                            │ 🤖 会议纪要助手  │
│  ┌──────┐  │  📁 办公                   │ [✕] [—] [□]     │
│  │ 办公 │✓ │  ┌────────┐ ┌────────┐   ├──────────────────┤
│  ├──────┤  │  │  📝    │ │  📊    │   │                  │
│  │ 数据 │  │  │会议纪要│ │工作报告│   │  🤖 您好！我是... │
│  ├──────┤  │  └────────┘ └────────┘   │                  │
│  │ 文档 │  │                            │  用户: ...      │
│  ├──────┤  │  📊 数据分析               │                  │
│  │ 沟通 │  │  ┌────────┐ ┌────────┐   ├──────────────────┤
│  ├──────┤  │  │ 数据统计│ │ 图表生成│   │ 📎 文件 📚 知识库│
│  │ 设置 │  │  └────────┘ └────────┘   │ [输入框]  [发送] │
│  └──────┘  │                            └──────────────────┘
└────────────┴────────────────────────────┴──────────────────┘
```

**特点**：
- ✅ 聊天面板从右侧滑出
- ✅ 工作台内容自动压缩
- ✅ 可以拖动调整面板宽度
- ✅ 关闭面板后工作台恢复

---

### 方案3：模态对话框

#### 界面设计

**点击场景卡片后（居中弹出对话框）**：
```
┌─────────────────────────────────────────────────────────┐
│  CoApis 工作台（背景变暗）                               │
├────────────┬────────────────────────────────────────────┤
│            │         ┌────────────────────────┐         │
│  ┌──────┐  │         │ 🤖 会议纪要助手 [✕]   │         │
│  │ 办公 │  │         ├────────────────────────┤         │
│  ├──────┤  │         │                        │         │
│  │ 数据 │  │         │  🤖 您好！我是...     │         │
│  ├──────┤  │         │                        │         │
│  │ 文档 │  │         │  用户: ...            │         │
│  ├──────┤  │         │                        │         │
│  │ 沟通 │  │         ├────────────────────────┤         │
│  ├──────┤  │         │ 📎 文件  📚 知识库     │         │
│  │ 设置 │  │         │ [输入框]      [发送]   │         │
│  └──────┘  │         └────────────────────────┘         │
└────────────┴────────────────────────────────────────────┘
```

**特点**：
- ✅ 聊天对话框居中显示
- ✅ 背景遮罩，聚焦聊天
- ✅ 可以调整对话框大小
- ✅ ESC键关闭对话框

---

### 方案4：底部面板嵌入

#### 界面设计

**点击场景卡片后（底部弹出面板）**：
```
┌─────────────────────────────────────────────────────────┐
│  CoApis 工作台                                          │
├────────────┬────────────────────────────────────────────┤
│            │                                            │
│  ┌──────┐  │  📁 办公                                   │
│  │ 办公 │✓ │  ┌────────┐ ┌────────┐ ┌────────┐        │
│  ├──────┤  │  │  📝    │ │  📊    │ │  ✉️    │        │
│  │ 数据 │  │  │会议纪要│ │工作报告│ │邮件撰写│        │
│  ├──────┤  │  └────────┘ └────────┘ └────────┘        │
│  │ 文档 │  │                                            │
│  ├──────┤  │  📊 数据分析                               │
│  │ 沟通 │  │  ┌────────┐ ┌────────┐                   │
│  ├──────┤  │  │ 数据统计│ │ 图表生成│                   │
│  │ 设置 │  │  └────────┘ └────────┘                   │
│  └──────┘  │                                            │
├────────────┴────────────────────────────────────────────┤
│  🤖 会议纪要助手                            [✕] [—] [□] │
├──────────────────────────────────────────────────────────┤
│  🤖 您好！我是会议纪要助手...                           │
│                                                          │
│  用户: ...                                              │
├──────────────────────────────────────────────────────────┤
│  📎 文件  📚 知识库    [输入框]              [发送]     │
└──────────────────────────────────────────────────────────┘
```

**特点**：
- ✅ 聊天面板从底部滑出
- ✅ 工作台内容上移
- ✅ 类似IDE的终端面板
- ✅ 可以拖动调整高度

---

## 三、方案对比

| 维度 | 方案1：浮动窗口 | 方案2：右侧面板 | 方案3：模态对话框 | 方案4：底部面板 |
|------|----------------|----------------|------------------|----------------|
| **沉浸感** | 中 | 高 | 最高 | 中 |
| **多任务** | 高 | 高 | 低 | 高 |
| **屏幕空间** | 最佳 | 中 | 中 | 中 |
| **移动端** | 需适配 | 需适配 | 好 | 好 |
| **实现复杂度** | 中 | 低 | 低 | 低 |
| **推荐度** | ⭐⭐⭐ | ⭐⭐⭐ | ⭐⭐ | ⭐⭐ |

---

## 四、推荐方案：方案1+方案2混合

### 4.1 核心设计

**智能切换**：
- 桌面端：浮动窗口（可拖动、调整大小）
- 移动端：全屏模态对话框
- 可选：右侧面板模式（用户可切换）

**用户可选择**：
```
设置 → 界面设置 → 聊天窗口模式：
  ◉ 浮动窗口（推荐）
  ○ 右侧面板
  ○ 模态对话框
  ○ 底部面板
```

---

### 4.2 浮动窗口详细设计

#### 窗口特性

```
┌──────────────────────────────────────────────┐
│ 🤖 会议纪要助手              [—] [□] [✕]   │ ← 窗口标题栏
├──────────────────────────────────────────────┤
│                                              │
│  🤖 您好！我是会议纪要助手。我可以帮您：     │
│     • 转写会议录音                          │
│     • 生成结构化会议纪要                    │
│     • 提取待办事项                          │
│                                              │
│  用户: 帮我处理这个音频文件                 │
│                                              │
│  🤖 好的，我已收到音频文件，正在转写...     │
│                                              │
├──────────────────────────────────────────────┤
│ 📎 文件  📚 知识库  🎙️ 音频转写             │ ← 工具栏
├──────────────────────────────────────────────┤
│ [输入框]                          [发送]     │ ← 输入区
└──────────────────────────────────────────────┘
```

**功能特性**：

| 功能 | 说明 |
|------|------|
| **拖动** | 点击标题栏可拖动窗口位置 |
| **调整大小** | 拖动窗口边缘可调整大小 |
| **最小化** | 点击 `[—]` 最小化为浮动按钮 |
| **最大化** | 点击 `[□]` 全屏显示 |
| **关闭** | 点击 `[✕]` 关闭窗口 |
| **置顶** | 默认置顶，可配置 |

**默认位置和大小**：
- 初始位置：屏幕右侧中部
- 初始大小：宽度 480px，高度 600px
- 最小宽度：320px
- 最小高度：400px

---

#### 窗口状态管理

```typescript
interface ChatWindowState {
  // 显示状态
  visible: boolean;           // 是否显示
  minimized: boolean;         // 是否最小化
  maximized: boolean;         // 是否最大化
  
  // 位置和大小
  position: {
    x: number;
    y: number;
  };
  size: {
    width: number;
    height: number;
  };
  
  // 场景信息
  scene: {
    id: string;
    name: string;
    icon: string;
  } | null;
  
  // 聊天会话
  chatId: string | null;
}
```

---

### 4.3 交互流程

#### 用户操作流程

```
工作台页面
    ↓
点击场景卡片（会议纪要）
    ↓
调用 POST /api/scenes/{scene_id}/inject
    ↓
├─ 创建聊天会话
├─ 注入系统提示词
└─ 加载关联技能
    ↓
返回 { chat_id, scene, skills }
    ↓
打开浮动聊天窗口
    ├─ 显示场景信息（标题栏）
    ├─ 显示欢迎消息
    └─ 显示工具栏（关联技能）
    ↓
用户开始对话
    ↓
┌─ 用户关闭窗口 ─┐
│  保存会话状态  │
│  会话历史保留  │
└────────────────┘

┌─ 用户点击其他场景 ─┐
│  关闭当前会话     │
│  创建新会话       │
│  打开新窗口       │
└────────────────────┘
```

---

#### 窗口操作

```
最小化 → 浮动按钮
    └─ 点击浮动按钮 → 恢复窗口

最大化 → 全屏
    └─ ESC或点击还原 → 恢复窗口

关闭 → 保存会话，窗口消失
    └─ 点击场景卡片 → 重新打开（新会话）
    └─ 点击历史会话 → 打开历史会话
```

---

## 五、技术实现

### 5.1 组件结构

```
client/src/pages/Workbench/
├── index.tsx                      # 工作台主页面
├── components/
│   ├── LeftMenu.tsx              # 左侧菜单
│   ├── SceneCard.tsx             # 场景卡片
│   └── SceneGrid.tsx             # 场景网格
└── hooks/
    └── useWorkbenchData.ts       # 工作台数据Hook

client/src/components/ChatWindow/
├── index.tsx                      # 聊天窗口组件
├── WindowHeader.tsx              # 窗口标题栏
├── ChatContent.tsx               # 聊天内容
├── ChatToolbar.tsx               # 工具栏
├── ChatInput.tsx                 # 输入框
└── hooks/
    ├── useWindowState.ts         # 窗口状态Hook
    └── useDraggable.ts           # 拖动Hook
```

---

### 5.2 核心代码

#### 浮动窗口组件

```typescript
import { useState, useEffect } from 'react';
import { Modal } from 'antd';
import { DraggableCore } from 'react-draggable';
import { Resizable } from 'react-resizable';

interface Props {
  visible: boolean;
  scene: Scene | null;
  chatId: string | null;
  onClose: () => void;
  onMinimize: () => void;
}

export default function ChatWindow({
  visible,
  scene,
  chatId,
  onClose,
  onMinimize
}: Props) {
  const [position, setPosition] = useState({ x: 100, y: 100 });
  const [size, setSize] = useState({ width: 480, height: 600 });
  const [maximized, setMaximized] = useState(false);
  
  // 拖动处理
  const handleDrag = (e, data) => {
    setPosition({ x: data.x, y: data.y });
  };
  
  // 调整大小处理
  const handleResize = (e, { size: newSize }) => {
    setSize(newSize);
  };
  
  if (!visible) return null;
  
  if (maximized) {
    // 全屏模式
    return (
      <Modal
        open={true}
        onCancel={() => setMaximized(false)}
        width="100vw"
        style={{ top: 0, padding: 0, margin: 0 }}
        bodyStyle={{ height: '100vh' }}
        title={null}
        closable={false}
        footer={null}
      >
        <ChatContent scene={scene} chatId={chatId} />
      </Modal>
    );
  }
  
  // 浮动窗口模式
  return (
    <DraggableCore onDrag={handleDrag}>
      <Resizable
        width={size.width}
        height={size.height}
        onResize={handleResize}
        minConstraints={[320, 400]}
      >
        <div
          style={{
            position: 'fixed',
            left: position.x,
            top: position.y,
            width: size.width,
            height: size.height,
            zIndex: 1000,
            boxShadow: '0 4px 12px rgba(0,0,0,0.15)',
            borderRadius: '8px',
            overflow: 'hidden',
            background: '#fff',
          }}
        >
          {/* 标题栏 */}
          <WindowHeader
            scene={scene}
            onMinimize={onMinimize}
            onMaximize={() => setMaximized(true)}
            onClose={onClose}
          />
          
          {/* 聊天内容 */}
          <ChatContent scene={scene} chatId={chatId} />
        </div>
      </Resizable>
    </DraggableCore>
  );
}
```

---

#### 工作台页面

```typescript
import { useState } from 'react';
import ChatWindow from '../../components/ChatWindow';

export default function Workbench() {
  const [menuItems, setMenuItems] = useState([]);
  const [selectedMenu, setSelectedMenu] = useState('');
  const [scenes, setScenes] = useState([]);
  
  // 聊天窗口状态
  const [chatWindow, setChatWindow] = useState({
    visible: false,
    minimized: false,
    scene: null,
    chatId: null,
  });
  
  // 场景代入
  const handleSceneClick = async (scene: Scene) => {
    const result = await scenesApi.injectScene(scene.id);
    
    setChatWindow({
      visible: true,
      minimized: false,
      scene: result.scene,
      chatId: result.chat_id,
    });
  };
  
  // 关闭窗口
  const handleClose = () => {
    setChatWindow({
      visible: false,
      minimized: false,
      scene: null,
      chatId: null,
    });
  };
  
  // 最小化窗口
  const handleMinimize = () => {
    setChatWindow(prev => ({
      ...prev,
      visible: false,
      minimized: true,
    }));
  };
  
  // 恢复窗口
  const handleRestore = () => {
    setChatWindow(prev => ({
      ...prev,
      visible: true,
      minimized: false,
    }));
  };
  
  return (
    <Layout>
      {/* 左侧菜单 */}
      <LeftMenu
        items={menuItems}
        selected={selectedMenu}
        onSelect={setSelectedMenu}
      />
      
      {/* 内容区 */}
      <Content>
        <SceneGrid
          scenes={scenes}
          onSceneClick={handleSceneClick}
        />
      </Content>
      
      {/* 浮动聊天窗口 */}
      <ChatWindow
        visible={chatWindow.visible}
        scene={chatWindow.scene}
        chatId={chatWindow.chatId}
        onClose={handleClose}
        onMinimize={handleMinimize}
      />
      
      {/* 最小化后的浮动按钮 */}
      {chatWindow.minimized && (
        <FloatButton
          icon={chatWindow.scene?.icon}
          onClick={handleRestore}
        />
      )}
    </Layout>
  );
}
```

---

### 5.3 状态管理

#### 使用 Zustand 管理全局状态

```typescript
// stores/chatWindowStore.ts
import { create } from 'zustand';

interface ChatWindowState {
  // 窗口状态
  visible: boolean;
  minimized: boolean;
  maximized: boolean;
  position: { x: number; y: number };
  size: { width: number; height: number };
  
  // 场景和会话
  scene: Scene | null;
  chatId: string | null;
  
  // Actions
  openWindow: (scene: Scene, chatId: string) => void;
  closeWindow: () => void;
  minimizeWindow: () => void;
  maximizeWindow: () => void;
  restoreWindow: () => void;
  updatePosition: (position: { x: number; y: number }) => void;
  updateSize: (size: { width: number; height: number }) => void;
}

export const useChatWindowStore = create<ChatWindowState>((set) => ({
  // 初始状态
  visible: false,
  minimized: false,
  maximized: false,
  position: { x: 100, y: 100 },
  size: { width: 480, height: 600 },
  scene: null,
  chatId: null,
  
  // Actions
  openWindow: (scene, chatId) => set({
    visible: true,
    minimized: false,
    maximized: false,
    scene,
    chatId,
  }),
  
  closeWindow: () => set({
    visible: false,
    minimized: false,
    maximized: false,
    scene: null,
    chatId: null,
  }),
  
  minimizeWindow: () => set({
    visible: false,
    minimized: true,
  }),
  
  maximizeWindow: () => set({
    maximized: true,
  }),
  
  restoreWindow: () => set({
    visible: true,
    minimized: false,
    maximized: false,
  }),
  
  updatePosition: (position) => set({ position }),
  updateSize: (size) => set({ size }),
}));
```

---

## 六、场景代入实现

### 6.1 代入流程

```
┌─────────────────────────────────────────────────────────┐
│                   场景代入流程                          │
└─────────────────────────────────────────────────────────┘

用户点击场景卡片
    ↓
前端调用 POST /api/scenes/{scene_id}/inject
    ↓
后端 SceneInjectService.inject_scene()
    ↓
    ├─ 1. 获取场景配置
    │     └─ scene = scene_service.get_scene(scene_id)
    │
    ├─ 2. 创建聊天会话
    │     └─ chat = chat_service.create_chat(
    │            user_id=user_id,
    │            title=f"场景：{scene['name']}",
    │            scene_id=scene_id
    │        )
    │
    ├─ 3. 注入系统提示词
    │     └─ agent_service.update_system_prompt(
    │            agent_id=chat.agent_id,
    │            system_prompt=scene['system_prompt']
    │        )
    │
    ├─ 4. 加载关联技能
    │     └─ skill_service.load_skills(
    │            agent_id=chat.agent_id,
    │            skill_ids=scene['related_skills']
    │        )
    │
    └─ 5. 返回代入信息
          └─ {
               "chat_id": chat.id,
               "scene": {
                 "id": scene_id,
                 "name": scene['name'],
                 "icon": scene['icon'],
                 "welcome_message": scene['welcome_message']
               },
               "skills": scene['related_skills']
             }
    ↓
前端接收响应
    ↓
打开浮动聊天窗口
    ├─ 窗口标题：场景名称
    ├─ 显示欢迎消息
    └─ 工具栏显示关联技能
```

---

### 6.2 后端实现

#### SceneInjectService（已在之前文档中设计）

```python
# server/coapis/services/scene_inject_service.py

class SceneInjectService:
    """场景代入服务"""
    
    def inject_scene(self, scene_id: str, user_id: str) -> dict:
        """场景代入"""
        
        # 1. 获取场景配置
        scene = self.scene_service.get_scene(scene_id)
        if not scene:
            raise ValueError(f"场景不存在: {scene_id}")
        
        # 2. 创建聊天会话
        chat = self.chat_service.create_chat(
            user_id=user_id,
            title=f"场景：{scene['name']}",
            scene_id=scene_id
        )
        
        # 3. 注入系统提示词
        if scene.get('system_prompt'):
            self.agent_service.update_system_prompt(
                agent_id=chat.agent_id,
                system_prompt=scene['system_prompt']
            )
        
        # 4. 加载关联技能
        skills = scene.get('related_skills', [])
        if skills:
            self.skill_service.load_skills(
                agent_id=chat.agent_id,
                skill_ids=skills
            )
        
        # 5. 增加使用次数
        self.scene_service.increment_usage(scene_id)
        
        # 6. 返回代入信息
        return {
            "chat_id": chat.id,
            "scene": {
                "id": scene["id"],
                "name": scene["name"],
                "icon": scene["icon"],
                "welcome_message": scene.get("welcome_message", "")
            },
            "skills": skills
        }
```

---

## 七、与现有控制台的关系

### 7.1 两个入口

**工作台入口**：
- 路径：`/workbench`
- 菜单：场景分类（办公、数据、文档、沟通）
- 功能：选择场景 → 浮动聊天窗口
- 定位：业务场景导向

**控制台入口**：
- 路径：`/console/chat`
- 菜单：系统功能（聊天、控制、智能体、设置）
- 功能：完整聊天界面
- 定位：系统管理导向

---

### 7.2 路由设计

```
工作台：
  /workbench               → 工作台页面（场景选择）
  /workbench?chat=xxx      → 工作台页面 + 打开聊天窗口

控制台：
  /console/chat            → 聊天页面（完整界面）
  /console/chat/:chatId    → 聊天页面（具体会话）
```

---

### 7.3 用户选择

**用户可以自由选择**：
1. 从工作台进入：场景导向，浮动窗口
2. 从控制台进入：功能导向，完整界面
3. 两种方式共享相同的聊天数据

**推荐使用场景**：
- 日常业务：工作台（快速选择场景）
- 系统管理：控制台（完整功能）
- 历史查看：控制台（会话列表）

---

## 八、总结

### 8.1 推荐方案

**方案1+方案2混合**：
- 桌面端：浮动窗口（可拖动、调整大小）
- 移动端：全屏模态对话框
- 可选：右侧面板模式（用户可切换）

---

### 8.2 核心优势

| 优势 | 说明 |
|------|------|
| **菜单不变** | 工作台保持独立的场景分类菜单 |
| **体验连贯** | 用户无需离开工作台页面 |
| **多任务友好** | 可同时查看工作台和聊天内容 |
| **灵活切换** | 浮动窗口可最小化、最大化、关闭 |
| **屏幕空间** | 浮动窗口不占用工作台空间 |

---

### 8.3 技术要点

| 要点 | 技术 |
|------|------|
| **窗口拖动** | react-draggable |
| **窗口调整** | react-resizable |
| **状态管理** | Zustand |
| **窗口置顶** | z-index: 1000 |
| **最小化** | 隐藏窗口，显示浮动按钮 |

---

### 8.4 实施计划

| 阶段 | 任务 | 时间 |
|------|------|------|
| 阶段1 | 浮动窗口组件开发 | 2-3天 |
| 阶段2 | 工作台页面开发 | 2-3天 |
| 阶段3 | 场景代入后端实现 | 2天 |
| 阶段4 | 测试和优化 | 2天 |
| **总计** | | **8-10天** |

---

**文档版本**：v1.0  
**最后更新**：2026-07-17
