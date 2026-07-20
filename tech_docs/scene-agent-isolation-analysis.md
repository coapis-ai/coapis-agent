# 场景代入与智能体隔离深度分析

> **核心问题**：场景代入时，如何处理智能体的选择和隔离？  
> **创建日期**：2026-07-17

---

## 一、问题定义

### 1.1 当前架构理解

#### 智能体架构

**智能体概念**：
- 智能体 = 独立的 AI 配置单元
- 每个智能体有独立的：
  - 系统提示词（system_prompt）
  - 技能配置（skills）
  - 工具配置（tools）
  - 模型配置（model）
  - 工作空间（workspace）

**用户默认智能体**：
- 每个用户有一个默认智能体
- 默认智能体 ID：`default` 或 `user:{username}`
- 用户的所有聊天会话默认使用该智能体

**聊天会话与智能体的关系**：
- 聊天会话（Chat）不属于智能体
- 聊天会话独立存在，通过 `session_id` 关联
- 但聊天的 **运行时** 会使用智能体的配置

---

#### 数据模型

**ChatSpec（聊天会话）**：
```json
{
  "id": "chat-xxx",
  "session_id": "default",
  "user_id": "user-123",
  "channel": "default",
  "name": "聊天会话名称",
  "status": "idle",
  "pinned": false,
  "created_at": "2026-07-17T10:00:00Z",
  "updated_at": "2026-07-17T10:00:00Z"
}
```

**Agent（智能体）**：
```json
{
  "id": "default",
  "name": "默认智能体",
  "description": "用户默认智能体",
  "workspace_dir": "/workspaces/user-123",
  "system_prompt": "你是一个有用的AI助手...",
  "skills": [],
  "tools": [],
  "active_model": {
    "provider_id": "openai",
    "model": "gpt-4"
  }
}
```

---

### 1.2 核心问题

**问题1：污染问题**

如果所有场景都使用用户的默认智能体：

```
用户选择"会议纪要"场景
    ↓
注入系统提示词到默认智能体
    ↓
用户选择"数据分析"场景
    ↓
覆盖默认智能体的系统提示词
    ↓
❌ 之前的"会议纪要"配置被污染！
```

**问题2：历史会话混乱**

如果用户查看历史会话：

```
用户查看"会议纪要"场景的历史会话
    ↓
历史会话保存了当时的系统提示词
    ↓
但现在默认智能体的系统提示词已变成"数据分析"
    ↓
❌ 历史会话的上下文不一致！
```

**问题3：技能冲突**

不同场景需要不同的技能：

```
场景A：会议纪要 → 需要 audio-transcription 技能
场景B：数据分析 → 需要 data-analysis 技能

如果都使用默认智能体：
❌ 技能会相互覆盖
❌ 或者技能列表越来越长
```

---

## 二、方案分析

### 方案1：每个场景创建专用智能体

#### 设计思路

**场景 → 智能体 一对一映射**：
```
场景：会议纪要 → 智能体：scene-meeting-minutes
场景：数据分析 → 智能体：scene-data-analysis
场景：邮件撰写 → 智能体：scene-email-compose
```

#### 数据结构

**scenes.json**：
```json
{
  "scenes": [
    {
      "id": "meeting-minutes",
      "name": "会议纪要",
      "agent_id": "scene-meeting-minutes",  // ← 关联智能体ID
      "system_prompt": "...",
      "related_skills": ["audio-transcription"]
    }
  ]
}
```

#### 交互流程

```
用户点击场景卡片（会议纪要）
    ↓
检查是否存在 scene-meeting-minutes 智能体
    ├─ 存在 → 直接使用
    └─ 不存在 → 基于场景配置创建智能体
    ↓
创建聊天会话，关联该智能体
    ↓
用户开始对话
```

#### 优点

- ✅ 每个场景有独立的智能体，配置隔离
- ✅ 不同场景的系统提示词、技能不会冲突
- ✅ 历史会话可以正确恢复场景上下文
- ✅ 用户可以分别管理每个场景的智能体

#### 缺点

- ❌ 智能体数量会爆炸（场景越多，智能体越多）
- ❌ 用户需要管理大量智能体
- ❌ 系统提示词和场景配置重复存储
- ❌ 不符合"场景是轻量级概念"的设计理念

---

### 方案2：场景使用临时智能体

#### 设计思路

**场景代入时创建临时智能体，退出时删除**：

```
用户点击场景卡片
    ↓
创建临时智能体：temp-scene-xxx-timestamp
    ↓
用户开始对话
    ↓
用户关闭窗口或退出场景
    ↓
删除临时智能体
```

#### 优点

- ✅ 场景隔离，不会污染默认智能体
- ✅ 智能体数量不会爆炸
- ✅ 符合"场景是临时的"理念

#### 缺点

- ❌ 无法保存场景的历史会话（智能体被删除）
- ❌ 用户无法管理场景的智能体配置
- ❌ 每次使用场景都需要重新创建智能体
- ❌ 实现复杂（临时智能体的生命周期管理）

---

### 方案3：场景关联智能体模板

#### 设计思路

**场景配置中定义智能体模板，首次使用时创建**：

```
场景配置（scenes.json）：
{
  "id": "meeting-minutes",
  "name": "会议纪要",
  "agent_template": {  // ← 智能体模板
    "name": "会议纪要助手",
    "system_prompt": "你是一个专业的会议纪要助手...",
    "skills": ["audio-transcription"]
  }
}

用户首次使用场景：
    ↓
基于模板创建智能体：scene-meeting-minutes
    ↓
记录：场景 → 智能体 映射关系
    ↓
后续使用场景：
    ↓
复用已创建的智能体
```

#### 数据结构

**用户场景映射（user_scene_agents.json）**：
```json
{
  "user-123": {
    "meeting-minutes": "scene-meeting-minutes-user123",
    "data-analysis": "scene-data-analysis-user123"
  }
}
```

#### 优点

- ✅ 每个用户每个场景有独立智能体
- ✅ 历史会话可以正确恢复
- ✅ 用户可以管理自己的场景智能体
- ✅ 智能体数量可控（按用户+场景）

#### 缺点

- ❌ 实现较复杂（需要管理用户-场景-智能体映射）
- ❌ 多用户环境下智能体数量仍较多
- ⭕ 用户需要理解"场景智能体"的概念

---

### 方案4：会话级隔离（推荐 ⭐）

#### 设计思路

**不创建新智能体，在会话级别保存场景配置**：

```
聊天会话（ChatSpec）增强：
{
  "id": "chat-xxx",
  "session_id": "default",
  "user_id": "user-123",
  "scene_id": "meeting-minutes",  // ← 关联场景ID
  "scene_config": {               // ← 场景配置快照
    "system_prompt": "...",
    "skills": ["audio-transcription"],
    "welcome_message": "..."
  }
}
```

**运行时逻辑**：
```
加载聊天会话
    ↓
检查是否有 scene_id
    ├─ 有 → 从 scene_config 加载场景配置
    └─ 无 → 使用默认智能体配置
    ↓
动态组装 Agent 配置：
    - 系统提示词：scene_config.system_prompt
    - 技能：scene_config.skills
    - 其他：默认智能体配置
    ↓
创建 Agent 实例并运行
```

#### 技术实现

##### 数据结构

**ChatSpec 增强**：
```typescript
interface ChatSpec {
  id: string;
  session_id: string;
  user_id: string;
  channel: string;
  name: string | null;
  status: string;
  pinned: boolean;
  
  // 场景相关（新增）
  scene_id?: string;           // 场景ID
  scene_config?: {             // 场景配置快照
    name: string;
    icon: string;
    system_prompt: string;
    skills: string[];
    welcome_message?: string;
  };
}
```

##### 运行时逻辑

**Agent 组装器**：
```python
class AgentAssembler:
    """智能体组装器 - 动态组装 Agent 配置"""
    
    def assemble_agent_config(
        self,
        chat: ChatSpec,
        base_agent: Agent
    ) -> AgentConfig:
        """组装智能体配置
        
        Args:
            chat: 聊天会话
            base_agent: 基础智能体（用户默认智能体）
            
        Returns:
            组装后的智能体配置
        """
        
        # 如果没有场景，直接返回基础配置
        if not chat.scene_id:
            return AgentConfig(
                id=base_agent.id,
                system_prompt=base_agent.system_prompt,
                skills=base_agent.skills,
                tools=base_agent.tools,
                model=base_agent.active_model
            )
        
        # 有场景，组装场景配置
        scene_config = chat.scene_config
        
        return AgentConfig(
            id=f"{base_agent.id}:{chat.scene_id}",  # 复合ID
            system_prompt=scene_config.system_prompt,  # 场景提示词
            skills=scene_config.skills + base_agent.skills,  # 合并技能
            tools=base_agent.tools,  # 使用基础工具
            model=base_agent.active_model  # 使用基础模型
        )
```

##### 场景代入 API

```python
@router.post("/scenes/{scene_id}/inject")
async def inject_scene(
    scene_id: str,
    request: Request
):
    """场景代入"""
    
    user_id = request.state.username
    
    # 1. 获取场景配置
    scene = scene_service.get_scene(scene_id)
    if not scene:
        raise HTTPException(404, "场景不存在")
    
    # 2. 创建聊天会话（带场景配置）
    chat = chat_manager.create_chat(
        user_id=user_id,
        name=f"场景：{scene['name']}",
        scene_id=scene_id,
        scene_config={
            "name": scene["name"],
            "icon": scene["icon"],
            "system_prompt": scene["system_prompt"],
            "skills": scene.get("related_skills", []),
            "welcome_message": scene.get("welcome_message", "")
        }
    )
    
    # 3. 返回代入信息
    return {
        "chat_id": chat.id,
        "scene": {
            "id": scene["id"],
            "name": scene["name"],
            "icon": scene["icon"],
            "welcome_message": scene.get("welcome_message", "")
        }
    }
```

#### 优点

- ✅ **不需要创建新智能体**，避免数量爆炸
- ✅ **场景配置与会话绑定**，历史会话可正确恢复
- ✅ **用户默认智能体不受污染**，保持干净
- ✅ **实现简单**，只需扩展 ChatSpec 数据结构
- ✅ **灵活**，支持动态组装 Agent 配置
- ✅ **性能好**，不需要频繁创建/删除智能体

#### 缺点

- ⭕ **场景配置快照**：场景更新后，历史会话仍使用旧配置
- ⭕ **需要运行时组装**：每次运行会话都需要组装 Agent 配置

---

### 方案5：智能体池 + 场景动态绑定

#### 设计思路

**用户有一个智能体池，场景动态绑定智能体**：

```
用户智能体池：
├─ default（默认智能体）
├─ scene-meeting-minutes（会议纪要专用）
├─ scene-data-analysis（数据分析专用）
└─ scene-email-compose（邮件撰写专用）

场景绑定：
场景（会议纪要） → 智能体（scene-meeting-minutes）
    ↓
如果用户删除该智能体
    ↓
场景回退到默认智能体
```

#### 优点

- ✅ 灵活，用户可自定义场景智能体
- ✅ 场景智能体可独立管理

#### 缺点

- ❌ 复杂度高，需要管理智能体池和绑定关系
- ❌ 用户需要理解智能体池概念
- ❌ 删除智能体后场景回退，体验不好

---

## 三、方案对比

| 维度 | 方案1 | 方案2 | 方案3 | 方案4 | 方案5 |
|------|-------|-------|-------|-------|-------|
| **智能体数量** | 爆炸 | 可控 | 可控 | 不增加 | 可控 |
| **历史恢复** | ✅ | ❌ | ✅ | ✅ | ✅ |
| **实现复杂度** | 低 | 高 | 中 | 低 | 高 |
| **用户管理** | 复杂 | 简单 | 中等 | 简单 | 复杂 |
| **污染问题** | ✅ 解决 | ✅ 解决 | ✅ 解决 | ✅ 解决 | ✅ 解决 |
| **性能** | 中 | 差（频繁创建删除） | 好 | 最好 | 好 |
| **推荐度** | ⭐⭐ | ⭐ | ⭐⭐⭐ | ⭐⭐⭐⭐⭐ | ⭐⭐ |

---

## 四、推荐方案：方案4（会话级隔离）

### 4.1 核心设计

**关键理念**：
- 场景是轻量级概念，不应该创建重量级资源（智能体）
- 场景配置应该在会话级别保存，而不是智能体级别
- 运行时动态组装 Agent 配置，而不是修改 Agent 本身

---

### 4.2 数据结构设计

#### ChatSpec 增强

```typescript
interface ChatSpec {
  // 基础字段（现有）
  id: string;
  session_id: string;
  user_id: string;
  channel: string;
  name: string | null;
  status: string;
  pinned: boolean;
  created_at: string;
  updated_at: string;
  
  // 场景相关（新增）
  scene_id?: string;           // 场景ID
  scene_config?: SceneConfig;  // 场景配置快照
}

interface SceneConfig {
  // 场景信息
  id: string;
  name: string;
  icon: string;
  
  // AI 配置
  system_prompt: string;
  skills: string[];
  welcome_message?: string;
  
  // 元数据
  applied_at: string;  // 代入时间
}
```

#### 为什么需要配置快照？

**问题**：场景配置可能更新

```
用户A使用"会议纪要"场景
    ↓
场景配置：system_prompt = "v1.0"
    ↓
管理员更新场景配置：system_prompt = "v2.0"
    ↓
用户A查看历史会话
    ↓
应该使用 v1.0 还是 v2.0？
```

**答案**：使用快照（v1.0）

**理由**：
- 历史会话的上下文应该保持一致
- 用户可能基于 v1.0 的提示词进行了对话
- 如果使用 v2.0，可能产生不一致的结果

**设计**：
- 场景代入时，保存配置快照到会话
- 历史会话使用快照配置
- 新会话使用最新场景配置

---

### 4.3 运行时逻辑

#### Agent 组装流程

```
┌─────────────────────────────────────────────────────────┐
│                  Agent 组装流程                         │
└─────────────────────────────────────────────────────────┘

用户打开聊天会话
    ↓
ChatManager.load_chat(chat_id)
    ↓
返回 ChatSpec（包含 scene_config）
    ↓
AgentAssembler.assemble_agent_config(chat, base_agent)
    ↓
    ├─ 检查 chat.scene_id
    │
    ├─ 如果无场景：
    │     └─ 返回 base_agent 配置
    │
    └─ 如果有场景：
          ├─ 从 chat.scene_config 读取场景配置
          ├─ 合并配置：
          │     - system_prompt: scene_config.system_prompt
          │     - skills: scene_config.skills + base_agent.skills
          │     - tools: base_agent.tools
          │     - model: base_agent.active_model
          └─ 返回组装后的 AgentConfig
    ↓
创建 Agent 实例（临时，不持久化）
    ↓
运行对话
```

---

### 4.4 场景代入实现

#### 后端实现

**文件位置**：`server/coapis/app/routers/scenes.py`

```python
from fastapi import APIRouter, HTTPException, Request
from typing import Dict, Any
from ..runner.chat_manager import ChatManager
from ..services.scene_service import SceneService

router = APIRouter(prefix="/api/scenes", tags=["scenes"])

@router.post("/{scene_id}/inject")
async def inject_scene(
    scene_id: str,
    request: Request
):
    """场景代入"""
    
    user_id = request.state.username
    
    # 获取场景配置
    scene_service = SceneService()
    scene = scene_service.get_scene(scene_id)
    if not scene:
        raise HTTPException(404, detail="场景不存在")
    
    # 创建聊天会话（带场景配置快照）
    chat_manager = ChatManager()
    chat = chat_manager.create_chat(
        user_id=user_id,
        name=f"场景：{scene['name']}",
        scene_id=scene_id,
        scene_config={
            "id": scene["id"],
            "name": scene["name"],
            "icon": scene["icon"],
            "system_prompt": scene["system_prompt"],
            "skills": scene.get("related_skills", []),
            "welcome_message": scene.get("welcome_message", ""),
            "applied_at": datetime.now().isoformat()
        }
    )
    
    # 增加使用次数
    scene_service.increment_usage(scene_id)
    
    return {
        "chat_id": chat.id,
        "scene": {
            "id": scene["id"],
            "name": scene["name"],
            "icon": scene["icon"],
            "welcome_message": scene.get("welcome_message", "")
        }
    }
```

---

#### Agent 组装器实现

**文件位置**：`server/coapis/agents/agent_assembler.py`

```python
from typing import Dict, Any, List
from dataclasses import dataclass

@dataclass
class AgentConfig:
    """组装后的智能体配置"""
    id: str
    system_prompt: str
    skills: List[str]
    tools: List[str]
    model: Dict[str, Any]


class AgentAssembler:
    """智能体组装器"""
    
    def assemble(
        self,
        chat: 'ChatSpec',
        base_agent: 'Agent'
    ) -> AgentConfig:
        """组装智能体配置
        
        Args:
            chat: 聊天会话（可能包含场景配置）
            base_agent: 用户默认智能体
            
        Returns:
            组装后的智能体配置
        """
        
        # 无场景：返回基础配置
        if not chat.scene_id:
            return AgentConfig(
                id=base_agent.id,
                system_prompt=base_agent.system_prompt,
                skills=base_agent.skills,
                tools=base_agent.tools,
                model=base_agent.active_model
            )
        
        # 有场景：组装场景配置
        scene_config = chat.scene_config
        
        # 合并技能：场景技能 + 基础技能（去重）
        skills = list(set(
            scene_config.get("skills", []) + 
            base_agent.skills
        ))
        
        return AgentConfig(
            id=f"{base_agent.id}:{chat.scene_id}",
            system_prompt=scene_config["system_prompt"],
            skills=skills,
            tools=base_agent.tools,
            model=base_agent.active_model
        )
```

---

### 4.5 前端实现

#### 聊天窗口组件

```typescript
// pages/Workbench/components/ChatWindow.tsx

export default function ChatWindow({ chatId, scene }: Props) {
  const [messages, setMessages] = useState<Message[]>([]);
  
  useEffect(() => {
    // 加载聊天会话
    loadChat(chatId);
  }, [chatId]);
  
  const loadChat = async (chatId: string) => {
    const chat = await chatsApi.getChat(chatId);
    
    // 如果有场景配置，显示欢迎消息
    if (chat.scene_config && messages.length === 0) {
      const welcomeMsg = {
        id: 'welcome',
        role: 'assistant',
        content: chat.scene_config.welcome_message,
        type: 'welcome'
      };
      setMessages([welcomeMsg]);
    }
  };
  
  return (
    <div className="chat-window">
      <WindowHeader scene={scene} />
      <ChatContent messages={messages} />
      <ChatToolbar skills={scene?.skills} />
      <ChatInput onSend={handleSend} />
    </div>
  );
}
```

---

## 五、场景更新与历史会话

### 5.1 场景更新策略

**场景配置更新时，历史会话的处理**：

```
管理员更新"会议纪要"场景配置
    ↓
已有会话（使用旧配置）：保持不变
    ↓
新会话：使用新配置
```

**用户可以手动更新**：

```
用户打开历史会话
    ↓
检测到场景配置有更新
    ↓
提示：场景配置已更新，是否应用新配置？
    ├─ 是 → 更新会话的场景配置
    └─ 否 → 保持当前配置
```

---

### 5.2 实现方式

```typescript
// 前端：检查场景更新
const checkSceneUpdate = async (chat: ChatSpec) => {
  if (!chat.scene_config) return;
  
  // 获取最新场景配置
  const latestScene = await scenesApi.getScene(chat.scene_id);
  
  // 比较时间戳
  if (latestScene.updated_at > chat.scene_config.applied_at) {
    // 提示用户
    const shouldUpdate = await confirm(
      '场景配置已更新，是否应用新配置？'
    );
    
    if (shouldUpdate) {
      // 更新会话的场景配置
      await chatsApi.updateChatScene(chat.id, latestScene);
    }
  }
};
```

---

## 六、总结

### 6.1 推荐方案

**方案4：会话级隔离**

---

### 6.2 核心优势

| 优势 | 说明 |
|------|------|
| **不创建智能体** | 避免智能体数量爆炸 |
| **配置隔离** | 场景配置与会话绑定，不污染默认智能体 |
| **历史可恢复** | 会话保存场景配置快照，历史会话可正确恢复 |
| **实现简单** | 只需扩展 ChatSpec 数据结构 |
| **性能好** | 不需要频繁创建/删除智能体 |
| **灵活** | 支持动态组装 Agent 配置 |

---

### 6.3 技术要点

| 要点 | 说明 |
|------|------|
| **ChatSpec 增强** | 添加 scene_id 和 scene_config 字段 |
| **配置快照** | 场景代入时保存配置快照到会话 |
| **Agent 组装器** | 运行时动态组装 Agent 配置 |
| **技能合并** | 场景技能 + 基础技能（去重） |
| **场景更新** | 历史会话保持快照，新会话使用最新配置 |

---

### 6.4 实施建议

**第一阶段**（2-3天）：
1. 扩展 ChatSpec 数据结构
2. 实现场景代入 API
3. 实现 Agent 组装器

**第二阶段**（2-3天）：
1. 前端聊天窗口组件
2. 场景配置快照管理
3. 场景更新检测

**第三阶段**（1-2天）：
1. 测试和优化
2. 文档完善

---

**文档版本**：v1.0  
**最后更新**：2026-07-17
