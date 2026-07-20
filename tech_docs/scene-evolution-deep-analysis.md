# 场景代入与进化能力的深度分析

> **核心问题**：场景代入后，进化结果应该保存到哪里？如何平衡隔离与共享？  
> **创建日期**：2026-07-17

---

## 一、问题定义

### 1.1 当前进化机制

#### 进化引擎工作原理

```
┌─────────────────────────────────────────────────────────┐
│                  进化引擎工作流程                        │
└─────────────────────────────────────────────────────────┘

对话轮次
    ↓
记录轨迹（trajectory）
    ├─ 用户输入
    ├─ AI 输出
    └─ 工具调用
    ↓
Nudge 触发（每 N 轮）
    ↓
经验提取（使用 LLM）
    ├─ 从对话中提取有价值经验
    └─ 判断置信度
    ↓
保存到 MEMORY.md
    ├─ 位置：workspace_dir / MEMORY.md
    └─ 格式：Markdown（人工可编辑）
    ↓
知识流动（可选）
    ├─ 实例层 → 专业层
    └─ 专业层 → 基础层
```

#### 进化结果存储位置

```
workspaces/{agent_id}/
├── MEMORY.md           # 进化记忆（长期记忆）
├── memory/             # 每日笔记
│   ├── 2026-07-17.md
│   └── ...
├── agents/             # 智能体配置
├── skills/             # 技能配置
└── files/              # 用户文件
```

**关键点**：
- 进化结果保存到 **智能体的工作空间**
- 每个智能体有独立的进化记忆
- 不同智能体的进化结果相互隔离

---

### 1.2 会话级隔离方案的进化问题

#### 问题1：进化结果存储位置

**会话级隔离方案**：
- 场景配置保存到 ChatSpec
- 不创建新智能体
- 运行时动态组装 Agent 配置

**问题**：
```
用户在"会议纪要"场景中进行对话
    ↓
进化引擎提取经验
    ↓
经验应该保存到哪里？
    ├─ 方案A：保存到默认智能体的 MEMORY.md
    │         → ❌ 污染默认智能体
    │
    ├─ 方案B：保存到场景知识库
    │         → ❌ 场景没有独立的进化空间
    │
    └─ 方案C：不保存
              → ❌ 进化能力丢失
```

---

#### 问题2：知识跨场景共享

**场景隔离 vs 知识共享**：

```
场景A：会议纪要
    ├─ 学到：音频转写的最佳实践
    └─ 学到：会议纪要的结构化方法

场景B：工作报告
    ├─ 需要：结构化写作方法
    └─ 问题：场景A的知识能共享吗？
```

**核心矛盾**：
- **隔离需求**：不同场景的系统提示词不同，进化结果应该隔离
- **共享需求**：某些知识是通用的，应该跨场景共享

---

#### 问题3：场景特定知识 vs 通用知识

**示例**：

```
场景A（会议纪要）学到的知识：
┌────────────────────────────────────────────────────┐
│ 场景特定知识（不应共享）                            │
│ - 会议纪要的标准格式                               │
│ - 音频转写的最佳实践                               │
│ - 待办事项提取的规则                               │
├────────────────────────────────────────────────────┤
│ 通用知识（可以共享）                               │
│ - 如何清晰表达                                     │
│ - 如何结构化写作                                   │
│ - 如何处理用户反馈                                 │
└────────────────────────────────────────────────────┘
```

---

## 二、方案分析

### 方案1：场景级进化（完全隔离）

#### 设计思路

**每个场景有独立的进化空间**：

```
场景：会议纪要
    ├─ MEMORY.md（场景记忆）
    ├─ 知识库（场景知识）
    └─ 进化引擎实例

场景：数据分析
    ├─ MEMORY.md（场景记忆）
    ├─ 知识库（场景知识）
    └─ 进化引擎实例
```

#### 数据结构

**场景配置（scenes.json）**：
```json
{
  "scenes": [
    {
      "id": "meeting-minutes",
      "name": "会议纪要",
      "workspace_dir": "scenes/meeting-minutes",  // ← 场景工作空间
      "system_prompt": "...",
      "related_skills": ["audio-transcription"]
    }
  ]
}
```

**场景工作空间**：
```
scenes/
├── meeting-minutes/
│   ├── MEMORY.md           # 场景进化记忆
│   ├── memory/             # 每日笔记
│   └── knowledge_base/     # 场景知识库
└── data-analysis/
    ├── MEMORY.md
    ├── memory/
    └── knowledge_base/
```

#### 进化流程

```
用户在"会议纪要"场景对话
    ↓
进化引擎提取经验
    ↓
保存到 scenes/meeting-minutes/MEMORY.md
    ↓
下次使用"会议纪要"场景时加载
```

#### 优点

- ✅ 完全隔离，不同场景互不干扰
- ✅ 场景特定的知识独立管理
- ✅ 进化结果清晰，易于追踪

#### 缺点

- ❌ 知识无法跨场景共享
- ❌ 相似场景需要重复学习
- ❌ 管理成本高（每个场景独立的 MEMORY.md）
- ❌ 不符合"场景是轻量级概念"的理念

---

### 方案2：智能体级进化（完全共享）

#### 设计思路

**所有场景共享默认智能体的进化空间**：

```
默认智能体
    ├─ MEMORY.md（共享记忆）
    ├─ 进化引擎实例
    └─ 场景配置（会话级）
        ├─ 会议纪要（快照）
        ├─ 数据分析（快照）
        └─ ...
```

#### 进化流程

```
用户在"会议纪要"场景对话
    ↓
进化引擎提取经验
    ↓
保存到默认智能体的 MEMORY.md
    ↓
所有场景共享该记忆
```

#### 优点

- ✅ 知识跨场景共享
- ✅ 实现简单，无需额外管理
- ✅ 进化结果统一

#### 缺点

- ❌ 可能污染：不同场景的知识混在一起
- ❌ 场景特定知识可能干扰其他场景
- ❌ 不符合场景隔离的理念

---

### 方案3：双层进化（推荐 ⭐⭐⭐）

#### 设计思路

**场景层 + 智能体层 双层进化**：

```
┌─────────────────────────────────────────────────────────┐
│                   双层进化架构                          │
└─────────────────────────────────────────────────────────┘

场景层（隔离）：
scenes/meeting-minutes/
    └─ MEMORY.md（场景特定知识）
        - 会议纪要的标准格式
        - 音频转写的最佳实践
        - 待办事项提取的规则

智能体层（共享）：
workspaces/default/
    └─ MEMORY.md（通用知识）
        - 如何清晰表达
        - 如何结构化写作
        - 如何处理用户反馈
```

#### 进化流程

```
用户在"会议纪要"场景对话
    ↓
进化引擎提取经验
    ↓
知识分类：
    ├─ 场景特定知识 → 保存到场景 MEMORY.md
    └─ 通用知识 → 保存到智能体 MEMORY.md
    ↓
下次使用"会议纪要"场景：
    ├─ 加载场景 MEMORY.md
    └─ 加载智能体 MEMORY.md（共享）
```

#### 技术实现

##### 数据结构

**场景工作空间**：
```
scenes/
├── meeting-minutes/
│   ├── MEMORY.md           # 场景记忆（隔离）
│   └── memory/
└── data-analysis/
    ├── MEMORY.md
    └── memory/
```

**智能体工作空间**：
```
workspaces/default/
├── MEMORY.md               # 通用记忆（共享）
└── memory/
```

##### 进化引擎增强

```python
class DualLayerEvolutionEngine:
    """双层进化引擎"""
    
    def __init__(
        self,
        scene_id: str = None,
        scene_workspace: Path = None,
        agent_workspace: Path = None
    ):
        self.scene_id = scene_id
        self.scene_workspace = scene_workspace
        self.agent_workspace = agent_workspace
    
    async def save_experience(self, experience: ExtractedExperience):
        """保存经验到双层"""
        
        # 判断知识类型
        if self._is_scene_specific(experience):
            # 场景特定知识 → 场景层
            memory_file = self.scene_workspace / "MEMORY.md"
        else:
            # 通用知识 → 智能体层
            memory_file = self.agent_workspace / "MEMORY.md"
        
        # 追加到 MEMORY.md
        self._append_to_memory(memory_file, experience)
    
    def _is_scene_specific(self, experience: ExtractedExperience) -> bool:
        """判断是否为场景特定知识"""
        
        # 方法1：基于标签判断
        if experience.tags and "scene-specific" in experience.tags:
            return True
        
        # 方法2：基于内容关键词判断
        scene_keywords = self._get_scene_keywords(self.scene_id)
        content = experience.content.lower()
        if any(kw in content for kw in scene_keywords):
            return True
        
        # 方法3：基于 LLM 判断（可选）
        # return await self._classify_with_llm(experience)
        
        return False
```

##### 知识分类规则

**基于标签判断**：
```python
# 场景配置中定义关键词
scene_keywords = {
    "meeting-minutes": ["会议", "纪要", "待办", "音频转写"],
    "data-analysis": ["数据", "分析", "图表", "报表"],
    "email-compose": ["邮件", "撰写", "商务"]
}

def is_scene_specific(experience, scene_id):
    keywords = scene_keywords.get(scene_id, [])
    content = experience.content.lower()
    return any(kw in content for kw in keywords)
```

**基于 LLM 判断**：
```python
async def classify_with_llm(experience, scene_config):
    prompt = f"""
    你是一个知识分类专家。请判断以下经验是否为场景特定知识。
    
    场景：{scene_config.name}
    场景描述：{scene_config.description}
    
    经验内容：
    {experience.content}
    
    如果该经验仅在当前场景中有用，回答"场景特定"。
    如果该经验在其他场景中也有用，回答"通用"。
    
    只回答"场景特定"或"通用"，不要其他内容。
    """
    
    response = await llm.chat(prompt)
    return "场景特定" in response
```

#### 优点

- ✅ 兼顾隔离和共享
- ✅ 场景特定知识独立管理
- ✅ 通用知识跨场景共享
- ✅ 符合知识流动的理念

#### 缺点

- ⭕ 实现复杂，需要知识分类逻辑
- ⭕ 需要管理两套 MEMORY.md
- ⭕ 用户需要理解双层概念

---

### 方案4：场景智能体（轻量级）

#### 设计思路

**每个场景对应一个轻量级智能体**：

```
场景：会议纪要 → 智能体：scene-meeting-minutes
    ├─ 但智能体配置由场景定义
    ├─ 用户不可见（自动管理）
    └─ 有独立的进化空间

场景：数据分析 → 智能体：scene-data-analysis
    └─ ...
```

#### 关键设计

**自动管理**：
- 场景智能体由系统自动创建
- 用户无需手动管理
- 场景智能体对用户不可见（或可选显示）

**轻量级**：
- 场景智能体只存储进化结果
- 其他配置从场景配置读取
- 不增加用户认知负担

#### 数据结构

**场景智能体配置**：
```json
{
  "id": "scene-meeting-minutes",
  "name": "会议纪要（场景智能体）",
  "type": "scene-agent",  // ← 标识为场景智能体
  "scene_id": "meeting-minutes",
  "visible": false,  // ← 对用户不可见
  "workspace_dir": "scenes/meeting-minutes",
  
  // 以下配置从场景配置读取（不存储）
  "system_prompt": null,  // 从场景配置读取
  "skills": null          // 从场景配置读取
}
```

#### 进化流程

```
用户在"会议纪要"场景对话
    ↓
使用场景智能体：scene-meeting-minutes
    ↓
进化引擎提取经验
    ↓
保存到场景智能体的 MEMORY.md
    ↓
下次使用"会议纪要"场景时加载
```

#### 优点

- ✅ 完全隔离，符合现有架构
- ✅ 进化能力不受影响
- ✅ 用户无需管理场景智能体
- ✅ 历史会话可正确恢复

#### 缺点

- ❌ 智能体数量增加
- ❌ 知识无法跨场景共享
- ⭕ 需要自动管理场景智能体

---

### 方案5：场景智能体 + 知识流动

#### 设计思路

**场景智能体 + 知识流动机制**：

```
┌─────────────────────────────────────────────────────────┐
│               场景智能体 + 知识流动                     │
└─────────────────────────────────────────────────────────┘

场景智能体（实例层）：
scene-meeting-minutes/
    └─ MEMORY.md
        - 会议纪要的标准格式（场景特定）
        - 音频转写的最佳实践（场景特定）
        - 如何清晰表达（通用）← 流动到专业层

专业层智能体：
user-default/
    └─ MEMORY.md
        - 如何清晰表达（来自场景）
        - 如何结构化写作
        - 通用知识库

知识流动：
场景智能体 → 专业层智能体
    └─ 通用知识自动流动
    └─ 场景特定知识保留
```

#### 知识流动规则

```python
class SceneKnowledgeFlow:
    """场景知识流动"""
    
    async def flow_to_professional(
        self,
        scene_agent: Agent,
        professional_agent: Agent
    ):
        """场景智能体 → 专业层智能体"""
        
        # 读取场景智能体的 MEMORY.md
        scene_memory = self._load_memory(scene_agent.workspace_dir)
        
        # 提取通用知识
        general_knowledge = self._extract_general_knowledge(scene_memory)
        
        # 流动到专业层智能体
        professional_memory = self._load_memory(professional_agent.workspace_dir)
        professional_memory += general_knowledge
        self._save_memory(professional_agent.workspace_dir, professional_memory)
        
        # 从场景智能体中移除已流动的知识
        scene_memory = self._remove_general_knowledge(scene_memory)
        self._save_memory(scene_agent.workspace_dir, scene_memory)
```

#### 优点

- ✅ 兼顾隔离和共享
- ✅ 知识流动机制已存在，可复用
- ✅ 符合多层架构理念
- ✅ 进化能力完整保留

#### 缺点

- ❌ 实现复杂
- ❌ 需要知识分类和流动逻辑
- ❌ 智能体数量增加

---

## 三、方案对比

| 维度 | 方案1 | 方案2 | 方案3 | 方案4 | 方案5 |
|------|-------|-------|-------|-------|-------|
| **知识隔离** | ✅ 完全隔离 | ❌ 无隔离 | ✅ 部分隔离 | ✅ 完全隔离 | ✅ 完全隔离 |
| **知识共享** | ❌ 无共享 | ✅ 完全共享 | ✅ 部分共享 | ❌ 无共享 | ✅ 流动共享 |
| **进化能力** | ✅ 完整 | ✅ 完整 | ✅ 完整 | ✅ 完整 | ✅ 完整 |
| **实现复杂度** | 低 | 低 | 高 | 中 | 高 |
| **智能体数量** | 场景数 | 不增加 | 不增加 | 场景数+1 | 场景数+1 |
| **用户管理** | 复杂 | 简单 | 中等 | 简单（自动） | 简单（自动） |
| **推荐度** | ⭐⭐ | ⭐⭐ | ⭐⭐⭐ | ⭐⭐⭐⭐ | ⭐⭐⭐⭐⭐ |

---

## 四、推荐方案：方案4（场景智能体）

### 4.1 核心设计

**关键理念**：
- 场景智能体 = 轻量级智能体，自动管理
- 场景智能体对用户不可见
- 场景智能体专注于进化结果存储

---

### 4.2 数据结构

#### 场景智能体配置

```json
{
  "id": "scene-meeting-minutes",
  "name": "会议纪要（场景智能体）",
  "type": "scene-agent",
  "scene_id": "meeting-minutes",
  "visible": false,
  "auto_managed": true,
  "workspace_dir": "scenes/meeting-minutes",
  
  // 以下配置运行时从场景配置读取
  "_runtime_config": {
    "system_prompt": null,
    "skills": null,
    "tools": null,
    "model": null
  }
}
```

#### 场景配置（scenes.json）

```json
{
  "scenes": [
    {
      "id": "meeting-minutes",
      "name": "会议纪要",
      "icon": "📝",
      "agent_id": "scene-meeting-minutes",  // ← 关联场景智能体
      
      "system_prompt": "你是一个专业的会议纪要助手...",
      "related_skills": ["audio-transcription"],
      "welcome_message": "您好！我是会议纪要助手..."
    }
  ]
}
```

---

### 4.3 自动管理逻辑

#### 场景智能体创建

```python
class SceneAgentManager:
    """场景智能体管理器"""
    
    def ensure_scene_agent(self, scene_id: str, user_id: str) -> str:
        """确保场景智能体存在"""
        
        agent_id = f"scene-{scene_id}-{user_id}"
        
        # 检查智能体是否存在
        if self.agent_exists(agent_id):
            return agent_id
        
        # 创建场景智能体
        scene = self.scene_service.get_scene(scene_id)
        
        agent_config = {
            "id": agent_id,
            "name": f"{scene['name']}（场景智能体）",
            "type": "scene-agent",
            "scene_id": scene_id,
            "visible": False,
            "auto_managed": True,
            "workspace_dir": f"scenes/{scene_id}/{user_id}",
            
            # 运行时配置（从场景配置读取）
            "_runtime_config": {
                "system_prompt": scene["system_prompt"],
                "skills": scene.get("related_skills", []),
                "tools": [],
                "model": self.get_default_model(user_id)
            }
        }
        
        self.create_agent(agent_config)
        return agent_id
```

#### 场景代入流程

```python
async def inject_scene(scene_id: str, user_id: str):
    """场景代入"""
    
    # 1. 确保场景智能体存在
    agent_id = scene_agent_manager.ensure_scene_agent(scene_id, user_id)
    
    # 2. 获取场景配置
    scene = scene_service.get_scene(scene_id)
    
    # 3. 创建聊天会话
    chat = chat_manager.create_chat(
        user_id=user_id,
        agent_id=agent_id,  # ← 使用场景智能体
        name=f"场景：{scene['name']}",
        scene_id=scene_id
    )
    
    # 4. 返回代入信息
    return {
        "chat_id": chat.id,
        "agent_id": agent_id,
        "scene": {
            "id": scene["id"],
            "name": scene["name"],
            "icon": scene["icon"],
            "welcome_message": scene.get("welcome_message", "")
        }
    }
```

---

### 4.4 进化能力保留

#### 进化引擎绑定

```python
# 运行时：场景智能体绑定进化引擎

agent = load_agent(agent_id)  # agent_id = "scene-meeting-minutes-user123"

# 绑定进化引擎
evolution_engine = EvolutionEngine(
    agent_core=agent,
    workspace_dir=agent.workspace_dir,  # scenes/meeting-minutes/user123
    config=evolution_config
)

agent.set_evolution_engine(evolution_engine)
```

#### 进化结果存储

```
scenes/
└── meeting-minutes/
    └── user123/
        ├── MEMORY.md           # 场景进化记忆
        ├── memory/             # 每日笔记
        │   ├── 2026-07-17.md
        │   └── ...
        └── files/              # 场景相关文件
```

---

### 4.5 场景智能体的生命周期

#### 自动创建

```
用户首次使用场景
    ↓
检查场景智能体是否存在
    ↓
不存在 → 自动创建
    ├─ 创建工作空间：scenes/{scene_id}/{user_id}
    ├─ 初始化 MEMORY.md
    └─ 绑定进化引擎
```

#### 自动清理（可选）

```
用户删除所有场景会话
    ↓
系统检测到场景智能体无活动会话
    ↓
提示用户：是否清理场景记忆？
    ├─ 是 → 删除场景智能体和工作空间
    └─ 否 → 保留
```

---

## 五、总结

### 5.1 推荐方案

**方案4：场景智能体（轻量级）**

---

### 5.2 核心优势

| 优势 | 说明 |
|------|------|
| **进化能力完整** | 场景智能体有独立的进化空间 |
| **知识隔离** | 不同场景的进化结果相互隔离 |
| **自动管理** | 场景智能体由系统自动创建和管理 |
| **用户无感** | 场景智能体对用户不可见，不增加认知负担 |
| **历史可恢复** | 场景会话关联场景智能体，历史可正确恢复 |
| **符合架构** | 复用现有智能体架构，无需大规模改造 |

---

### 5.3 与会话级隔离方案的对比

| 维度 | 会话级隔离 | 场景智能体 |
|------|-----------|-----------|
| **进化能力** | ❌ 丢失或污染 | ✅ 完整保留 |
| **知识隔离** | ⭕ 会话级隔离 | ✅ 场景级隔离 |
| **历史恢复** | ⭕ 需要配置快照 | ✅ 智能体绑定 |
| **实现复杂度** | 低 | 中 |
| **智能体数量** | 不增加 | 增加（自动管理） |
| **推荐度** | ⭐⭐⭐ | ⭐⭐⭐⭐⭐ |

---

### 5.4 实施建议

**第一阶段**（3-4天）：
1. 实现场景智能体自动创建逻辑
2. 修改场景代入 API（使用场景智能体）
3. 测试场景智能体的进化能力

**第二阶段**（2-3天）：
1. 实现场景智能体自动清理逻辑
2. 前端场景管理界面
3. 用户体验优化

**第三阶段**（2-3天）：
1. 场景智能体的可视化管理（可选）
2. 知识流动机制（可选）
3. 文档完善

---

**文档版本**：v1.0  
**最后更新**：2026-07-17
