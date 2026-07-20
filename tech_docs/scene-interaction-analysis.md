# 场景卡片点击行为与代入功能分析

> **核心问题**：点击场景卡片后的交互方式，以及"场景代入"的技术实现  
> **创建日期**：2026-07-17

---

## 一、问题分析

### 1.1 两种交互方式对比

| 方案 | 描述 | 优点 | 缺点 |
|------|------|------|------|
| **A：直接跳转** | 点击卡片 → 直接跳转到聊天界面 | 快速、简单、用户体验流畅 | 无法预先选择文件/知识库 |
| **B：弹出对话框** | 点击卡片 → 弹出配置对话框 → 确认后跳转 | 可以预先配置参数 | 步骤多、增加用户操作成本 |

### 1.2 场景分类

根据是否需要外部输入，场景可以分为两类：

| 类型 | 特征 | 示例 | 推荐交互 |
|------|------|------|---------|
| **简单场景** | 无需外部输入，直接对话 | 邮件撰写、工作计划、通知公告 | 直接跳转 |
| **复杂场景** | 需要文件/知识库输入 | 会议纪要（音频）、合同审查（文档）、数据分析（表格） | 可能需要预配置 |

---

## 二、推荐方案：智能交互

### 2.1 核心设计

**统一使用"直接跳转"**，在聊天界面提供"场景工具栏"让用户按需选择文件/知识库。

**设计理念**：
- ✅ 保持交互简洁（一键直达）
- ✅ 在聊天界面提供足够的工具（文件选择、知识库选择）
- ✅ 欢迎消息引导用户使用工具

### 2.2 交互流程

```
┌─────────────────────────────────────────────┐
│  工作台界面                                  │
├─────────────────────────────────────────────┤
│                                             │
│  用户点击"会议纪要"卡片                     │
│                                             │
└───────────────┬─────────────────────────────┘
                ↓
┌─────────────────────────────────────────────┐
│  场景代入 API                                │
│  ├─ 创建聊天会话                            │
│  ├─ 注入系统提示词                          │
│  └─ 加载关联技能                            │
└───────────────┬─────────────────────────────┘
                ↓
┌─────────────────────────────────────────────┐
│  跳转到聊天界面                              │
├─────────────────────────────────────────────┤
│  顶部显示：                                  │
│  📝 会议纪要  [退出场景]                     │
├─────────────────────────────────────────────┤
│  欢迎消息：                                  │
│  "您好！我是会议纪要助手。我可以帮您：       │
│   • 转写会议录音                            │
│   • 生成结构化会议纪要                      │
│   • 提取待办事项                            │
│                                             │
│   [📎 上传音频文件] 开始转换"               │
├─────────────────────────────────────────────┤
│  工具栏（已加载技能）：                      │
│  📎 文件  📚 知识库  🎙️ 音频转写            │
└─────────────────────────────────────────────┘
```

---

## 三、场景代入的技术实现

### 3.1 代入流程

```
┌─────────────────────────────────────────────────────────┐
│                     场景代入流程                        │
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
    │     ├─ skills = get_related_skills(scene)
    │     └─ skill_service.load_skills(
    │            agent_id=chat.agent_id,
    │            skill_ids=skills
    │        )
    │
    ├─ 5. 增加使用次数
    │     └─ scene_service.increment_usage(scene_id)
    │
    └─ 6. 返回代入信息
          └─ {
               "chat_id": chat.id,
               "scene": {
                 "id": scene_id,
                 "name": scene['name'],
                 "icon": scene['icon'],
                 "welcome_message": scene['welcome_message']
               },
               "skills": skills
             }
    ↓
前端接收响应
    ↓
跳转到聊天界面 /chat/{chat_id}?scene={scene_id}
    ↓
聊天界面渲染
    ├─ 顶部显示场景信息（名称、图标、退出按钮）
    ├─ 显示欢迎消息
    └─ 工具栏显示关联技能
```

---

### 3.2 数据结构增强

#### 3.2.1 场景配置（scenes.json）

```json
{
  "scenes": [
    {
      "id": "meeting-minutes",
      "name": "会议纪要",
      "icon": "📝",
      "description": "快速生成会议纪要...",
      "short_description": "支持音频转写",
      
      "primary_tag": "office-function",
      "tags": ["office-function", "general-industry", "high-frequency"],
      
      "system_prompt": "你是一个专业的会议纪要助手...",
      "welcome_message": "您好！我是会议纪要助手。我可以帮您：\n• 转写会议录音\n• 生成结构化会议纪要\n• 提取待办事项\n\n[📎 上传音频文件] 开始转换",
      
      "related_skills": ["audio-transcription", "content-extraction"],
      
      "usage_count": 0,
      "created_at": "2026-07-17T10:00:00Z",
      "updated_at": "2026-07-17T10:00:00Z",
      "enabled": true
    }
  ]
}
```

**关键字段说明**：

| 字段 | 必填 | 说明 |
|------|------|------|
| `system_prompt` | ✅ | 系统提示词，定义AI的角色和行为 |
| `welcome_message` | ✅ | 欢迎消息，引导用户使用场景 |
| `related_skills` | ❌ | 关联技能ID列表，代入时自动加载 |

---

#### 3.2.2 聊天会话配置（chats.json）

```json
{
  "chats": [
    {
      "id": "chat-xxx",
      "title": "场景：会议纪要",
      "agent_id": "agent-xxx",
      "scene_id": "meeting-minutes",  // ← 新增：关联场景ID
      "user_id": "user-xxx",
      "created_at": "2026-07-17T10:00:00Z",
      "updated_at": "2026-07-17T10:00:00Z"
    }
  ]
}
```

**新增字段**：

| 字段 | 类型 | 说明 |
|------|------|------|
| `scene_id` | string | 关联的场景ID，可为空（普通聊天无场景） |

---

### 3.3 后端实现

#### 3.3.1 场景代入服务

**文件位置**：`server/coapis/services/scene_inject_service.py`

```python
from typing import Dict, List, Optional
from pathlib import Path
import json

class SceneInjectService:
    """场景代入服务"""
    
    def __init__(
        self,
        scene_service: SceneService,
        chat_service: ChatService,
        agent_service: AgentService,
        skill_service: SkillService
    ):
        self.scene_service = scene_service
        self.chat_service = chat_service
        self.agent_service = agent_service
        self.skill_service = skill_service
    
    def inject_scene(
        self,
        scene_id: str,
        user_id: str
    ) -> Dict:
        """
        场景代入
        
        Args:
            scene_id: 场景ID
            user_id: 用户ID
            
        Returns:
            代入结果，包含 chat_id, scene, skills
        """
        
        # 1. 获取场景配置
        scene = self.scene_service.get_scene(scene_id)
        if not scene:
            raise ValueError(f"场景不存在: {scene_id}")
        
        if not scene.get("enabled", True):
            raise ValueError(f"场景已禁用: {scene_id}")
        
        # 2. 创建聊天会话
        chat = self.chat_service.create_chat(
            user_id=user_id,
            title=f"场景：{scene['name']}",
            scene_id=scene_id  # 关联场景
        )
        
        # 3. 注入系统提示词
        system_prompt = scene.get("system_prompt", "")
        if system_prompt:
            self.agent_service.update_system_prompt(
                agent_id=chat.agent_id,
                system_prompt=system_prompt
            )
        
        # 4. 加载关联技能
        skills = self._get_related_skills(scene)
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
    
    def _get_related_skills(self, scene: Dict) -> List[str]:
        """获取关联技能"""
        
        skills = []
        
        # 1. 从场景配置获取
        scene_skills = scene.get("related_skills", [])
        skills.extend(scene_skills)
        
        # 2. 从主标签获取关联技能
        primary_tag_id = scene.get("primary_tag")
        if primary_tag_id:
            tag = self.scene_service.get_tag(primary_tag_id)
            if tag:
                tag_skills = tag.get("related_skills", [])
                skills.extend(tag_skills)
        
        # 去重
        return list(set(skills))
    
    def exit_scene(self, chat_id: str) -> Dict:
        """
        退出场景
        
        Args:
            chat_id: 聊天会话ID
            
        Returns:
            退出结果
        """
        
        # 获取聊天会话
        chat = self.chat_service.get_chat(chat_id)
        if not chat:
            raise ValueError(f"聊天会话不存在: {chat_id}")
        
        scene_id = chat.get("scene_id")
        if not scene_id:
            raise ValueError("当前会话不在场景中")
        
        # 清除场景关联
        self.chat_service.update_chat(
            chat_id=chat_id,
            scene_id=None
        )
        
        # 恢复默认系统提示词
        self.agent_service.reset_system_prompt(chat.agent_id)
        
        # 卸载场景技能
        scene = self.scene_service.get_scene(scene_id)
        if scene:
            skills = self._get_related_skills(scene)
            if skills:
                self.skill_service.unload_skills(
                    agent_id=chat.agent_id,
                    skill_ids=skills
                )
        
        return {
            "success": True,
            "scene_id": scene_id
        }
```

---

#### 3.3.2 API 接口

**文件位置**：`server/coapis/app/scenes.py`

```python
from fastapi import APIRouter, Depends, HTTPException
from typing import Optional

router = APIRouter(prefix="/api/scenes", tags=["scenes"])

@router.post("/{scene_id}/inject")
async def inject_scene(
    scene_id: str,
    user_id: str = Depends(get_current_user_id)
):
    """
    场景代入
    
    点击场景卡片后调用此API，创建聊天会话并注入场景配置
    """
    
    try:
        service = SceneInjectService()
        result = service.inject_scene(scene_id, user_id)
        return result
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.post("/chat/{chat_id}/exit")
async def exit_scene(
    chat_id: str,
    user_id: str = Depends(get_current_user_id)
):
    """
    退出场景
    
    在聊天界面点击"退出场景"按钮时调用
    """
    
    try:
        service = SceneInjectService()
        result = service.exit_scene(chat_id)
        return result
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.get("/chat/{chat_id}/scene")
async def get_chat_scene(
    chat_id: str,
    user_id: str = Depends(get_current_user_id)
):
    """
    获取聊天会话的场景信息
    
    用于聊天界面显示场景信息
    """
    
    chat_service = ChatService()
    chat = chat_service.get_chat(chat_id)
    
    if not chat:
        raise HTTPException(status_code=404, detail="聊天会话不存在")
    
    scene_id = chat.get("scene_id")
    if not scene_id:
        return {"scene": None}
    
    scene_service = SceneService()
    scene = scene_service.get_scene(scene_id)
    
    return {"scene": scene}
```

---

### 3.4 前端实现

#### 3.4.1 聊天界面场景显示

**文件位置**：`client/src/pages/Chat/components/SceneHeader.tsx`

```typescript
import React from 'react';
import { Tag, Button, Space } from 'antd';
import { CloseOutlined } from '@ant-design/icons';

interface Props {
  scene: {
    id: string;
    name: string;
    icon: string;
  };
  onExit: () => void;
}

export default function SceneHeader({ scene, onExit }: Props) {
  return (
    <div style={{
      padding: '8px 16px',
      background: '#f5f5f5',
      borderBottom: '1px solid #e8e8e8'
    }}>
      <Space>
        <Tag 
          color="blue" 
          style={{ fontSize: '14px', padding: '4px 8px' }}
        >
          {scene.icon} {scene.name}
        </Tag>
        
        <Button
          type="text"
          size="small"
          icon={<CloseOutlined />}
          onClick={onExit}
        >
          退出场景
        </Button>
      </Space>
    </div>
  );
}
```

---

#### 3.4.2 聊天页面集成

**文件位置**：`client/src/pages/Chat/index.tsx`

```typescript
import { useState, useEffect } from 'react';
import { useNavigate, useParams, useSearchParams } from 'react-router-dom';
import SceneHeader from './components/SceneHeader';

export default function ChatPage() {
  const { chatId } = useParams();
  const [searchParams] = useSearchParams();
  const navigate = useNavigate();
  
  const [scene, setScene] = useState(null);
  const [messages, setMessages] = useState([]);
  
  // 加载场景信息
  useEffect(() => {
    if (chatId) {
      loadChatScene(chatId);
    }
  }, [chatId]);
  
  const loadChatScene = async (chatId: string) => {
    try {
      const res = await scenesApi.getChatScene(chatId);
      setScene(res.scene);
      
      // 如果有场景，添加欢迎消息
      if (res.scene && messages.length === 0) {
        setMessages([{
          role: 'assistant',
          content: res.scene.welcome_message,
          type: 'welcome'
        }]);
      }
    } catch (error) {
      console.error('加载场景失败:', error);
    }
  };
  
  const handleExitScene = async () => {
    try {
      await scenesApi.exitScene(chatId);
      setScene(null);
      setMessages([]); // 清空消息
    } catch (error) {
      console.error('退出场景失败:', error);
    }
  };
  
  return (
    <div className="chat-page">
      {/* 场景头部 */}
      {scene && (
        <SceneHeader scene={scene} onExit={handleExitScene} />
      )}
      
      {/* 聊天内容 */}
      <div className="chat-content">
        <MessageList messages={messages} />
      </div>
      
      {/* 工具栏 */}
      <ChatToolbar scene={scene} />
      
      {/* 输入框 */}
      <ChatInput onSend={handleSend} />
    </div>
  );
}
```

---

## 四、场景代入的核心技术点

### 4.1 系统提示词注入

**时机**：场景代入时注入，退出场景时恢复

**实现方式**：

```python
# Agent 服务
class AgentService:
    
    def update_system_prompt(self, agent_id: str, system_prompt: str):
        """更新智能体的系统提示词"""
        
        agent = self.get_agent(agent_id)
        
        # 保存原始系统提示词
        if not hasattr(agent, '_original_system_prompt'):
            agent._original_system_prompt = agent.system_prompt
        
        # 设置新的系统提示词
        agent.system_prompt = system_prompt
        
        # 保存到配置文件
        self._save_agent_config(agent)
    
    def reset_system_prompt(self, agent_id: str):
        """恢复默认系统提示词"""
        
        agent = self.get_agent(agent_id)
        
        if hasattr(agent, '_original_system_prompt'):
            agent.system_prompt = agent._original_system_prompt
            delattr(agent, '_original_system_prompt')
            
            self._save_agent_config(agent)
```

---

### 4.2 技能加载

**时机**：场景代入时加载，退出场景时卸载

**实现方式**：

```python
# Skill 服务
class SkillService:
    
    def load_skills(self, agent_id: str, skill_ids: List[str]):
        """为智能体加载技能"""
        
        agent = self.get_agent(agent_id)
        
        for skill_id in skill_ids:
            skill = self.get_skill(skill_id)
            if skill:
                agent.add_skill(skill)
        
        # 更新智能体配置
        self._save_agent_config(agent)
    
    def unload_skills(self, agent_id: str, skill_ids: List[str]):
        """卸载智能体的技能"""
        
        agent = self.get_agent(agent_id)
        
        for skill_id in skill_ids:
            agent.remove_skill(skill_id)
        
        # 更新智能体配置
        self._save_agent_config(agent)
```

---

### 4.3 欢迎消息显示

**时机**：聊天会话创建后显示

**实现方式**：

```typescript
// 前端：检查是否需要显示欢迎消息
const loadChatScene = async (chatId: string) => {
  const res = await scenesApi.getChatScene(chatId);
  setScene(res.scene);
  
  // 如果有场景且没有历史消息，显示欢迎消息
  if (res.scene && messages.length === 0) {
    const welcomeMsg = {
      id: 'welcome',
      role: 'assistant',
      content: res.scene.welcome_message,
      type: 'welcome',  // 特殊类型，不持久化
      timestamp: new Date().toISOString()
    };
    
    setMessages([welcomeMsg]);
  }
};
```

**关键点**：
- 欢迎消息是虚拟消息，不保存到数据库
- 用户发送第一条消息后，欢迎消息消失
- 刷新页面时重新显示欢迎消息

---

## 五、总结

### 5.1 推荐方案

| 维度 | 设计 |
|------|------|
| **交互方式** | 直接跳转到聊天界面 |
| **场景代入** | 创建会话时注入配置 |
| **工具支持** | 聊天界面提供文件/知识库选择 |
| **欢迎引导** | 显示欢迎消息，引导用户使用 |

---

### 5.2 技术要点

| 功能 | 实现位置 | 说明 |
|------|---------|------|
| 系统提示词注入 | AgentService.update_system_prompt() | 场景代入时注入，退出时恢复 |
| 技能加载 | SkillService.load_skills() | 场景代入时加载，退出时卸载 |
| 欢迎消息 | 前端 ChatPage | 虚拟消息，不持久化 |
| 场景标识 | chats.scene_id | 会话关联场景ID |
| 退出场景 | SceneInjectService.exit_scene() | 清除场景配置 |

---

### 5.3 用户体验流程

```
工作台点击场景卡片
    ↓ 快速跳转
聊天界面（已注入场景配置）
    ├─ 顶部显示：📝 会议纪要 [退出场景]
    ├─ 显示欢迎消息
    └─ 工具栏显示关联技能
    ↓
用户选择文件（可选）
    ↓
开始对话
```

---

**文档版本**：v1.0  
**最后更新**：2026-07-17
