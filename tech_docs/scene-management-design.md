# 场景管理设计方案

> **版本**: v1.0  
> **日期**: 2026-07-20  
> **设计原则**: 结合标签管理系统，实现场景的分类、搜索、推荐

---

## 一、核心设计

### 1.1 场景与标签的关系

```
场景（Scene）
├── 主标签（primary_tag_id）- 决定归属哪个菜单分区
├── 其他标签（tag_ids）- 场景属性标签
└── 技能列表（skills）- 自动加载的技能

示例：
会议纪要
├── 主标签：nature-office（办公通用）
│   └─ 显示在"办公"菜单下
├── 其他标签：[nature-office, industry-general, frequency-high]
│   ├─ nature-office: 办公通用（主标签）
│   ├─ industry-general: 通用行业
│   └─ frequency-high: 高频使用
└── 技能：[audio-transcription, docx]
    └─ 场景代入时自动加载
```

### 1.2 标签系统回顾

**标签类型**（TagType）：
- `dimension`: 维度标签（一级菜单）- 如"业务性质"
- `category`: 分类标签（二级菜单）- 如"办公通用"、"审批服务"
- `industry`: 行业标签（场景属性）- 如"通用"、"政府"
- `frequency`: 频率标签（场景属性）- 如"高频"、"中频"

**标签树形结构**：
```
业务性质（dimension）
├── 办公通用（category）← 场景的主标签
├── 审批服务（category）
├── 规划编制（category）
└── ...
```

---

## 二、数据模型设计

### 2.1 场景配置模型（SceneConfig）

```python
class SceneConfig(BaseModel):
    """场景配置模型"""
    
    # 基本信息
    id: str                          # 场景ID（如 meeting-minutes）
    name: str                        # 场景名称（如 会议纪要）
    icon: str = "📝"                 # 场景图标（emoji）
    description: str = ""            # 详细描述
    short_description: str = ""      # 简短描述（显示在卡片上）
    
    # 标签关联
    primary_tag_id: Optional[str]    # 主标签ID（决定归属分区）
    tag_ids: List[str] = []          # 所有标签ID列表
    
    # 场景能力
    skills: List[str] = []           # 关联技能ID列表
    system_prompt: str = ""          # 系统提示词
    welcome_message: str = ""        # 欢迎消息
    
    # 状态和统计
    status: str = "active"           # active / disabled / deleted
    usage_count: int = 0             # 使用次数
    
    # 时间戳
    created_at: datetime
    updated_at: datetime
    created_by: str = "system"       # 创建者
    
    # 向后兼容字段
    category: str = ""               # 旧字段，保持兼容
    tags: List[str] = []             # 旧字段，保持兼容
```

### 2.2 场景创建请求（SceneCreateRequest）

```python
class SceneCreateRequest(BaseModel):
    """场景创建请求"""
    
    # 必填字段
    id: str
    name: str
    
    # 可选字段
    icon: str = "📝"
    description: str = ""
    short_description: str = ""
    
    # 标签关联
    primary_tag_id: Optional[str] = None
    tag_ids: List[str] = []
    
    # 场景能力
    skills: List[str] = []
    system_prompt: str = ""
    welcome_message: str = ""
    
    # 状态
    status: str = "active"
```

### 2.3 场景更新请求（SceneUpdateRequest）

```python
class SceneUpdateRequest(BaseModel):
    """场景更新请求"""
    
    name: Optional[str] = None
    icon: Optional[str] = None
    description: Optional[str] = None
    short_description: Optional[str] = None
    
    primary_tag_id: Optional[str] = None
    tag_ids: Optional[List[str]] = None
    
    skills: Optional[List[str]] = None
    system_prompt: Optional[str] = None
    welcome_message: Optional[str] = None
    
    status: Optional[str] = None
```

### 2.4 场景列表响应（SceneListResponse）

```python
class SceneListResponse(BaseModel):
    """场景列表响应"""
    
    total: int
    scenes: List[SceneConfig]
```

---

## 三、API 设计

### 3.1 管理端 API（/api/admin/scenes）

| 方法 | 路径 | 说明 | 权限 |
|------|------|------|------|
| GET | `/api/admin/scenes` | 获取场景列表 | scene:read |
| GET | `/api/admin/scenes/{scene_id}` | 获取场景详情 | scene:read |
| POST | `/api/admin/scenes` | 创建场景 | scene:create |
| PUT | `/api/admin/scenes/{scene_id}` | 更新场景 | scene:update |
| DELETE | `/api/admin/scenes/{scene_id}` | 删除场景 | scene:delete |

**查询参数**：
- `status`: 按状态筛选（active/disabled/deleted）
- `primary_tag_id`: 按主标签筛选
- `tag_id`: 按标签筛选（包含该标签的场景）
- `keyword`: 按关键词搜索（名称、描述）

### 3.2 工作台 API（/api/scenes/workbench）

| 方法 | 路径 | 说明 | 权限 |
|------|------|------|------|
| GET | `/api/scenes/workbench/menu` | 获取工作台菜单 | 无需认证 |
| GET | `/api/scenes/workbench/section/{tag_id}` | 获取分区场景 | 无需认证 |
| GET | `/api/scenes/workbench/scene/{scene_id}` | 获取场景详情 | 无需认证 |

---

## 四、前端页面设计

### 4.1 场景管理页面（SceneManagement.tsx）

#### 列表显示

```
┌──────────────────────────────────────────────────────────────┐
│  场景管理                                     [新建场景]    │
├──────────────────────────────────────────────────────────────┤
│  筛选：[状态 ▼] [主标签 ▼] [搜索...]                        │
├──────────────────────────────────────────────────────────────┤
│  ID          名称      图标  主标签      状态   使用次数 操作│
│  meeting-min 会议纪要  📝   办公通用    启用   100     编辑 │
│  work-report 工作报告  📊   办公通用    启用   80      编辑 │
│  project-app 项目审批  ✅   审批服务    启用   50      编辑 │
└──────────────────────────────────────────────────────────────┘
```

#### 表单设计（新建/编辑场景）

```
┌────────────────────────────────────────────────┐
│  新建场景                                      │
├────────────────────────────────────────────────┤
│  基本信息                                      │
│  ────────────────────────────────────────     │
│  场景ID：    [meeting-minutes]                 │
│  名称：      [会议纪要]                        │
│  图标：      [📝]              [选择图标]     │
│  描述：      [快速生成会议纪要，支持音频...]   │
│  简短描述：  [支持音频转写]                    │
│                                                │
│  标签配置                                      │
│  ────────────────────────────────────────     │
│  主标签：    [办公通用 ▼]                      │
│              └─ 决定显示在哪个菜单分区        │
│                                                │
│  其他标签：  [✓] 通用行业                      │
│             [✓] 高频使用                       │
│             [ ] 政府行业                       │
│                                                │
│  场景能力                                      │
│  ────────────────────────────────────────     │
│  关联技能：  [✓] audio-transcription          │
│             [✓] docx                           │
│             [ ] document-analysis              │
│                                                │
│  系统提示词：                                  │
│  ┌────────────────────────────────────────┐  │
│  │你是一个专业的会议纪要助手...           │  │
│  └────────────────────────────────────────┘  │
│                                                │
│  欢迎消息：                                    │
│  ┌────────────────────────────────────────┐  │
│  │您好！我可以帮您：                      │  │
│  │• 转写会议录音                          │  │
│  │• 生成结构化会议纪要                    │  │
│  │• 提取待办事项和决议                    │  │
│  └────────────────────────────────────────┘  │
│                                                │
│  状态：      [✓] 启用                         │
│                                                │
│              [取消]  [保存]                    │
└────────────────────────────────────────────────┘
```

### 4.2 标签选择器组件

**主标签选择器**：
```typescript
// 只显示 category 类型的标签
// 树形结构显示
<Select
  mode="single"
  placeholder="选择主标签"
  treeData={categoryTags}  // 只有 category 类型的标签
  onChange={handlePrimaryTagChange}
/>
```

**其他标签选择器**：
```typescript
// 显示所有类型的标签（除了 category，因为 category 已在主标签中选择）
// 多选模式
<Select
  mode="multiple"
  placeholder="选择其他标签"
  options={otherTags}  // industry, frequency 类型的标签
  onChange={handleTagsChange}
/>
```

---

## 五、数据迁移方案

### 5.1 迁移目标

将现有场景数据的 `category` 字段迁移到 `primary_tag_id` 字段。

### 5.2 迁移脚本

```python
# scripts/migrate_scene_tags.py

def migrate_scenes():
    """迁移场景数据"""
    
    # 1. 读取现有场景
    scenes = load_scenes()
    
    # 2. 读取标签数据
    tags = load_tags()
    
    # 3. 建立 category -> tag_id 映射
    category_map = {}
    for tag in tags:
        if tag["type"] == "category":
            # 旧数据: "办公通用" -> 新数据: "nature-office"
            category_map[tag["name"]] = tag["id"]
    
    # 4. 更新场景数据
    for scene in scenes:
        old_category = scene.get("category", "")
        
        # 查找对应的主标签ID
        primary_tag_id = category_map.get(old_category)
        
        if primary_tag_id:
            scene["primary_tag_id"] = primary_tag_id
        else:
            # 如果找不到，使用默认标签
            scene["primary_tag_id"] = "nature-office"
        
        # 保留旧字段（向后兼容）
        # scene["category"] = old_category
    
    # 5. 保存更新后的场景数据
    save_scenes(scenes)
```

---

## 六、实施步骤

### 第一阶段：数据准备（1天）

- [ ] 创建标签数据（tags.json）
  - 维度标签：业务性质
  - 分类标签：办公通用、审批服务、规划编制等
  - 行业标签：通用、政府、金融、医疗
  - 频率标签：高频、中频、低频

- [ ] 执行数据迁移脚本
  - 将场景的 category 字段映射到 primary_tag_id
  - 验证迁移结果

### 第二阶段：后端开发（1天）

- [ ] 优化数据模型
  - 添加 primary_tag_id 字段
  - 更新 SceneConfig 模型

- [ ] 实现服务层
  - SceneService: 场景CRUD
  - 标签关联逻辑
  - 工作台数据接口

- [ ] 实现 API
  - 管理端 API
  - 工作台 API

### 第三阶段：前端开发（1天）

- [ ] 场景管理页面
  - 列表显示
  - 表单组件
  - 标签选择器

- [ ] 工作台页面
  - 左侧菜单
  - 场景卡片

### 第四阶段：测试优化（1天）

- [ ] 功能测试
- [ ] 数据迁移验证
- [ ] UI/UX 优化

---

## 七、关键技术点

### 7.1 标签选择器逻辑

**主标签选择器**：
- 只显示 `category` 类型的标签
- 树形结构显示（dimension → category）
- 单选模式

**其他标签选择器**：
- 显示 `industry` 和 `frequency` 类型的标签
- 扁平化显示
- 多选模式

### 7.2 场景代入逻辑

```python
def inject_scene(scene_id: str, user_id: str):
    """场景代入"""
    
    # 1. 获取场景配置
    scene = get_scene(scene_id)
    
    # 2. 创建聊天会话
    chat_id = create_chat(user_id, scene_id)
    
    # 3. 注入系统提示词
    if scene.system_prompt:
        inject_system_prompt(chat_id, scene.system_prompt)
    
    # 4. 加载关联技能
    skills = scene.skills
    if skills:
        load_skills(chat_id, skills)
    
    # 5. 增加使用次数
    increment_usage(scene_id)
    
    # 6. 返回代入信息
    return {
        "chat_id": chat_id,
        "scene": scene,
        "welcome_message": scene.welcome_message
    }
```

### 7.3 工作台菜单逻辑

```python
def get_workbench_menu():
    """获取工作台菜单"""
    
    # 1. 获取所有 category 类型的标签
    categories = list_tags(tag_type="category", enabled=True)
    
    # 2. 统计每个标签下的场景数量
    scenes = list_scenes(status="active")
    
    menu_items = []
    for category in categories:
        scene_count = sum(
            1 for s in scenes 
            if s.primary_tag_id == category.id
        )
        
        menu_items.append({
            "id": category.id,
            "name": category.name,
            "icon": category.icon,
            "scene_count": scene_count
        })
    
    return menu_items
```

---

## 八、成功指标

### 8.1 功能指标

- ✅ 管理员可以创建、编辑、删除场景
- ✅ 场景可以关联主标签和其他标签
- ✅ 用户可以在工作台看到场景分类
- ✅ 用户可以点击场景卡片代入场景
- ✅ 场景代入时自动加载关联技能

### 8.2 数据迁移指标

- ✅ 所有现有场景的 category 字段都映射到 primary_tag_id
- ✅ 标签关联正确
- ✅ 向后兼容（旧字段保留）

---

## 九、后续迭代

### 9.1 第二阶段功能

- 场景使用统计和分析
- 场景推荐算法
- 自定义场景模板
- 场景收藏功能

### 9.2 第三阶段功能

- 场景版本管理
- 场景分享和导入
- 场景评价和反馈
- 场景搜索优化

---

**文档版本**: v1.0  
**最后更新**: 2026-07-20
