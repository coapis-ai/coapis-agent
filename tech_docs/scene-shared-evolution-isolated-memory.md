# 场景智能体的共享进化与隔离记忆架构

> **核心设计**：进化结果共享（共同进化） + 记忆隔离（用户隐私）  
> **创建日期**：2026-07-17

---

## 一、核心概念区分

### 1.1 两个关键概念

#### 进化结果（Evolution Results）- 共享

**定义**：从对话中提取的通用经验、知识、最佳实践

**特征**：
- ✅ 可以共享：不同用户共同贡献
- ✅ 持久化：长期积累，场景越来越聪明
- ✅ 匿名化：不包含用户隐私信息

**示例**：
```
进化结果（共享）：
┌────────────────────────────────────────────────────────┐
│ 会议纪要场景学到的经验：                                │
│                                                        │
│ 1. 结构化写作经验：                                     │
│    - 会议纪要应包含：时间、参会人、议题、决议、待办      │
│    - 待办事项应明确责任人、截止时间                      │
│                                                        │
│ 2. 音频转写经验：                                       │
│    - 音频质量差时，建议分段转写                          │
│    - 专业术语需要上下文支持                              │
│                                                        │
│ 3. 用户偏好经验：                                       │
│    - 大部分用户喜欢简洁的会议纪要                        │
│    - 待办事项最好用表格形式                              │
└────────────────────────────────────────────────────────┘
```

---

#### 记忆（Memory）- 隔离

**定义**：用户的个人对话历史、偏好、上下文

**特征**：
- ❌ 不能共享：每个用户独立
- ❌ 持久化：用户级别持久化
- ❌ 隐私保护：包含用户隐私信息

**示例**：
```
用户A的记忆（隔离）：
┌────────────────────────────────────────────────────────┐
│ 个人对话历史：                                          │
│ - 2026-07-17：处理了财务部会议纪要                      │
│ - 2026-07-16：处理了技术部会议纪要                      │
│                                                        │
│ 个人偏好：                                              │
│ - 喜欢详细的会议纪要                                    │
│ - 待办事项用Markdown表格                                │
│ - 常用参会人：张三、李四、王五                          │
│                                                        │
│ 个人上下文：                                            │
│ - 最近处理的是财务部会议                                │
│ - 下次会议是下周一                                      │
└────────────────────────────────────────────────────────┘

用户B的记忆（隔离）：
┌────────────────────────────────────────────────────────┐
│ 个人对话历史：                                          │
│ - 2026-07-17：处理了销售部会议纪要                      │
│ - 2026-07-15：处理了市场部会议纪要                      │
│                                                        │
│ 个人偏好：                                              │
│ - 喜欢简洁的会议纪要                                    │
│ - 待办事项用列表形式                                    │
│ - 常用参会人：赵六、孙七                                │
└────────────────────────────────────────────────────────┘
```

---

### 1.2 类比理解

**类比1：维基百科 + 个人笔记本**

```
场景智能体 = 维基百科（共享）
    ├─ 进化结果 = 公共词条（共享）
    │   └─ 所有用户共同编辑、贡献
    │
    └─ 记忆 = 个人笔记本（隔离）
        ├─ 用户A的笔记本（隔离）
        └─ 用户B的笔记本（隔离）
```

**类比2：开源项目 + 个人配置**

```
场景智能体 = 开源项目（共享）
    ├─ 进化结果 = 项目代码（共享）
    │   └─ 所有开发者共同贡献
    │
    └─ 记忆 = 个人配置文件（隔离）
        ├─ 用户A的 .config（隔离）
        └─ 用户B的 .config（隔离）
```

---

## 二、架构设计

### 2.1 三层架构

```
┌─────────────────────────────────────────────────────────┐
│                   场景智能体三层架构                     │
└─────────────────────────────────────────────────────────┘

第1层：场景基础层（全局共享）
scenes/meeting-minutes/
    ├── MEMORY.md               # 进化结果（共享）
    ├── evolution_history.jsonl # 进化历史（共享）
    └── knowledge_base/         # 场景知识库（共享）

第2层：用户实例层（用户隔离）
scenes/meeting-minutes/
    └── users/
        ├── user-A/
        │   ├── MEMORY.md       # 用户A的记忆（隔离）
        │   ├── preferences.json # 用户A的偏好（隔离）
        │   └── chat_history/   # 用户A的对话历史（隔离）
        │
        └── user-B/
            ├── MEMORY.md       # 用户B的记忆（隔离）
            ├── preferences.json # 用户B的偏好（隔离）
            └── chat_history/   # 用户B的对话历史（隔离）

第3层：会话层（会话级）
chats/
    ├── chat-xxx（用户A的会话）
    └── chat-yyy（用户B的会话）
```

---

### 2.2 数据存储结构

#### 场景基础层（共享）

```
scenes/meeting-minutes/
├── MEMORY.md                    # 进化结果（共享）
│   ┌────────────────────────────┐
│   │ # 会议纪要场景进化记忆      │
│   │                            │
│   │ ## 结构化写作经验           │
│   │ - 会议纪要应包含：...      │
│   │                            │
│   │ ## 音频转写经验             │
│   │ - 音频质量差时，...        │
│   └────────────────────────────┘
│
├── evolution_history.jsonl      # 进化历史（共享）
│   {"timestamp": "...", "experience": "...", "confidence": 0.8}
│   {"timestamp": "...", "experience": "...", "confidence": 0.9}
│
└── knowledge_base/              # 场景知识库（共享）
    ├── meeting_template.md
    └── terminology.md
```

#### 用户实例层（隔离）

```
scenes/meeting-minutes/users/
├── user-A/
│   ├── MEMORY.md               # 用户A的记忆（隔离）
│   │   ┌────────────────────────┐
│   │   │ # 个人记忆              │
│   │   │                        │
│   │   │ ## 最近对话             │
│   │   │ - 处理了财务部会议...  │
│   │   │                        │
│   │   │ ## 个人偏好             │
│   │   │ - 喜欢详细的纪要       │
│   │   └────────────────────────┘
│   │
│   ├── preferences.json        # 用户偏好（隔离）
│   │   {
│   │     "style": "detailed",
│   │     "format": "markdown-table",
│   │     "common_attendees": ["张三", "李四"]
│   │   }
│   │
│   └── chat_history/           # 对话历史（隔离）
│       ├── 2026-07-17.jsonl
│       └── 2026-07-16.jsonl
│
└── user-B/
    ├── MEMORY.md               # 用户B的记忆（隔离）
    ├── preferences.json        # 用户偏好（隔离）
    └── chat_history/           # 对话历史（隔离）
```

---

### 2.3 运行时加载逻辑

```python
class SceneAgentLoader:
    """场景智能体加载器"""
    
    def load_scene_agent(
        self,
        scene_id: str,
        user_id: str
    ) -> SceneAgent:
        """加载场景智能体（共享进化 + 隔离记忆）"""
        
        # 1. 加载共享的进化结果
        shared_memory = self._load_shared_memory(scene_id)
        # 路径：scenes/meeting-minutes/MEMORY.md
        
        # 2. 加载用户隔离的记忆
        user_memory = self._load_user_memory(scene_id, user_id)
        # 路径：scenes/meeting-minutes/users/user-A/MEMORY.md
        
        # 3. 加载用户偏好
        user_preferences = self._load_user_preferences(scene_id, user_id)
        # 路径：scenes/meeting-minutes/users/user-A/preferences.json
        
        # 4. 组装场景智能体
        agent = SceneAgent(
            scene_id=scene_id,
            user_id=user_id,
            
            # 共享部分
            shared_memory=shared_memory,
            evolution_engine=self._create_evolution_engine(scene_id),
            
            # 隔离部分
            user_memory=user_memory,
            user_preferences=user_preferences,
            chat_history=self._load_chat_history(scene_id, user_id)
        )
        
        return agent
```

---

## 三、进化流程

### 3.1 进化提取与分类

```
┌─────────────────────────────────────────────────────────┐
│              进化提取与分类流程                         │
└─────────────────────────────────────────────────────────┘

用户A在"会议纪要"场景对话
    ↓
进化引擎提取经验
    ↓
经验分类：
    ├─ 通用经验 → 保存到共享层
    │   └─ scenes/meeting-minutes/MEMORY.md
    │
    └─ 个人经验 → 保存到用户层
        └─ scenes/meeting-minutes/users/user-A/MEMORY.md
    ↓
下次用户B使用场景：
    ├─ 加载共享的通用经验
    └─ 加载用户B的个人记忆
```

---

### 3.2 经验分类规则

#### 规则1：基于内容判断

```python
def classify_experience(experience: ExtractedExperience) -> str:
    """分类经验：shared（共享）或 user-specific（用户特定）"""
    
    # 关键词判断
    shared_keywords = [
        "最佳实践", "建议", "规则", "标准", "格式",
        "方法", "技巧", "经验", "总结"
    ]
    
    user_specific_keywords = [
        "我的", "个人", "偏好", "习惯", "最近"
    ]
    
    content = experience.content.lower()
    
    # 判断是否包含用户特定关键词
    if any(kw in content for kw in user_specific_keywords):
        return "user-specific"
    
    # 判断是否包含共享关键词
    if any(kw in content for kw in shared_keywords):
        return "shared"
    
    # 默认：共享
    return "shared"
```

#### 规则2：基于 LLM 判断（更智能）

```python
async def classify_with_llm(experience: ExtractedExperience) -> str:
    """使用 LLM 分类经验"""
    
    prompt = f"""
你是一个知识分类专家。请判断以下经验是否应该共享给其他用户。

经验内容：
{experience.content}

分类规则：
1. 如果该经验是通用的、对其他用户也有帮助的知识、方法、技巧、最佳实践
   → 回答"shared"（共享）

2. 如果该经验是用户个人的偏好、习惯、特定上下文
   → 回答"user-specific"（用户特定）

3. 如果经验包含用户隐私信息（姓名、电话、具体业务数据）
   → 回答"private"（私有，不保存）

只回答 "shared"、"user-specific" 或 "private"，不要其他内容。
"""
    
    response = await llm.chat(prompt)
    
    if "shared" in response:
        return "shared"
    elif "user-specific" in response:
        return "user-specific"
    else:
        return "private"
```

---

### 3.3 进化保存流程

```python
class DualLayerEvolutionEngine:
    """双层进化引擎（共享层 + 用户层）"""
    
    async def save_experience(
        self,
        experience: ExtractedExperience,
        scene_id: str,
        user_id: str
    ):
        """保存经验到双层"""
        
        # 1. 分类经验
        category = await self._classify_experience(experience)
        
        if category == "private":
            # 私有经验：不保存
            logger.info("Private experience discarded")
            return
        
        if category == "shared":
            # 共享经验：保存到场景基础层
            memory_file = self._get_shared_memory_path(scene_id)
            # scenes/meeting-minutes/MEMORY.md
            
            # 记录贡献者（可选）
            experience.metadata["contributed_by"] = user_id
            experience.metadata["contributed_at"] = datetime.now().isoformat()
            
            await self._append_to_memory(memory_file, experience)
            
            logger.info(
                f"Shared experience saved to {memory_file}, "
                f"contributed by {user_id}"
            )
        
        else:  # user-specific
            # 用户特定经验：保存到用户实例层
            memory_file = self._get_user_memory_path(scene_id, user_id)
            # scenes/meeting-minutes/users/user-A/MEMORY.md
            
            await self._append_to_memory(memory_file, experience)
            
            logger.info(
                f"User-specific experience saved to {memory_file}"
            )
```

---

## 四、记忆隔离机制

### 4.1 用户记忆的组成

```
用户记忆 = 个人对话历史 + 个人偏好 + 个人上下文
```

#### 个人对话历史

**存储位置**：`scenes/meeting-minutes/users/user-A/chat_history/`

**格式**：JSONL（按日期分文件）

```jsonl
# 2026-07-17.jsonl
{"timestamp": "2026-07-17T10:00:00Z", "role": "user", "content": "帮我处理财务部会议纪要"}
{"timestamp": "2026-07-17T10:00:05Z", "role": "assistant", "content": "好的，请上传会议录音..."}
```

**用途**：
- 回顾历史对话
- 学习用户偏好
- 提供上下文

**隔离级别**：完全隔离，不同用户之间不可见

---

#### 个人偏好

**存储位置**：`scenes/meeting-minutes/users/user-A/preferences.json`

**格式**：JSON

```json
{
  "style": "detailed",           // 详细 vs 简洁
  "format": "markdown-table",    // 格式偏好
  "language": "zh-CN",           // 语言偏好
  "common_attendees": [          // 常用参会人
    "张三",
    "李四",
    "王五"
  ],
  "common_topics": [             // 常用主题
    "周会",
    "项目评审",
    "季度总结"
  ],
  "custom_rules": [              // 自定义规则
    "待办事项必须包含截止时间",
    "决议必须标注负责人"
  ]
}
```

**用途**：
- 个性化服务
- 快速填充
- 自动优化

**隔离级别**：完全隔离，不同用户之间不可见

---

#### 个人上下文

**存储位置**：`scenes/meeting-minutes/users/user-A/MEMORY.md`

**格式**：Markdown

```markdown
# 个人记忆

## 最近对话
- 2026-07-17：处理了财务部会议纪要（预算评审）
- 2026-07-16：处理了技术部会议纪要（架构讨论）

## 个人偏好
- 喜欢详细的会议纪要
- 待办事项用Markdown表格
- 决议部分要加粗显示

## 常用上下文
- 最近处理的是财务部会议
- 下次会议是下周一（项目启动会）
- 需要关注预算相关问题
```

**用途**：
- 短期记忆
- 上下文理解
- 个性化响应

**隔离级别**：完全隔离，不同用户之间不可见

---

### 4.2 记忆访问控制

```python
class UserMemoryAccessControl:
    """用户记忆访问控制"""
    
    def can_access(
        self,
        memory_path: str,
        requesting_user: str,
        target_user: str
    ) -> bool:
        """检查是否有权限访问记忆"""
        
        # 管理员可以访问所有记忆
        if self._is_admin(requesting_user):
            return True
        
        # 用户只能访问自己的记忆
        if requesting_user == target_user:
            return True
        
        # 其他情况：拒绝访问
        logger.warning(
            f"Access denied: user {requesting_user} "
            f"tried to access {target_user}'s memory"
        )
        return False
    
    def get_user_memory_path(
        self,
        scene_id: str,
        user_id: str
    ) -> Path:
        """获取用户记忆路径（带权限检查）"""
        
        # 权限检查会在调用时进行
        return Path(f"scenes/{scene_id}/users/{user_id}/MEMORY.md")
```

---

## 五、团队协作共同进化

### 5.1 共享进化机制

```
┌─────────────────────────────────────────────────────────┐
│              团队协作共同进化流程                       │
└─────────────────────────────────────────────────────────┘

用户A使用"会议纪要"场景
    ↓
学到经验1："会议纪要应包含待办事项表格"
    ↓
分类：通用经验 → 保存到共享层
    ↓
用户B使用"会议纪要"场景
    ↓
加载共享层经验
    ├─ 经验1："会议纪要应包含待办事项表格"（来自用户A）
    ├─ 经验2："音频转写应分段处理"（来自用户C）
    └─ ...
    ↓
用户B学到经验3："专业术语需要上下文支持"
    ↓
分类：通用经验 → 保存到共享层
    ↓
场景越来越聪明！
```

---

### 5.2 进化贡献追踪

**目的**：追踪每个用户对场景进化的贡献

**存储位置**：`scenes/meeting-minutes/evolution_contributors.json`

```json
{
  "scene_id": "meeting-minutes",
  "total_contributions": 127,
  "contributors": {
    "user-A": {
      "count": 45,
      "last_contribution": "2026-07-17T10:00:00Z",
      "top_categories": ["结构化写作", "音频转写"]
    },
    "user-B": {
      "count": 32,
      "last_contribution": "2026-07-17T09:30:00Z",
      "top_categories": ["数据分析", "报告生成"]
    },
    "user-C": {
      "count": 50,
      "last_contribution": "2026-07-17T11:00:00Z",
      "top_categories": ["最佳实践", "规则提取"]
    }
  }
}
```

**用途**：
- 激励贡献
- 质量控制
- 贡献者认可

---

### 5.3 进化质量控制

**问题**：如何确保共享进化的质量？

#### 机制1：置信度过滤

```python
# 只有高置信度的经验才保存到共享层
if experience.confidence >= 0.7:
    save_to_shared_layer(experience)
else:
    save_to_user_layer(experience)
```

#### 机制2：多人验证

```python
# 经验需要多人验证才能进入共享层
class ExperienceValidator:
    """经验验证器"""
    
    async def validate_experience(
        self,
        experience: ExtractedExperience
    ) -> bool:
        """验证经验是否应该共享"""
        
        # 获取已验证次数
        validations = self._get_validations(experience.id)
        
        # 如果已有3人验证通过，自动批准
        if validations.count >= 3:
            return True
        
        # 否则，需要人工审核
        # 或者等待更多验证
        return False
```

#### 机制3：管理员审核

```python
# 关键经验需要管理员审核
class EvolutionReviewer:
    """进化审核器"""
    
    async def review_shared_experience(
        self,
        experience: ExtractedExperience
    ) -> ApprovalStatus:
        """审核共享经验"""
        
        # 自动判断：如果包含敏感关键词，需要人工审核
        if self._contains_sensitive_info(experience):
            return ApprovalStatus.PENDING_REVIEW
        
        # 自动批准：高置信度 + 无敏感信息
        if experience.confidence >= 0.8:
            return ApprovalStatus.AUTO_APPROVED
        
        # 其他情况：等待审核
        return ApprovalStatus.PENDING_REVIEW
```

---

## 六、完整架构

### 6.1 数据流

```
┌─────────────────────────────────────────────────────────┐
│                   完整数据流架构                        │
└─────────────────────────────────────────────────────────┘

场景代入请求（scene_id + user_id）
    ↓
SceneAgentLoader.load_scene_agent()
    ↓
    ├─ 加载共享层（共享）
    │   ├─ scenes/meeting-minutes/MEMORY.md
    │   ├─ scenes/meeting-minutes/evolution_history.jsonl
    │   └─ scenes/meeting-minutes/knowledge_base/
    │
    └─ 加载用户层（隔离）
        ├─ scenes/meeting-minutes/users/user-A/MEMORY.md
        ├─ scenes/meeting-minutes/users/user-A/preferences.json
        └─ scenes/meeting-minutes/users/user-A/chat_history/
    ↓
组装 SceneAgent 实例
    ↓
用户开始对话
    ↓
对话结束
    ↓
进化引擎提取经验
    ↓
经验分类
    ├─ 通用经验 → 保存到共享层
    ├─ 用户特定经验 → 保存到用户层
    └─ 私有经验 → 不保存
    ↓
下次使用时加载更新后的记忆
```

---

### 6.2 组件架构

```
┌─────────────────────────────────────────────────────────┐
│                   组件架构                             │
└─────────────────────────────────────────────────────────┘

SceneAgentLoader
    ├─ load_shared_memory() → 加载共享进化结果
    ├─ load_user_memory() → 加载用户隔离记忆
    └─ assemble_agent() → 组装场景智能体

DualLayerEvolutionEngine
    ├─ extract_experiences() → 提取经验
    ├─ classify_experience() → 分类经验
    ├─ save_to_shared_layer() → 保存到共享层
    └─ save_to_user_layer() → 保存到用户层

UserMemoryAccessControl
    ├─ can_access() → 权限检查
    ├─ get_user_memory_path() → 获取用户记忆路径
    └─ enforce_isolation() → 强制隔离

ExperienceValidator
    ├─ validate() → 验证经验质量
    ├─ filter_low_confidence() → 过滤低置信度经验
    └─ require_consensus() → 多人验证

EvolutionContributorTracker
    ├─ track_contribution() → 追踪贡献
    ├─ get_contributors() → 获取贡献者列表
    └─ get_user_stats() → 获取用户统计
```

---

## 七、安全与隐私

### 7.1 隐私保护机制

#### 敏感信息检测

```python
class SensitiveInfoDetector:
    """敏感信息检测器"""
    
    PATTERNS = {
        "phone": r"\d{11}",
        "email": r"[\w.-]+@[\w.-]+\.\w+",
        "id_card": r"\d{17}[\dXx]",
        "bank_card": r"\d{16,19}"
    }
    
    def detect(self, text: str) -> List[str]:
        """检测敏感信息"""
        detected = []
        for name, pattern in self.PATTERNS.items():
            if re.search(pattern, text):
                detected.append(name)
        return detected
    
    def sanitize(self, text: str) -> str:
        """脱敏处理"""
        for name, pattern in self.PATTERNS.items():
            text = re.sub(pattern, f"[{name}_REDACTED]", text)
        return text
```

#### 自动脱敏

```python
async def save_experience(experience: ExtractedExperience):
    """保存经验前自动脱敏"""
    
    # 检测敏感信息
    detector = SensitiveInfoDetector()
    sensitive_types = detector.detect(experience.content)
    
    if sensitive_types:
        # 记录日志
        logger.warning(
            f"Sensitive info detected: {sensitive_types}, "
            f"sanitizing before save"
        )
        
        # 脱敏处理
        experience.content = detector.sanitize(experience.content)
        
        # 标记为已脱敏
        experience.metadata["sanitized"] = True
        experience.metadata["sanitized_types"] = sensitive_types
    
    # 保存
    await _save(experience)
```

---

### 7.2 访问控制

#### 权限矩阵

| 资源 | 用户A | 用户B | 管理员 |
|------|-------|-------|--------|
| 用户A的记忆 | ✅ | ❌ | ✅ |
| 用户B的记忆 | ❌ | ✅ | ✅ |
| 共享进化结果 | ✅ | ✅ | ✅ |
| 场景知识库 | ✅ | ✅ | ✅ |

#### 实现示例

```python
@router.get("/scenes/{scene_id}/memory")
async def get_scene_memory(
    scene_id: str,
    request: Request
):
    """获取场景记忆（共享 + 用户）"""
    
    user_id = request.state.username
    
    # 1. 获取共享记忆
    shared_memory = scene_service.get_shared_memory(scene_id)
    
    # 2. 获取用户记忆（带权限检查）
    user_memory = scene_service.get_user_memory(
        scene_id,
        user_id,
        requesting_user=user_id  # 只能访问自己的
    )
    
    return {
        "shared": shared_memory,
        "user": user_memory
    }
```

---

## 八、总结

### 8.1 核心设计

**三层架构**：
1. **场景基础层（共享）**：进化结果、知识库
2. **用户实例层（隔离）**：个人记忆、偏好、对话历史
3. **会话层**：具体对话会话

**关键机制**：
- 进化结果共享：不同用户共同贡献，场景越来越聪明
- 记忆隔离：每个用户的个人记忆完全隔离
- 经验分类：自动判断经验应该共享还是隔离
- 质量控制：置信度过滤、多人验证、管理员审核

---

### 8.2 核心优势

| 优势 | 说明 |
|------|------|
| **共同进化** | 不同用户共同贡献，场景越来越聪明 |
| **记忆隔离** | 用户隐私保护，记忆完全隔离 |
| **知识共享** | 通用经验共享，避免重复学习 |
| **质量控制** | 多重机制确保进化质量 |
| **灵活扩展** | 支持企业级多租户场景 |

---

### 8.3 实施计划

| 阶段 | 任务 | 时间 |
|------|------|------|
| 阶段1 | 双层存储结构实现 | 2天 |
| 阶段2 | 进化引擎改造（分类保存） | 2天 |
| 阶段3 | 记忆访问控制实现 | 1天 |
| 阶段4 | 敏感信息检测与脱敏 | 1天 |
| 阶段5 | 质量控制机制实现 | 1天 |
| 阶段6 | 测试与优化 | 2天 |
| **总计** | | **9天** |

---

**文档版本**：v1.0  
**最后更新**：2026-07-17
